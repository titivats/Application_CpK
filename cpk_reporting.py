from __future__ import annotations

from io import BytesIO
import math
from pathlib import Path
from tempfile import NamedTemporaryFile
from statistics import NormalDist

from matplotlib.figure import Figure
import numpy as np
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from cpk_tool.analysis import AxisReport, ReportMetadata, format_metric, format_ppm, overall_result


PAGE_SIZE = landscape(A4)
PAGE_WIDTH, PAGE_HEIGHT = PAGE_SIZE
PAGE_MARGIN = 28

PAPER = "#FCFBF7"
PANEL = "#FFFFFF"
INK = "#18212A"
MUTED = "#5B6670"
ACCENT = "#0F766E"
ACCENT_SOFT = "#D6F2EE"
WARNING = "#C2410C"
PASS = "#18794E"
FAIL = "#B42318"
STATUS_COLORS = {"PASS": PASS, "FAIL": FAIL, "N/A": MUTED}
WITHIN = "#D97706"
OVERALL = "#2563EB"
SPEC = "#B91C1C"
TARGET = "#7C3AED"
SECTION_RENDER_DPI = 160


def create_axis_figure(report: AxisReport) -> Figure:
    figure = Figure(figsize=(15.6, 10.2), facecolor=PAPER, layout="constrained")
    grid = figure.add_gridspec(2, 2, hspace=0.18, wspace=0.16, width_ratios=(1.05, 1.2))
    histogram_axis = figure.add_subplot(grid[0, 0])
    run_axis = figure.add_subplot(grid[0, 1])
    probability_axis = figure.add_subplot(grid[1, 0])
    summary_axis = figure.add_subplot(grid[1, 1])

    values = np.array(report.values, dtype=float)
    spec = report.spec
    x_min, x_max = _expanded_limits(report)

    _style_plot_axis(histogram_axis)
    bins = min(12, max(6, int(round(math.sqrt(report.sample_count) * 1.8))))
    _, edges, _ = histogram_axis.hist(
        values,
        bins=bins,
        color=ACCENT_SOFT,
        edgecolor=ACCENT,
        linewidth=1.1,
        alpha=0.95,
    )
    bin_width = edges[1] - edges[0] if len(edges) > 1 else 1.0
    xs = np.linspace(x_min, x_max, 400)
    if report.within_std > 0:
        histogram_axis.plot(
            xs,
            _scaled_pdf(xs, report.mean, report.within_std, report.sample_count, bin_width),
            color=WITHIN,
            linewidth=2.4,
            label="Within Curve",
        )
    if report.overall_std > 0:
        histogram_axis.plot(
            xs,
            _scaled_pdf(xs, report.mean, report.overall_std, report.sample_count, bin_width),
            color=OVERALL,
            linewidth=2.1,
            linestyle="--",
            label="Overall Curve",
        )
    _draw_vertical_spec_lines(histogram_axis, report)
    histogram_axis.set_title("Capability Histogram", fontsize=14.5, color=INK, pad=12)
    histogram_axis.set_xlabel("Measurement", color=INK)
    histogram_axis.set_ylabel("Frequency", color=INK)
    histogram_axis.legend(
        loc="upper left",
        frameon=True,
        framealpha=0.95,
        facecolor=PANEL,
        edgecolor="#D9E0E7",
        fontsize=10,
    )

    _style_plot_axis(run_axis)
    trial_numbers = np.arange(1, report.sample_count + 1)
    run_axis.plot(
        trial_numbers,
        values,
        color=ACCENT,
        linewidth=1.8,
        marker="o",
        markersize=4.8,
        markerfacecolor=PANEL,
    )
    run_axis.axhspan(spec.lsl, spec.usl, color="#E8F4EE", alpha=0.7, zorder=0)
    run_axis.axhline(report.mean, color=OVERALL, linewidth=1.4, linestyle="--", label="Mean")
    _draw_horizontal_spec_lines(run_axis, report)
    run_axis.set_xlim(1, report.sample_count)
    run_axis.set_title("Run Chart (30 Trials)", fontsize=14.5, color=INK, pad=12)
    run_axis.set_xlabel("Trial", color=INK)
    run_axis.set_ylabel("Measurement", color=INK)
    run_axis.legend(
        loc="upper left",
        frameon=True,
        framealpha=0.95,
        facecolor=PANEL,
        edgecolor="#D9E0E7",
        fontsize=10,
    )

    _style_plot_axis(probability_axis)
    probability_values = np.sort(values)
    plotting_positions = [
        (index - 0.375) / (report.sample_count + 0.25)
        for index in range(1, report.sample_count + 1)
    ]
    theoretical_quantiles = np.array(
        [NormalDist().inv_cdf(position) for position in plotting_positions]
    )
    slope, intercept = np.polyfit(theoretical_quantiles, probability_values, 1)
    fit_line = slope * theoretical_quantiles + intercept
    probability_axis.scatter(
        theoretical_quantiles,
        probability_values,
        color=ACCENT,
        edgecolors=PANEL,
        s=42,
        linewidths=0.7,
        zorder=3,
    )
    probability_axis.plot(
        theoretical_quantiles,
        fit_line,
        color=WARNING,
        linewidth=2.0,
        label="Best Fit",
    )
    probability_axis.set_title("Normal Probability Plot", fontsize=14.5, color=INK, pad=12)
    probability_axis.set_xlabel("Normal Quantile", color=INK)
    probability_axis.set_ylabel("Ordered Measurement", color=INK)
    probability_axis.legend(
        loc="upper left",
        frameon=True,
        framealpha=0.95,
        facecolor=PANEL,
        edgecolor="#D9E0E7",
        fontsize=10,
    )

    _draw_summary_panel(summary_axis, report, x_min, x_max)

    figure.suptitle(
        f"Machine Capability Analysis - Axis {spec.axis_name}",
        fontsize=22,
        fontweight="bold",
        color=INK,
    )
    figure.text(
        0.5,
        0.955,
        (
            f"LSL {format_metric(spec.lsl)}   |   "
            f"Target {format_metric(spec.resolved_target)}   |   "
            f"USL {format_metric(spec.usl)}   |   "
            f"Required Cpk >= {format_metric(spec.cpk_requirement, 2)}"
        ),
        ha="center",
        fontsize=12,
        color=MUTED,
    )
    return figure


