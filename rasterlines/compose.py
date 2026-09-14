"""Composition maths: the frame, the items in it, and the final render.

Pure functions and plain data - importable and testable without a display.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import ClassVar

from PIL import Image, ImageDraw

FRAME_PRESETS = (
    (2000, 2000),
    (4000, 2000),
    (2000, 4000),
    (4000, 3000),
    (3000, 4000),
)

MIN_FRAME, MAX_FRAME = 16, 20000
MIN_SCALE, MAX_SCALE = 0.01, 20.0


def format_size(size: tuple[int, int]) -> str:
    return f"{size[0]} x {size[1]}"


def parse_frame_size(text: str) -> tuple[int, int] | None:
    """Read '4000 x 3000', '4000:3000' or '4000/3000'; None if unusable.

    The combobox stays editable, so anything holding two numbers is fair game.
    Values outside a sane pixel range are rejected rather than clamped, so the
    caller can keep the previous frame instead of silently resizing it.
    """
    nums = re.findall(r"\d+", text)
    if len(nums) < 2:
        return None
    w, h = int(nums[0]), int(nums[1])
    if not (MIN_FRAME <= w <= MAX_FRAME and MIN_FRAME <= h <= MAX_FRAME):
        return None
    return w, h


def fit_scale(iw: int, ih: int, fw: int, fh: int, cover: bool = False) -> float:
    """Scale that fits an iw x ih photo inside (or, with *cover*, over) a frame."""
    if iw < 1 or ih < 1:
        return 1.0
    pick = max if cover else min
    return pick(fw / iw, fh / ih)


@dataclass
class Item:
    """Something sitting in the frame; x / y are its top-left in frame pixels."""

    # What the mode may do with this item; the background says no to both.
    movable: ClassVar[bool] = True
    removable: ClassVar[bool] = True

    name: str
    x: float = 0.0
    y: float = 0.0

    @property
    def size(self) -> tuple[float, float]:
        raise NotImplementedError

    @property
    def box(self) -> tuple[float, float, float, float]:
        w, h = self.size
        return self.x, self.y, self.x + w, self.y + h

    @property
    def center(self) -> tuple[float, float]:
        w, h = self.size
        return self.x + w / 2, self.y + h / 2

    def contains(self, px: float, py: float, tol: float = 0.0) -> bool:
        """Is (px, py) on this item? *tol* widens the grab area in frame pixels."""
        x0, y0, x1, y1 = self.box
        return x0 - tol <= px <= x1 + tol and y0 - tol <= py <= y1 + tol

    def center_in(self, fw: int, fh: int) -> None:
        w, h = self.size
        self.x = (fw - w) / 2
        self.y = (fh - h) / 2

    def resize(self, factor: float, anchor: tuple[float, float] | None = None) -> None:
        """Grow or shrink, keeping the frame point *anchor* over the same spot.

        Limits belong to the subclass: `_limit` trims the factor to what it can
        actually take, so the move and the resize stay in step at the stops.
        """
        factor = self._limit(factor)
        if factor == 1.0:
            return
        ax, ay = self.center if anchor is None else anchor
        self.x = ax - (ax - self.x) * factor
        self.y = ay - (ay - self.y) * factor
        self._apply(factor)

    def _limit(self, factor: float) -> float:
        return factor

    def _apply(self, factor: float) -> None:
        raise NotImplementedError


@dataclass
class Placement(Item):
    """A photo dropped into the frame."""

    image: Image.Image = None  # type: ignore[assignment]
    scale: float = 1.0

    @property
    def size(self) -> tuple[float, float]:
        return self.image.width * self.scale, self.image.height * self.scale

    def rescale(self, scale: float, anchor: tuple[float, float] | None = None) -> None:
        """Set an absolute scale, keeping *anchor* over the same pixel."""
        self.resize(max(MIN_SCALE, min(scale, MAX_SCALE)) / self.scale, anchor)

    def _limit(self, factor: float) -> float:
        return max(MIN_SCALE, min(self.scale * factor, MAX_SCALE)) / self.scale

    def _apply(self, factor: float) -> None:
        self.scale *= factor


SHAPE_KINDS = ("rectangle", "circle")
MIN_SHAPE, MAX_SHAPE = 8.0, float(MAX_FRAME * 4)
MIN_THICKNESS, MAX_THICKNESS = 1, MAX_FRAME  # the real ceiling is per shape
SHAPE_COLOR = (255, 0, 0)
# Eraser brush radius, in screen pixels: the bite should look the same size
# under the cursor whatever the view zoom is.
MIN_ERASER_PX, DEFAULT_ERASER_PX, MAX_ERASER_PX = 2, 12, 120


def default_shape_size(frame_size: tuple[int, int]) -> float:
    """A new shape covers about a third of the frame's short edge."""
    return max(MIN_SHAPE, min(frame_size) / 3)


def default_thickness(frame_size: tuple[int, int]) -> int:
    """An outline that reads at a glance whatever the frame resolution is."""
    return max(2, round(min(frame_size) / 200))


