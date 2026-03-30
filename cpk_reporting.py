from __future__ import annotations

from collections import OrderedDict
from io import BytesIO
import math
from pathlib import Path
import textwrap
from statistics import NormalDist

from matplotlib.figure import Figure
import numpy as np
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from cpk_tool.analysis import AxisReport, ReportMetadata, format_metric


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
WITHIN = "#D97706"
OVERALL = "#2563EB"
SPEC = "#B91C1C"
TARGET = "#7C3AED"
SECTION_RENDER_DPI = 160
SECTION_IMAGE_CACHE_LIMIT = 48
_SECTION_IMAGE_CACHE: OrderedDict[tuple[object, ...], bytes] = OrderedDict()


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


SECTION_FACTORIES = (
    ("Capability Histogram", create_capability_histogram_figure),
    ("Normal Probability Plot", create_normal_probability_figure),
    ("Run Chart (30 Trials)", create_run_chart_figure),
    ("Capability Summary", create_capability_summary_figure),
)


def export_pdf(metadata: ReportMetadata, reports: list[AxisReport], output_path: str | Path) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    regular_font, bold_font = _register_fonts()
    pdf = canvas.Canvas(str(destination), pagesize=PAGE_SIZE, pageCompression=0)
    pdf.setTitle(metadata.report_title or "Machine Capability Report")

    _draw_cover_page(pdf, metadata, reports, regular_font, bold_font)
    page_number = 2
    for report in reports:
        for section_index, (section_title, figure_factory) in enumerate(SECTION_FACTORIES, start=1):
            _draw_axis_section_page(
                pdf,
                metadata,
                report,
                regular_font,
                bold_font,
                page_number,
                section_index,
                section_title,
                figure_factory,
            )
            page_number += 1

    pdf.save()
    return destination


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


def _report_signature(report: AxisReport) -> tuple[object, ...]:
    spec = report.spec
    return (
        spec.axis_name,
        spec.lsl,
        spec.usl,
        spec.target,
        spec.cpk_requirement,
        tuple(report.values),
    )


def _get_cached_section_image(report: AxisReport, section_title: str, figure_factory) -> bytes:
    cache_key = (_report_signature(report), section_title)
    cached_image = _SECTION_IMAGE_CACHE.get(cache_key)
    if cached_image is not None:
        _SECTION_IMAGE_CACHE.move_to_end(cache_key)
        return cached_image

    image_bytes = figure_to_png_bytes(figure_factory(report))
    _SECTION_IMAGE_CACHE[cache_key] = image_bytes
    if len(_SECTION_IMAGE_CACHE) > SECTION_IMAGE_CACHE_LIMIT:
        _SECTION_IMAGE_CACHE.popitem(last=False)
    return image_bytes