def create_axis_pdf_charts_figure(report: AxisReport) -> Figure:
    figure = Figure(figsize=(15.6, 10.2), facecolor=PAPER, layout="constrained")
    grid = figure.add_gridspec(2, 2, hspace=0.18, wspace=0.16, height_ratios=(1.0, 1.08))
    histogram_axis = figure.add_subplot(grid[0, 0])
    run_axis = figure.add_subplot(grid[0, 1])
    probability_axis = figure.add_subplot(grid[1, :])

    values = np.array(report.values, dtype=float)
    spec = report.spec
    x_min, x_max = _expanded_limits(report)

    _style_plot_axis(histogram_axis)
    bins = min(12, max(6, int(round(math.sqrt(report.sample_count) * 1.8))))
    _, edges, _ = histogram_axis.hist(
        values,
        bins=bins,
        color=ACCENT_SOFT,
        edgecolor=ACCENT,
        linewidth=1.1,
        alpha=0.95,
    )
    bin_width = edges[1] - edges[0] if len(edges) > 1 else 1.0
    xs = np.linspace(x_min, x_max, 400)
    if report.within_std > 0:
        histogram_axis.plot(
            xs,
            _scaled_pdf(xs, report.mean, report.within_std, report.sample_count, bin_width),
            color=WITHIN,
            linewidth=2.5,
            label="Within Curve",
        )
    if report.overall_std > 0:
        histogram_axis.plot(
            xs,
            _scaled_pdf(xs, report.mean, report.overall_std, report.sample_count, bin_width),
            color=OVERALL,
            linewidth=2.3,
            linestyle="--",
            label="Overall Curve",
        )
    _draw_vertical_spec_lines(histogram_axis, report)
    histogram_axis.set_title("Capability Histogram", fontsize=16, color=INK, pad=12)
    histogram_axis.set_xlabel("Measurement", color=INK)
    histogram_axis.set_ylabel("Frequency", color=INK)
    histogram_axis.legend(
        loc="upper left",
        frameon=True,
        framealpha=0.95,
        facecolor=PANEL,
        edgecolor="#D9E0E7",
        fontsize=10.5,
    )

    _style_plot_axis(run_axis)
    trial_numbers = np.arange(1, report.sample_count + 1)
    run_axis.plot(
        trial_numbers,
        values,
        color=ACCENT,
        linewidth=1.9,
        marker="o",
        markersize=5.1,
        markerfacecolor=PANEL,
    )
    run_axis.axhspan(spec.lsl, spec.usl, color="#E8F4EE", alpha=0.72, zorder=0)
    run_axis.axhline(report.mean, color=OVERALL, linewidth=1.6, linestyle="--", label="Mean")
    _draw_horizontal_spec_lines(run_axis, report)
    run_axis.set_xlim(1, report.sample_count)
    run_axis.set_title("Run Chart (30 Trials)", fontsize=16, color=INK, pad=12)
    run_axis.set_xlabel("Trial", color=INK)
    run_axis.set_ylabel("Measurement", color=INK)
    run_axis.legend(
        loc="upper left",
        frameon=True,
        framealpha=0.95,
        facecolor=PANEL,
        edgecolor="#D9E0E7",
        fontsize=10.5,
    )

    _style_plot_axis(probability_axis)
    probability_values = np.sort(values)
    plotting_positions = [
        (index - 0.375) / (report.sample_count + 0.25)
        for index in range(1, report.sample_count + 1)
    ]
    theoretical_quantiles = np.array(
        [NormalDist().inv_cdf(position) for position in plotting_positions]
    )
    slope, intercept = np.polyfit(theoretical_quantiles, probability_values, 1)
    fit_line = slope * theoretical_quantiles + intercept
    probability_axis.scatter(
        theoretical_quantiles,
        probability_values,
        color=ACCENT,
        edgecolors=PANEL,
        s=52,
        linewidths=0.7,
        zorder=3,
    )
    probability_axis.plot(
        theoretical_quantiles,
        fit_line,
        color=WARNING,
        linewidth=2.2,
        label="Best Fit",
    )
    probability_axis.set_title("Normal Probability Plot", fontsize=16, color=INK, pad=12)
    probability_axis.set_xlabel("Normal Quantile", color=INK)
    probability_axis.set_ylabel("Ordered Measurement", color=INK)
    probability_axis.legend(
        loc="upper left",
        frameon=True,
        framealpha=0.95,
        facecolor=PANEL,
        edgecolor="#D9E0E7",
        fontsize=10.5,
    )

    return figure


def create_axis_summary_figure(
    report: AxisReport,
    *,
    figure_size: tuple[float, float] = (15.4, 9.8),
) -> Figure:
    figure = Figure(figsize=figure_size, facecolor=PAPER, layout="constrained")
    summary_axis = figure.add_subplot(111)
    _draw_summary_sheet(summary_axis, report)
    return figure


def create_capability_histogram_figure(
    report: AxisReport,
    *,
    figure_size: tuple[float, float] = (15.2, 8.8),
) -> Figure:
    return _create_single_chart_figure(
        report,
        "Capability Histogram",
        _plot_histogram_panel,
        figure_size=figure_size,
    )


