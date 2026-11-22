from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math
from statistics import stdev


EXPECTED_SAMPLE_COUNT = 30
INDIVIDUAL_D2 = 1.128


@dataclass(slots=True)
class ReportMetadata:
    report_title: str
    customer_name: str
    machine_name: str
    machine_model: str
    part_name: str
    serial_number: str
    measurement_tool_name: str
    measurement_tool_model: str
    inspected_by: str
    report_date: str
    notes: str = ""


@dataclass(slots=True)
class AxisSpec:
    axis_name: str
    lsl: float
    usl: float
    target: float | None = None
    cpk_requirement: float = 1.33

    @property
    def resolved_target(self) -> float:
        if self.target is not None:
            return self.target
        return (self.lsl + self.usl) / 2.0


@dataclass(frozen=True, slots=True)
class PerformancePPM:
    below: float
    above: float

    @property
    def total(self) -> float:
        return self.below + self.above


@dataclass(slots=True)
class AxisReport:
    spec: AxisSpec
    values: list[float]
    sample_count: int
    mean: float
    minimum: float
    maximum: float
    range_value: float
    overall_std: float
    within_std: float
    average_moving_range: float
    cp: float
    cpk: float
    cpu: float
    cpl: float
    pp: float
    ppk: float
    ppu: float
    ppl: float
    observed_oos_count: int
    observed_oos_percent: float
    cpm: float
    observed_ppm: PerformancePPM
    overall_ppm: PerformancePPM
    within_ppm: PerformancePPM
    expected_yield_percent: float
    status: str

    @property
    def predicted_oos_ppm(self) -> float:
        return self.overall_ppm.total


def parse_measurement_values(raw_values: list[str], axis_name: str) -> list[float]:
    cleaned: list[float] = []
    for index, raw_value in enumerate(raw_values, start=1):
        value_text = raw_value.strip()
        if not value_text:
            raise ValueError(f"Axis {axis_name}: measurement #{index} is blank.")
        try:
            cleaned.append(float(value_text))
        except ValueError as exc:
            raise ValueError(
                f"Axis {axis_name}: measurement #{index} is not a valid number."
            ) from exc

    if len(cleaned) != EXPECTED_SAMPLE_COUNT:
        raise ValueError(
            f"Axis {axis_name}: expected {EXPECTED_SAMPLE_COUNT} measurements, got {len(cleaned)}."
        )
    return cleaned


def validate_axis_spec(spec: AxisSpec) -> None:
    fields = {"LSL": spec.lsl, "USL": spec.usl, "Required Cpk": spec.cpk_requirement}
    if spec.target is not None:
        fields["Target"] = spec.target
    for field, value in fields.items():
        if not math.isfinite(value):
            raise ValueError(f"Axis {spec.axis_name}: {field} must be finite.")
    if spec.cpk_requirement < 0:
        raise ValueError(f"Axis {spec.axis_name}: Required Cpk must be non-negative.")
    if spec.usl <= spec.lsl:
        raise ValueError(f"Axis {spec.axis_name}: USL must be greater than LSL.")
    if spec.target is not None and not spec.lsl <= spec.target <= spec.usl:
        raise ValueError(f"Axis {spec.axis_name}: Target must be between LSL and USL.")


