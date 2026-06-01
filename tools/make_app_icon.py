"""Generate the SmartSaver app icon — a stylized white bookmark on a deep
blue gradient, exported as a single 1024×1024 PNG that Xcode (14+) accepts
as the sole AppIcon size and rescales for every other slot.

Run once after editing:
    ./venv/bin/python tools/make_app_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = (
    PROJECT_ROOT
    / "ios" / "SmartSaver" / "Assets.xcassets" / "AppIcon.appiconset"
    / "AppIcon-1024.png"
)

# Brand palette — deep navy → vibrant azure. Single-tone bookmark to keep
# the silhouette crisp at every Home-Screen / Settings icon size.
GRAD_TOP = (10, 32, 92)        # deep navy
GRAD_BOTTOM = (62, 134, 248)   # vibrant azure


def _vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    """Build a vertical RGB gradient by writing one column and resizing."""
    col = Image.new("RGB", (1, size))
    px = col.load()
    for y in range(size):
        t = y / (size - 1)
        px[0, y] = (
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
        )
    return col.resize((size, size), Image.BILINEAR)


def _radial_highlight(size: int) -> Image.Image:
    """A soft off-center radial glow that gives the gradient depth."""
    glow = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(glow)
    cx, cy = size * 0.30, size * 0.22
    max_r = size * 0.55
    steps = 60
    for i in range(steps, 0, -1):
        r = max_r * (i / steps)
        intensity = int(40 * (1 - i / steps))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=intensity)
    return glow.filter(ImageFilter.GaussianBlur(radius=size * 0.06))


def _bookmark_polygon(size: int) -> list[tuple[float, float]]:
    """Return the 5-point polygon for a classic bookmark shape, centered."""
    bw = size * 0.36
    bh = size * 0.54
    bx = (size - bw) / 2
    by = (size - bh) / 2 - size * 0.015
    notch = bh * 0.24
    return [
        (bx, by),                                  # top-left
        (bx + bw, by),                             # top-right
        (bx + bw, by + bh),                        # bottom-right
        (bx + bw / 2, by + bh - notch),            # notch apex
        (bx, by + bh),                             # bottom-left
    ]


def render() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    # Background — vertical brand gradient.
    img = _vertical_gradient(SIZE, GRAD_TOP, GRAD_BOTTOM).convert("RGBA")

    # Soft off-center glow overlay so the background isn't a flat ramp.
    glow_mask = _radial_highlight(SIZE)
    glow_layer = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
    img = Image.composite(glow_layer, img.convert("RGB"), glow_mask).convert("RGBA")

    poly = _bookmark_polygon(SIZE)

    # Drop shadow.
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    offset = SIZE * 0.013
    shadow_poly = [(x + offset, y + offset) for (x, y) in poly]
    sdraw.polygon(shadow_poly, fill=(0, 0, 0, 130))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=SIZE * 0.020))
    img.alpha_composite(shadow)

    # Solid white bookmark — crisp silhouette at every iOS icon scale.
    bookmark = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(bookmark).polygon(poly, fill=(255, 255, 255, 255))
    img.alpha_composite(bookmark)

    img.convert("RGB").save(OUTPUT, "PNG", optimize=True)
    return OUTPUT


if __name__ == "__main__":
    out = render()
    print(f"Wrote {out} ({SIZE}x{SIZE})")