def create_normal_probability_figure(
    report: AxisReport,
    *,
    figure_size: tuple[float, float] = (15.2, 8.8),
) -> Figure:
    return _create_single_chart_figure(
        report,
        "Normal Probability Plot",
        _plot_probability_panel,
        figure_size=figure_size,
    )


def create_run_chart_figure(
    report: AxisReport,
    *,
    figure_size: tuple[float, float] = (15.2, 8.8),
) -> Figure:
    return _create_single_chart_figure(
        report,
        "Run Chart (30 Trials)",
        _plot_run_chart_panel,
        figure_size=figure_size,
    )


def create_capability_summary_figure(
    report: AxisReport,
    *,
    figure_size: tuple[float, float] = (15.4, 9.8),
) -> Figure:
    return create_axis_summary_figure(report, figure_size=figure_size)


def _performance_rows(report: AxisReport):
    models = (report.observed_ppm, report.overall_ppm, report.within_ppm)
    return [
        ("Below LSL", *(format_ppm(p.below) for p in models)),
        ("Above USL", *(format_ppm(p.above) for p in models)),
        ("Total", *(format_ppm(p.total) for p in models)),
    ]


def create_performance_figure(
    report: AxisReport, *, figure_size: tuple[float, float] = (11.8, 7.2)
) -> Figure:
    figure = Figure(figsize=figure_size, facecolor=PAPER, layout="constrained")
    axis = figure.subplots()
    axis.set_axis_off()
    axis.text(.04, .91, f"Axis {report.spec.axis_name}   /   Performance", fontsize=22, color=INK)
    axis.text(.04, .80, f"Cpm {format_metric(report.cpm, 3)}    |    "
              f"Outside specification: {report.observed_oos_count} of {report.sample_count}", fontsize=14)
    table = axis.table(cellText=_performance_rows(report),
                       colLabels=("PPM", "Observed", "Expected overall", "Expected within"),
                       bbox=(.04, .31, .92, .40), cellLoc="right")
    table.auto_set_font_size(False)
    table.set_fontsize(12)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor(PANEL)
        cell.set_facecolor(ACCENT if row == 0 else ACCENT_SOFT)
        cell.get_text().set_color(PANEL if row == 0 else INK)
    axis.text(.04, .23, "Expected PPM assumes a normal distribution.", fontsize=12, color=MUTED)
    return figure


def _create_single_chart_figure(
    report: AxisReport,
    title: str,
    plotter,
    *,
    figure_size: tuple[float, float] = (15.2, 8.8),
) -> Figure:
    figure = Figure(figsize=figure_size, facecolor=PAPER)
    axis = figure.add_subplot(111)
    figure.subplots_adjust(left=0.075, right=0.985, top=0.90, bottom=0.12)
    plotter(axis, report)
    return figure


def figure_to_png_bytes(figure: Figure, *, dpi: int = SECTION_RENDER_DPI) -> bytes:
    buffer = BytesIO()
    try:
        figure.savefig(
            buffer,
            format="png",
            dpi=dpi,
            facecolor=figure.get_facecolor(),
        )
        return buffer.getvalue()
    finally:
        figure.clear()


def _register_fonts() -> tuple[str, str]:
    regular_candidates = [
        Path("C:/Windows/Fonts/tahoma.ttf"),
        Path("C:/Windows/Fonts/LeelawUI.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    bold_candidates = [
        Path("C:/Windows/Fonts/tahomabd.ttf"),
        Path("C:/Windows/Fonts/leelawdb.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
    ]

    regular_path = next((path for path in regular_candidates if path.exists()), None)
    bold_path = next((path for path in bold_candidates if path.exists()), None)

    if regular_path is None:
        return "Helvetica", "Helvetica-Bold"

    regular_name = "ReportUIFont"
    if regular_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))

    if bold_path is None:
        return regular_name, regular_name

    bold_name = "ReportUIFontBold"
    if bold_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
    return regular_name, bold_name


def _draw_vertical_spec_lines(axis, report: AxisReport) -> None:
    axis.axvline(report.spec.lsl, color=SPEC, linewidth=1.5, linestyle="-", label="LSL")
    axis.axvline(report.spec.usl, color=SPEC, linewidth=1.5, linestyle="-", label="USL")
    axis.axvline(
        report.spec.resolved_target,
        color=TARGET,
        linewidth=1.3,
        linestyle=":",
        label="Target" if report.spec.target is not None else "Spec midpoint",
    )


def _draw_horizontal_spec_lines(axis, report: AxisReport) -> None:
    axis.axhline(report.spec.lsl, color=SPEC, linewidth=1.4, linestyle="-", label="LSL")
    axis.axhline(report.spec.usl, color=SPEC, linewidth=1.4, linestyle="-", label="USL")
    axis.axhline(
        report.spec.resolved_target,
        color=TARGET,
        linewidth=1.2,
        linestyle=":",
        label="Target" if report.spec.target is not None else "Spec midpoint",
    )