def _draw_cover_page(
    pdf: canvas.Canvas,
    metadata: ReportMetadata,
    reports: list[AxisReport],
    regular_font: str,
    bold_font: str,
) -> None:
    title = metadata.report_title or "Machine Cpk Capability Report"
    overall_status = "PASS" if all(report.status == "PASS" for report in reports) else "FAIL"
    status_color = PASS if overall_status == "PASS" else FAIL

    pdf.setFillColor(HexColor(PAPER))
    pdf.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)

    pdf.setFillColor(HexColor(INK))
    pdf.setFont(bold_font, 24)
    pdf.drawString(PAGE_MARGIN, PAGE_HEIGHT - 52, title)

    pdf.setFillColor(HexColor(MUTED))
    pdf.setFont(regular_font, 11)
    pdf.drawString(
        PAGE_MARGIN,
        PAGE_HEIGHT - 72,
        _describe_axis_scope(reports),
    )

    _draw_status_badge(
        pdf,
        x=PAGE_WIDTH - 140,
        y=PAGE_HEIGHT - 70,
        width=96,
        height=28,
        text=overall_status,
        fill_color=status_color,
        font_name=bold_font,
        font_size=13,
    )

    info_top = PAGE_HEIGHT - 105
    info_items = [
        ("Customer", metadata.customer_name or "-"),
        ("Machine", metadata.machine_name or "-"),
        ("Machine Model", metadata.machine_model or "-"),
        ("Measurement Tool", metadata.measurement_tool_name or "-"),
        ("Tool Model", metadata.measurement_tool_model or "-"),
        ("Part Name", metadata.part_name or "-"),
        ("Serial No.", metadata.serial_number or "-"),
        ("Inspected By", metadata.inspected_by or "-"),
        ("Report Date", metadata.report_date or "-"),
    ]
    card_width = (PAGE_WIDTH - (PAGE_MARGIN * 2) - 36) / 3
    row_height = 34
    for index, (label, value) in enumerate(info_items):
        row = index % 3
        column = index // 3
        x = PAGE_MARGIN + column * (card_width + 18)
        y = info_top - (row * (row_height + 8))
        pdf.setFillColor(HexColor(PANEL))
        pdf.roundRect(x, y - row_height, card_width, row_height, 8, fill=1, stroke=0)
        pdf.setStrokeColor(HexColor("#D9E0E7"))
        pdf.roundRect(x, y - row_height, card_width, row_height, 8, fill=0, stroke=1)
        pdf.setFillColor(HexColor(MUTED))
        pdf.setFont(regular_font, 9.5)
        pdf.drawString(x + 12, y - 12, label)
        pdf.setFillColor(HexColor(INK))
        pdf.setFont(bold_font, 11)
        pdf.drawString(x + 12, y - 25, _clip_text(value, 28))

    table_top = PAGE_HEIGHT - 255
    pdf.setFillColor(HexColor(INK))
    pdf.setFont(bold_font, 15)
    pdf.drawString(PAGE_MARGIN, table_top, "Axis Summary")

    headers = ["Axis", "Mean", "Within Sigma", "Overall Sigma", "Cp", "Cpk", "Ppk", "Result"]
    widths = [70, 90, 90, 90, 70, 70, 70, 84]
    table_x = PAGE_MARGIN
    table_y = table_top - 18
    table_row_height = 28

    pdf.setFillColor(HexColor(ACCENT))
    pdf.roundRect(table_x, table_y - table_row_height, sum(widths), table_row_height, 8, fill=1, stroke=0)
    pdf.setFillColor(HexColor(PANEL))
    pdf.setFont(bold_font, 10.5)
    cell_x = table_x
    for header, width in zip(headers, widths):
        pdf.drawCentredString(cell_x + (width / 2), table_y - 18, header)
        cell_x += width

    body_y = table_y - table_row_height - 8
    for report in reports:
        pdf.setFillColor(HexColor(PANEL))
        pdf.roundRect(table_x, body_y - table_row_height + 6, sum(widths), table_row_height, 8, fill=1, stroke=0)
        pdf.setStrokeColor(HexColor("#D9E0E7"))
        pdf.roundRect(table_x, body_y - table_row_height + 6, sum(widths), table_row_height, 8, fill=0, stroke=1)

        row_values = [
            report.spec.axis_name,
            format_metric(report.mean, 4),
            format_metric(report.within_std, 4),
            format_metric(report.overall_std, 4),
            format_metric(report.cp, 3),
            format_metric(report.cpk, 3),
            format_metric(report.ppk, 3),
            report.status,
        ]
        cell_x = table_x
        for value, width in zip(row_values, widths):
            value_color = INK
            if value in {"PASS", "FAIL"}:
                value_color = PASS if value == "PASS" else FAIL
            pdf.setFillColor(HexColor(value_color))
            pdf.setFont(bold_font if value in {"PASS", "FAIL"} else regular_font, 10.5)
            pdf.drawCentredString(cell_x + (width / 2), body_y - 12, value)
            cell_x += width
        body_y -= table_row_height + 8

    notes_title_y = body_y - 18
    pdf.setFillColor(HexColor(INK))
    pdf.setFont(bold_font, 15)
    pdf.drawString(PAGE_MARGIN, notes_title_y, "Notes")

    notes_text = metadata.notes.strip() or "No additional notes."
    wrapped_lines = simpleSplit(
        notes_text,
        regular_font,
        10.5,
        PAGE_WIDTH - (PAGE_MARGIN * 2) - 24,
    )
    box_y = notes_title_y - 12
    box_height = max(84, (len(wrapped_lines) * 13) + 24)
    pdf.setFillColor(HexColor(PANEL))
    pdf.roundRect(
        PAGE_MARGIN,
        box_y - box_height,
        PAGE_WIDTH - (PAGE_MARGIN * 2),
        box_height,
        10,
        fill=1,
        stroke=0,
    )
    pdf.setStrokeColor(HexColor("#D9E0E7"))
    pdf.roundRect(
        PAGE_MARGIN,
        box_y - box_height,
        PAGE_WIDTH - (PAGE_MARGIN * 2),
        box_height,
        10,
        fill=0,
        stroke=1,
    )
    text_object = pdf.beginText(PAGE_MARGIN + 12, box_y - 20)
    text_object.setFont(regular_font, 10.5)
    text_object.setFillColor(HexColor(INK))
    for line in wrapped_lines:
        text_object.textLine(line)
    pdf.drawText(text_object)

    _draw_footer(pdf, regular_font, 1)
    pdf.showPage()


