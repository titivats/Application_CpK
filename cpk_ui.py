from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
import random
import re
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries
from PIL import Image

from cpk_desktop.axes import (
    DEFAULT_AXIS_NAMES,
    axis_color_for_index,
    axis_tab_label,
    suggest_next_axis_name,
    validate_axis_name,
)
from cpk_desktop.assets import get_first_existing_asset_path
from cpk_desktop.widgets import PreviewImagePanel, ScrollablePanel
from cpk_reporting import (
    create_capability_histogram_figure,
    create_capability_summary_figure,
    create_normal_probability_figure,
    create_run_chart_figure,
    export_pdf,
    figure_to_png_bytes,
)
from cpk_tool.analysis import (
    AxisSpec,
    EXPECTED_SAMPLE_COUNT,
    ReportMetadata,
    calculate_axis_report,
    format_metric,
    parse_measurement_values,
)


APP_BG = "#EEF3F7"
SURFACE = "#F8FBFD"
CARD = "#FFFFFF"
CARD_SOFT = "#F3F7FA"
TEXT = "#18212A"
MUTED = "#5B6670"
ACCENT = "#0F766E"
ACCENT_DARK = "#0B5E58"
HEADER_BG = "#102A43"
HEADER_TOP = "#173B5B"
HEADER_SOFT = "#DCEAF5"
GOLD = "#C89B5A"
GOLD_SOFT = "#F7ECD8"
LINE = "#D6E0E8"
PASS = "#18794E"
FAIL = "#B42318"
PENDING = "#64748B"

FULL_HD_WIDTH = 1920
FULL_HD_HEIGHT = 1080
FULL_HD_WINDOW_WIDTH = 1840
FULL_HD_WINDOW_HEIGHT = 980
PREVIEW_RENDER_DPI = 110
PREVIEW_CHART_FIGURE_SIZE = (11.4, 6.7)
PREVIEW_SUMMARY_FIGURE_SIZE = (11.8, 7.2)
PREVIEW_TABS = (
    ("histogram", "Capability Histogram"),
    ("probability", "Normal Probability Plot"),
    ("run_chart", "Run Chart"),
    ("summary", "Capability Summary"),
)