def _plot_histogram_panel(axis, report: AxisReport) -> None:
    values = np.array(report.values, dtype=float)
    x_min, x_max = _expanded_limits(report)
    _style_plot_axis(axis)
    bins = min(12, max(6, int(round(math.sqrt(report.sample_count) * 1.8))))
    _, edges, _ = axis.hist(
        values,
        bins=bins,
        color=ACCENT_SOFT,
        edgecolor=ACCENT,
        linewidth=1.1,
        alpha=0.95,
    )
    bin_width = edges[1] - edges[0] if len(edges) > 1 else 1.0
    xs = np.linspace(x_min, x_max, 400)
    if report.within_std > 0:
        axis.plot(
            xs,
            _scaled_pdf(xs, report.mean, report.within_std, report.sample_count, bin_width),
            color=WITHIN,
            linewidth=2.5,
            label="Within Curve",
        )
    if report.overall_std > 0:
        axis.plot(
            xs,
            _scaled_pdf(xs, report.mean, report.overall_std, report.sample_count, bin_width),
            color=OVERALL,
            linewidth=2.3,
            linestyle="--",
            label="Overall Curve",
        )
    _draw_vertical_spec_lines(axis, report)
    axis.set_title("Capability Histogram", fontsize=16, color=INK, pad=12)
    axis.set_xlabel("Measurement", color=INK)
    axis.set_ylabel("Frequency", color=INK)
    axis.legend(
        loc="upper left",
        frameon=True,
        framealpha=0.95,
        facecolor=PANEL,
        edgecolor="#D9E0E7",
        fontsize=10.5,
    )


def _plot_run_chart_panel(axis, report: AxisReport) -> None:
    values = np.array(report.values, dtype=float)
    spec = report.spec
    _style_plot_axis(axis)
    trial_numbers = np.arange(1, report.sample_count + 1)
    axis.plot(
        trial_numbers,
        values,
        color=ACCENT,
        linewidth=1.9,
        marker="o",
        markersize=5.1,
        markerfacecolor=PANEL,
    )
    axis.axhspan(spec.lsl, spec.usl, color="#E8F4EE", alpha=0.72, zorder=0)
    axis.axhline(report.mean, color=OVERALL, linewidth=1.6, linestyle="--", label="Mean")
    _draw_horizontal_spec_lines(axis, report)
    axis.set_xlim(1, report.sample_count)
    axis.set_title("Run Chart (30 Trials)", fontsize=16, color=INK, pad=12)
    axis.set_xlabel("Trial", color=INK)
    axis.set_ylabel("Measurement", color=INK)
    axis.legend(
        loc="upper left",
        frameon=True,
        framealpha=0.95,
        facecolor=PANEL,
        edgecolor="#D9E0E7",
        fontsize=10.5,
    )


def _plot_probability_panel(axis, report: AxisReport) -> None:
    values = np.array(report.values, dtype=float)
    _style_plot_axis(axis)
    probability_values = np.sort(values)
    plotting_positions = [
        (index - 0.375) / (report.sample_count + 0.25)
        for index in range(1, report.sample_count + 1)
    ]
    theoretical_quantiles = np.array(
        [NormalDist().inv_cdf(position) for position in plotting_positions]
    )
    slope, intercept = np.polyfit(theoretical_quantiles, probability_values, 1)
    fit_line = slope * theoretical_quantiles + intercept
    axis.scatter(
        theoretical_quantiles,
        probability_values,
        color=ACCENT,
        edgecolors=PANEL,
        s=52,
        linewidths=0.7,
        zorder=3,
    )
    axis.plot(
        theoretical_quantiles,
        fit_line,
        color=WARNING,
        linewidth=2.2,
        label="Best Fit",
    )
    axis.set_title("Normal Probability Plot", fontsize=16, color=INK, pad=12)
    axis.set_xlabel("Normal Quantile", color=INK)
    axis.set_ylabel("Ordered Measurement", color=INK)
    axis.legend(
        loc="upper left",
        frameon=True,
        framealpha=0.95,
        facecolor=PANEL,
        edgecolor="#D9E0E7",
        fontsize=10.5,
    )


def _draw_summary_panel(summary_axis, report: AxisReport, x_min: float, x_max: float) -> None:
    summary_axis.set_facecolor(PANEL)
    summary_axis.set_xticks([])
    summary_axis.set_yticks([])
    for spine in summary_axis.spines.values():
        spine.set_color("#D9E0E7")
        spine.set_linewidth(1.1)

    status_color = STATUS_COLORS[report.status]
    spec = report.spec

    summary_axis.text(
        0.03,
        0.94,
        "Capability Summary",
        transform=summary_axis.transAxes,
        fontsize=17,
        fontweight="bold",
        color=INK,
    )
    summary_axis.text(
        0.97,
        0.94,
        report.status,
        transform=summary_axis.transAxes,
        fontsize=15,
        fontweight="bold",
        ha="right",
        color=status_color,
    )

    left_metrics = [
        ("Axis", spec.axis_name),
        ("Samples", str(report.sample_count)),
        ("Mean", format_metric(report.mean)),
        ("Min / Max", f"{format_metric(report.minimum)} / {format_metric(report.maximum)}"),
        ("Within Stdev", format_metric(report.within_std)),
        ("Overall Stdev", format_metric(report.overall_std)),
    ]
    right_metrics = [
        ("Cp / Cpk", f"{format_metric(report.cp, 3)} / {format_metric(report.cpk, 3)}"),
        ("Cpu / Cpl", f"{format_metric(report.cpu, 3)} / {format_metric(report.cpl, 3)}"),
        ("Pp / Ppk", f"{format_metric(report.pp, 3)} / {format_metric(report.ppk, 3)}"),
        ("Ppu / Ppl", f"{format_metric(report.ppu, 3)} / {format_metric(report.ppl, 3)}"),
        ("Predicted OOS", format_ppm(report.predicted_oos_ppm) + " ppm"),
    ]
    if report.observed_oos_count > 0:
        right_metrics.insert(
            4,
            ("Observed OOS", f"{report.observed_oos_count} ({report.observed_oos_percent:.2f}%)"),
        )

    _draw_metric_column(summary_axis, left_metrics, label_x=0.04, value_x=0.34, top_y=0.83)
    _draw_metric_column(summary_axis, right_metrics, label_x=0.55, value_x=0.86, top_y=0.83)

    detail_y = 0.31
    detail_lines = [
        f"Spec Limits: {format_metric(spec.lsl)} to {format_metric(spec.usl)}",
        f"Target: {spec.target if spec.target is not None else 'Not set'}",
        f"Required Cpk: >= {format_metric(spec.cpk_requirement, 2)}",
        f"Expected Yield: {format_metric(report.expected_yield_percent, 3, unit='%')}",
    ]
    for line in detail_lines:
        summary_axis.text(
            0.05,
            detail_y,
            line,
            transform=summary_axis.transAxes,
            fontsize=10.7,
            color=INK,
            va="top",
        )
        detail_y -= 0.048

    gauge_axis = summary_axis.inset_axes([0.08, 0.05, 0.84, 0.16])
    gauge_axis.set_facecolor(PANEL)
    gauge_axis.axvspan(spec.lsl, spec.usl, color="#E8F4EE", alpha=0.95)
    gauge_axis.axvline(spec.lsl, color=SPEC, linewidth=1.6)
    gauge_axis.axvline(spec.usl, color=SPEC, linewidth=1.6)
    gauge_axis.axvline(spec.resolved_target, color=TARGET, linewidth=1.4, linestyle=":")
    _plot_sigma_span(gauge_axis, report.mean, report.overall_std, 1.0, OVERALL)
    _plot_sigma_span(gauge_axis, report.mean, report.within_std, 0.0, WITHIN)
    gauge_axis.scatter([report.mean], [0.5], s=55, color=ACCENT, zorder=4)
    gauge_axis.set_yticks([0.0, 1.0], ["Within", "Overall"])
    gauge_axis.set_xlim(x_min, x_max)
    gauge_axis.set_title("Process Spread vs Spec", fontsize=11.8, color=INK, pad=8)
    gauge_axis.grid(axis="x", color="#E6ECF2", linewidth=0.8, alpha=0.8)
    gauge_axis.tick_params(axis="x", labelsize=9.2, colors=MUTED)
    gauge_axis.tick_params(axis="y", labelsize=9.2, colors=MUTED)
    for spine in gauge_axis.spines.values():
        spine.set_color("#D9E0E7")