def _draw_axis_charts_page(
    pdf: canvas.Canvas,
    metadata: ReportMetadata,
    report: AxisReport,
    regular_font: str,
    bold_font: str,
    page_number: int,
) -> None:
    status_color = PASS if report.status == "PASS" else FAIL
    spec = report.spec

    pdf.setFillColor(HexColor(PAPER))
    pdf.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)

    pdf.setFillColor(HexColor(INK))
    pdf.setFont(bold_font, 20)
    pdf.drawString(PAGE_MARGIN, PAGE_HEIGHT - 44, f"Axis {spec.axis_name} Capability Analysis")

    pdf.setFillColor(HexColor(MUTED))
    pdf.setFont(regular_font, 10.5)
    subtitle = (
        f"Customer: {metadata.customer_name or '-'}   |   "
        f"Machine: {_format_machine_descriptor(metadata)}   |   "
        f"Inspector: {metadata.inspected_by or '-'}"
    )
    pdf.drawString(PAGE_MARGIN, PAGE_HEIGHT - 60, _clip_text(subtitle, 110))

    _draw_status_badge(
        pdf,
        x=PAGE_WIDTH - 140,
        y=PAGE_HEIGHT - 60,
        width=96,
        height=24,
        text=report.status,
        fill_color=status_color,
        font_name=bold_font,
        font_size=11.5,
    )

    spec_line = (
        f"LSL {format_metric(spec.lsl)}   |   "
        f"Target {format_metric(spec.resolved_target)}   |   "
        f"USL {format_metric(spec.usl)}   |   "
        f"Required Cpk >= {format_metric(spec.cpk_requirement, 2)}"
    )
    pdf.setFillColor(HexColor(INK))
    pdf.setFont(regular_font, 10)
    pdf.drawString(PAGE_MARGIN, PAGE_HEIGHT - 82, spec_line)

    image_data = _get_cached_section_image(report, "Combined Capability Charts", create_axis_pdf_charts_figure)
    image = ImageReader(BytesIO(image_data))
    pdf.drawImage(
        image,
        PAGE_MARGIN,
        32,
        width=PAGE_WIDTH - (PAGE_MARGIN * 2),
        height=PAGE_HEIGHT - 128,
        preserveAspectRatio=True,
        anchor="c",
        mask="auto",
    )

    _draw_footer(pdf, regular_font, page_number)
    pdf.showPage()


