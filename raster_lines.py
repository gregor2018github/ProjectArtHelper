"""Raster Lines - grid overlays for photos, and layout planning for new work.

Two modes share one window:

* **Grid mode** overlays a regular raster on a photo and saves a copy with the
  lines baked in, to replace drawing the grid by hand before copying a subject.
* **Compose mode** plans a new picture: choose the final frame size, drop a
  photo into it, and move / scale it until the crop is right. Whatever spills
  over the frame edge is shown greyed out so the final crop stays obvious.
"""

from __future__ import annotations

import math
import os
import re
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageTk

OPEN_FILETYPES = [
    ("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
    ("All files", "*.*"),
]

COLORS = {
    "Red": (255, 0, 0),
    "Green": (0, 255, 0),
    "Blue": (0, 0, 255),
    "Magenta": (255, 0, 255),
    "Cyan": (0, 255, 255),
    "Yellow": (255, 255, 0),
    "Black": (0, 0, 0),
    "White": (255, 255, 255),
}

MIN_ZOOM = 0.02
MAX_ZOOM = 16.0

BG = "#2b2b2b"
BG_RGB = (43, 43, 43)


def script_dir() -> str:
    """The folder this script lives in - where the photos are kept."""
    return str(Path(__file__).resolve().parent)


def load_image(path: str | Path) -> Image.Image:
    """Open *path* as an RGB / RGBA image with the pixels already decoded."""
    image = Image.open(path)
    image.load()
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    return image


# --------------------------------------------------------------- grid maths

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


# ------------------------------------------------------------ compose maths

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
class Placement:
    """One photo dropped into the frame; x / y / scale are in frame pixels."""

    image: Image.Image
    name: str
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0

    @property
    def size(self) -> tuple[float, float]:
        return self.image.width * self.scale, self.image.height * self.scale

    @property
    def box(self) -> tuple[float, float, float, float]:
        w, h = self.size
        return self.x, self.y, self.x + w, self.y + h

    def contains(self, px: float, py: float) -> bool:
        x0, y0, x1, y1 = self.box
        return x0 <= px <= x1 and y0 <= py <= y1

    def center_in(self, fw: int, fh: int) -> None:
        w, h = self.size
        self.x = (fw - w) / 2
        self.y = (fh - h) / 2

    def rescale(self, scale: float, anchor: tuple[float, float] | None = None) -> None:
        """Set the scale, keeping the frame point *anchor* over the same pixel."""
        new = max(MIN_SCALE, min(scale, MAX_SCALE))
        if anchor is None:  # no anchor: grow and shrink around the middle
            w, h = self.size
            anchor = (self.x + w / 2, self.y + h / 2)
        ax, ay = anchor
        ratio = new / self.scale
        self.x = ax - (ax - self.x) * ratio
        self.y = ay - (ay - self.y) * ratio
        self.scale = new


def render_composition(
    frame_size: tuple[int, int],
    items: list[Placement],
    background: tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """Flatten the placements into the final frame-sized image.

    Everything outside the frame is simply cropped away - the greyed-out spill
    is a preview aid, not part of the result.
    """
    out = Image.new("RGB", frame_size, background)
    for item in items:
        w = max(1, round(item.image.width * item.scale))
        h = max(1, round(item.image.height * item.scale))
        layer = item.image.convert("RGBA").resize((w, h), Image.LANCZOS)
        out.paste(layer, (round(item.x), round(item.y)), layer)
    return out


# -------------------------------------------------------------- shared view


class CanvasView(ttk.Frame):
    """Sidebar + canvas with the zoom / pan plumbing both modes share.

    The view is stored as an image-space offset plus a zoom factor; subclasses
    supply `content_size` (the world they live in) and `draw`.
    """

    fit_padding = 0.98
    clamp_margin = 0.0  # how far outside the content panning may go, as a fraction

    def __init__(self, app: RasterApp) -> None:
        super().__init__(app.body)
        self.app = app
        self.zoom = 1.0
        self.offset_x = 0.0  # top-left corner of the view, in content coordinates
        self.offset_y = 0.0
        self._photo: ImageTk.PhotoImage | None = None
        self._cache_key = None
        self._drag = None
        self._press = (0, 0)
        self._redraw_job = None

    # ---------------------------------------------------------------- widgets

    def make_sidebar(self) -> ttk.Frame:
        side = ttk.Frame(self, padding=12)
        side.pack(side="left", fill="y")
        return side

    def make_canvas(self) -> tk.Canvas:
        self.canvas = tk.Canvas(self, background=BG, highlightthickness=0, takefocus=1)
        self.canvas.pack(side="right", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.request_redraw())
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<MouseWheel>", self.on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self.on_wheel(e, delta=120))
        self.canvas.bind("<Button-5>", lambda e: self.on_wheel(e, delta=-120))
        return self.canvas

    # ------------------------------------------------------------ view maths

    def content_size(self) -> tuple[int, int]:
        raise NotImplementedError

    def canvas_size(self) -> tuple[int, int]:
        return max(self.canvas.winfo_width(), 1), max(self.canvas.winfo_height(), 1)

    def to_image(self, cx: float, cy: float) -> tuple[float, float]:
        return self.offset_x + cx / self.zoom, self.offset_y + cy / self.zoom

    def to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.offset_x) * self.zoom, (y - self.offset_y) * self.zoom

    def fit_to_window(self) -> None:
        """Zoom so the content fills the canvas, and centre it.

        Centring has to be explicit: compose mode lets the view roam well
        outside its frame, so the clamp alone would leave it wherever it was.
        """
        cw, ch = self.canvas_size()
        w, h = self.content_size()
        if w < 1 or h < 1:
            return
        self.zoom = max(MIN_ZOOM, min(min(cw / w, ch / h) * self.fit_padding, MAX_ZOOM))
        self.offset_x = (w - cw / self.zoom) / 2
        self.offset_y = (h - ch / self.zoom) / 2
        self.request_redraw()

    def set_zoom(self, zoom: float, anchor: tuple[float, float] | None = None) -> None:
        cw, ch = self.canvas_size()
        new = max(MIN_ZOOM, min(zoom, MAX_ZOOM))
        if anchor is None:
            anchor = (cw / 2, ch / 2)
        ax, ay = anchor
        img_x, img_y = self.to_image(ax, ay)
        self.zoom = new
        self.offset_x = img_x - ax / new
        self.offset_y = img_y - ay / new
        self.request_redraw()

    def zoom_by(self, factor: float) -> None:
        self.set_zoom(self.zoom * factor)

    @staticmethod
    def _clamp_axis(offset: float, view: float, size: float, margin: float) -> float:
        lo, hi = -margin, size + margin - view
        if hi < lo:  # the whole content fits on screen: centre it
            return (size - view) / 2
        return min(max(offset, lo), hi)

    def clamp_offsets(self) -> None:
        cw, ch = self.canvas_size()
        w, h = self.content_size()
        self.offset_x = self._clamp_axis(self.offset_x, cw / self.zoom, w, w * self.clamp_margin)
        self.offset_y = self._clamp_axis(self.offset_y, ch / self.zoom, h, h * self.clamp_margin)

    # -------------------------------------------------- events (overridable)

    def on_press(self, event) -> None:
        self.canvas.focus_set()
        self._drag = (event.x, event.y, self.offset_x, self.offset_y)
        self._press = (event.x, event.y)
        self.canvas.config(cursor="fleur")

    def on_drag(self, event) -> None:
        if not self._drag:
            return
        sx, sy, ox, oy = self._drag
        self.offset_x = ox - (event.x - sx) / self.zoom
        self.offset_y = oy - (event.y - sy) / self.zoom
        self.request_redraw()

    def on_release(self, event) -> None:
        self._drag = None
        self.canvas.config(cursor="")
        self.request_redraw()

    def on_wheel(self, event, delta: int | None = None) -> None:
        step = delta if delta is not None else event.delta
        self.set_zoom(self.zoom * (1.15 if step > 0 else 1 / 1.15), anchor=(event.x, event.y))

    # --------------------------------------------------------------- drawing

    def request_redraw(self) -> None:
        """Coalesce redraws to ~60 fps.

        A pending job is deliberately left to fire rather than rescheduled:
        cancelling it on every event starves the redraw during a continuous
        drag, so the view would only catch up once the mouse stopped moving.
        """
        if self._redraw_job is None:
            self._redraw_job = self.after(16, self.draw)

    def cancel_redraw(self) -> None:
        if self._redraw_job is not None:
            self.after_cancel(self._redraw_job)
            self._redraw_job = None

    def draw(self) -> None:
        raise NotImplementedError

    def placeholder(self, text: str) -> None:
        cw, ch = self.canvas_size()
        self.canvas.delete("all")
        self.canvas.create_text(cw / 2, ch / 2, text=text, fill="#888", font=("Segoe UI", 12))


# ---------------------------------------------------------------- grid mode


class GridMode(CanvasView):
    """Overlay a raster on a photo and save it baked in at full resolution."""

    def __init__(self, app: RasterApp) -> None:
        super().__init__(app)
        self.image: Image.Image | None = None
        self.path: Path | None = None
        self.iw = self.ih = 0
        self.options: list[int] = [50]
        self.exact_possible = True

        self.var_thickness = tk.IntVar(value=2)
        self.var_spacing = tk.StringVar(value="50")
        self.var_color = tk.StringVar(value="Red")
        self.var_status = tk.StringVar(value="")
        self.var_warning = tk.StringVar(value="")
        self.var_info = tk.StringVar(value="No photo loaded")
        self.var_subdivide = tk.BooleanVar(value=False)
        self.var_factor = tk.StringVar(value="4x")
        # Cells refined for critical areas (hands, faces): (col, row) -> factor.
        # Cell indices only mean something for one spacing, so a spacing change
        # drops them (see draw).
        self.subdivisions: dict[tuple[int, int], int] = {}
        self._sub_spacing = None

        self._build_ui()

    # ---------------------------------------------------------------- layout

    def _build_ui(self) -> None:
        side = self.make_sidebar()
        ttk.Label(side, text="Raster settings", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(side, textvariable=self.var_info, foreground="#555").pack(anchor="w", pady=(4, 6))
        ttk.Button(side, text="Open photo...", command=self.app.open_image).pack(
            anchor="w", fill="x", pady=(0, 12)
        )

        ttk.Label(side, text="Line thickness (px)").pack(anchor="w")
        ttk.Spinbox(
            side, from_=1, to=50, width=10, textvariable=self.var_thickness,
            command=self.request_redraw,
        ).pack(anchor="w", pady=(2, 12))

        ttk.Label(side, text="Distance between lines (px)").pack(anchor="w")
        self.spacing_box = ttk.Combobox(side, width=20, textvariable=self.var_spacing)
        self.spacing_box.pack(anchor="w", pady=(2, 12))
        self.spacing_box.bind("<<ComboboxSelected>>", lambda _e: self._normalize_spacing())
        self.spacing_box.bind("<Return>", lambda _e: self._normalize_spacing())
        self.spacing_box.bind("<FocusOut>", lambda _e: self._normalize_spacing())
        ttk.Label(
            side, textvariable=self.var_warning, foreground="#b35300", wraplength=200
        ).pack(anchor="w", pady=(0, 12))

        sub_row = ttk.Frame(side)
        sub_row.pack(anchor="w", fill="x")
        ttk.Checkbutton(
            sub_row, text="Refine cell", variable=self.var_subdivide,
            command=self._on_subdivide_toggle,
        ).pack(side="left")
        ttk.Combobox(
            sub_row, width=4, textvariable=self.var_factor, state="readonly",
            values=[f"{f}x" for f in SUBDIVISION_FACTORS],
        ).pack(side="left", padx=(6, 0))
        ttk.Label(
            side, text="Click a cell to split it; click it again to undo.",
            foreground="#777", wraplength=200,
        ).pack(anchor="w", pady=(2, 4))
        ttk.Button(side, text="Reset refinements", command=self.reset_subdivisions).pack(
            anchor="w", pady=(0, 12)
        )

        ttk.Label(side, text="Colour").pack(anchor="w")
        ttk.Combobox(
            side, width=20, textvariable=self.var_color, values=list(COLORS), state="readonly"
        ).pack(anchor="w", pady=(2, 12))
        self.var_color.trace_add("write", lambda *_: self.request_redraw())
        self.var_thickness.trace_add("write", lambda *_: self.request_redraw())

        ttk.Separator(side).pack(fill="x", pady=8)
        zoom_row = ttk.Frame(side)
        zoom_row.pack(anchor="w", pady=(0, 8))
        ttk.Button(zoom_row, text="-", width=3, command=lambda: self.zoom_by(1 / 1.25)).pack(side="left")
        ttk.Button(zoom_row, text="+", width=3, command=lambda: self.zoom_by(1.25)).pack(side="left", padx=4)
        ttk.Button(zoom_row, text="Fit", width=5, command=self.fit_to_window).pack(side="left")
        ttk.Button(zoom_row, text="100%", width=6, command=lambda: self.set_zoom(1.0)).pack(side="left", padx=4)
        ttk.Label(side, text="Wheel = zoom, drag = pan", foreground="#777").pack(anchor="w")

        ttk.Separator(side).pack(fill="x", pady=8)
        ttk.Button(side, text="Save as...", command=self.save_as).pack(fill="x", ipady=4)
        ttk.Label(side, textvariable=self.var_status, foreground="#237", wraplength=200).pack(
            anchor="w", pady=(8, 0)
        )

        self.make_canvas()

    # ----------------------------------------------------------------- image

    def set_image(self, path: Path, image: Image.Image) -> None:
        self.image = image
        self.path = path
        self.iw, self.ih = image.size
        self.var_info.set(f"{path.name}\n{self.iw} x {self.ih} px")
        self.options = spacing_options(self.iw, self.ih)
        # False when the dimensions share no usable divisor, i.e. no spacing can
        # tile this photo with whole squares.
        self.exact_possible = any(self.iw % v == 0 and self.ih % v == 0 for v in self.options)
        self.spacing_box.config(
            values=[f"{v} px   ({cells(self.iw, v)} x {cells(self.ih, v)})" for v in self.options]
        )
        self.var_spacing.set(str(default_spacing(self.options, self.iw, self.ih)))
        self.subdivisions.clear()
        self._cache_key = None
        self.after(60, self.fit_to_window)
        if not self.exact_possible:
            self.after(200, self._warn_no_exact_raster)

    def _warn_no_exact_raster(self) -> None:
        if self.path is None or not self.winfo_ismapped():
            return  # the user is off in the other mode; do not ambush them
        messagebox.showwarning(
            "No perfect raster possible",
            f"{self.path.name} is {self.iw} x {self.ih} px.\n\n"
            "These dimensions share no common divisor in a useful range, so no "
            "line distance splits the photo into whole squares - the last row "
            "and column will always be narrower than the rest.\n\n"
            "The suggested values are round numbers instead. Crop the photo to "
            "friendlier dimensions if you need an exact grid.",
            parent=self,
        )

    def content_size(self) -> tuple[int, int]:
        return self.iw, self.ih

    # -------------------------------------------------------------- settings

    def _normalize_spacing(self) -> None:
        self.var_spacing.set(str(self.spacing))
        self.request_redraw()

    @property
    def spacing(self) -> int:
        raw = self.var_spacing.get().split("px")[0].strip()
        try:
            value = int(float(raw))
        except ValueError:
            value = default_spacing(self.options, max(self.iw, 1), max(self.ih, 1))
        return max(2, min(value, max(self.iw, self.ih, 2)))

    @property
    def thickness(self) -> int:
        try:
            return max(1, min(int(self.var_thickness.get()), 50))
        except (tk.TclError, ValueError):
            return 2

    @property
    def color(self) -> tuple[int, int, int]:
        return COLORS.get(self.var_color.get(), (255, 0, 0))

    @property
    def factor(self) -> int:
        try:
            return int(self.var_factor.get().rstrip("xX"))
        except ValueError:
            return 4

    def _on_subdivide_toggle(self) -> None:
        self.canvas.config(cursor="crosshair" if self.var_subdivide.get() else "")

    def reset_subdivisions(self) -> None:
        self.subdivisions.clear()
        self.request_redraw()

    def toggle_cell(self, cx: int, cy: int) -> None:
        """Refine (or un-refine) the cell under a canvas point."""
        img_x, img_y = self.to_image(cx, cy)
        cell = cell_at(img_x, img_y, self.spacing, self.iw, self.ih)
        if cell is None:
            return
        factor = self.factor
        if self.subdivisions.get(cell) == factor:
            del self.subdivisions[cell]
        else:
            self.subdivisions[cell] = factor
        self._sub_spacing = self.spacing
        self.request_redraw()

    def on_release(self, event) -> None:
        self._drag = None
        self.canvas.config(cursor="crosshair" if self.var_subdivide.get() else "")
        # A click that did not pan is a cell pick; anything further is a drag.
        px, py = self._press
        if self.var_subdivide.get() and abs(event.x - px) < 3 and abs(event.y - py) < 3:
            self.toggle_cell(event.x, event.y)
        self.request_redraw()  # redo the last frame at full resample quality

    # --------------------------------------------------------------- drawing

    def draw(self) -> None:
        self._redraw_job = None
        if self.image is None:
            self.placeholder("Open a photo to start")
            return
        self.clamp_offsets()
        cw, ch = self.canvas_size()
        z = self.zoom
        self.canvas.delete("all")

        x0 = max(0, int(math.floor(self.offset_x)))
        y0 = max(0, int(math.floor(self.offset_y)))
        x1 = min(self.iw, int(math.ceil(self.offset_x + cw / z)))
        y1 = min(self.ih, int(math.ceil(self.offset_y + ch / z)))
        if x1 <= x0 or y1 <= y0:
            return

        tw = max(1, int(round((x1 - x0) * z)))
        th = max(1, int(round((y1 - y0) * z)))
        # Downscaling with LANCZOS costs real time on a large photo, so use the
        # cheap filter while a drag is in flight; on_release redraws sharply.
        if z >= 1:
            resample = Image.NEAREST
        else:
            resample = Image.BILINEAR if self._drag else Image.LANCZOS
        key = (x0, y0, x1, y1, tw, th, resample)
        if key != self._cache_key:
            crop = self.image.crop((x0, y0, x1, y1)).resize((tw, th), resample)
            self._photo = ImageTk.PhotoImage(crop.convert("RGB"))
            self._cache_key = key

        px = (x0 - self.offset_x) * z
        py = (y0 - self.offset_y) * z
        self.canvas.create_image(px, py, image=self._photo, anchor="nw")

        # The grid is drawn as canvas lines rather than baked into the preview
        # bitmap, so thin lines stay visible (min 1 px) even when zoomed out.
        spacing, thickness = self.spacing, self.thickness
        width = max(1, int(round(thickness * z)))
        rgb = "#%02x%02x%02x" % self.color
        top, bottom = py, py + th
        left, right = px, px + tw
        for gx in grid_positions(self.iw, spacing):
            if x0 - spacing <= gx <= x1 + spacing:
                cx = (gx - self.offset_x) * z + (width - thickness * z) / 2
                self.canvas.create_line(cx, top, cx, bottom, fill=rgb, width=width)
        for gy in grid_positions(self.ih, spacing):
            if y0 - spacing <= gy <= y1 + spacing:
                cy = (gy - self.offset_y) * z + (width - thickness * z) / 2
                self.canvas.create_line(left, cy, right, cy, fill=rgb, width=width)

        if self.subdivisions and self._sub_spacing != spacing:
            self.subdivisions.clear()  # cell indices are tied to one spacing
        for (col, row), factor in self.subdivisions.items():
            cx0, cy0, cx1, cy1 = cell_bounds(col, row, spacing, self.iw, self.ih)
            if cx1 < x0 or cx0 > x1 or cy1 < y0 or cy0 > y1:
                continue
            sxs, sys_ = subdivision_lines(col, row, spacing, factor, self.iw, self.ih)
            cell_top = (cy0 - self.offset_y) * z
            cell_bottom = (cy1 - self.offset_y) * z
            cell_left = (cx0 - self.offset_x) * z
            cell_right = (cx1 - self.offset_x) * z
            for sx in sxs:
                cx = (sx - self.offset_x) * z + (width - thickness * z) / 2
                self.canvas.create_line(cx, cell_top, cx, cell_bottom, fill=rgb, width=width)
            for sy in sys_:
                cy = (sy - self.offset_y) * z + (width - thickness * z) / 2
                self.canvas.create_line(cell_left, cy, cell_right, cy, fill=rgb, width=width)

        refined = f"  -  {len(self.subdivisions)} refined" if self.subdivisions else ""
        self.var_status.set(
            f"Zoom {z * 100:.0f}%  -  grid {spacing} px  -  "
            f"{cells(self.iw, spacing)} x {cells(self.ih, spacing)} cells{refined}"
        )
        if self.iw % spacing == 0 and self.ih % spacing == 0:
            self.var_warning.set("")
        elif self.exact_possible:
            rest_w, rest_h = self.iw % spacing, self.ih % spacing
            self.var_warning.set(
                f"Warning: {spacing} px does not divide this photo evenly - the "
                f"edge cells are {rest_w or spacing} x {rest_h or spacing} px. "
                "Pick a value from the list for whole squares."
            )
        else:
            self.var_warning.set(
                f"Warning: no line distance divides {self.iw} x {self.ih} px into "
                "whole squares - the edge cells will always be partial."
            )

    # ------------------------------------------------------------------ save

    def save_as(self) -> None:
        if self.image is None or self.path is None:
            messagebox.showinfo("Nothing to save", "Open a photo first.", parent=self)
            return
        ext = self.path.suffix.lower() or ".png"
        target = filedialog.asksaveasfilename(
            parent=self,
            title="Save image with raster",
            initialdir=str(self.path.parent),
            initialfile=f"{self.path.stem}_raster{ext}",
            defaultextension=ext,
            filetypes=OPEN_FILETYPES,
        )
        if not target:
            return
        try:
            result = draw_grid(
                self.image, self.spacing, self.thickness, self.color, self.subdivisions
            )
            out_ext = Path(target).suffix.lower()
            if out_ext in (".jpg", ".jpeg"):
                result.convert("RGB").save(target, quality=95, subsampling=0)
            else:
                result.save(target)
        except Exception as exc:  # noqa: BLE001 - surface any save failure to the user
            messagebox.showerror("Save failed", str(exc), parent=self)
            return
        self.var_status.set(f"Saved: {os.path.basename(target)}")


# ------------------------------------------------------------- compose mode

# The spill outside the frame is desaturated and washed towards a flat grey.
# Blending towards the dark backdrop instead would bury dark photos completely;
# a mid grey leaves the cut-off part as a faint ghost of itself.
FADE = 0.75
MUTE_RGB = (120, 120, 120)


class ComposeMode(CanvasView):
    """Plan a new picture: a fixed output frame plus a photo placed inside it."""

    fit_padding = 0.88
    clamp_margin = 0.75  # the photo may hang well outside, so let the view follow

    def __init__(self, app: RasterApp) -> None:
        super().__init__(app)
        self.items: list[Placement] = []
        self.active: Placement | None = None
        self.frame_size: tuple[int, int] = FRAME_PRESETS[3]
        self._item_drag = None

        self.var_frame = tk.StringVar(value=format_size(self.frame_size))
        self.var_scale = tk.StringVar(value="Open a photo to place it in the frame")
        self.var_status = tk.StringVar(value="")
        self.var_info = tk.StringVar(value="No photo placed")

        self._build_ui()

    # ---------------------------------------------------------------- layout

    def _build_ui(self) -> None:
        side = self.make_sidebar()
        ttk.Label(side, text="Design plan", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(side, textvariable=self.var_info, foreground="#555").pack(anchor="w", pady=(4, 6))
        ttk.Button(side, text="Open photo...", command=self.app.open_image).pack(
            anchor="w", fill="x", pady=(0, 12)
        )

        ttk.Label(side, text="Frame size (px)").pack(anchor="w")
        self.frame_box = ttk.Combobox(
            side, width=20, textvariable=self.var_frame,
            values=[format_size(s) for s in FRAME_PRESETS],
        )
        self.frame_box.pack(anchor="w", pady=(2, 2))
        self.frame_box.bind("<<ComboboxSelected>>", lambda _e: self.apply_frame_size())
        self.frame_box.bind("<Return>", lambda _e: self.apply_frame_size())
        self.frame_box.bind("<FocusOut>", lambda _e: self.apply_frame_size())
        ttk.Label(
            side, text="Pick a preset or type your own, e.g. 3500 x 2400.",
            foreground="#777", wraplength=200,
        ).pack(anchor="w", pady=(0, 12))

        ttk.Separator(side).pack(fill="x", pady=4)
        ttk.Label(side, text="Photo", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(4, 2))
        ttk.Label(side, textvariable=self.var_scale, foreground="#237", wraplength=200).pack(
            anchor="w", pady=(0, 6)
        )
        place_row = ttk.Frame(side)
        place_row.pack(anchor="w", fill="x")
        ttk.Button(place_row, text="Fit in", width=7, command=lambda: self.fit_item(False)).pack(side="left")
        ttk.Button(place_row, text="Fill", width=6, command=lambda: self.fit_item(True)).pack(side="left", padx=4)
        ttk.Button(place_row, text="Centre", width=8, command=self.center_item).pack(side="left")
        scale_row = ttk.Frame(side)
        scale_row.pack(anchor="w", fill="x", pady=(4, 6))
        ttk.Button(scale_row, text="-", width=3, command=lambda: self.scale_item(1 / 1.1)).pack(side="left")
        ttk.Button(scale_row, text="+", width=3, command=lambda: self.scale_item(1.1)).pack(side="left", padx=4)
        ttk.Button(scale_row, text="Remove", width=8, command=self.remove_item).pack(side="left")
        ttk.Label(
            side,
            text="Left-click the photo to activate it, then wheel or +/- to resize "
                 "and drag to move; arrow keys nudge. Click the backdrop to "
                 "deselect. Ctrl+wheel always zooms the view instead.",
            foreground="#777", wraplength=200,
        ).pack(anchor="w", pady=(0, 12))

        ttk.Separator(side).pack(fill="x", pady=8)
        zoom_row = ttk.Frame(side)
        zoom_row.pack(anchor="w", pady=(0, 8))
        ttk.Button(zoom_row, text="-", width=3, command=lambda: self.zoom_by(1 / 1.25)).pack(side="left")
        ttk.Button(zoom_row, text="+", width=3, command=lambda: self.zoom_by(1.25)).pack(side="left", padx=4)
        ttk.Button(zoom_row, text="Fit", width=5, command=self.fit_to_window).pack(side="left")
        ttk.Button(zoom_row, text="100%", width=6, command=lambda: self.set_zoom(1.0)).pack(side="left", padx=4)
        ttk.Label(side, text="View zoom, not the photo", foreground="#777").pack(anchor="w")

        ttk.Separator(side).pack(fill="x", pady=8)
        ttk.Button(side, text="Save frame as...", command=self.save_as).pack(fill="x", ipady=4)
        ttk.Label(side, textvariable=self.var_status, foreground="#237", wraplength=200).pack(
            anchor="w", pady=(8, 0)
        )

        canvas = self.make_canvas()
        for seq in ("<plus>", "<KP_Add>", "<equal>"):
            canvas.bind(seq, lambda _e: self.scale_item(1.1))
        for seq in ("<minus>", "<KP_Subtract>"):
            canvas.bind(seq, lambda _e: self.scale_item(1 / 1.1))
        canvas.bind("<Delete>", lambda _e: self.remove_item())
        canvas.bind("<Left>", lambda e: self.nudge(-1, 0, e))
        canvas.bind("<Right>", lambda e: self.nudge(1, 0, e))
        canvas.bind("<Up>", lambda e: self.nudge(0, -1, e))
        canvas.bind("<Down>", lambda e: self.nudge(0, 1, e))

    def content_size(self) -> tuple[int, int]:
        return self.frame_size

    # ------------------------------------------------------ frame and photo

    def apply_frame_size(self) -> None:
        size = parse_frame_size(self.var_frame.get())
        if size is None:
            self.var_frame.set(format_size(self.frame_size))
            self.var_status.set(
                f"Frame size needs two numbers between {MIN_FRAME} and {MAX_FRAME}."
            )
            return
        changed = size != self.frame_size
        self.frame_size = size
        self.var_frame.set(format_size(size))
        if changed:
            self.fit_to_window()
        self.request_redraw()

    def set_image(self, path: Path, image: Image.Image) -> None:
        """Place a freshly opened photo in the frame, fitted and centred."""
        item = Placement(image=image, name=path.name)
        item.scale = fit_scale(image.width, image.height, *self.frame_size)
        item.center_in(*self.frame_size)
        self.items = [item]  # one photo for now; the list keeps room for more
        self.active = item
        self.var_info.set(f"{path.name}\n{image.width} x {image.height} px")
        self.after(60, self.fit_to_window)
        self.request_redraw()

    def fit_item(self, cover: bool) -> None:
        item = self.active
        if item is None:
            return
        item.rescale(fit_scale(item.image.width, item.image.height, *self.frame_size, cover=cover))
        item.center_in(*self.frame_size)
        self.request_redraw()

    def center_item(self) -> None:
        if self.active is None:
            return
        self.active.center_in(*self.frame_size)
        self.request_redraw()

    def scale_item(self, factor: float, anchor: tuple[float, float] | None = None) -> None:
        if self.active is None:
            return
        self.active.rescale(self.active.scale * factor, anchor)
        self.request_redraw()

    def remove_item(self) -> None:
        if self.active is None:
            return
        self.items.remove(self.active)
        self.active = self.items[-1] if self.items else None
        if not self.items:
            self.var_info.set("No photo placed")
        self.request_redraw()

    def nudge(self, dx: int, dy: int, event=None) -> None:
        """Move the active photo; a screen pixel at a time, ten with Shift."""
        item = self.active
        if item is None:
            return
        shift = bool(event and event.state & 0x0001)
        step = max(1.0, (10 if shift else 1) / self.zoom)
        item.x += dx * step
        item.y += dy * step
        self.request_redraw()

    def item_at(self, cx: float, cy: float) -> Placement | None:
        px, py = self.to_image(cx, cy)
        for item in reversed(self.items):  # topmost first
            if item.contains(px, py):
                return item
        return None

    # ---------------------------------------------------------------- events

    def on_press(self, event) -> None:
        self.canvas.focus_set()
        self._press = (event.x, event.y)
        hit = self.item_at(event.x, event.y)
        if hit is None:  # nothing under the cursor: the drag pans the view
            self._item_drag = None
            super().on_press(event)
            return
        self.active = hit
        self._item_drag = (event.x, event.y, hit.x, hit.y)
        self._drag = None
        self.canvas.config(cursor="fleur")
        self.request_redraw()

    def on_drag(self, event) -> None:
        if not self._item_drag:
            super().on_drag(event)
            return
        sx, sy, ix, iy = self._item_drag
        item = self.active
        if item is not None:
            item.x = ix + (event.x - sx) / self.zoom
            item.y = iy + (event.y - sy) / self.zoom
        self._drag = self._item_drag  # a drag is in flight: use the cheap filter
        self.request_redraw()

    def on_release(self, event) -> None:
        px, py = self._press
        clicked = abs(event.x - px) < 3 and abs(event.y - py) < 3
        if clicked and self._item_drag is None:
            self.active = None  # a click on the backdrop drops the selection
        self._item_drag = None
        self._drag = None
        self.canvas.config(cursor="")
        self.request_redraw()  # redo the last frame at full resample quality

    def on_wheel(self, event, delta: int | None = None) -> None:
        """Wheel resizes the active photo; with Ctrl (or nothing active) it zooms."""
        step = delta if delta is not None else event.delta
        ctrl = bool(event.state & 0x0004)
        if self.active is not None and not ctrl:
            self.scale_item(1.1 if step > 0 else 1 / 1.1, anchor=self.to_image(event.x, event.y))
        else:
            self.set_zoom(self.zoom * (1.15 if step > 0 else 1 / 1.15), anchor=(event.x, event.y))

    # --------------------------------------------------------------- drawing

    def _tile(self, item: Placement, cw: int, ch: int, resample: int):
        """Resize only the visible part of *item*: (tile image, canvas position).

        A photo scaled up inside a zoomed-in view can be tens of thousands of
        pixels wide, so never resize more of it than the canvas can show.
        """
        sc = item.scale * self.zoom  # source pixel -> canvas pixel
        if sc <= 0:
            return None
        dx0, dy0 = self.to_canvas(item.x, item.y)
        dw, dh = item.image.width * sc, item.image.height * sc
        vx0, vy0 = max(0, int(math.floor(dx0))), max(0, int(math.floor(dy0)))
        vx1, vy1 = min(cw, int(math.ceil(dx0 + dw))), min(ch, int(math.ceil(dy0 + dh)))
        if vx1 <= vx0 or vy1 <= vy0:
            return None
        sx0 = max(0, int(math.floor((vx0 - dx0) / sc)))
        sy0 = max(0, int(math.floor((vy0 - dy0) / sc)))
        sx1 = min(item.image.width, int(math.ceil((vx1 - dx0) / sc)))
        sy1 = min(item.image.height, int(math.ceil((vy1 - dy0) / sc)))
        if sx1 <= sx0 or sy1 <= sy0:
            return None
        tw = max(1, int(round((sx1 - sx0) * sc)))
        th = max(1, int(round((sy1 - sy0) * sc)))
        filt = Image.NEAREST if sc >= 1 else resample
        tile = item.image.crop((sx0, sy0, sx1, sy1)).resize((tw, th), filt)
        return tile.convert("RGB"), (int(round(dx0 + sx0 * sc)), int(round(dy0 + sy0 * sc)))

    def _render_preview(self, cw: int, ch: int, resample: int) -> Image.Image:
        """Backdrop, white frame, photos - faded wherever they leave the frame."""
        base = Image.new("RGB", (cw, ch), BG_RGB)
        fx0, fy0 = self.to_canvas(0, 0)
        fx1, fy1 = self.to_canvas(*self.frame_size)
        rect = [int(round(fx0)), int(round(fy0)), int(round(fx1)) - 1, int(round(fy1)) - 1]
        frame_mask = Image.new("L", (cw, ch), 0)
        if rect[2] >= rect[0] and rect[3] >= rect[1]:
            ImageDraw.Draw(base).rectangle(rect, fill=(255, 255, 255))
            ImageDraw.Draw(frame_mask).rectangle(rect, fill=255)

        layer = Image.new("RGB", (cw, ch), BG_RGB)
        drawn = Image.new("L", (cw, ch), 0)  # where a photo actually landed
        for item in self.items:
            tile = self._tile(item, cw, ch, resample)
            if tile is None:
                continue
            img, pos = tile
            layer.paste(img, pos)
            drawn.paste(Image.new("L", img.size, 255), pos)
        if not drawn.getbbox():
            return base

        base.paste(layer, (0, 0), ImageChops.multiply(drawn, frame_mask))
        # Outside the frame the photo is only a hint about what gets cut off:
        # drain the colour and wash it out towards grey.
        faded = Image.blend(
            ImageOps.grayscale(layer).convert("RGB"), Image.new("RGB", (cw, ch), MUTE_RGB), FADE
        )
        base.paste(faded, (0, 0), ImageChops.subtract(drawn, frame_mask))
        return base

    def draw(self) -> None:
        self._redraw_job = None
        self.clamp_offsets()
        cw, ch = self.canvas_size()
        self.canvas.delete("all")

        resample = Image.BILINEAR if self._drag else Image.LANCZOS
        key = (
            cw, ch, round(self.offset_x, 2), round(self.offset_y, 2), round(self.zoom, 6),
            self.frame_size, resample,
            tuple(
                (id(i.image), round(i.x, 2), round(i.y, 2), round(i.scale, 6)) for i in self.items
            ),
        )
        if key != self._cache_key:
            self._photo = ImageTk.PhotoImage(self._render_preview(cw, ch, resample))
            self._cache_key = key
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")

        fw, fh = self.frame_size
        fx0, fy0 = self.to_canvas(0, 0)
        fx1, fy1 = self.to_canvas(fw, fh)
        self.canvas.create_rectangle(fx0, fy0, fx1, fy1, outline="#99aadd", width=1)
        item = self.active
        if item is not None:
            x0, y0, x1, y1 = item.box
            bx0, by0 = self.to_canvas(x0, y0)
            bx1, by1 = self.to_canvas(x1, y1)
            self.canvas.create_rectangle(
                bx0, by0, bx1, by1, outline="#4ea1ff", width=2, dash=(5, 3)
            )
            w, h = item.size
            self.var_scale.set(
                f"{item.name} - active\n{item.scale * 100:.1f}% - covers "
                f"{w:.0f} x {h:.0f} px of the {fw} x {fh} frame"
            )
        elif self.items:
            self.var_scale.set("No photo active - click the photo to activate it")
        else:
            self.var_scale.set("Open a photo to place it in the frame")
        self.var_status.set(f"Frame {fw} x {fh} px  -  view zoom {self.zoom * 100:.0f}%")

    # ------------------------------------------------------------------ save

    def save_as(self) -> None:
        if not self.items:
            messagebox.showinfo("Nothing to save", "Place a photo first.", parent=self)
            return
        target = filedialog.asksaveasfilename(
            parent=self,
            title="Save design frame",
            initialdir=str(self.app.path.parent) if self.app.path else script_dir(),
            initialfile="design.png",
            defaultextension=".png",
            filetypes=OPEN_FILETYPES,
        )
        if not target:
            return
        try:
            result = render_composition(self.frame_size, self.items)
            if Path(target).suffix.lower() in (".jpg", ".jpeg"):
                result.save(target, quality=95, subsampling=0)
            else:
                result.save(target)
        except Exception as exc:  # noqa: BLE001 - surface any save failure to the user
            messagebox.showerror("Save failed", str(exc), parent=self)
            return
        self.var_status.set(f"Saved: {os.path.basename(target)}")


# -------------------------------------------------------------------- shell


class RasterApp(tk.Tk):
    """The window: a mode switch on top, one mode frame filling the rest."""

    def __init__(self, path: Path | None = None, image: Image.Image | None = None) -> None:
        super().__init__()
        self.path: Path | None = None
        self.image: Image.Image | None = None

        self.geometry("1200x760")
        self.minsize(820, 520)

        self.var_mode = tk.StringVar(value="grid")
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(side="top", fill="x")
        for value, label in (("grid", "Grid mode"), ("compose", "Compose mode")):
            ttk.Radiobutton(
                bar, text=label, value=value, variable=self.var_mode,
                style="Toolbutton", width=14, command=self.show_mode,
            ).pack(side="left", padx=(0, 6))
        ttk.Label(
            bar, text="Grid: raster over a photo.    Compose: plan a new picture in a frame.",
            foreground="#777",
        ).pack(side="left", padx=12)
        ttk.Separator(self).pack(side="top", fill="x")

        self.body = ttk.Frame(self)
        self.body.pack(side="top", fill="both", expand=True)
        self.grid_mode = GridMode(self)
        self.compose_mode = ComposeMode(self)
        self.current: CanvasView = self.grid_mode
        self.show_mode()

        self.protocol("WM_DELETE_WINDOW", self.close)
        if path is not None and image is not None:
            self.set_image(path, image)
        else:
            self.update_title()

    # -------------------------------------------------------- mode switching

    def show_mode(self) -> None:
        target = self.compose_mode if self.var_mode.get() == "compose" else self.grid_mode
        for mode in (self.grid_mode, self.compose_mode):
            if mode is not target:
                mode.pack_forget()
        target.pack(fill="both", expand=True)
        self.current = target
        self.update_title()
        target.request_redraw()

    def update_title(self) -> None:
        mode = "Compose" if self.var_mode.get() == "compose" else "Grid"
        if self.path is None or self.image is None:
            self.title(f"Raster Lines - {mode} mode")
        else:
            w, h = self.image.size
            self.title(f"Raster Lines - {mode} mode - {self.path.name}  ({w} x {h})")

    # ----------------------------------------------------------------- image

    def set_image(self, path: Path, image: Image.Image) -> None:
        """Hand a freshly opened photo to both modes."""
        self.path = path
        self.image = image
        self.grid_mode.set_image(path, image)
        self.compose_mode.set_image(path, image)
        self.update_title()

    def open_image(self) -> None:
        target = filedialog.askopenfilename(
            parent=self, title="Choose a photo", initialdir=script_dir(),
            filetypes=OPEN_FILETYPES,
        )
        if not target:
            return
        try:
            image = load_image(target)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Could not open image", f"{target}\n\n{exc}", parent=self)
            return
        self.set_image(Path(target), image)

    def close(self) -> None:
        """Cancel pending redraws so Tk does not fire them on a dead window."""
        for mode in (self.grid_mode, self.compose_mode):
            mode.cancel_redraw()
        self.destroy()


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(
        title="Choose a photo (Cancel to start with an empty window)",
        initialdir=script_dir(),
        filetypes=OPEN_FILETYPES,
    )
    root.destroy()

    image = None
    if path:
        try:
            image = load_image(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Could not open image", f"{path}\n\n{exc}")
            return 1

    RasterApp(Path(path) if image is not None else None, image).mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