def calculate_axis_report(spec: AxisSpec, values: list[float]) -> AxisReport:
    if len(values) != EXPECTED_SAMPLE_COUNT:
        raise ValueError(f"Axis {spec.axis_name}: expected {EXPECTED_SAMPLE_COUNT} measurements.")
    validate_axis_spec(spec)
    for index, value in enumerate(values, start=1):
        if not math.isfinite(value):
            raise ValueError(f"Axis {spec.axis_name}: measurement #{index} must be finite.")

    ordered_values = list(values)
    sample_count = len(ordered_values)
    minimum = min(ordered_values)
    maximum = max(ordered_values)
    # Subtract in the original decimal representation before converting small
    # differences to floats for the normal tails and displayed indices.
    samples = [Fraction(str(value)) for value in ordered_values]
    center = sum(samples) / sample_count
    mean = float(center)
    range_value = float(max(samples) - min(samples))
    overall_std = stdev(samples)
    upper_limit = Fraction(str(spec.usl))
    lower_limit = Fraction(str(spec.lsl))
    upper_distance = upper_limit - center
    lower_distance = center - lower_limit
    mr_sum = sum(abs(b - a) for a, b in zip(samples, samples[1:]))
    average_mr = mr_sum / (sample_count - 1)
    average_moving_range = float(average_mr)
    exact_within = average_mr / Fraction(str(INDIVIDUAL_D2))
    within_std = float(exact_within)
    exact_cpk = None
    if exact_within:
        upper = upper_distance / (3 * exact_within)
        lower = lower_distance / (3 * exact_within)
        exact_cpk = min(upper, lower)
        cpu, cpl, cpk = float(upper), float(lower), float(exact_cpk)
        cp = float((upper + lower) / 2)
    else:
        cpu = cpl = cpk = cp = math.nan

    ppu = _one_sided_index(float(upper_distance), overall_std)
    ppl = _one_sided_index(float(lower_distance), overall_std)
    ppk = min(ppu, ppl)
    spec_width = float(upper_limit - lower_limit)
    pp = _spread_index(spec_width, overall_std)

    below_count = sum(value < spec.lsl for value in ordered_values)
    above_count = sum(value > spec.usl for value in ordered_values)
    observed_oos_count = below_count + above_count
    observed_oos_percent = 100.0 * observed_oos_count / sample_count
    observed_ppm = PerformancePPM(1e6 * below_count / sample_count, 1e6 * above_count / sample_count)
    overall_ppm = _expected_ppm(float(lower_distance), float(upper_distance), overall_std)
    within_ppm = _expected_ppm(float(lower_distance), float(upper_distance), within_std)
    expected_yield_percent = 100.0 - overall_ppm.total / 10_000.0

    cpm = math.nan
    if spec.target is not None and overall_std > 0:
        target_spread = math.hypot(overall_std, float(center - Fraction(str(spec.target))))
        cpm = _spread_index(spec_width, target_spread)

    status = "PASS"
    if observed_oos_count or (exact_cpk is not None and exact_cpk < Fraction(str(spec.cpk_requirement))):
        status = "FAIL"
    elif exact_cpk is None:
        status = "N/A"

    return AxisReport(
        spec=spec,
        values=ordered_values,
        sample_count=sample_count,
        mean=mean,
        minimum=minimum,
        maximum=maximum,
        range_value=range_value,
        overall_std=overall_std,
        within_std=within_std,
        average_moving_range=average_moving_range,
        cp=cp,
        cpk=cpk,
        cpu=cpu,
        cpl=cpl,
        pp=pp,
        ppk=ppk,
        ppu=ppu,
        ppl=ppl,
        observed_oos_count=observed_oos_count,
        observed_oos_percent=observed_oos_percent,
        cpm=cpm,
        observed_ppm=observed_ppm,
        within_ppm=within_ppm,
        overall_ppm=overall_ppm,
        expected_yield_percent=expected_yield_percent,
        status=status,
    )


def overall_result(reports: list[AxisReport]) -> str:
    if any(report.status == "FAIL" for report in reports):
        return "FAIL"
    if reports and all(report.status == "PASS" for report in reports):
        return "PASS"
    return "N/A"


def format_metric(value: float, digits: int = 4, *, unit: str = "") -> str:
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if math.isnan(value):
        return "N/A"
    return f"{value:.{digits}f}{unit}"


def _one_sided_index(distance_to_limit: float, sigma: float) -> float:
    if sigma > 0:
        return distance_to_limit / (3.0 * sigma)
    return math.nan


def _spread_index(spec_width: float, sigma: float) -> float:
    if sigma > 0:
        return spec_width / (6.0 * sigma)
    return math.nan


def _expected_ppm(lower_distance: float, upper_distance: float, sigma: float) -> PerformancePPM:
    if sigma <= 0:
        return PerformancePPM(math.nan, math.nan)
    # erfc evaluates each tail directly, including probabilities close to zero.
    scale = sigma * math.sqrt(2)
    return PerformancePPM(
        500_000 * math.erfc(lower_distance / scale),
        500_000 * math.erfc(upper_distance / scale),
    )


def format_ppm(value: float) -> str:
    if 0 < value < 0.001:
        return "< 0.001"
    if value == 0:
        return "0"
    return format_metric(value, 3)