def _draw_axis_summary_page(
    pdf: canvas.Canvas,
    metadata: ReportMetadata,
    report: AxisReport,
    regular_font: str,
    bold_font: str,
    page_number: int,
) -> None:
    status_color = PASS if report.status == "PASS" else FAIL
    spec = report.spec

    pdf.setFillColor(HexColor(PAPER))
    pdf.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)

    pdf.setFillColor(HexColor(INK))
    pdf.setFont(bold_font, 20)
    pdf.drawString(PAGE_MARGIN, PAGE_HEIGHT - 44, f"Axis {spec.axis_name} Capability Analysis (2)")

    pdf.setFillColor(HexColor(MUTED))
    pdf.setFont(regular_font, 10.5)
    subtitle = (
        f"Customer: {metadata.customer_name or '-'}   |   "
        f"Machine: {_format_machine_descriptor(metadata)}   |   "
        f"Inspector: {metadata.inspected_by or '-'}"
    )
    pdf.drawString(PAGE_MARGIN, PAGE_HEIGHT - 60, _clip_text(subtitle, 110))

    _draw_status_badge(
        pdf,
        x=PAGE_WIDTH - 140,
        y=PAGE_HEIGHT - 60,
        width=96,
        height=24,
        text=report.status,
        fill_color=status_color,
        font_name=bold_font,
        font_size=11.5,
    )

    spec_line = (
        f"Capability Summary   |   "
        f"LSL {format_metric(spec.lsl)}   |   "
        f"Target {format_metric(spec.resolved_target)}   |   "
        f"USL {format_metric(spec.usl)}"
    )
    pdf.setFillColor(HexColor(INK))
    pdf.setFont(regular_font, 10)
    pdf.drawString(PAGE_MARGIN, PAGE_HEIGHT - 82, spec_line)

    image_data = _get_cached_section_image(report, "Detailed Capability Summary", create_axis_summary_figure)
    image = ImageReader(BytesIO(image_data))
    pdf.drawImage(
        image,
        PAGE_MARGIN,
        32,
        width=PAGE_WIDTH - (PAGE_MARGIN * 2),
        height=PAGE_HEIGHT - 128,
        preserveAspectRatio=True,
        anchor="c",
        mask="auto",
    )

    _draw_footer(pdf, regular_font, page_number)
    pdf.showPage()


def _draw_axis_section_page(
    pdf: canvas.Canvas,
    metadata: ReportMetadata,
    report: AxisReport,
    regular_font: str,
    bold_font: str,
    page_number: int,
    section_index: int,
    section_title: str,
    figure_factory,
) -> None:
    status_color = PASS if report.status == "PASS" else FAIL
    spec = report.spec
    title_suffix = "" if section_index == 1 else f" ({section_index})"

    pdf.setFillColor(HexColor(PAPER))
    pdf.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)

    pdf.setFillColor(HexColor(INK))
    pdf.setFont(bold_font, 20)
    pdf.drawString(PAGE_MARGIN, PAGE_HEIGHT - 44, f"Axis {spec.axis_name} Capability Analysis{title_suffix}")

    pdf.setFillColor(HexColor(MUTED))
    pdf.setFont(regular_font, 10.5)
    subtitle = (
        f"Customer: {metadata.customer_name or '-'}   |   "
        f"Machine: {_format_machine_descriptor(metadata)}   |   "
        f"Inspector: {metadata.inspected_by or '-'}"
    )
    pdf.drawString(PAGE_MARGIN, PAGE_HEIGHT - 60, _clip_text(subtitle, 110))

    _draw_status_badge(
        pdf,
        x=PAGE_WIDTH - 140,
        y=PAGE_HEIGHT - 60,
        width=96,
        height=24,
        text=report.status,
        fill_color=status_color,
        font_name=bold_font,
        font_size=11.5,
    )

    spec_line = (
        f"{section_title}   |   "
        f"LSL {format_metric(spec.lsl)}   |   "
        f"Target {format_metric(spec.resolved_target)}   |   "
        f"USL {format_metric(spec.usl)}   |   "
        f"Required Cpk >= {format_metric(spec.cpk_requirement, 2)}"
    )
    pdf.setFillColor(HexColor(INK))
    pdf.setFont(regular_font, 10)
    pdf.drawString(PAGE_MARGIN, PAGE_HEIGHT - 82, _clip_text(spec_line, 150))

    image_data = _get_cached_section_image(report, section_title, figure_factory)
    image = ImageReader(BytesIO(image_data))
    pdf.drawImage(
        image,
        PAGE_MARGIN,
        32,
        width=PAGE_WIDTH - (PAGE_MARGIN * 2),
        height=PAGE_HEIGHT - 128,
        preserveAspectRatio=True,
        anchor="c",
        mask="auto",
    )

    _draw_footer(pdf, regular_font, page_number)
    pdf.showPage()


