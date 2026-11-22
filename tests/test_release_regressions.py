import math
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import desktop_main  # Prepare the same Tk runtime as the launcher.
from openpyxl import Workbook
from matplotlib.figure import Figure

from cpk_desktop.widgets import PreviewImagePanel
from cpk_tool.analysis import AxisSpec, calculate_axis_report, format_metric, format_ppm
from cpk_ui import CpkReporterApp


class CapabilityTests(unittest.TestCase):
    def wait_for_preview(self, view):
        view.update()
        deadline = time.monotonic() + 3
        while view._render_job is not None and time.monotonic() < deadline:
            time.sleep(0.01)
            view.update()
        self.assertIsNone(view._render_job)

    def test_ppm_rounding_for_fine_measurements_at_different_origins(self):
        for origin in (10, 20, 30):
            with self.subTest(origin=origin):
                spec = AxisSpec("X", origin - 0.000010, origin + 0.000003)
                report = calculate_axis_report(spec, [origin, origin + 0.000004] * 15)
                self.assertAlmostEqual(report.overall_ppm.total, 311502.47350029805, places=7)
                self.assertEqual(format_ppm(report.overall_ppm.total), "311502.474")
                self.assertEqual(report.observed_oos_count, 15)

    def test_preview_fits_window_and_input_scroll_is_independent(self):
        app = CpkReporterApp()
        try:
            app.load_demo_data()
            frame = app.axis_frames[app.axis_order[0]]
            app.notebook.select(frame)
            app.update()
            app.calculate_preview()
            for size in ("1840x980", "1280x680"):
                app.geometry(size)
                for key in ("histogram", "performance"):
                    frame.preview_notebook.select(frame.preview_tabs[key])
                    view = frame.preview_views[key]
                    self.wait_for_preview(view)
                    self.assertTrue(view.has_content())
                    x1, y1, x2, y2 = view.canvas.bbox("all")
                    self.assertGreaterEqual(min(x1, y1), 0)
                    self.assertLessEqual(x2, view.canvas.winfo_width())
                    self.assertLessEqual(y2, view.canvas.winfo_height())
                left_pane = frame.spec_frame.master.master
                before = view.canvas.winfo_rooty()
                left_pane.canvas.yview_moveto(1.0)
                app.update()
                self.assertGreater(left_pane.canvas.yview()[0], 0)
                self.assertEqual(view.canvas.winfo_rooty(), before)
        finally:
            app.destroy()

    def test_preview_renders_at_screen_resolution_and_reuses_the_displayed_chart(self):
        root = tk.Tk()
        figure_size = (11.4, 6.7)
        builds = []

        def new_figure():
            builds.append(True)
            return Figure(figsize=figure_size)

        try:
            view = PreviewImagePanel(root, background="white")
            view.pack(fill="both", expand=True)
            root.geometry("1600x960")
            view.set_figure(new_figure, figure_size)
            self.wait_for_preview(view)
            self.assertGreater(view._photo_image.width(), 1254)  # Previous 110-DPI limit.
            initial_photo = view._photo_image
            initial_builds = len(builds)
            view.pack_forget()
            root.update()
            view.pack(fill="both", expand=True)
            self.wait_for_preview(view)
            self.assertIs(view._photo_image, initial_photo)
            self.assertEqual(len(builds), initial_builds)

            for width in (1200, 1100, 1000):
                root.geometry(f"{width}x720")
                root.update_idletasks()
            self.wait_for_preview(view)
            self.assertEqual(len(builds), initial_builds + 1)
            self.assertAlmostEqual(view._photo_image.width(), view.canvas.winfo_width() - 12, delta=1)

            root.geometry("980x700")
            root.update_idletasks()
            view.set_placeholder("Inputs changed")
            self.wait_for_preview(view)
            self.assertFalse(view.has_content())
            self.assertEqual(len(builds), initial_builds + 1)
        finally:
            root.destroy()

    def test_exact_threshold_and_just_below(self):
        values = [9.999436, 10.000564] * 15
        spec = AxisSpec("X", 9.99601, 10.00399)
        report = calculate_axis_report(spec, values)
        self.assertEqual((report.cpk, report.status), (1.33, "PASS"))
        spec.usl = 10.00398999999999
        self.assertEqual(calculate_axis_report(spec, values).status, "FAIL")

    def test_constant_measurements(self):
        for value, status in [(0, "N/A"), (1, "N/A"), (2, "FAIL")]:
            report = calculate_axis_report(AxisSpec("X", -1, 1), [value] * 30)
            self.assertEqual(report.status, status)
            for metric in [report.cpk, report.predicted_oos_ppm, report.expected_yield_percent]:
                self.assertEqual(format_metric(metric), "N/A")

    def test_target_and_directional_performance(self):
        # Both limits occur in the data and must be counted as in specification.
        samples = [-2, -1, 1, 2, 2, 0] * 5
        spec = AxisSpec("X", -1, 1, target=0.25)
        report = calculate_axis_report(spec, samples)
        self.assertAlmostEqual(report.observed_ppm.below, 1e6 * 5 / 30)
        self.assertAlmostEqual(report.observed_ppm.above, 1e6 * 10 / 30)
        self.assertAlmostEqual(report.observed_ppm.total, 500000)
        variance = sum((v - sum(samples) / 30)**2 for v in samples) / 29
        rms = math.sqrt(variance + (sum(samples) / 30 - spec.target)**2)
        self.assertAlmostEqual(report.cpm, 2 / (6 * rms))
        self.assertGreater(report.overall_ppm.above, report.overall_ppm.below)
        self.assertNotEqual(report.overall_ppm.total, report.within_ppm.total)
        spec.target = None
        self.assertTrue(math.isnan(calculate_axis_report(spec, samples).cpm))

    def test_expected_tails_and_zero_variation(self):
        values = [-1, 1] * 15
        sigma = math.sqrt(30 / 29)
        report = calculate_axis_report(AxisSpec("X", -sigma, sigma), values)
        for tail in (report.overall_ppm.below, report.overall_ppm.above):
            self.assertAlmostEqual(tail, 158655.253931457, places=6)
        report = calculate_axis_report(AxisSpec("X", -10, 10), values)
        self.assertGreater(report.overall_ppm.above, 0)
        report = calculate_axis_report(AxisSpec("X", -1, 1, target=0), [2] * 30)
        self.assertEqual(report.observed_ppm.total, 1e6)
        self.assertTrue(math.isnan(report.cpm))
        self.assertTrue(math.isnan(report.within_ppm.total))
        self.assertTrue(math.isnan(report.overall_ppm.total))

    def test_excel_to_preview_and_export(self):
        with TemporaryDirectory() as folder:
            app = CpkReporterApp()
            app.withdraw()
            try:
                app.load_demo_data()
                axis = app.axis_frames[app.axis_order[0]]
                path = Path(folder) / "input.xlsx"
                book = Workbook()
                for value in [1, 1.000004] * 15 + ["1,25", "1,26"] * 15:
                    book.active.append([value])
                book.save(path)
                axis.excel_path_var.set(str(path))
                axis.excel_sheet_var.set("Sheet")
                axis.excel_range_var.set("A31:A60")
                with self.assertRaisesRegex(ValueError, "Ambiguous number"):
                    axis._query_excel_range()
                axis.excel_range_var.set("A1:A30")
                axis.load_excel_range()
                axis.lsl_var.set("0.999990")
                axis.usl_var.set("1.000003")
                axis.target_var.set("")
                _, reports = app.calculate_preview()
                self.assertEqual(reports[0].observed_oos_count, 15)
                self.assertEqual(reports[0].status, "FAIL")
                axis.usl_var.set("2")
                axis.lsl_var.set("0")
                app.calculate_preview()
                self.assertEqual(axis.axis_status_var.get(), "PASS")
                axis.value_vars[0].set("invalid")
                self.assertEqual(axis.axis_status_var.get(), "Recalculate")
                self.assertIn("Inputs changed", app.summary_note_var.get())
                self.assertIsNone(app._cached_reports)
                with patch("cpk_ui.messagebox.showerror"), patch("cpk_ui.filedialog.asksaveasfilename") as save:
                    app.export_current_pdf()
                    save.assert_not_called()
                axis._populate_measurements([1] * 30)
                pdf = Path(folder) / "report.pdf"
                with patch("cpk_ui.messagebox.showinfo"), patch("cpk_ui.filedialog.asksaveasfilename", return_value=str(pdf)):
                    app.export_current_pdf()
                self.assertEqual(axis.axis_status_var.get(), "N/A")
                self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
            finally:
                app.destroy()