def _draw_summary_sheet(summary_axis, report: AxisReport) -> None:
    summary_axis.set_facecolor(PANEL)
    summary_axis.set_xticks([])
    summary_axis.set_yticks([])
    for spine in summary_axis.spines.values():
        spine.set_color("#D9E0E7")
        spine.set_linewidth(1.2)

    spec = report.spec
    status_color = STATUS_COLORS[report.status]

    summary_axis.text(
        0.04,
        0.95,
        "Capability Summary",
        transform=summary_axis.transAxes,
        fontsize=23,
        fontweight="bold",
        color=INK,
        va="top",
    )
    summary_axis.text(
        0.96,
        0.95,
        report.status,
        transform=summary_axis.transAxes,
        fontsize=20,
        fontweight="bold",
        color=status_color,
        ha="right",
        va="top",
    )

    summary_axis.text(
        0.04,
        0.90,
        (
            f"Axis {spec.axis_name}   |   Samples {report.sample_count}   |   "
            f"Required Cpk >= {format_metric(spec.cpk_requirement, 2)}"
        ),
        transform=summary_axis.transAxes,
        fontsize=12,
        color=MUTED,
        va="top",
    )

    left_metrics = [
        ("Mean", format_metric(report.mean)),
        ("Minimum", format_metric(report.minimum)),
        ("Maximum", format_metric(report.maximum)),
        ("Range", format_metric(report.range_value)),
        ("Within Stdev", format_metric(report.within_std)),
        ("Overall Stdev", format_metric(report.overall_std)),
        ("Avg Moving Range", format_metric(report.average_moving_range)),
    ]
    right_metrics = [
        ("Cp / Cpk", f"{format_metric(report.cp, 3)} / {format_metric(report.cpk, 3)}"),
        ("Cpu / Cpl", f"{format_metric(report.cpu, 3)} / {format_metric(report.cpl, 3)}"),
        ("Pp / Ppk", f"{format_metric(report.pp, 3)} / {format_metric(report.ppk, 3)}"),
        ("Ppu / Ppl", f"{format_metric(report.ppu, 3)} / {format_metric(report.ppl, 3)}"),
        ("Predicted OOS", format_ppm(report.predicted_oos_ppm) + " ppm"),
        ("Expected Yield", format_metric(report.expected_yield_percent, 3, unit="%")),
    ]
    if report.observed_oos_count > 0:
        right_metrics.insert(
            4,
            ("Observed OOS", f"{report.observed_oos_count} ({report.observed_oos_percent:.2f}%)"),
        )

    _draw_metric_column(summary_axis, left_metrics, label_x=0.06, value_x=0.44, top_y=0.80, row_gap=0.074)
    _draw_metric_column(summary_axis, right_metrics, label_x=0.54, value_x=0.93, top_y=0.80, row_gap=0.074)

    summary_axis.text(
        0.06,
        0.24,
        f"Specification Window: {format_metric(spec.lsl)} to {format_metric(spec.usl)}",
        transform=summary_axis.transAxes,
        fontsize=11.2,
        color=INK,
        va="top",
    )
    summary_axis.text(
        0.06,
        0.205,
        f"Target: {spec.target if spec.target is not None else 'Not set'}",
        transform=summary_axis.transAxes,
        fontsize=11.2,
        color=INK,
        va="top",
    )
    summary_axis.text(
        0.52,
        0.24,
        (
            "Judgement: " +
            ("No measurable variation" if report.within_std == 0 else
             "Meets requirement" if report.status == "PASS" else "Requires attention")
        ),
        transform=summary_axis.transAxes,
        fontsize=11.2,
        color=INK,
        va="top",
    )
    summary_axis.text(
        0.5,
        0.165,
        "Process Spread vs Specification",
        transform=summary_axis.transAxes,
        fontsize=13.2,
        fontweight="bold",
        color=INK,
        ha="center",
        va="center",
    )

    gauge_axis = summary_axis.inset_axes([0.08, 0.055, 0.84, 0.10])
    x_min, x_max = _expanded_limits(report)
    gauge_axis.set_facecolor(PANEL)
    gauge_axis.axvspan(spec.lsl, spec.usl, color="#E8F4EE", alpha=0.95)
    gauge_axis.axvline(spec.lsl, color=SPEC, linewidth=1.8)
    gauge_axis.axvline(spec.usl, color=SPEC, linewidth=1.8)
    gauge_axis.axvline(spec.resolved_target, color=TARGET, linewidth=1.5, linestyle=":")
    _plot_sigma_span(gauge_axis, report.mean, report.overall_std, 1.0, OVERALL)
    _plot_sigma_span(gauge_axis, report.mean, report.within_std, 0.0, WITHIN)
    gauge_axis.scatter([report.mean], [0.5], s=62, color=ACCENT, zorder=4)
    gauge_axis.set_yticks([0.0, 1.0], ["Within", "Overall"])
    gauge_axis.set_xlim(x_min, x_max)
    gauge_axis.grid(axis="x", color="#E6ECF2", linewidth=0.9, alpha=0.9)
    gauge_axis.tick_params(axis="x", labelsize=10, colors=MUTED)
    gauge_axis.tick_params(axis="y", labelsize=10, colors=MUTED)
    for spine in gauge_axis.spines.values():
        spine.set_color("#D9E0E7")


