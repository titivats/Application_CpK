from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import desktop_main  # Use the launcher's Tk runtime.
from openpyxl import load_workbook

from cpk_tool.excel_template import MEASUREMENTS, SPECIFICATIONS, read_excel_template, save_excel_template
from cpk_ui import CpkReporterApp


class ExcelTemplateTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "template.xlsx"
        self.axes = ["X1", "Y", "Z"]
        save_excel_template(self.path, self.axes)
        self.book = load_workbook(self.path)
        self.addCleanup(self.book.close)
        for col in range(2, 5):
            for row in range(2, 32):
                self.book[MEASUREMENTS].cell(row, col, (100 * col + row) / 1000)

    def test_columns_are_matched_by_name_on_each_sheet(self):
        spec = self.book[SPECIFICATIONS]
        spec["B1"], spec["D1"] = "Z", "X1"
        spec["B2"], spec["B4"] = -1, 2
        self.book.save(self.path)
        readings, specs = read_excel_template(self.path, ["Z", "X1", "Y"])
        self.assertEqual(list(readings), self.axes)
        self.assertEqual(readings["X1"], [(200 + row) / 1000 for row in range(2, 32)])
        self.assertEqual(set(specs), {"Z"})
        self.assertEqual((specs["Z"].lsl, specs["Z"].target, specs["Z"].cpk_requirement), (-1, None, 1.33))

    def test_invalid_cells_axes_trial_order_and_specs(self):
        for sheet, address, value, error in (
            (MEASUREMENTS, "D31", None, "D31"),
            (MEASUREMENTS, "C2", "1,20", "C2"),
            (MEASUREMENTS, "B5", True, "B5"),
            (MEASUREMENTS, "B2", "=1+2", "B2"),
            (MEASUREMENTS, "A12", 13, "A12"),
            (MEASUREMENTS, "D1", "y", "duplicate axis"),
            (MEASUREMENTS, "D1", None, "missing axis"),
            (MEASUREMENTS, "C32", 15, "final template row"),
            (SPECIFICATIONS, "B2", 0, "both LSL and USL"),
        ):
            with self.subTest(address=address, value=value):
                cell = self.book[sheet][address]
                previous = cell.value
                cell.value = value
                self.book.save(self.path)
                with self.assertRaisesRegex(ValueError, error):
                    read_excel_template(self.path, self.axes)
                cell.value = previous

    def test_import_is_atomic_and_preserves_unspecified_limits(self):
        app = CpkReporterApp()
        self.addCleanup(app.destroy)
        app.withdraw()
        app._apply_axis_name(app.axis_order[0], "X1")
        app.load_demo_data()
        _, old_reports = app.calculate_preview()
        frames = [app.axis_frames[key] for key in app.axis_order]
        original = [frame.build_state_token() for frame in frames]
        spec = self.book[SPECIFICATIONS]
        spec["B2"], spec["B3"], spec["B4"], spec["B5"] = 0, 0.22, 1, 1.67
        self.book[MEASUREMENTS]["D31"] = "=1"
        self.book.save(self.path)
        with patch("cpk_ui.filedialog.askopenfilename", return_value=str(self.path)), patch("cpk_ui.messagebox.showerror") as error:
            app.import_excel_template()
            self.assertIn("D31", error.call_args.args[1])
            self.assertEqual([frame.build_state_token() for frame in frames], original)
            self.assertIs(app._cached_reports, old_reports)
            self.book[MEASUREMENTS]["D31"] = 0.431
            self.book.save(self.path)
            app.import_excel_template()
            self.assertEqual(error.call_count, 1)
        self.assertIsNone(app._cached_reports)
        self.assertEqual(frames[0].cpk_requirement_var.get(), "1.67")
        self.assertEqual(frames[1].build_state_token()[1:5], original[1][1:5])
        self.assertEqual([f.excel_range_var.get() for f in frames], ["B2:B31", "C2:C31", "D2:D31"])
        for col, report in enumerate(app.calculate_preview()[1], 2):
            self.assertEqual(report.values, [(100 * col + row) / 1000 for row in range(2, 32)])

        frames[1]._refresh_excel_sheets(str(self.path))
        self.assertEqual(frames[1].excel_range_var.get(), "C2:C31")
        self.book[MEASUREMENTS]["C2"] = 0.3234
        self.book.save(self.path)
        self.assertEqual(frames[1]._query_excel_range()[0][0], 0.3234)
