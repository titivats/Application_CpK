from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "assets"
PNG_PATH = ASSET_DIR / "machine_cpk_reporter_256.png"
ICO_PATH = ASSET_DIR / "machine_cpk_reporter.ico"


def lerp_color(start: tuple[int, int, int], end: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(int(start[i] + (end[i] - start[i]) * amount) for i in range(3))


def draw_background(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    base_start = (92, 105, 120)
    base_end = (22, 50, 78)
    for y in range(size):
        amount = y / max(size - 1, 1)
        color = lerp_color(base_start, base_end, amount)
        draw.line((0, y, size, y), fill=color + (255,), width=1)

    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (54, 72, size - 38, size - 24),
        radius=132,
        fill=(7, 16, 28, 135),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    image.alpha_composite(shadow)

    card = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    card_draw = ImageDraw.Draw(card)
    card_draw.rounded_rectangle(
        (36, 40, size - 44, size - 44),
        radius=128,
        fill=(244, 247, 250, 255),
        outline=(202, 214, 224, 255),
        width=6,
    )
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((96, 96, size - 96, size - 180), fill=(67, 126, 188, 35))
    glow = glow.filter(ImageFilter.GaussianBlur(24))
    card.alpha_composite(glow)
    image.alpha_composite(card)

    return image


def draw_grid(draw: ImageDraw.ImageDraw, size: int) -> None:
    left = 148
    right = size - 136
    top = 170
    bottom = size - 176
    for index in range(5):
        x = int(left + ((right - left) / 4) * index)
        draw.line((x, top, x, bottom), fill=(208, 218, 226, 255), width=3)
    for index in range(5):
        y = int(top + ((bottom - top) / 4) * index)
        draw.line((left, y, right, y), fill=(216, 224, 232, 255), width=3)


def draw_bars(draw: ImageDraw.ImageDraw, size: int) -> None:
    baseline = size - 212
    left = 182
    bar_width = 74
    gap = 28
    heights = (168, 238, 310)
    fills = ((157, 169, 181, 255), (132, 146, 160, 255), (104, 119, 136, 255))
    for index, height in enumerate(heights):
        x0 = left + index * (bar_width + gap)
        y0 = baseline - height
        x1 = x0 + bar_width
        y1 = baseline
        draw.rounded_rectangle((x0, y0, x1, y1), radius=18, fill=fills[index])


def draw_trend(draw: ImageDraw.ImageDraw, size: int) -> None:
    points = [
        (344, 620),
        (432, 540),
        (516, 564),
        (620, 438),
        (718, 478),
        (822, 330),
    ]
    draw.line(points, fill=(41, 102, 165, 255), width=28, joint="curve")
    draw.line(points, fill=(120, 184, 231, 255), width=12, joint="curve")

    accent_points = [
        (432, 540),
        (620, 438),
        (822, 330),
    ]
    for x, y in accent_points:
        draw.ellipse((x - 26, y - 26, x + 26, y + 26), fill=(15, 118, 110, 255), outline=(236, 248, 251, 255), width=8)

    draw.line((316, 674, 844, 674), fill=(190, 198, 208, 255), width=6)
    draw.line((316, 674, 316, 226), fill=(190, 198, 208, 255), width=6)


def draw_signal(draw: ImageDraw.ImageDraw, size: int) -> None:
    curve_points = [
        (414, 246),
        (468, 222),
        (520, 256),
        (566, 338),
        (608, 404),
        (652, 432),
        (702, 404),
        (748, 328),
        (798, 260),
    ]
    draw.line(curve_points, fill=(136, 153, 170, 255), width=10, joint="curve")
    draw.line((614, 224, 614, 478), fill=(92, 122, 154, 255), width=6)
    draw.ellipse((596, 396, 632, 432), fill=(28, 123, 197, 255))
    draw.ellipse((596, 396, 632, 432), outline=(243, 249, 252, 255), width=6)


def build_icon(size: int = 1024) -> Image.Image:
    image = draw_background(size)
    draw = ImageDraw.Draw(image)
    draw_grid(draw, size)
    draw_bars(draw, size)
    draw_trend(draw, size)
    draw_signal(draw, size)
    return image


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    image = build_icon()
    image.resize((256, 256), Image.Resampling.LANCZOS).save(PNG_PATH)
    image.save(
        ICO_PATH,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Saved {PNG_PATH}")
    print(f"Saved {ICO_PATH}")


if __name__ == "__main__":
    main()
