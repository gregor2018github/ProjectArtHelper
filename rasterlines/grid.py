"""Grid maths: where the raster lines go, and how to bake them in.

Pure functions - importable and testable without a display.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

ROUND_SPACINGS = (25, 50, 100, 125, 150, 200, 250, 300, 400, 500)


def spacing_options(width: int, height: int) -> list[int]:
    """Spacings that divide *both* dimensions exactly, so every cell is full size."""
    g = math.gcd(width, height)
    smallest = min(width, height)
    lo, hi = 10, max(10, smallest // 2)
    exact = sorted(d for d in range(1, g + 1) if g % d == 0 and lo <= d <= hi)
    if exact:
        return exact
    # Awkward dimensions (e.g. 1001 x 2003) have no exact divisor in range;
    # offer round values instead so the dropdown is never empty.
    return sorted(v for v in ROUND_SPACINGS if lo <= v <= hi) or [max(10, smallest // 2)]


def default_spacing(options: list[int], width: int, height: int) -> int:
    """Roughly a 4x4 grid on the short edge - 250 px for a 2000x1000 photo."""
    target = min(width, height) / 4
    return min(options, key=lambda v: (abs(v - target), -v))


def cells(length: int, spacing: int) -> int:
    """Number of cells along an edge; a trailing partial cell still counts."""
    return max(1, -(-length // max(1, spacing)))


def grid_positions(length: int, spacing: int) -> list[int]:
    """Interior grid coordinates; the image border is a line already."""
    if spacing < 1:
        return []
    return list(range(spacing, length, spacing))


SUBDIVISION_FACTORS = (2, 4, 8)


def cell_at(x: float, y: float, spacing: int, width: int, height: int) -> tuple[int, int] | None:
    """Grid cell (column, row) holding image point (x, y), or None if outside."""
    if spacing < 1 or not (0 <= x < width and 0 <= y < height):
        return None
    return int(x // spacing), int(y // spacing)


def cell_bounds(
    col: int, row: int, spacing: int, width: int, height: int
) -> tuple[int, int, int, int]:
    """Pixel box (x0, y0, x1, y1) of a cell; edge cells are clipped to the image."""
    x0, y0 = col * spacing, row * spacing
    return x0, y0, min(x0 + spacing, width), min(y0 + spacing, height)


def subdivision_lines(
    col: int, row: int, spacing: int, factor: int, width: int, height: int
) -> tuple[list[int], list[int]]:
    """Interior line coordinates that split one cell into *factor* x *factor*.

    Positions are rounded, so a spacing that is not a multiple of the factor
    still gets evenly spread lines. A partial edge cell simply drops the lines
    that fall outside it.
    """
    x0, y0, x1, y1 = cell_bounds(col, row, spacing, width, height)
    xs = [x0 + round(i * spacing / factor) for i in range(1, factor)]
    ys = [y0 + round(i * spacing / factor) for i in range(1, factor)]
    return [x for x in xs if x0 < x < x1], [y for y in ys if y0 < y < y1]


def draw_grid(
    image: Image.Image,
    spacing: int,
    thickness: int,
    color: tuple[int, int, int],
    subdivisions: dict[tuple[int, int], int] | None = None,
) -> Image.Image:
    """Return a copy of *image* with the raster baked in at full resolution."""
    out = image.copy()
    draw = ImageDraw.Draw(out)
    fill = color + (255,) if out.mode == "RGBA" else color
    w, h = out.size
    half = thickness // 2
    for x in grid_positions(w, spacing):
        draw.rectangle([x - half, 0, x - half + thickness - 1, h - 1], fill=fill)
    for y in grid_positions(h, spacing):
        draw.rectangle([0, y - half, w - 1, y - half + thickness - 1], fill=fill)
    for (col, row), factor in (subdivisions or {}).items():
        x0, y0, x1, y1 = cell_bounds(col, row, spacing, w, h)
        xs, ys = subdivision_lines(col, row, spacing, factor, w, h)
        for x in xs:
            draw.rectangle([x - half, y0, x - half + thickness - 1, y1 - 1], fill=fill)
        for y in ys:
            draw.rectangle([x0, y - half, x1 - 1, y - half + thickness - 1], fill=fill)
    return out
