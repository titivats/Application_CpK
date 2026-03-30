from __future__ import annotations

from pathlib import Path
import sys


def get_asset_path(*parts: str) -> Path:
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base_dir.joinpath(*parts)


def get_first_existing_asset_path(*relative_paths: tuple[str, ...]) -> Path | None:
    for parts in relative_paths:
        candidate = get_asset_path(*parts)
        if candidate.exists():
            return candidate
    return None