def _plot_sigma_span(axis, mean: float, sigma: float, y_value: float, color: str) -> None:
    if sigma > 0:
        lower = mean - (3.0 * sigma)
        upper = mean + (3.0 * sigma)
    else:
        lower = mean
        upper = mean
    axis.hlines(y_value, lower, upper, color=color, linewidth=4.2)
    axis.scatter([lower, upper], [y_value, y_value], color=color, s=42, zorder=3)


def _draw_metric_column(
    summary_axis,
    metrics: list[tuple[str, str]],
    *,
    label_x: float,
    value_x: float,
    top_y: float,
    row_gap: float = 0.09,
) -> None:
    y_position = top_y
    for label, value in metrics:
        summary_axis.text(
            label_x,
            y_position,
            label,
            transform=summary_axis.transAxes,
            fontsize=10.6,
            color=MUTED,
            va="top",
            fontweight="bold",
        )
        summary_axis.text(
            value_x,
            y_position,
            value,
            transform=summary_axis.transAxes,
            fontsize=10.8,
            color=INK,
            va="top",
            ha="right",
        )
        y_position -= row_gap


def _expanded_limits(report: AxisReport) -> tuple[float, float]:
    lower = min(min(report.values), report.spec.lsl)
    upper = max(max(report.values), report.spec.usl)
    spread = upper - lower
    padding = spread * 0.12 if spread > 0 else max(abs(lower), 1.0) * 0.1 or 0.1
    return lower - padding, upper + padding


def _scaled_pdf(xs: np.ndarray, mean: float, sigma: float, count: int, bin_width: float) -> np.ndarray:
    coefficient = 1.0 / (sigma * math.sqrt(2.0 * math.pi))
    exponent = -0.5 * ((xs - mean) / sigma) ** 2
    return coefficient * np.exp(exponent) * count * bin_width


def _style_plot_axis(axis) -> None:
    axis.set_facecolor(PANEL)
    axis.grid(True, color="#E6ECF2", linewidth=0.9, alpha=0.85)
    axis.tick_params(colors=MUTED, labelsize=10)
    for spine in axis.spines.values():
        spine.set_color("#D9E0E7")
        spine.set_linewidth(1.0)