class AxisInputFrame(ttk.Frame):
    def __init__(
        self,
        master: ttk.Notebook,
        axis_key: str,
        axis_name: str,
        accent_color: str,
        *,
        on_request_rename,
        on_request_remove,
    ) -> None:
        super().__init__(master, padding=14, style="Surface.TFrame")
        self.axis_key = axis_key
        self.axis_name = axis_name
        self.accent_color = accent_color
        self._on_request_rename = on_request_rename
        self._on_request_remove = on_request_remove
        self.lsl_var = tk.StringVar()
        self.target_var = tk.StringVar()
        self.usl_var = tk.StringVar()
        self.cpk_requirement_var = tk.StringVar(value="1.33")
        self.value_vars = [tk.StringVar() for _ in range(EXPECTED_SAMPLE_COUNT)]

        self.excel_path_var = tk.StringVar()
        self.excel_sheet_var = tk.StringVar()
        self.excel_range_var = tk.StringVar(value="A2:A31")
        self.excel_source_note_var = tk.StringVar(
            value="Import an Excel workbook, choose a sheet, then query a range such as A2:A31."
        )
        self.axis_status_var = tk.StringVar(value="Awaiting Data")
        self.axis_meta_var = tk.StringVar(value="30 measurements required | Manual input or Excel query")

        self.sheet_selector: ttk.Combobox | None = None
        self.status_pill: tk.Label | None = None
        self.preview_notebook: ttk.Notebook | None = None
        self.preview_tabs: dict[str, ttk.Frame] = {}
        self.preview_views: dict[str, PreviewImagePanel] = {}
        self._pending_report = None
        self._pending_report_token: tuple[object, ...] | None = None
        self._rendered_report_token: tuple[object, ...] | None = None
        self._rendered_preview_tabs: set[str] = set()
        self._cached_workbook = None
        self._cached_workbook_path = ""
        self._cached_workbook_mtime_ns = 0
        self._hero_title_var = tk.StringVar()
        self._preview_title_var = tk.StringVar()
        self._axis_badge_var = tk.StringVar()
        self.spec_frame: ttk.LabelFrame | None = None

        self._sync_axis_labels()
        self._build_layout()


    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        page_scroll = ScrollablePanel(self, background=SURFACE)
        page_scroll.grid(row=0, column=0, sticky="nsew")
        page_scroll.content.columnconfigure(0, weight=1)
        page_scroll.content.rowconfigure(0, weight=1)

        paned = ttk.Panedwindow(page_scroll.content, orient="horizontal")
        paned.grid(row=0, column=0, sticky="nsew")

        input_column = ttk.Frame(paned, style="Surface.TFrame")
        preview_column = ttk.Frame(paned, style="Surface.TFrame")
        input_column.columnconfigure(0, weight=1)
        preview_column.columnconfigure(0, weight=1)
        preview_column.rowconfigure(0, weight=1)
        paned.add(input_column, weight=0)
        paned.add(preview_column, weight=1)
        self.after(120, lambda: paned.sashpos(0, 600))

        hero_card = self._build_axis_hero(input_column)
        hero_card.grid(row=0, column=0, sticky="ew", pady=(0, 14))

        self.spec_frame = ttk.LabelFrame(input_column, text=f"Axis {self.axis_name} Specification")
        self.spec_frame.grid(row=1, column=0, sticky="ew")
        for column in range(2):
            self.spec_frame.columnconfigure(column, weight=1)

        self._add_labeled_entry(self.spec_frame, "LSL", self.lsl_var, 0, 0)
        self._add_labeled_entry(self.spec_frame, "Target", self.target_var, 0, 1)
        self._add_labeled_entry(self.spec_frame, "USL", self.usl_var, 1, 0)
        self._add_labeled_entry(self.spec_frame, "Required Cpk", self.cpk_requirement_var, 1, 1)

        source_frame = ttk.LabelFrame(input_column, text="Measurement Source")
        source_frame.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        source_frame.columnconfigure(0, weight=1)
        source_frame.columnconfigure(1, weight=0)
        source_frame.columnconfigure(2, weight=0)

        ttk.Label(source_frame, text="Excel File", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 4)
        )
        ttk.Entry(source_frame, textvariable=self.excel_path_var, state="readonly").grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=(12, 8), pady=(0, 8)
        )
        ttk.Button(
            source_frame,
            text="Browse Excel",
            command=self.browse_excel_file,
            style="Secondary.TButton",
        ).grid(row=1, column=2, sticky="ew", padx=(0, 12), pady=(0, 8))

        ttk.Label(source_frame, text="Sheet", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", padx=12
        )
        ttk.Label(source_frame, text="Range / Query", style="Muted.TLabel").grid(
            row=2, column=1, columnspan=2, sticky="w", padx=(0, 12)
        )

        self.sheet_selector = ttk.Combobox(
            source_frame,
            textvariable=self.excel_sheet_var,
            state="readonly",
            values=(),
        )
        self.sheet_selector.grid(row=3, column=0, sticky="ew", padx=(12, 8), pady=(4, 8))
        ttk.Entry(source_frame, textvariable=self.excel_range_var, justify="center").grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(0, 12), pady=(4, 8)
        )

        button_shell = tk.Frame(
            source_frame,
            bg=CARD_SOFT,
            highlightbackground=LINE,
            highlightthickness=1,
            padx=10,
            pady=10,
        )
        button_shell.grid(row=4, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 8))
        button_shell.columnconfigure(0, weight=1)
        button_shell.columnconfigure(1, weight=1)

        ttk.Button(
            button_shell,
            text="Load Range to Table",
            command=self.load_excel_range,
            style="Accent.TButton",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(
            button_shell,
            text="Clear Axis",
            command=self.clear_axis,
            style="Secondary.TButton",
        ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ttk.Label(
            source_frame,
            textvariable=self.excel_source_note_var,
            style="Muted.TLabel",
            wraplength=540,
            justify="left",
        ).grid(row=5, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 12))

        values_frame = ttk.LabelFrame(
            input_column,
            text=f"Measurement Input ({EXPECTED_SAMPLE_COUNT} values)",
        )
        values_frame.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        values_frame.columnconfigure(0, weight=1)
        inner_values = ttk.Frame(values_frame, style="Card.TFrame")
        inner_values.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        for column in range(3):
            inner_values.columnconfigure(column, weight=1)

        group_titles = ("Trials 01-10", "Trials 11-20", "Trials 21-30")
        row_count = (EXPECTED_SAMPLE_COUNT + 2) // 3
        for group_index, title in enumerate(group_titles):
            group_card = tk.Frame(
                inner_values,
                bg=CARD_SOFT,
                highlightbackground=LINE,
                highlightthickness=1,
                padx=12,
                pady=12,
            )
            group_card.grid(row=0, column=group_index, sticky="nsew", padx=(0 if group_index == 0 else 8, 0))
            group_card.columnconfigure(1, weight=1)

            tk.Label(
                group_card,
                text=title,
                bg=CARD_SOFT,
                fg=ACCENT_DARK,
                font=("Segoe UI Semibold", 10),
            ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

            for offset in range(row_count):
                index = (group_index * row_count) + offset
                if index >= EXPECTED_SAMPLE_COUNT:
                    continue
                tk.Label(
                    group_card,
                    text=f"{index + 1:02d}",
                    bg=CARD_SOFT,
                    fg=MUTED,
                    font=("Segoe UI", 9),
                ).grid(row=offset + 1, column=0, sticky="w", padx=(0, 8), pady=4)
                ttk.Entry(
                    group_card,
                    textvariable=self.value_vars[index],
                    width=12,
                    justify="center",
                ).grid(row=offset + 1, column=1, sticky="ew", pady=4)

        preview_frame = ttk.LabelFrame(preview_column, text="Capability Preview")
        preview_frame.grid(row=0, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(2, weight=1)

        preview_hero = tk.Frame(
            preview_frame,
            bg=CARD_SOFT,
            highlightbackground=LINE,
            highlightthickness=1,
            padx=14,
            pady=12,
        )
        preview_hero.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        preview_hero.columnconfigure(0, weight=1)

        tk.Label(
            preview_hero,
            textvariable=self._preview_title_var,
            bg=CARD_SOFT,
            fg=TEXT,
            font=("Segoe UI Semibold", 12),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            preview_hero,
            textvariable=self.axis_meta_var,
            bg=CARD_SOFT,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.status_pill = tk.Label(
            preview_hero,
            textvariable=self.axis_status_var,
            bg="#EAF1F7",
            fg=PENDING,
            font=("Segoe UI Semibold", 9),
            padx=12,
            pady=6,
        )
        self.status_pill.grid(row=0, column=1, rowspan=2, sticky="e", padx=(16, 0))

        ttk.Label(
            preview_frame,
            text="Each tab mirrors one export section. Use the scroll bars if a chart needs extra space.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", padx=12, pady=(10, 0))

        self.preview_notebook = ttk.Notebook(preview_frame, takefocus=False)
        self.preview_notebook.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)
        self.preview_notebook.bind("<<NotebookTabChanged>>", self._handle_preview_tab_change)
        for tab_key, tab_title in PREVIEW_TABS:
            tab_frame = ttk.Frame(self.preview_notebook, style="Surface.TFrame")
            tab_frame.columnconfigure(0, weight=1)
            tab_frame.rowconfigure(0, weight=1)
            self.preview_notebook.add(tab_frame, text=tab_title)

            preview_view = PreviewImagePanel(tab_frame, background=SURFACE)
            preview_view.grid(row=0, column=0, sticky="nsew")

            self.preview_tabs[tab_key] = tab_frame
            self.preview_views[tab_key] = preview_view

        self._show_placeholder(
            "Preview not generated yet.\nClick Calculate Preview after entering the specification and 30 values."
        )


    def _build_axis_hero(self, parent) -> tk.Frame:
        card = tk.Frame(
            parent,
            bg=HEADER_BG,
            highlightbackground="#21496E",
            highlightthickness=1,
            padx=18,
            pady=16,
        )
        card.columnconfigure(0, weight=1)
        card.columnconfigure(1, weight=0)

        tk.Label(
            card,
            textvariable=self._hero_title_var,
            bg=HEADER_BG,
            fg="#FFFFFF",
            font=("Segoe UI Semibold", 16),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            card,
            text="Configure specification limits, load 30 measurements, review previews, and export the audit package.",
            bg=HEADER_BG,
            fg=HEADER_SOFT,
            font=("Segoe UI", 9),
            wraplength=420,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(5, 12))

        action_stack = tk.Frame(card, bg=HEADER_BG)
        action_stack.grid(row=0, column=1, rowspan=2, sticky="ne", padx=(16, 0))
        ttk.Button(
            action_stack,
            text="Rename Axis",
            command=self._request_axis_rename,
            style="Secondary.TButton",
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            action_stack,
            text="- Axis",
            command=self._request_axis_remove,
            style="Secondary.TButton",
        ).grid(row=1, column=0, sticky="ew", pady=(8, 0))

        badge_row = tk.Frame(card, bg=HEADER_BG)
        badge_row.grid(row=2, column=0, sticky="w")
        self._build_axis_badge(
            badge_row,
            textvariable=self._axis_badge_var,
            color=self.accent_color,
        ).pack(side="left")
        self._build_axis_badge(badge_row, "30 Samples", GOLD).pack(side="left", padx=(8, 0))
        self._build_axis_badge(badge_row, "Excel + Manual", self.accent_color).pack(side="left", padx=(8, 0))

        return card


    @staticmethod
    def _build_axis_badge(
        parent,
        text: str | None = None,
        color: str = ACCENT,
        *,
        textvariable: tk.StringVar | None = None,
    ) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            textvariable=textvariable,
            bg=color,
            fg="#FFFFFF",
            font=("Segoe UI Semibold", 8),
            padx=10,
            pady=5,
        )


    def _set_axis_status(self, label: str, bg_color: str, fg_color: str) -> None:
        self.axis_status_var.set(label)
        if self.status_pill is not None:
            self.status_pill.configure(bg=bg_color, fg=fg_color)


    def rename_axis(self, new_name: str) -> None:
        self.axis_name = new_name
        self._sync_axis_labels()
        if self.spec_frame is not None:
            self.spec_frame.configure(text=f"Axis {self.axis_name} Specification")
        self._pending_report = None
        self._pending_report_token = None
        self._rendered_report_token = None
        self._rendered_preview_tabs.clear()
        self.axis_meta_var.set("Axis renamed | Click Calculate Preview to refresh charts and report labels")
        self._set_axis_status("Axis Renamed", "#EAF1F7", "#34506A")
        self._show_placeholder(
            "Axis name updated.\nClick Calculate Preview to refresh charts and PDF labels."
        )


    def _request_axis_rename(self) -> None:
        if self._on_request_rename is not None:
            self._on_request_rename(self.axis_key)


    def _request_axis_remove(self) -> None:
        if self._on_request_remove is not None:
            self._on_request_remove(self.axis_key)


    def _sync_axis_labels(self) -> None:
        self._hero_title_var.set(f"Axis {self.axis_name} Workflow")
        self._preview_title_var.set(f"Axis {self.axis_name} Capability Stage")
        self._axis_badge_var.set(f"Axis {self.axis_name}")


    def build_report(self):
        lsl = self._parse_float(self.lsl_var.get(), "LSL")
        usl = self._parse_float(self.usl_var.get(), "USL")
        if usl <= lsl:
            raise ValueError(f"Axis {self.axis_name}: USL must be greater than LSL.")

        target_text = self.target_var.get().strip()
        target = self._parse_float(target_text, "Target") if target_text else None
        if target is not None and not (lsl <= target <= usl):
            raise ValueError(f"Axis {self.axis_name}: Target must be between LSL and USL.")

        requirement_text = self.cpk_requirement_var.get().strip()
        cpk_requirement = self._parse_float(requirement_text, "Required Cpk") if requirement_text else 1.33
        if cpk_requirement < 0:
            raise ValueError(f"Axis {self.axis_name}: Required Cpk must be non-negative.")

        values = parse_measurement_values([variable.get() for variable in self.value_vars], self.axis_name)
        spec = AxisSpec(
            axis_name=self.axis_name,
            lsl=lsl,
            usl=usl,
            target=target,
            cpk_requirement=cpk_requirement,
        )
        return calculate_axis_report(spec, values)


    def build_state_token(self) -> tuple[object, ...]:
        return (
            self.axis_name,
            self.lsl_var.get().strip(),
            self.target_var.get().strip(),
            self.usl_var.get().strip(),
            self.cpk_requirement_var.get().strip(),
            tuple(variable.get().strip() for variable in self.value_vars),
        )


    def update_preview(self, report, *, render_preview: bool = True) -> None:
        meta_parts = [
            f"Mean {format_metric(report.mean)}",
            f"Cpk {format_metric(report.cpk, 3)}",
        ]
        if report.observed_oos_count > 0:
            meta_parts.append(f"Observed OOS {report.observed_oos_count}")
        self.axis_meta_var.set(" | ".join(meta_parts))
        if report.status == "PASS":
            self._set_axis_status("PASS", "#DFF4E8", PASS)
        else:
            self._set_axis_status("FAIL", "#FBE7E4", FAIL)
        self._pending_report = report
        self._pending_report_token = self.build_state_token()
        self._rendered_report_token = None
        self._rendered_preview_tabs.clear()
        self._show_placeholder("Preview ready.\nSelect a preview tab to render the chart.")
        if render_preview:
            self.render_pending_preview()


    def render_pending_preview(self) -> None:
        if self._pending_report is None or self._pending_report_token is None:
            return
        if self._rendered_report_token != self._pending_report_token:
            self._rendered_report_token = self._pending_report_token
            self._rendered_preview_tabs.clear()

        selected_tab_key = self._selected_preview_tab_key()
        if selected_tab_key is None or selected_tab_key in self._rendered_preview_tabs:
            return

        figure_factories = {
            "histogram": lambda report: create_capability_histogram_figure(
                report,
                figure_size=PREVIEW_CHART_FIGURE_SIZE,
            ),
            "probability": lambda report: create_normal_probability_figure(
                report,
                figure_size=PREVIEW_CHART_FIGURE_SIZE,
            ),
            "run_chart": lambda report: create_run_chart_figure(
                report,
                figure_size=PREVIEW_CHART_FIGURE_SIZE,
            ),
            "summary": lambda report: create_capability_summary_figure(
                report,
                figure_size=PREVIEW_SUMMARY_FIGURE_SIZE,
            ),
        }
        preview_image = self._render_preview_image(figure_factories[selected_tab_key](self._pending_report))
        self.preview_views[selected_tab_key].set_image(preview_image)
        self._rendered_preview_tabs.add(selected_tab_key)


    def browse_excel_file(self) -> None:
        selected = filedialog.askopenfilename(
            title=f"Select Excel workbook for Axis {self.axis_name}",
            filetypes=[
                ("Excel Workbook", "*.xlsx *.xlsm"),
                ("Excel Workbook", "*.xlsx"),
                ("Macro-Enabled Workbook", "*.xlsm"),
            ],
        )
        if not selected:
            return

        self.excel_path_var.set(selected)
        try:
            self._refresh_excel_sheets(selected)
        except ValueError as exc:
            messagebox.showerror("Excel import error", str(exc))
            self.excel_path_var.set("")
            return

        self.excel_source_note_var.set(
            f"Workbook loaded for Axis {self.axis_name}. Choose a sheet and range, then load 30 values."
        )
        self.axis_meta_var.set("Excel workbook connected | Choose a sheet and query a 30-value range")
        self._set_axis_status("Workbook Linked", "#EAF1F7", "#34506A")
        self._set_status(f"Axis {self.axis_name}: workbook ready")


    def load_excel_range(self) -> None:
        try:
            values, source_note = self._query_excel_range()
        except ValueError as exc:
            messagebox.showerror("Excel query error", str(exc))
            self._set_status(f"Axis {self.axis_name}: Excel query failed")
            return

        self._populate_measurements(values)
        self.excel_source_note_var.set(source_note)
        self.axis_meta_var.set(
            f"Excel query loaded | Sheet {self.excel_sheet_var.get().strip()} | Range {self.excel_range_var.get().strip().upper()}"
        )
        self._set_axis_status("Data Loaded", "#E4F5F1", ACCENT)
        self._set_status(f"Axis {self.axis_name}: loaded 30 values from Excel range")


    def clear_axis(self) -> None:
        self._close_cached_workbook()
        self._pending_report = None
        self._pending_report_token = None
        self._rendered_report_token = None
        self._rendered_preview_tabs.clear()
        for variable in self.value_vars:
            variable.set("")
        self.lsl_var.set("")
        self.target_var.set("")
        self.usl_var.set("")
        self.cpk_requirement_var.set("1.33")
        self.excel_path_var.set("")
        self.excel_sheet_var.set("")
        self.excel_range_var.set("A2:A31")
        if self.sheet_selector is not None:
            self.sheet_selector.configure(values=())
        self.excel_source_note_var.set(
            "Import an Excel workbook, choose a sheet, then query a range such as A2:A31."
        )
        self.axis_meta_var.set("30 measurements required | Manual input or Excel query")
        self._set_axis_status("Awaiting Data", "#EAF1F7", PENDING)
        self._show_placeholder(
            "Preview not generated yet.\nClick Calculate Preview after entering the specification and 30 values."
        )


    def populate_demo(
        self,
        *,
        lsl: float,
        target: float,
        usl: float,
        cpk_requirement: float,
        values: list[float],
    ) -> None:
        self.lsl_var.set(f"{lsl:.4f}")
        self.target_var.set(f"{target:.4f}")
        self.usl_var.set(f"{usl:.4f}")
        self.cpk_requirement_var.set(f"{cpk_requirement:.2f}")
        self._populate_measurements(values)
        self.excel_source_note_var.set("Demo values loaded into the measurement table.")
        self.axis_meta_var.set("Demo data staged | Ready for preview generation")
        self._set_axis_status("Demo Ready", GOLD_SOFT, "#8A611D")


    def _refresh_excel_sheets(self, workbook_path: str) -> None:
        try:
            workbook = self._get_cached_workbook(workbook_path)
            sheet_names = list(workbook.sheetnames)
        except Exception as exc:
            raise ValueError(f"Axis {self.axis_name}: could not open the Excel workbook. {exc}") from exc

        if not sheet_names:
            raise ValueError(f"Axis {self.axis_name}: the selected workbook does not contain any sheets.")

        if self.sheet_selector is not None:
            self.sheet_selector.configure(values=sheet_names)
        self.excel_sheet_var.set(sheet_names[0])


    def _query_excel_range(self) -> tuple[list[float], str]:
        workbook_path = self.excel_path_var.get().strip()
        sheet_name = self.excel_sheet_var.get().strip()
        range_ref = self.excel_range_var.get().strip().upper()

        if not workbook_path:
            raise ValueError(f"Axis {self.axis_name}: choose an Excel workbook first.")
        if not Path(workbook_path).exists():
            raise ValueError(f"Axis {self.axis_name}: the selected workbook cannot be found.")
        if not sheet_name:
            raise ValueError(f"Axis {self.axis_name}: choose a sheet before loading data.")
        if not range_ref:
            raise ValueError(f"Axis {self.axis_name}: enter an Excel range such as A2:A31.")

        try:
            range_boundaries(range_ref)
        except Exception as exc:
            raise ValueError(f"Axis {self.axis_name}: '{range_ref}' is not a valid Excel range.") from exc

        values: list[float] = []
        try:
            min_col, min_row, max_col, max_row = range_boundaries(range_ref)
            workbook = self._get_cached_workbook(workbook_path)
            worksheet = workbook[sheet_name]
            for row in worksheet.iter_rows(
                min_row=min_row,
                max_row=max_row,
                min_col=min_col,
                max_col=max_col,
                values_only=True,
            ):
                for value in row:
                    number = self._coerce_excel_value(value)
                    if number is not None:
                        values.append(number)
        except KeyError as exc:
            raise ValueError(f"Axis {self.axis_name}: sheet '{sheet_name}' was not found in the workbook.") from exc
        except Exception as exc:
            raise ValueError(f"Axis {self.axis_name}: unable to read range '{range_ref}'. {exc}") from exc

        if len(values) != EXPECTED_SAMPLE_COUNT:
            raise ValueError(
                (
                    f"Axis {self.axis_name}: range '{range_ref}' on sheet '{sheet_name}' produced "
                    f"{len(values)} numeric values. Expected {EXPECTED_SAMPLE_COUNT}."
                )
            )

        source_note = (
            f"Loaded {EXPECTED_SAMPLE_COUNT} values from sheet '{sheet_name}' "
            f"range '{range_ref}' into the measurement table."
        )
        return values, source_note


    def close_resources(self) -> None:
        self._close_cached_workbook()


    def destroy(self) -> None:
        self._close_cached_workbook()
        super().destroy()


    def _close_cached_workbook(self) -> None:
        if self._cached_workbook is not None:
            try:
                self._cached_workbook.close()
            except Exception:
                pass
        self._cached_workbook = None
        self._cached_workbook_path = ""
        self._cached_workbook_mtime_ns = 0


    def _get_cached_workbook(self, workbook_path: str):
        resolved_path = str(Path(workbook_path).resolve())
        mtime_ns = Path(resolved_path).stat().st_mtime_ns
        if (
            self._cached_workbook is None
            or self._cached_workbook_path != resolved_path
            or self._cached_workbook_mtime_ns != mtime_ns
        ):
            self._close_cached_workbook()
            self._cached_workbook = load_workbook(resolved_path, read_only=True, data_only=True)
            self._cached_workbook_path = resolved_path
            self._cached_workbook_mtime_ns = mtime_ns
        return self._cached_workbook


    def _populate_measurements(self, values: list[float]) -> None:
        for variable, value in zip(self.value_vars, values):
            variable.set(_format_input_value(value))


    def _clear_preview(self) -> None:
        self._rendered_report_token = None
        self._rendered_preview_tabs.clear()
        for preview_view in self.preview_views.values():
            preview_view.clear()


    def _render_preview_image(self, figure) -> Image.Image:
        image_bytes = figure_to_png_bytes(figure, dpi=PREVIEW_RENDER_DPI)
        with Image.open(BytesIO(image_bytes)) as rendered:
            return rendered.convert("RGBA").copy()


    def _show_placeholder(self, text: str) -> None:
        self._clear_preview()
        descriptions = {
            "histogram": text,
            "probability": "Normal Probability Plot preview will appear after calculation.",
            "run_chart": "Run Chart preview will appear after calculation.",
            "summary": "Capability Summary preview will appear after calculation.",
        }
        for tab_key, preview_view in self.preview_views.items():
            preview_view.set_placeholder(descriptions[tab_key])


    def _handle_preview_tab_change(self, _event=None) -> None:
        self.render_pending_preview()


    def _selected_preview_tab_key(self) -> str | None:
        if self.preview_notebook is None:
            return None
        selected_tab = self.preview_notebook.select()
        if not selected_tab:
            return None
        selected_widget = self.preview_notebook.nametowidget(selected_tab)
        for tab_key, tab_frame in self.preview_tabs.items():
            if tab_frame is selected_widget:
                return tab_key
        return None


    def _set_status(self, text: str) -> None:
        root = self.winfo_toplevel()
        if hasattr(root, "set_status"):
            root.set_status(text)


    @staticmethod
    def _coerce_excel_value(value) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.strip().replace(",", "")
            if not cleaned:
                return None
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None


    @staticmethod
    def _parse_float(raw_value: str, field_name: str) -> float:
        value_text = raw_value.strip()
        if not value_text:
            raise ValueError(f"{field_name} is required.")
        try:
            return float(value_text)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a valid number.") from exc


    @staticmethod
    def _add_labeled_entry(parent, label_text: str, variable: tk.StringVar, row: int, column: int) -> None:
        holder = ttk.Frame(parent, style="Surface.TFrame")
        holder.grid(row=row, column=column, sticky="ew", padx=12, pady=8)
        holder.columnconfigure(0, weight=1)
        ttk.Label(holder, text=label_text, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(holder, textvariable=variable, justify="center").grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(4, 0),
        )


class CpkReporterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Machine Cpk Capability Reporter")
        self.minsize(1440, 860)
        self.configure(bg=APP_BG)
        self._app_icon_image: tk.PhotoImage | None = None
        self._apply_app_icon()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.report_title_var = tk.StringVar(value="Machine Repeatability Cpk Report")
        self.customer_var = tk.StringVar()
        self.machine_var = tk.StringVar()
        self.machine_model_var = tk.StringVar()
        self.part_var = tk.StringVar()
        self.serial_var = tk.StringVar()
        self.measurement_tool_name_var = tk.StringVar()
        self.measurement_tool_model_var = tk.StringVar()
        self.inspector_var = tk.StringVar()
        self.report_date_var = tk.StringVar(value=date.today().isoformat())
        self.status_var = tk.StringVar(value="Ready")
        self.summary_note_var = tk.StringVar(value="Preview has not been generated yet.")

        self.axis_frames: dict[str, AxisInputFrame] = {}
        self.axis_order: list[str] = []
        self._axis_counter = 0
        self.summary_tree: ttk.Treeview | None = None
        self.notes_box: tk.Text | None = None
        self.notebook: ttk.Notebook | None = None
        self._cached_axis_token: tuple[object, ...] | None = None
        self._cached_reports = None

        self._apply_window_geometry()
        self._configure_styles()
        self._build_layout()


    def _apply_window_geometry(self) -> None:
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        if screen_width >= FULL_HD_WIDTH and screen_height >= FULL_HD_HEIGHT:
            target_width = FULL_HD_WINDOW_WIDTH
            target_height = FULL_HD_WINDOW_HEIGHT
        else:
            target_width = max(1360, min(FULL_HD_WINDOW_WIDTH, screen_width - 40))
            target_height = max(820, min(FULL_HD_WINDOW_HEIGHT, screen_height - 80))

        x_position = max(0, (screen_width - target_width) // 2)
        y_position = max(0, (screen_height - target_height) // 2)
        self.geometry(f"{target_width}x{target_height}+{x_position}+{y_position}")


    def _apply_app_icon(self) -> None:
        icon_path = get_first_existing_asset_path(
            ("assets", "program_source.ico"),
            ("assets", "machine_cpk_reporter.ico"),
        )
        if icon_path is not None:
            try:
                self.iconbitmap(default=str(icon_path))
                return
            except tk.TclError:
                pass

        png_path = get_first_existing_asset_path(
            ("Icon", "Program.png"),
            ("Icon", "program.png"),
            ("assets", "program_source_256.png"),
            ("assets", "machine_cpk_reporter_256.png"),
        )
        if png_path is not None:
            try:
                self._app_icon_image = tk.PhotoImage(file=str(png_path))
                self.iconphoto(True, self._app_icon_image)
            except tk.TclError:
                self._app_icon_image = None


    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", font=("Segoe UI", 10), foreground=TEXT)
        style.configure("TFrame", background=APP_BG)
        style.configure("Surface.TFrame", background=SURFACE)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=SURFACE, foreground=TEXT)
        style.configure("Muted.TLabel", background=SURFACE, foreground=MUTED)
        style.configure("Body.TLabel", background=CARD, foreground=TEXT)
        style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 9))
        style.configure(
            "SectionCaption.TLabel",
            background=CARD,
            foreground=ACCENT_DARK,
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "TLabelframe",
            background=SURFACE,
            borderwidth=1,
            relief="solid",
            bordercolor=LINE,
        )
        style.configure(
            "TLabelframe.Label",
            background=SURFACE,
            foreground=TEXT,
            font=("Segoe UI Semibold", 10),
        )
        style.configure("TNotebook", background=APP_BG, borderwidth=0, tabmargins=(0, 4, 0, 0))
        style.layout(
            "TNotebook.Tab",
            [
                (
                    "Notebook.tab",
                    {
                        "sticky": "nswe",
                        "children": [
                            (
                                "Notebook.padding",
                                {
                                    "side": "top",
                                    "sticky": "nswe",
                                    "children": [
                                        ("Notebook.label", {"side": "top", "sticky": ""}),
                                    ],
                                },
                            )
                        ],
                    },
                )
            ],
        )
        style.configure(
            "TNotebook.Tab",
            background="#E3EAF1",
            foreground=MUTED,
            borderwidth=1,
            bordercolor="#B6C7D5",
            lightcolor="#B6C7D5",
            darkcolor="#B6C7D5",
            padding=(18, 10),
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#F7FBFF"), ("active", "#EEF4F9")],
            foreground=[("selected", HEADER_TOP), ("active", TEXT)],
            bordercolor=[("selected", ACCENT), ("active", "#B6C7D5")],
            lightcolor=[("selected", ACCENT), ("active", "#B6C7D5")],
            darkcolor=[("selected", ACCENT), ("active", "#B6C7D5")],
            padding=[("selected", (18, 10))],
            expand=[("selected", (0, 0, 0, 0))],
        )
        style.configure(
            "TButton",
            padding=(12, 8),
            borderwidth=0,
            focusthickness=0,
        )
        style.configure(
            "Accent.TButton",
            background=HEADER_TOP,
            foreground="#FFFFFF",
            borderwidth=1,
            bordercolor="#274C6B",
            focusthickness=0,
            padding=(14, 9),
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "Accent.TButton",
            background=[("active", HEADER_BG), ("pressed", HEADER_BG)],
            foreground=[("disabled", "#EAF6F4")],
        )
        style.configure(
            "Secondary.TButton",
            background="#FFFFFF",
            foreground=TEXT,
            borderwidth=1,
            bordercolor=LINE,
            padding=(12, 8),
            font=("Segoe UI", 9),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", CARD_SOFT), ("pressed", CARD_SOFT)],
        )
        style.configure(
            "TEntry",
            fieldbackground="#FCFEFF",
            bordercolor="#C5D3DE",
            lightcolor="#C5D3DE",
            darkcolor="#C5D3DE",
            insertcolor=TEXT,
            padding=8,
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", ACCENT)],
            lightcolor=[("focus", ACCENT)],
            darkcolor=[("focus", ACCENT)],
        )
        style.configure(
            "TCombobox",
            fieldbackground="#FCFEFF",
            bordercolor="#C5D3DE",
            lightcolor="#C5D3DE",
            darkcolor="#C5D3DE",
            padding=7,
            arrowsize=14,
        )
        style.map(
            "TCombobox",
            bordercolor=[("focus", ACCENT)],
            lightcolor=[("focus", ACCENT)],
            darkcolor=[("focus", ACCENT)],
        )
        style.configure("TPanedwindow", background=SURFACE, sashwidth=10)
        style.configure(
            "Vertical.TScrollbar",
            background="#BFCFDB",
            troughcolor="#E8EFF5",
            arrowcolor="#3E5466",
            bordercolor="#C9D6DF",
            lightcolor="#BFCFDB",
            darkcolor="#BFCFDB",
        )
        style.configure(
            "Horizontal.TScrollbar",
            background="#BFCFDB",
            troughcolor="#E8EFF5",
            arrowcolor="#3E5466",
            bordercolor="#C9D6DF",
            lightcolor="#BFCFDB",
            darkcolor="#BFCFDB",
        )
        style.configure(
            "Treeview",
            rowheight=34,
            fieldbackground=CARD,
            background=CARD,
            foreground=TEXT,
            bordercolor=LINE,
            lightcolor=LINE,
            darkcolor=LINE,
        )
        style.configure(
            "Treeview.Heading",
            background="#E8EFF5",
            foreground=TEXT,
            font=("Segoe UI Semibold", 10),
            relief="flat",
        )


    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=HEADER_BG, padx=22, pady=16)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        tk.Frame(header, bg=HEADER_TOP, height=4).grid(row=0, column=0, columnspan=2, sticky="new", pady=(0, 14))

        tk.Label(
            header,
            text="Machine Cpk Capability Reporter",
            bg=HEADER_BG,
            fg="#FFFFFF",
            font=("Segoe UI Semibold", 23),
        ).grid(row=1, column=0, sticky="w")
        tk.Label(
            header,
            text="Desktop capability analysis for multi-axis repeatability, Excel-assisted data import, and customer-ready PDF export.",
            bg=HEADER_BG,
            fg=HEADER_SOFT,
            font=("Segoe UI", 10),
        ).grid(row=2, column=0, sticky="w", pady=(5, 0))

        badge_row = tk.Frame(header, bg=HEADER_BG)
        badge_row.grid(row=3, column=0, sticky="w", pady=(12, 0))
        self._build_header_badge(badge_row, "Audit-Ready Desktop", GOLD, "#102A43").pack(side="left")
        self._build_header_badge(badge_row, "Dynamic Axis Tabs", "#1F4F6E", "#FFFFFF").pack(side="left", padx=(8, 0))
        self._build_header_badge(badge_row, "Excel Query + PDF Export", "#1B5E55", "#FFFFFF").pack(side="left", padx=(8, 0))

        action_panel = tk.Frame(
            header,
            bg="#F4F8FB",
            highlightbackground="#365576",
            highlightthickness=1,
            padx=12,
            pady=12,
        )
        action_panel.grid(row=1, column=1, rowspan=3, sticky="e")
        action_panel.columnconfigure(0, weight=1)
        action_panel.columnconfigure(1, weight=1)

        tk.Label(
            action_panel,
            text="Quick Actions",
            bg="#F4F8FB",
            fg=TEXT,
            font=("Segoe UI Semibold", 10),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        ttk.Button(
            action_panel,
            text="Load Demo",
            command=self.load_demo_data,
            style="Secondary.TButton",
        ).grid(row=1, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(
            action_panel,
            text="Clear All",
            command=self.clear_all,
            style="Secondary.TButton",
        ).grid(row=1, column=1, sticky="ew", padx=(6, 0))
        ttk.Button(
            action_panel,
            text="Calculate Preview",
            command=self.calculate_preview,
            style="Accent.TButton",
        ).grid(row=2, column=0, sticky="ew", pady=(8, 0), padx=(0, 6))
        ttk.Button(
            action_panel,
            text="Export PDF",
            command=self.export_current_pdf,
            style="Accent.TButton",
        ).grid(row=2, column=1, sticky="ew", pady=(8, 0), padx=(6, 0))
        ttk.Button(
            action_panel,
            text="+ Axis",
            command=self.add_axis,
            style="Secondary.TButton",
        ).grid(row=3, column=0, sticky="ew", pady=(8, 0), padx=(0, 6))
        ttk.Button(
            action_panel,
            text="- Axis",
            command=self.remove_axis,
            style="Secondary.TButton",
        ).grid(row=3, column=1, sticky="ew", pady=(8, 0), padx=(6, 0))

        body = ttk.Frame(self, padding=14, style="Surface.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(body, takefocus=False)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.notebook.bind("<<NotebookTabChanged>>", self._handle_main_tab_change)

        overview_tab = ttk.Frame(self.notebook, padding=0, style="Surface.TFrame")
        overview_tab.columnconfigure(0, weight=1)
        overview_tab.rowconfigure(0, weight=1)
        self.notebook.add(overview_tab, text="Report Info")
        self._build_overview_tab(overview_tab)

        for axis_name in DEFAULT_AXIS_NAMES:
            self._add_axis_tab(axis_name=axis_name, select=False)

        status_bar = ttk.Frame(self, padding=(14, 8), style="Surface.TFrame")
        status_bar.grid(row=2, column=0, sticky="ew")
        status_bar.columnconfigure(0, weight=1)
        ttk.Label(status_bar, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")


    @staticmethod
    def _build_header_badge(parent, text: str, bg_color: str, fg_color: str) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=bg_color,
            fg=fg_color,
            font=("Segoe UI Semibold", 8),
            padx=10,
            pady=5,
        )


    def add_axis(self) -> None:
        existing_names = {frame.axis_name for frame in self.axis_frames.values()}
        suggested_name = suggest_next_axis_name(existing_names)
        axis_name = self._prompt_axis_name(
            title="Add Axis",
            prompt="Enter the new axis name.",
            initial_value=suggested_name,
        )
        if axis_name is None:
            return

        self._add_axis_tab(axis_name=axis_name, select=True)
        self._clear_summary_view()
        self.summary_note_var.set("Axis list updated. Click Calculate Preview to refresh the report package.")
        self.set_status(f"Added axis {axis_name}")


    def rename_axis(self, axis_key: str | None = None) -> None:
        target_key = axis_key or self._selected_axis_key()
        if target_key is None:
            messagebox.showinfo("Rename axis", "Select an axis tab before renaming it.")
            return

        frame = self.axis_frames[target_key]
        axis_name = self._prompt_axis_name(
            title="Rename Axis",
            prompt="Enter the updated axis name.",
            initial_value=frame.axis_name,
            exclude_axis_key=target_key,
        )
        if axis_name is None or axis_name == frame.axis_name:
            return

        self._apply_axis_name(target_key, axis_name)
        self._clear_summary_view()
        self.summary_note_var.set("Axis renamed. Click Calculate Preview to refresh charts and PDF labels.")
        self.set_status(f"Renamed axis to {axis_name}")


    def remove_axis(self, axis_key: str | None = None) -> None:
        target_key = axis_key or self._selected_axis_key()
        if target_key is None:
            messagebox.showinfo("Remove axis", "Select an axis tab before removing it.")
            return
        if len(self.axis_order) <= 1:
            messagebox.showwarning("Remove axis", "At least one axis tab must remain in the report.")
            return

        frame = self.axis_frames[target_key]
        should_remove = messagebox.askyesno(
            "Remove Axis",
            f"Remove axis '{frame.axis_name}' from this study?",
            parent=self,
        )
        if not should_remove:
            return

        removed_axis_name = frame.axis_name
        self._remove_axis_tab(target_key)
        self.summary_note_var.set("Axis removed. Click Calculate Preview to refresh the report package.")
        self.set_status(f"Removed axis {removed_axis_name}")


    def _add_axis_tab(self, *, axis_name: str, select: bool) -> str:
        if self.notebook is None:
            raise RuntimeError("Notebook has not been initialized.")
        axis_name = validate_axis_name(axis_name)
        self._assert_axis_name_available(axis_name)

        axis_key = self._next_axis_key()
        axis_frame = AxisInputFrame(
            self.notebook,
            axis_key,
            axis_name,
            axis_color_for_index(len(self.axis_order)),
            on_request_rename=self.rename_axis,
            on_request_remove=self.remove_axis,
        )
        self.axis_frames[axis_key] = axis_frame
        self.axis_order.append(axis_key)
        self.notebook.add(axis_frame, text=axis_tab_label(axis_name))
        if select:
            self.notebook.select(axis_frame)
        self._invalidate_cached_reports()
        return axis_key


    def _next_axis_key(self) -> str:
        self._axis_counter += 1
        return f"axis_{self._axis_counter:03d}"


    def _remove_axis_tab(self, axis_key: str) -> None:
        if self.notebook is None:
            raise RuntimeError("Notebook has not been initialized.")

        frame = self.axis_frames[axis_key]
        tab_index = self.axis_order.index(axis_key)
        fallback_index = max(0, tab_index - 1)

        frame.close_resources()
        self.notebook.forget(frame)
        frame.destroy()

        del self.axis_frames[axis_key]
        self.axis_order.remove(axis_key)
        self._invalidate_cached_reports()
        self._clear_summary_view()

        if self.axis_order:
            fallback_key = self.axis_order[min(fallback_index, len(self.axis_order) - 1)]
            self.notebook.select(self.axis_frames[fallback_key])
        else:
            self.notebook.select(0)


    def _apply_axis_name(self, axis_key: str, axis_name: str) -> None:
        frame = self.axis_frames[axis_key]
        frame.rename_axis(axis_name)
        if self.notebook is not None:
            self.notebook.tab(frame, text=axis_tab_label(axis_name))
        self._invalidate_cached_reports()


    def _prompt_axis_name(
        self,
        *,
        title: str,
        prompt: str,
        initial_value: str,
        exclude_axis_key: str | None = None,
    ) -> str | None:
        candidate = initial_value
        while True:
            response = simpledialog.askstring(
                title,
                prompt,
                initialvalue=candidate,
                parent=self,
            )
            if response is None:
                return None
            try:
                axis_name = validate_axis_name(response)
                self._assert_axis_name_available(axis_name, exclude_axis_key=exclude_axis_key)
                return axis_name
            except ValueError as exc:
                messagebox.showerror(title, str(exc))
                candidate = response


    def _assert_axis_name_available(
        self,
        axis_name: str,
        *,
        exclude_axis_key: str | None = None,
    ) -> None:
        axis_name_key = axis_name.casefold()
        for current_key, frame in self.axis_frames.items():
            if current_key == exclude_axis_key:
                continue
            if frame.axis_name.casefold() == axis_name_key:
                raise ValueError(f"Axis name '{axis_name}' is already in use.")


    def _build_shell_dashboard(self, parent) -> tk.Frame:
        strip = tk.Frame(parent, bg=SURFACE)
        for column in range(4):
            strip.columnconfigure(column, weight=1)

        cards = (
            ("01", "Multi-Axis Study", "Add, rename, and review multiple axis tabs in one audit package.", HEADER_BG, "#FFFFFF", HEADER_SOFT),
            ("30", "Measurements / Axis", "Structured table for 30 repeatability values with cleaner grouping.", ACCENT, "#FFFFFF", "#DDF7F2"),
            ("XL", "Excel Query", "Load a sheet and range directly into the measurement table.", GOLD, "#102A43", GOLD_SOFT),
            ("PDF", "Review to Export", "Preview tabs mirror the final multi-page PDF layout.", "#1F4F6E", "#FFFFFF", "#D9EAF6"),
        )
        for index, (eyebrow, title, detail, bg_color, title_fg, detail_fg) in enumerate(cards):
            card = tk.Frame(
                strip,
                bg=bg_color,
                highlightbackground=LINE,
                highlightthickness=0,
                padx=16,
                pady=14,
            )
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 8, 0))
            tk.Label(
                card,
                text=eyebrow,
                bg=bg_color,
                fg=detail_fg,
                font=("Segoe UI Semibold", 9),
            ).pack(anchor="w")
            tk.Label(
                card,
                text=title,
                bg=bg_color,
                fg=title_fg,
                font=("Segoe UI Semibold", 13),
                anchor="w",
                justify="left",
            ).pack(anchor="w", pady=(4, 0))
            tk.Label(
                card,
                text=detail,
                bg=bg_color,
                fg=detail_fg,
                font=("Segoe UI", 9),
                anchor="w",
                justify="left",
                wraplength=270,
            ).pack(anchor="w", pady=(6, 0))
        return strip


    def _build_overview_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        intro_panel = tk.Frame(
            parent,
            bg=HEADER_BG,
            highlightbackground="#21496E",
            highlightthickness=1,
            padx=18,
            pady=14,
        )
        intro_panel.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 14))
        intro_panel.columnconfigure(0, weight=1)

        tk.Label(
            intro_panel,
            text="Report Information",
            bg=HEADER_BG,
            fg="#FFFFFF",
            font=("Segoe UI Semibold", 16),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            intro_panel,
            text="Complete this section once. The values are reused in the PDF cover page, page headers, and customer-facing report details.",
            bg=HEADER_BG,
            fg=HEADER_SOFT,
            font=("Segoe UI", 9),
            justify="left",
            wraplength=1240,
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

        form_frame = ttk.LabelFrame(parent, text="Report Fields")
        form_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        for column in range(2):
            form_frame.columnconfigure(column, weight=1)

        self._add_overview_entry(form_frame, "Report Title", self.report_title_var, 0, 0)
        self._add_overview_entry(form_frame, "Customer Name", self.customer_var, 0, 1)
        self._add_overview_entry(form_frame, "Machine Name", self.machine_var, 1, 0)
        self._add_overview_entry(form_frame, "Machine Model", self.machine_model_var, 1, 1)
        self._add_overview_entry(form_frame, "Part Name", self.part_var, 2, 0)
        self._add_overview_entry(form_frame, "Serial Number", self.serial_var, 2, 1)
        self._add_overview_entry(form_frame, "Measurement Tools Name", self.measurement_tool_name_var, 3, 0)
        self._add_overview_entry(form_frame, "Measurement Tools Model", self.measurement_tool_model_var, 3, 1)
        self._add_overview_entry(form_frame, "Inspected By", self.inspector_var, 4, 0)
        self._add_overview_entry(form_frame, "Report Date", self.report_date_var, 4, 1)

        notes_frame = ttk.LabelFrame(parent, text="Notes for Customer / Audit Trail")
        notes_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 16))
        notes_frame.columnconfigure(0, weight=1)
        notes_frame.rowconfigure(1, weight=1)
        ttk.Label(
            notes_frame,
            text="Use this area for audit notes, measurement conditions, or customer remarks.",
            style="Muted.TLabel",
            wraplength=1240,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        self.notes_box = tk.Text(
            notes_frame,
            height=8,
            wrap="word",
            font=("Segoe UI", 10),
            bd=0,
            relief="flat",
            background="#FCFEFF",
            foreground=TEXT,
            insertbackground=TEXT,
        )
        self.notes_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))


    def _build_summary_tab(self, parent: ttk.Frame) -> None:
        summary_banner = tk.Frame(
            parent,
            bg=HEADER_BG,
            highlightbackground="#21496E",
            highlightthickness=1,
            padx=18,
            pady=16,
        )
        summary_banner.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 14))
        summary_banner.columnconfigure(0, weight=1)

        tk.Label(
            summary_banner,
            text="Summary Review Board",
            bg=HEADER_BG,
            fg="#FFFFFF",
            font=("Segoe UI Semibold", 16),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            summary_banner,
            textvariable=self.summary_note_var,
            bg=HEADER_BG,
            fg=HEADER_SOFT,
            font=("Segoe UI", 9),
            wraplength=1220,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

        chip_row = tk.Frame(summary_banner, bg=HEADER_BG)
        chip_row.grid(row=0, column=1, rowspan=2, sticky="e", padx=(16, 0))
        self._build_header_badge(chip_row, "Axis-Level Comparison", GOLD, "#102A43").pack(side="left")
        self._build_header_badge(chip_row, "Audit Snapshot", "#1F4F6E", "#FFFFFF").pack(side="left", padx=(8, 0))

        columns = (
            "axis",
            "mean",
            "within_sigma",
            "overall_sigma",
            "cpk",
            "ppk",
            "requirement",
            "oos",
            "result",
        )
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=10)
        headings = {
            "axis": "Axis",
            "mean": "Mean",
            "within_sigma": "Within Sigma",
            "overall_sigma": "Overall Sigma",
            "cpk": "Cpk",
            "ppk": "Ppk",
            "requirement": "Required",
            "oos": "Observed OOS",
            "result": "Result",
        }
        widths = {
            "axis": 80,
            "mean": 120,
            "within_sigma": 130,
            "overall_sigma": 130,
            "cpk": 95,
            "ppk": 95,
            "requirement": 100,
            "oos": 130,
            "result": 100,
        }
        table_shell = tk.Frame(
            parent,
            bg=CARD,
            highlightbackground=LINE,
            highlightthickness=1,
            padx=14,
            pady=14,
        )
        table_shell.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        table_shell.columnconfigure(0, weight=1)
        table_shell.rowconfigure(1, weight=1)

        tk.Label(
            table_shell,
            text="Capability roll-up across all axes",
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI Semibold", 12),
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="center", stretch=False)
        tree.configure(height=12)
        tree.grid(in_=table_shell, row=1, column=0, sticky="nsew")
        tree.tag_configure("PASS", foreground=PASS)
        tree.tag_configure("FAIL", foreground=FAIL)
        self.summary_tree = tree


    def calculate_preview(self):
        metadata = self._build_metadata()
        axis_token = tuple(self.axis_frames[axis_key].build_state_token() for axis_key in self.axis_order)
        if self._cached_axis_token == axis_token and self._cached_reports is not None:
            self._render_selected_axis_preview()
            self.set_status("Preview ready | using latest calculated result")
            return metadata, self._cached_reports

        try:
            reports = [self.axis_frames[axis_key].build_report() for axis_key in self.axis_order]
        except ValueError as exc:
            messagebox.showerror("Validation error", str(exc))
            self.set_status("Validation error")
            return None

        selected_axis_key = self._selected_axis_key()
        for axis_key, report in zip(self.axis_order, reports):
            self.axis_frames[axis_key].update_preview(
                report,
                render_preview=(axis_key == selected_axis_key),
            )

        self._cached_axis_token = axis_token
        self._cached_reports = reports
        self._refresh_summary(metadata, reports)
        self.set_status("Preview updated successfully")
        return metadata, reports


    def export_current_pdf(self) -> None:
        result = self.calculate_preview()
        if result is None:
            return

        metadata, reports = result
        default_name = _safe_filename(
            f"{metadata.machine_name or 'machine'}_{metadata.report_date or date.today().isoformat()}_cpk_report"
        )
        destination = filedialog.asksaveasfilename(
            title="Export Cpk Report PDF",
            defaultextension=".pdf",
            filetypes=[("PDF Files", "*.pdf")],
            initialfile=f"{default_name}.pdf",
        )
        if not destination:
            self.set_status("PDF export cancelled")
            return

        export_pdf(metadata, reports, destination)
        self.set_status(f"PDF exported: {destination}")
        messagebox.showinfo("Export complete", f"PDF report saved to:\n{destination}")


    def load_demo_data(self) -> None:
        self._invalidate_cached_reports()
        rng = random.Random(20260328)

        self.report_title_var.set("Machine Repeatability Cpk Report")
        self.customer_var.set("Demo Customer")
        self.machine_var.set("Linear Motion Tester")
        self.machine_model_var.set("LMT-500")
        self.part_var.set("XYZ Repeatability Study")
        self.serial_var.set("SN-CPK-2026-001")
        self.measurement_tool_name_var.set("Digital Indicator")
        self.measurement_tool_model_var.set("DI-01")
        self.inspector_var.set("Quality Engineer")
        self.report_date_var.set(date.today().isoformat())
        if self.notes_box is not None:
            self.notes_box.delete("1.0", "end")
            self.notes_box.insert(
                "1.0",
                "Demonstration data loaded automatically. Replace with actual machine measurements before issuing the customer report.",
            )

        demo_templates = (
            (9.9500, 10.0000, 10.0500, 1.33, 10.001, 0.0075),
            (19.9500, 20.0000, 20.0500, 1.33, 20.003, 0.0085),
            (29.9300, 30.0000, 30.0700, 1.33, 29.998, 0.0090),
        )

        for index, axis_key in enumerate(self.axis_order):
            lsl, target, usl, cpk_requirement, mean, sigma = demo_templates[index % len(demo_templates)]
            mean += (index // len(demo_templates)) * 0.0015
            self.axis_frames[axis_key].populate_demo(
                lsl=lsl,
                target=target,
                usl=usl,
                cpk_requirement=cpk_requirement,
                values=_generate_demo_values(rng, mean, sigma),
            )

        self.summary_note_var.set("Demo data loaded. Click Calculate Preview to generate the active axis previews.")
        self.set_status("Demo data loaded")


    def clear_all(self) -> None:
        self._invalidate_cached_reports()
        self.report_title_var.set("Machine Repeatability Cpk Report")
        self.customer_var.set("")
        self.machine_var.set("")
        self.machine_model_var.set("")
        self.part_var.set("")
        self.serial_var.set("")
        self.measurement_tool_name_var.set("")
        self.measurement_tool_model_var.set("")
        self.inspector_var.set("")
        self.report_date_var.set(date.today().isoformat())
        if self.notes_box is not None:
            self.notes_box.delete("1.0", "end")
        for axis_key in self.axis_order:
            self.axis_frames[axis_key].clear_axis()
        self._clear_summary_view()
        self.summary_note_var.set("Preview has not been generated yet.")
        self.set_status("All fields cleared")


    def set_status(self, text: str) -> None:
        self.status_var.set(text)


    def _build_metadata(self) -> ReportMetadata:
        return ReportMetadata(
            report_title=self.report_title_var.get().strip() or "Machine Repeatability Cpk Report",
            customer_name=self.customer_var.get().strip(),
            machine_name=self.machine_var.get().strip(),
            machine_model=self.machine_model_var.get().strip(),
            part_name=self.part_var.get().strip(),
            serial_number=self.serial_var.get().strip(),
            measurement_tool_name=self.measurement_tool_name_var.get().strip(),
            measurement_tool_model=self.measurement_tool_model_var.get().strip(),
            inspected_by=self.inspector_var.get().strip(),
            report_date=self.report_date_var.get().strip() or date.today().isoformat(),
            notes=self.notes_box.get("1.0", "end").strip() if self.notes_box is not None else "",
        )


    def _invalidate_cached_reports(self) -> None:
        self._cached_axis_token = None
        self._cached_reports = None


    def _clear_summary_view(self) -> None:
        if self.summary_tree is not None:
            for item in self.summary_tree.get_children():
                self.summary_tree.delete(item)


    def _refresh_summary(self, metadata: ReportMetadata, reports) -> None:
        if self.summary_tree is not None:
            for item in self.summary_tree.get_children():
                self.summary_tree.delete(item)
            for report in reports:
                self.summary_tree.insert(
                    "",
                    "end",
                    values=(
                        report.spec.axis_name,
                        format_metric(report.mean, 4),
                        format_metric(report.within_std, 4),
                        format_metric(report.overall_std, 4),
                        format_metric(report.cpk, 3),
                        format_metric(report.ppk, 3),
                        format_metric(report.spec.cpk_requirement, 2),
                        f"{report.observed_oos_count} ({report.observed_oos_percent:.2f}%)",
                        report.status,
                    ),
                    tags=(report.status,),
                )

        overall_status = "PASS" if all(report.status == "PASS" for report in reports) else "FAIL"
        self.summary_note_var.set(
            f"{metadata.report_title} | Customer: {metadata.customer_name or '-'} | Overall result: {overall_status}"
        )


    def _handle_main_tab_change(self, _event=None) -> None:
        self._render_selected_axis_preview()


    def _render_selected_axis_preview(self) -> None:
        selected_axis_key = self._selected_axis_key()
        if selected_axis_key is None:
            return
        self.axis_frames[selected_axis_key].render_pending_preview()


    def _selected_axis_key(self) -> str | None:
        if self.notebook is None:
            return None
        selected_tab = self.notebook.select()
        if not selected_tab:
            return None
        selected_widget = self.notebook.nametowidget(selected_tab)
        for axis_name, frame in self.axis_frames.items():
            if frame is selected_widget:
                return axis_name
        return None


    def _on_close(self) -> None:
        for axis_key in self.axis_order:
            self.axis_frames[axis_key].close_resources()
        self.destroy()


    def destroy(self) -> None:
        for axis_key in self.axis_order:
            self.axis_frames[axis_key].close_resources()
        super().destroy()


    @staticmethod
    def _add_overview_entry(parent, label_text: str, variable: tk.StringVar, row: int, column: int) -> None:
        holder = ttk.Frame(parent, style="Surface.TFrame")
        holder.grid(row=row, column=column, sticky="ew", padx=12, pady=8)
        holder.columnconfigure(0, weight=1)
        ttk.Label(holder, text=label_text, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(holder, textvariable=variable).grid(row=1, column=0, sticky="ew", pady=(4, 0))


def _generate_demo_values(rng: random.Random, mean: float, sigma: float) -> list[float]:
    return [rng.gauss(mean, sigma) for _ in range(EXPECTED_SAMPLE_COUNT)]


def _format_input_value(value: float) -> str:
    return f"{value:.5f}".rstrip("0").rstrip(".")


def _safe_filename(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")
    return cleaned or "cpk_report"


def run_app() -> None:
    app = CpkReporterApp()
    app.mainloop()