def step_thickness(thickness: int, grow: bool, cap: int = MAX_THICKNESS) -> int:
    """One notch of the wheel; proportional, so big outlines are not 1 px work.

    *cap* is the point where the stroke has closed over the middle and the
    shape is solid - past that, thickening it would change nothing.
    """
    delta = max(1, round(thickness * 0.25))
    ceiling = max(MIN_THICKNESS, min(cap, MAX_THICKNESS))
    return max(MIN_THICKNESS, min(thickness + (delta if grow else -delta), ceiling))


@dataclass
class Shape(Item):
    """A hollow rectangle or ellipse used to block out the composition.

    The box is the outer edge of the stroke and the stroke runs inwards, which
    is what `ImageDraw`'s `width` does, so preview and saved file agree.
    """

    kind: str = "rectangle"
    w: float = 100.0
    h: float = 100.0
    thickness: int = 4
    color: tuple[int, int, int] = SHAPE_COLOR
    # Scratched-out bites, as (u, v, r) fractions of the shape's own box, so
    # they travel and scale with it. u and v are along w and h; r is measured
    # against w alone, which keeps the bite round on a non-square shape.
    erased: list[tuple[float, float, float]] = field(default_factory=list)

    @property
    def size(self) -> tuple[float, float]:
        return self.w, self.h

    @property
    def max_thickness(self) -> int:
        """The stroke that just closes the middle: any thicker is the same shape."""
        return max(MIN_THICKNESS, math.ceil(min(self.w, self.h) / 2))

    @property
    def filled(self) -> bool:
        """True once the inward stroke has met itself and the shape reads solid."""
        return 2 * self.thickness >= min(self.w, self.h)

    def erase(self, px: float, py: float, radius: float) -> None:
        """Scratch a round bite out of the outline at a frame-space point."""
        if self.w <= 0 or self.h <= 0 or radius <= 0:
            return
        self.erased.append(((px - self.x) / self.w, (py - self.y) / self.h, radius / self.w))

    def erase_circles(self) -> list[tuple[float, float, float]]:
        """The bites in frame coordinates: (centre x, centre y, radius)."""
        return [
            (self.x + u * self.w, self.y + v * self.h, r * self.w) for u, v, r in self.erased
        ]

    def near(self, px: float, py: float, tol: float = 0.0) -> bool:
        """Is the point anywhere in the shape's box, hollow middle included?"""
        x0, y0, x1, y1 = self.box
        return x0 - tol <= px <= x1 + tol and y0 - tol <= py <= y1 + tol

    def contains(self, px: float, py: float, tol: float = 0.0) -> bool:
        """Only the outline counts - the hollow middle belongs to what is under it."""
        x0, y0, x1, y1 = self.box
        band = self.thickness + tol
        if self.kind == "circle":
            cx, cy = self.center
            rx, ry = self.w / 2, self.h / 2
            if _ellipse_ratio(px, py, cx, cy, rx + tol, ry + tol) > 1.0:
                return False
            return _ellipse_ratio(px, py, cx, cy, rx - band, ry - band) >= 1.0
        if not (x0 - tol <= px <= x1 + tol and y0 - tol <= py <= y1 + tol):
            return False
        return not (x0 + band < px < x1 - band and y0 + band < py < y1 - band)

    def _limit(self, factor: float) -> float:
        smallest = min(self.w, self.h)
        largest = max(self.w, self.h)
        return max(MIN_SHAPE / smallest, min(factor, MAX_SHAPE / largest))

    def _apply(self, factor: float) -> None:
        self.w *= factor
        self.h *= factor


BACKGROUND_COLOR = (255, 255, 255)


@dataclass
class Background(Shape):
    """The frame's own fill.

    A `Shape` so that colour, the eraser and the one drawing path all work on
    it unchanged; pinned to the frame, and neither movable nor removable. Where
    it has been erased the saved file is transparent - there is nothing behind
    it but the backdrop.
    """

    movable: ClassVar[bool] = False
    removable: ClassVar[bool] = False

    name: str = "Background"
    color: tuple[int, int, int] = BACKGROUND_COLOR

    def fit_frame(self, frame_size: tuple[int, int]) -> None:
        """Follow the frame; the stroke is always thick enough to fill it."""
        self.x = self.y = 0.0
        self.w, self.h = float(frame_size[0]), float(frame_size[1])
        self.thickness = self.max_thickness


def _ellipse_ratio(px: float, py: float, cx: float, cy: float, rx: float, ry: float) -> float:
    """< 1 inside the ellipse, 1 on it, > 1 outside; a collapsed one holds nothing."""
    if rx <= 0 or ry <= 0:
        return float("inf")
    return ((px - cx) / rx) ** 2 + ((py - cy) / ry) ** 2


# Resize handles, corners first so a corner wins over the two sides meeting
# there. The names say which edges the handle moves: "nw" moves north and west.
HANDLES = ("nw", "ne", "se", "sw", "n", "e", "s", "w")


