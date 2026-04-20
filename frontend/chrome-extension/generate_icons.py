"""Generate PNG icons for the Chrome extension from the JobSearch SVG favicon.

Reproduces the 5-petal ember fan motif as 16×16, 48×48, 128×128 PNGs.
Run once: `python generate_icons.py`. Output goes to icons/.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

# Ember gradient matching frontend/static/favicon.svg
PETAL_COLORS: tuple[str, ...] = (
    "#8a4a24",
    "#b56332",
    "#e87d3e",
    "#f09b6b",
    "#f5c9a5",
)

# Rotation per petal, matching the favicon angles
PETAL_ROTATIONS: tuple[int, ...] = (-10, 5, 20, 35, 50)


def _petal_points(
    pivot_x: float, pivot_y: float, length: float, width: float, angle_deg: float
) -> list[tuple[float, float]]:
    """Polygon approximation of a pointed-teardrop petal rooted at the pivot."""
    theta = math.radians(angle_deg)
    # Base geometry in local coords: tip at (0,0), bulge at (0, -length).
    # Simulate the quadratic curves via many sampled points.
    steps = 24
    left = []
    right = []
    for i in range(steps + 1):
        t = i / steps
        # Right side curve: bezier-ish bulge on +x axis
        x = (1 - t) * (1 - t) * 0 + 2 * (1 - t) * t * (width) + t * t * 0
        y = (1 - t) * (1 - t) * 0 + 2 * (1 - t) * t * (-length / 2) + t * t * (-length)
        right.append((x, y))
        left.append((-x, y))
    points_local = right + list(reversed(left))

    # Rotate around (0,0), then translate to pivot
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    return [(pivot_x + p[0] * cos_t - p[1] * sin_t, pivot_y + p[0] * sin_t + p[1] * cos_t) for p in points_local]


def render_icon(size: int, out_path: Path) -> None:
    """Draw the 5-petal fan at the given pixel size, antialiased via 4× supersampling."""
    scale = 4
    canvas = size * scale
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Pivot at bottom-left third, petals fan upward-right. Proportions
    # reference a 20-unit box (matches the tightened favicon.svg viewBox
    # "7 7 20 20"): the old 0..32 denominator left ~30% empty padding
    # and the extension icon looked undersized in the toolbar.
    pivot_x = canvas * (4 / 20)
    pivot_y = canvas * (19 / 20)
    petal_length = canvas * (18 / 20)
    petal_width = canvas * (3.2 / 20)

    for color, angle in zip(PETAL_COLORS, PETAL_ROTATIONS, strict=True):
        pts = _petal_points(pivot_x, pivot_y, petal_length, petal_width, angle)
        draw.polygon(pts, fill=color)

    img = img.resize((size, size), Image.Resampling.LANCZOS)
    img.save(out_path, "PNG")


def main() -> None:
    out_dir = Path(__file__).parent / "icons"
    out_dir.mkdir(parents=True, exist_ok=True)
    for size in (16, 48, 128):
        path = out_dir / f"icon-{size}.png"
        render_icon(size, path)
        print(f"wrote {path} ({size}×{size})")


if __name__ == "__main__":
    main()