class _CapabilityPDF:
    margin = 36
    width = PAGE_WIDTH - 2 * margin

    def __init__(self, pdf: canvas.Canvas, metadata: ReportMetadata, page_count: int):
        self.pdf = pdf
        self.metadata = metadata
        self.page_count = page_count
        self.regular, self.bold = _register_fonts()

    def text(self, x, y, value, size=11, *, bold=False, color=INK, right=False, width=None):
        value = str(value)
        font = self.bold if bold else self.regular
        if width is not None:
            length = pdfmetrics.stringWidth(value, font, size)
            if length > width:
                size *= width / length
        self.pdf.setFont(font, size)
        self.pdf.setFillColor(HexColor(color))
        draw = self.pdf.drawRightString if right else self.pdf.drawString
        draw(x, y, value)

    def box(self, x, y, width, height, color):
        self.pdf.setFillColor(HexColor(color))
        self.pdf.rect(x, y, width, height, fill=1, stroke=0)

    def header(self, title, subtitle):
        key = f"page-{self.pdf.getPageNumber()}"
        self.pdf.bookmarkPage(key)
        self.pdf.addOutlineEntry(title, key)
        self.text(36, 560, "QUALITY ENGINEERING   /   REPEATABILITY", 10, bold=True, color=ACCENT)
        self.text(PAGE_WIDTH - 36, 560, self.metadata.report_date, 10, right=True, width=280)
        self.text(36, 519, title, 28, bold=True, width=self.width)
        self.text(36, 496, subtitle, 11, color=MUTED, width=self.width)
        self.box(36, 482, self.width, 0.6, "#CCDAD9")

    def finish(self):
        self.box(36, 34, self.width, 0.6, "#CCDAD9")
        machine = "   /   ".join(filter(None, (self.metadata.machine_model, self.metadata.serial_number)))
        self.text(36, 17, machine, 9, color=MUTED, width=self.width - 80)
        self.text(PAGE_WIDTH - 36, 17, f"{self.pdf.getPageNumber()} / {self.page_count}", 9, right=True)
        self.pdf.showPage()

    def table(self, x, top, width, headers, rows, fractions, row_height=24):
        def draw_row(values, y, header):
            left = x
            for i, (value, fraction) in enumerate(zip(values, fractions)):
                cell = width * fraction
                right = i > 0
                self.text(left + cell - 7 if right else left + 7, y + 7, value, 10.5,
                          bold=header or i == 0, color=PANEL if header else INK,
                          right=right, width=cell - 14)
                left += cell

        y = top - row_height
        self.box(x, y, width, row_height, "#244558")
        draw_row(headers, y, True)
        for i, row in enumerate(rows):
            y -= row_height
            if i % 2 == 0:
                self.box(x, y, width, row_height, "#F0F5F5")
            draw_row(row, y, False)

    def overview(self, all_reports, page_reports, first, notes):
        meta = self.metadata
        result = overall_result(all_reports)
        title = meta.report_title or "Machine repeatability study"
        self.header(title if first else "Axis summary (continued)",
                    f"{len(all_reports)} axes   /   {all_reports[0].sample_count} measurements per axis   /   Millimetres")
        labels = {"PASS": "All axes meet the study criteria", "FAIL": "One or more axes failed",
                  "N/A": "Capability could not be assessed for all axes"}
        self.box(36, 389, self.width, 71, "#F0F5F5")
        self.text(50, 431, f"{result}   /   {labels[result]}", 19, bold=True, color=STATUS_COLORS[result])
        defined = [report for report in all_reports if math.isfinite(report.cpk)]
        outside = sum(report.observed_oos_count for report in all_reports)
        trials = sum(report.sample_count for report in all_reports)
        reason = f"Outside specification: {outside} of {trials} readings."
        if defined:
            lowest = min(defined, key=lambda report: report.cpk)
            reason += f" Lowest measured Cpk: {format_metric(lowest.cpk, 3)} on axis {lowest.spec.axis_name}."
        if len(defined) < len(all_reports):
            reason += " N/A indicates no measurable variation."
        self.text(50, 406, reason, width=self.width - 28)
        self.text(36, 361, "Acceptance criteria", 13, bold=True)
        self.text(36, 341, "Each unrounded Cpk must meet its required value, with all readings inside or on the specification limits.")
        rows = []
        for r in page_reports:
            rows.append((r.spec.axis_name, r.sample_count, format_metric(r.mean, 5),
                         str(r.spec.cpk_requirement), format_metric(r.cpk, 3), format_metric(r.ppk, 3),
                         format_metric(r.cpm, 3), f"{r.observed_oos_count} / {r.sample_count}", r.status))
        self.table(36, 319, self.width,
                   ("Axis", "N", "Mean (mm)", "Required Cpk", "Cpk", "Ppk", "Cpm", "Outside spec", "Result"),
                   rows, (.16, .05, .15, .14, .09, .09, .09, .13, .10))
        self.text(36, 177, "Study details", 13, bold=True)
        left = (("Customer", meta.customer_name), ("Machine", meta.machine_name),
                ("Model", meta.machine_model), ("Serial number", meta.serial_number))
        right = (("Part", meta.part_name), ("Measurement tool", meta.measurement_tool_name),
                 ("Tool model", meta.measurement_tool_model), ("Inspector", meta.inspected_by))
        for x, details in ((36, left), (422, right)):
            for i, (label, value) in enumerate(details):
                self.text(x, 157 - 17*i, label, 10, color=MUTED)
                self.text(x + 98, 157 - 17*i, value or "-", 10, width=270)
        if notes:
            self.text(36, 83, "Notes", 11, bold=True)
            for i, note in enumerate(notes):
                self.text(36, 66 - 14*i, note, 10, width=self.width)
        self.finish()

    def metric_list(self, x, right, title, items):
        self.text(x, 458, title, 13, bold=True, color=ACCENT)
        for i, (label, value) in enumerate(items):
            y = 433 - 20*i
            self.text(x, y, label, 10)
            self.text(right, y, value, 10, bold=True, right=True, width=right-x-65)

    def chart(self, report, plotter, x, y, width, height):
        fig = Figure(figsize=(width/63, height/63), layout="constrained", facecolor=PANEL)
        axis = fig.subplots()
        plotter(axis, report)
        axis.set_title("")
        axis.tick_params(labelsize=9)
        axis.xaxis.label.set_size(10)
        axis.yaxis.label.set_size(10)
        axis.ticklabel_format(useOffset=False)
        axis.legend(loc="best", fontsize=8)
        image = ImageReader(BytesIO(figure_to_png_bytes(fig)))
        self.pdf.drawImage(image, x, y, width, height)

    def capability(self, r):
        spec = r.spec
        details = (f"{r.status}   |   Required Cpk {spec.cpk_requirement}   |   Actual Cpk {format_metric(r.cpk, 3)}"
                   f"   |   {r.observed_oos_count} of {r.sample_count} outside specification")
        self.header(f"Axis {spec.axis_name}   /   Capability summary", details)
        self.metric_list(36, 187, "Process data (mm)", [
            ("LSL", str(spec.lsl)), ("Target", str(spec.target) if spec.target is not None else "Not set"),
            ("USL", str(spec.usl)), ("Sample mean", format_metric(r.mean, 5)),
            ("Within StDev", format_metric(r.within_std, 5)), ("Overall StDev", format_metric(r.overall_std, 5)),
            ("Minimum", str(r.minimum)), ("Maximum", str(r.maximum)),
        ])
        self.text(208, 458, "Capability histogram", 13, bold=True, color=ACCENT)
        self.chart(r, _plot_histogram_panel, 198, 248, 397, 200)
        self.metric_list(612, PAGE_WIDTH-36, "Capability indices", [
            ("Cp", format_metric(r.cp, 3)), ("CPL / CPU", f"{format_metric(r.cpl, 3)} / {format_metric(r.cpu, 3)}"),
            ("Cpk", format_metric(r.cpk, 3)), ("Pp", format_metric(r.pp, 3)),
            ("PPL / PPU", f"{format_metric(r.ppl, 3)} / {format_metric(r.ppu, 3)}"),
            ("Ppk", format_metric(r.ppk, 3)), ("Cpm", format_metric(r.cpm, 3)),
        ])
        self.box(36, 245, self.width, .6, "#CCDAD9")
        self.text(36, 222, "Performance in parts per million (PPM)", 14, bold=True)
        self.table(36, 208, self.width, ("Position", "Observed", "Expected overall", "Expected within"),
                   _performance_rows(r), (.30, .20, .25, .25), 23)
        self.text(36, 94, f"Observed PPM uses {r.sample_count} readings. Expected PPM assumes a normal distribution. Positive estimates below 0.001 PPM appear as < 0.001.", 10, width=self.width)
        self.text(36, 74, "Within StDev = mean moving range / 1.128. Overall StDev = sample standard deviation (n - 1).", 9, color=MUTED)
        self.text(36, 55, "Cpm = (USL - LSL) / [6 x sqrt(overall variance + (mean - target) squared)]. Cpm requires a target and measurable variation.", 9, color=MUTED)
        self.finish()

    def diagnostics(self, r):
        self.header(f"Axis {r.spec.axis_name}   /   Diagnostic charts",
                    "Measurement sequence, normal-model fit and estimated spread relative to the specification limits.")
        for x, title, plotter in [(36, "Run chart", _plot_run_chart_panel),
                                  (433, "Normal probability plot", _plot_probability_panel)]:
            self.text(x, 458, title, 14, bold=True, color=ACCENT)
            self.chart(r, plotter, x, 206, 370, 235)
        self.box(36, 192, self.width, .6, "#CCDAD9")
        self.text(36, 168, "Process spread vs. specification", 14, bold=True)
        fig = Figure(figsize=(10.9, 1.45), layout="constrained", facecolor=PANEL)
        ax = fig.subplots()
        ax.axvspan(r.spec.lsl, r.spec.usl, color="#EAF5F2")
        for limit in (r.spec.lsl, r.spec.usl):
            ax.axvline(limit, color=SPEC, linewidth=1.1)
        if r.spec.target is not None:
            ax.axvline(r.spec.target, color=TARGET, linestyle=":")
        for y, sigma, color in [(1, r.overall_std, OVERALL), (0, r.within_std, WITHIN)]:
            _plot_sigma_span(ax, r.mean, sigma, y, color)
            ax.scatter([r.mean], [y], color=color, s=18)
        ax.set_yticks([0,1], ["Within", "Overall"])
        ax.set_ylim(-.6,1.6)
        ax.ticklabel_format(axis="x", useOffset=False)
        self.pdf.drawImage(ImageReader(BytesIO(figure_to_png_bytes(fig))), 38, 67, self.width-4, 93)
        self.text(36, 49, "Each bar spans the mean plus or minus three standard deviations. The centre dot marks the sample mean. Measurements in mm.", 10, color=MUTED)
        self.finish()

    def measurements(self, group):
        self.header("Measurement data", "Readings in acquisition order. One row per trial; all dimensions in millimetres.")
        headers = ["Trial", *(r.spec.axis_name + " (mm)" for r in group)]
        fractions = [.15] + [.85 / len(group)] * len(group)
        for start, x in ((0, 36), (15, 431)):
            rows = [(i+1, *(str(r.values[i]) for r in group)) for i in range(start, start + 15)]
            self.table(x, 457, 374, headers, rows, fractions)
        self.text(36, 52, "The values shown here were used to calculate the capability and performance results.", 10, color=MUTED)
        self.finish()


