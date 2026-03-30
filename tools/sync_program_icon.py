from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PNG = ROOT / "Icon" / "Program.png"
ASSET_DIR = ROOT / "assets"
OUTPUT_PNG = ASSET_DIR / "program_source_256.png"
OUTPUT_ICO = ASSET_DIR / "program_source.ico"


def main() -> None:
    if not SOURCE_PNG.exists():
        raise SystemExit(f"Missing icon source: {SOURCE_PNG}")

    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    with Image.open(SOURCE_PNG) as image:
        prepared = image.convert("RGBA")
        prepared.save(
            OUTPUT_ICO,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        prepared.resize((256, 256), Image.Resampling.LANCZOS).save(OUTPUT_PNG)

    print(f"Saved {OUTPUT_ICO}")
    print(f"Saved {OUTPUT_PNG}")


if __name__ == "__main__":
    main()
