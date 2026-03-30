from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import NormalDist, fmean, stdev


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
    predicted_oos_ppm: float
    expected_yield_percent: float
    status: str


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


def calculate_axis_report(spec: AxisSpec, values: list[float]) -> AxisReport:
    if len(values) != EXPECTED_SAMPLE_COUNT:
        raise ValueError(
            f"Axis {spec.axis_name}: expected {EXPECTED_SAMPLE_COUNT} measurements."
        )
    if spec.usl <= spec.lsl:
        raise ValueError(f"Axis {spec.axis_name}: USL must be greater than LSL.")

    ordered_values = list(values)
    sample_count = len(ordered_values)
    mean = fmean(ordered_values)
    minimum = min(ordered_values)
    maximum = max(ordered_values)
    range_value = maximum - minimum

    overall_std = stdev(ordered_values) if sample_count > 1 else 0.0
    moving_ranges = [
        abs(current - previous)
        for previous, current in zip(ordered_values[:-1], ordered_values[1:])
    ]
    average_moving_range = fmean(moving_ranges) if moving_ranges else 0.0
    within_std = average_moving_range / INDIVIDUAL_D2 if average_moving_range else 0.0

    cpu = _one_sided_index(spec.usl - mean, within_std)
    cpl = _one_sided_index(mean - spec.lsl, within_std)
    cpk = min(cpu, cpl)
    cp = _spread_index(spec.usl - spec.lsl, within_std)

    ppu = _one_sided_index(spec.usl - mean, overall_std)
    ppl = _one_sided_index(mean - spec.lsl, overall_std)
    ppk = min(ppu, ppl)
    pp = _spread_index(spec.usl - spec.lsl, overall_std)

    observed_oos_count = sum(
        1 for value in ordered_values if value < spec.lsl or value > spec.usl
    )
    observed_oos_percent = (observed_oos_count / sample_count) * 100.0

    predicted_oos_ppm = _predicted_ppm(mean, overall_std, spec.lsl, spec.usl)
    expected_yield_percent = max(0.0, 100.0 - (predicted_oos_ppm / 10_000.0))

    status = "PASS"
    if observed_oos_count > 0 or cpk < spec.cpk_requirement:
        status = "FAIL"

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
        predicted_oos_ppm=predicted_oos_ppm,
        expected_yield_percent=expected_yield_percent,
        status=status,
    )


def format_metric(value: float, digits: int = 4) -> str:
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if math.isnan(value):
        return "NaN"
    return f"{value:.{digits}f}"


def _one_sided_index(distance_to_limit: float, sigma: float) -> float:
    if sigma > 0:
        return distance_to_limit / (3.0 * sigma)
    if distance_to_limit > 0:
        return math.inf
    if distance_to_limit == 0:
        return 0.0
    return -math.inf


def _spread_index(spec_width: float, sigma: float) -> float:
    if sigma > 0:
        return spec_width / (6.0 * sigma)
    if spec_width > 0:
        return math.inf
    return 0.0


def _predicted_ppm(mean: float, sigma: float, lsl: float, usl: float) -> float:
    if sigma <= 0:
        if lsl <= mean <= usl:
            return 0.0
        return 1_000_000.0

    normal_dist = NormalDist(mu=mean, sigma=sigma)
    lower_tail = max(0.0, normal_dist.cdf(lsl))
    upper_tail = max(0.0, 1.0 - normal_dist.cdf(usl))
    return (lower_tail + upper_tail) * 1_000_000.0