def export_pdf(metadata: ReportMetadata, reports: list[AxisReport], output_path: str | Path) -> Path:
    if not reports:
        raise ValueError("At least one axis is required to export a report.")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    regular, _ = _register_fonts()
    notes = simpleSplit(metadata.notes.strip(), regular, 10, _CapabilityPDF.width) if metadata.notes.strip() else []
    overflow_notes = [notes[i:i+25] for i in range(2, len(notes), 25)]
    overview_groups = [reports[i:i+4] for i in range(0, len(reports), 4)]
    measurement_groups = [reports[i:i+3] for i in range(0, len(reports), 3)]
    page_count = len(overview_groups) + 2*len(reports) + len(measurement_groups) + len(overflow_notes)

    # Finish the new document before replacing an existing customer report.
    with NamedTemporaryFile(dir=destination.parent, suffix=".pdf", delete=False) as staged:
        staged_path = Path(staged.name)
    try:
        pdf = canvas.Canvas(str(staged_path), pagesize=PAGE_SIZE)
        pdf.setTitle(metadata.report_title or "Machine repeatability study")
        writer = _CapabilityPDF(pdf, metadata, page_count)
        for i, group in enumerate(overview_groups):
            writer.overview(reports, group, i == 0, notes[:2] if i == 0 else [])
        for lines in overflow_notes:
            writer.header("Study notes", metadata.report_title)
            for i, note in enumerate(lines):
                writer.text(36, 458 - i*16, note, 10, width=writer.width)
            writer.finish()
        for report in reports:
            writer.capability(report)
            writer.diagnostics(report)
        for group in measurement_groups:
            writer.measurements(group)
        pdf.save()
        staged_path.replace(destination)
    finally:
        staged_path.unlink(missing_ok=True)
    return destination