def handle_points(
    box: tuple[float, float, float, float]
) -> dict[str, tuple[float, float]]:
    """Where each resize handle sits on a box."""
    x0, y0, x1, y1 = box
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    return {
        "nw": (x0, y0), "ne": (x1, y0), "se": (x1, y1), "sw": (x0, y1),
        "n": (mx, y0), "e": (x1, my), "s": (mx, y1), "w": (x0, my),
    }


def handle_at(
    box: tuple[float, float, float, float], px: float, py: float, tol: float
) -> str | None:
    """Which handle of *box* the point is on, if any; corners beat sides."""
    points = handle_points(box)
    for name in HANDLES:
        hx, hy = points[name]
        if abs(px - hx) <= tol and abs(py - hy) <= tol:
            return name
    return None


def resize_box(
    box: tuple[float, float, float, float],
    handle: str,
    px: float,
    py: float,
    min_size: float = MIN_SHAPE,
) -> tuple[float, float, float, float]:
    """The box after dragging *handle* to (px, py).

    Only the edges the handle names move, so the opposite side stays put and a
    side handle changes one dimension alone - that is what makes a drag read as
    a reshape rather than a move. An edge stops rather than folding through the
    one opposite it.
    """
    x0, y0, x1, y1 = box
    if "w" in handle:
        x0 = min(px, x1 - min_size)
    if "e" in handle:
        x1 = max(px, x0 + min_size)
    if "n" in handle:
        y0 = min(py, y1 - min_size)
    if "s" in handle:
        y1 = max(py, y0 + min_size)
    return x0, y0, x1, y1


def shape_mask(
    shape: Shape,
    size: tuple[int, int],
    scale: float = 1.0,
    origin: tuple[float, float] = (0.0, 0.0),
    min_width: int = 1,
) -> Image.Image:
    """Where *shape* covers pixels, as an L mask of *size*, bites taken out.

    The one drawing path for a shape: the saved file uses it at scale 1, the
    preview at the view's zoom with the view's origin. `min_width` keeps a thin
    outline from vanishing when the frame is shown small - the same trick grid
    mode uses for its lines.

    The stroke runs inwards from the box, so a thick enough one meets in the
    middle and the shape reads as filled.
    """
    mask = Image.new("L", size, 0)
    ox, oy = origin
    bx0, by0, bx1, by1 = shape.box
    x0, y0 = round((bx0 - ox) * scale), round((by0 - oy) * scale)
    x1, y1 = round((bx1 - ox) * scale), round((by1 - oy) * scale)
    if x1 <= x0 or y1 <= y0:
        return mask
    draw = ImageDraw.Draw(mask)
    box = [x0, y0, x1 - 1, y1 - 1]
    width = max(min_width, round(shape.thickness * scale))
    if 2 * width >= min(x1 - x0, y1 - y0):
        # The stroke has closed over the hollow middle: draw it solid, which
        # also spares ImageDraw a pile of overlapping outline passes.
        if shape.kind == "circle":
            draw.ellipse(box, fill=255)
        else:
            draw.rectangle(box, fill=255)
    elif shape.kind == "circle":
        draw.ellipse(box, outline=255, width=width)
    else:
        draw.rectangle(box, outline=255, width=width)

    for cx, cy, radius in shape.erase_circles():
        ex, ey, er = (cx - ox) * scale, (cy - oy) * scale, radius * scale
        if er <= 0 or ex + er < 0 or ey + er < 0 or ex - er > size[0] or ey - er > size[1]:
            continue
        draw.ellipse([ex - er, ey - er, ex + er, ey + er], fill=0)
    return mask


def render_composition(
    frame_size: tuple[int, int],
    items: list[Item],
    background: Background | None = None,
) -> Image.Image:
    """Flatten the items into the final frame-sized RGBA image.

    Everything outside the frame is simply cropped away - the greyed-out spill
    is a preview aid, not part of the result. The background goes down first
    and the shapes last, matching the preview. Anything the background does not
    cover - because it was erased, or never there - stays transparent.
    """
    out = Image.new("RGBA", frame_size, (0, 0, 0, 0))
    if background is None:
        background = Background()
        background.fit_frame(frame_size)
    out.paste(
        Image.new("RGB", frame_size, background.color),
        (0, 0),
        shape_mask(background, frame_size),
    )
    for item in items:
        if isinstance(item, Placement):
            w = max(1, round(item.image.width * item.scale))
            h = max(1, round(item.image.height * item.scale))
            layer = item.image.convert("RGBA").resize((w, h), Image.LANCZOS)
            out.paste(layer, (round(item.x), round(item.y)), layer)
    for item in items:
        if isinstance(item, Shape):
            out.paste(
                Image.new("RGB", frame_size, item.color),
                (0, 0),
                shape_mask(item, frame_size),
            )
    return out


def flatten(image: Image.Image, behind: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """Drop the alpha for formats that cannot keep it, e.g. JPEG."""
    if image.mode != "RGBA":
        return image.convert("RGB")
    flat = Image.new("RGB", image.size, behind)
    flat.paste(image, (0, 0), image)
    return flat