def _draw_footer(pdf: canvas.Canvas, regular_font: str, page_number: int) -> None:
    pdf.setFillColor(HexColor(MUTED))
    pdf.setFont(regular_font, 9)
    pdf.drawString(PAGE_MARGIN, 16, "Generated by Machine Cpk Capability Reporter")
    pdf.drawRightString(PAGE_WIDTH - PAGE_MARGIN, 16, f"Page {page_number}")


def _format_machine_descriptor(metadata: ReportMetadata) -> str:
    if metadata.machine_name and metadata.machine_model:
        return f"{metadata.machine_name} ({metadata.machine_model})"
    return metadata.machine_name or metadata.machine_model or "-"


def _describe_axis_scope(reports: list[AxisReport]) -> str:
    axis_names = [report.spec.axis_name for report in reports]
    if not axis_names:
        return "Machine capability report for repeatability verification"

    axis_list = ", ".join(axis_names)
    if len(axis_names) <= 6 and len(axis_list) <= 48:
        return f"Machine capability report for repeatability verification across {axis_list}"
    return (
        "Machine capability report for repeatability verification across "
        f"{len(axis_names)} axes"
    )


def _draw_status_badge(
    pdf: canvas.Canvas,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    text: str,
    fill_color: str,
    font_name: str,
    font_size: float,
) -> None:
    pdf.setFillColor(HexColor(fill_color))
    pdf.roundRect(x, y, width, height, 8, fill=1, stroke=0)

    ascent = pdfmetrics.getAscent(font_name) * font_size / 1000.0
    descent = abs(pdfmetrics.getDescent(font_name) * font_size / 1000.0)
    baseline = y + ((height - ascent + descent) / 2.0)

    pdf.setFillColor(HexColor(PANEL))
    pdf.setFont(font_name, font_size)
    pdf.drawCentredString(x + (width / 2.0), baseline, text)


def _register_fonts() -> tuple[str, str]:
    regular_candidates = [
        Path("C:/Windows/Fonts/LeelawUI.ttf"),
        Path("C:/Windows/Fonts/tahoma.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    bold_candidates = [
        Path("C:/Windows/Fonts/leelawdb.ttf"),
        Path("C:/Windows/Fonts/tahomabd.ttf"),
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
        label="Target",
    )


def _draw_horizontal_spec_lines(axis, report: AxisReport) -> None:
    axis.axhline(report.spec.lsl, color=SPEC, linewidth=1.4, linestyle="-", label="LSL")
    axis.axhline(report.spec.usl, color=SPEC, linewidth=1.4, linestyle="-", label="USL")
    axis.axhline(
        report.spec.resolved_target,
        color=TARGET,
        linewidth=1.2,
        linestyle=":",
        label="Target",
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

    status_color = PASS if report.status == "PASS" else FAIL
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
        ("Predicted OOS", f"{report.predicted_oos_ppm:.1f} ppm"),
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
        f"Target: {format_metric(spec.resolved_target)}",
        f"Required Cpk: >= {format_metric(spec.cpk_requirement, 2)}",
        f"Expected Yield: {report.expected_yield_percent:.3f}%",
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
    status_color = PASS if report.status == "PASS" else FAIL

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
        ("Predicted OOS", f"{report.predicted_oos_ppm:.1f} ppm"),
        ("Expected Yield", f"{report.expected_yield_percent:.3f}%"),
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
        f"Target: {format_metric(spec.resolved_target)}",
        transform=summary_axis.transAxes,
        fontsize=11.2,
        color=INK,
        va="top",
    )
    summary_axis.text(
        0.52,
        0.24,
        (
            "Judgement: "
            f"{'Meets requirement' if report.status == 'PASS' else 'Requires attention'}"
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


def _clip_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return textwrap.shorten(text, width=max_chars, placeholder="...")
