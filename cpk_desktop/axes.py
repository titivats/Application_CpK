from __future__ import annotations

import re


DEFAULT_AXIS_NAMES = ("X", "Y", "Z")
MAX_AXIS_NAME_LENGTH = 18
AXIS_COLOR_CYCLE = (
    "#0F766E",
    "#A16207",
    "#1D4ED8",
    "#7C3AED",
    "#C2410C",
    "#0F4C81",
    "#047857",
    "#B45309",
)
_AXIS_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")


def normalize_axis_name(raw_value: str) -> str:
    return re.sub(r"\s+", " ", raw_value).strip()


def validate_axis_name(raw_value: str) -> str:
    axis_name = normalize_axis_name(raw_value)
    if not axis_name:
        raise ValueError("Axis name is required.")
    if len(axis_name) > MAX_AXIS_NAME_LENGTH:
        raise ValueError(
            f"Axis name must be {MAX_AXIS_NAME_LENGTH} characters or fewer."
        )
    if not _AXIS_NAME_PATTERN.fullmatch(axis_name):
        raise ValueError(
            "Axis name can use letters, numbers, spaces, '.', '_' and '-'."
        )
    return axis_name


def suggest_next_axis_name(existing_names: set[str]) -> str:
    normalized_names = {normalize_axis_name(name).casefold() for name in existing_names}

    for axis_name in DEFAULT_AXIS_NAMES:
        if axis_name.casefold() not in normalized_names:
            return axis_name

    suffix = 1
    while True:
        for base_name in DEFAULT_AXIS_NAMES:
            candidate = f"{base_name}{suffix}"
            if candidate.casefold() not in normalized_names:
                return candidate
        suffix += 1


def axis_color_for_index(index: int) -> str:
    return AXIS_COLOR_CYCLE[index % len(AXIS_COLOR_CYCLE)]


def axis_tab_label(axis_name: str) -> str:
    return f"Axis {axis_name}"
