from __future__ import annotations

import math
from pathlib import Path
from tempfile import NamedTemporaryFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from cpk_tool.analysis import AxisSpec, EXPECTED_SAMPLE_COUNT, validate_axis_spec


MEASUREMENTS = "Measurements"
SPECIFICATIONS = "Specifications"
SPEC_FIELDS = ("LSL (mm)", "Target (mm)", "USL (mm)", "Required Cpk")


def save_excel_template(destination: Path, axes: list[str]) -> None:
    book = Workbook()
    readings = book.active
    readings.title = MEASUREMENTS
    specs = book.create_sheet(SPECIFICATIONS)
    header_fill = PatternFill("solid", fgColor="173B5B")
    input_fill = PatternFill("solid", fgColor="E2F5F1")
    for sheet, heading, labels in (
        (readings, "Trial", range(1, EXPECTED_SAMPLE_COUNT + 1)),
        (specs, "Specification", SPEC_FIELDS),
    ):
        sheet.append([heading, *axes])
        sheet.freeze_panes = "B2"
        sheet.column_dimensions["A"].width = 21
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = Font(bold=True, color="FFFFFF")
            if cell.column > 1:
                sheet.column_dimensions[cell.column_letter].width = max(17, len(cell.value) + 3)
        for row, label in enumerate(labels, start=2):
            sheet.cell(row, 1, label)
            for col in range(2, len(axes) + 2):
                sheet.cell(row, col).fill = input_fill
        numeric = DataValidation(type="custom", formula1="ISNUMBER(B2)", allow_blank=True,
                                 showErrorMessage=True, errorStyle="stop")
        numeric.errorTitle = "Numeric value required"
        numeric.error = "Enter a number, or paste numeric values only."
        sheet.add_data_validation(numeric)
        numeric.add(f"B2:{get_column_letter(len(axes) + 1)}{sheet.max_row}")

    guide = book.create_sheet("Instructions")
    guide.column_dimensions["A"].width = 106
    guide.append(["วิธีกรอก Excel Template"])
    guide["A1"].fill = header_fill
    guide["A1"].font = Font(bold=True, color="FFFFFF")
    guide.append([f"Measurements — กรอกค่าวัดจริงหน่วย mm แกนละ {EXPECTED_SAMPLE_COUNT} ค่า ตามลำดับการวัด ในช่องสีเขียว"])
    guide.append(["ใส่ตัวเลขหรือวางแบบ Values เท่านั้น โดยคงชื่อแกนและเลข Trial ตามเดิม"])
    guide.append(["Specifications — กรอก LSL และ USL หากต้องการนำเข้าสเปกของแกนนั้นด้วย"])
    guide.append(["Target เว้นว่างได้ และ Required Cpk ที่เว้นว่างจะใช้ 1.33 เมื่อนำเข้าสเปก"])
    guide.append(["หากต้องการใช้สเปกที่ตั้งในแอป ให้เว้นทั้งคอลัมน์ของแกนนั้นในชีต Specifications"])
    guide.append(["บันทึกไฟล์ .xlsx แล้วเลือก Report Info > Import Filled Template ในแอป จากนั้นกด Calculate Preview"])

    with NamedTemporaryFile(dir=destination.parent, suffix=".xlsx", delete=False) as staged:
        staged_path = Path(staged.name)
    try:
        book.save(staged_path)
        staged_path.replace(destination)
    finally:
        book.close()
        staged_path.unlink(missing_ok=True)


def _read_columns(sheet, heading, labels, axes):
    rows = iter(sheet.values)
    header = list(next(rows, ()))
    while header and header[-1] is None:
        header.pop()
    if not header or header[0] != heading:
        raise ValueError(f"{sheet.title}!A1 must contain '{heading}'.")
    axis_names = {name.casefold(): name for name in axes}
    columns = []
    for col, name in enumerate(header[1:], start=2):
        axis = axis_names.get(str(name).strip().casefold()) if isinstance(name, str) else None
        if axis is None or axis in columns:
            raise ValueError(f"{sheet.title}!{get_column_letter(col)}1: unknown or duplicate axis '{name}'. "
                             "Download a template for the current axis tabs.")
        columns.append(axis)
    missing = [name for name in axes if name not in columns]
    if missing:
        raise ValueError(f"{sheet.title}: missing axis columns: {', '.join(missing)}.")

    result = {axis: [] for axis in columns}
    for row_number, label in enumerate(labels, start=2):
        row = next(rows, ())
        if not row or row[0] != label or isinstance(row[0], bool):
            raise ValueError(f"{sheet.title}!A{row_number}: expected '{label}'. Keep the template row order.")
        if any(value is not None for value in row[len(header):]):
            raise ValueError(f"{sheet.title} row {row_number}: data found beyond the last axis header.")
        for col, axis in enumerate(columns, start=2):
            value = row[col - 1] if col <= len(row) else None
            if value is None and sheet.title == SPECIFICATIONS:
                result[axis].append(None)
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                address = f"{sheet.title}!{get_column_letter(col)}{row_number}"
                raise ValueError(f"{address} (Axis {axis}): enter a numeric value or paste as values.")
            result[axis].append(float(value))
    if any(any(value is not None for value in row) for row in rows):
        raise ValueError(f"{sheet.title}: data found after the final template row.")
    return result


def read_excel_template(path: Path, axes: list[str]) -> tuple[dict[str, list[float]], dict[str, AxisSpec]]:
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        if MEASUREMENTS not in book.sheetnames or SPECIFICATIONS not in book.sheetnames:
            raise ValueError("Choose a downloaded template with the Measurements and Specifications sheets. "
                             "For other workbooks, use Browse Excel in an axis tab.")
        readings = _read_columns(book[MEASUREMENTS], "Trial", range(1, EXPECTED_SAMPLE_COUNT + 1), axes)
        spec_columns = _read_columns(book[SPECIFICATIONS], "Specification", SPEC_FIELDS, axes)
        specs = {}
        for axis, (lsl, target, usl, required) in spec_columns.items():
            if (lsl, target, usl, required) == (None, None, None, None):
                continue
            if lsl is None or usl is None:
                raise ValueError(f"Specifications, Axis {axis}: enter both LSL and USL or leave all four cells blank.")
            spec = AxisSpec(axis, lsl, usl, target, required if required is not None else 1.33)
            validate_axis_spec(spec)
            specs[axis] = spec
        return readings, specs
    finally:
        book.close()
