"""Raster Lines - draw a reference grid onto a photo.

Pick an image, choose line thickness / grid spacing / colour, check the live
preview, and save a copy with the grid baked in.
"""

from __future__ import annotations

import math
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

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


def desktop_dir() -> str:
    """Best guess at the desktop folder, falling back to the home folder."""
    home = Path.home()
    for candidate in (home / "Desktop", home / "OneDrive" / "Desktop"):
        if candidate.is_dir():
            return str(candidate)
    return str(home)


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


class RasterApp(tk.Tk):
    def __init__(self, path: Path, image: Image.Image) -> None:
        super().__init__()
        self.path = path
        self.image = image
        self.iw, self.ih = image.size

        self.title(f"Raster Lines - {path.name}  ({self.iw} x {self.ih})")
        self.geometry("1200x760")
        self.minsize(760, 480)

        self.zoom = 1.0
        self.offset_x = 0.0  # top-left corner of the view, in image coordinates
        self.offset_y = 0.0
        self._photo: ImageTk.PhotoImage | None = None
        self._cache_key = None
        self._drag = None
        self._press = (0, 0)
        self._redraw_job = None

        self.options = spacing_options(self.iw, self.ih)
        # False when the dimensions share no usable divisor, i.e. no spacing can
        # tile this photo with whole squares.
        self.exact_possible = any(self.iw % v == 0 and self.ih % v == 0 for v in self.options)
        self.var_thickness = tk.IntVar(value=2)
        self.var_spacing = tk.StringVar(value=str(default_spacing(self.options, self.iw, self.ih)))
        self.var_color = tk.StringVar(value="Red")
        self.var_status = tk.StringVar(value="")
        self.var_warning = tk.StringVar(value="")
        self.var_subdivide = tk.BooleanVar(value=False)
        self.var_factor = tk.StringVar(value="4x")
        # Cells refined for critical areas (hands, faces): (col, row) -> factor.
        # Cell indices only mean something for one spacing, so a spacing change
        # drops them (see redraw).
        self.subdivisions: dict[tuple[int, int], int] = {}
        self._sub_spacing = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(60, self.fit_to_window)
        if not self.exact_possible:
            self.after(200, self._warn_no_exact_raster)

    def close(self) -> None:
        """Cancel any pending redraw so Tk does not fire it on a dead window."""
        if self._redraw_job is not None:
            self.after_cancel(self._redraw_job)
            self._redraw_job = None
        self.destroy()

    def _warn_no_exact_raster(self) -> None:
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

    # ---------------------------------------------------------------- layout

    def _build_ui(self) -> None:
        side = ttk.Frame(self, padding=12)
        side.pack(side="left", fill="y")
        ttk.Label(side, text="Raster settings", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(
            side, text=f"{self.path.name}\n{self.iw} x {self.ih} px", foreground="#555"
        ).pack(anchor="w", pady=(4, 12))

        ttk.Label(side, text="Line thickness (px)").pack(anchor="w")
        ttk.Spinbox(
            side, from_=1, to=50, width=10, textvariable=self.var_thickness,
            command=self.request_redraw,
        ).pack(anchor="w", pady=(2, 12))

        ttk.Label(side, text="Distance between lines (px)").pack(anchor="w")
        labels = [f"{v} px   ({cells(self.iw, v)} x {cells(self.ih, v)})" for v in self.options]
        self.spacing_box = ttk.Combobox(side, width=20, textvariable=self.var_spacing, values=labels)
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

        self.canvas = tk.Canvas(self, background="#2b2b2b", highlightthickness=0)
        self.canvas.pack(side="right", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.request_redraw())
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<MouseWheel>", self.on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self.on_wheel(e, delta=120))
        self.canvas.bind("<Button-5>", lambda e: self.on_wheel(e, delta=-120))

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
            value = default_spacing(self.options, self.iw, self.ih)
        return max(2, min(value, max(self.iw, self.ih)))

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
        img_x = self.offset_x + cx / self.zoom
        img_y = self.offset_y + cy / self.zoom
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

    # ------------------------------------------------------------------ view

    def canvas_size(self) -> tuple[int, int]:
        return max(self.canvas.winfo_width(), 1), max(self.canvas.winfo_height(), 1)

    def fit_to_window(self) -> None:
        cw, ch = self.canvas_size()
        self.set_zoom(min(cw / self.iw, ch / self.ih) * 0.98)

    def set_zoom(self, zoom: float, anchor: tuple[float, float] | None = None) -> None:
        cw, ch = self.canvas_size()
        new = max(MIN_ZOOM, min(zoom, MAX_ZOOM))
        if anchor is None:
            anchor = (cw / 2, ch / 2)
        ax, ay = anchor
        img_x = self.offset_x + ax / self.zoom
        img_y = self.offset_y + ay / self.zoom
        self.zoom = new
        self.offset_x = img_x - ax / new
        self.offset_y = img_y - ay / new
        self.request_redraw()

    def zoom_by(self, factor: float) -> None:
        self.set_zoom(self.zoom * factor)

    def clamp_offsets(self) -> None:
        cw, ch = self.canvas_size()
        vw, vh = cw / self.zoom, ch / self.zoom
        self.offset_x = (self.iw - vw) / 2 if vw >= self.iw else min(max(self.offset_x, 0), self.iw - vw)
        self.offset_y = (self.ih - vh) / 2 if vh >= self.ih else min(max(self.offset_y, 0), self.ih - vh)

    def on_press(self, event) -> None:
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
        self.canvas.config(cursor="crosshair" if self.var_subdivide.get() else "")
        # A click that did not pan is a cell pick; anything further is a drag.
        px, py = self._press
        if self.var_subdivide.get() and abs(event.x - px) < 3 and abs(event.y - py) < 3:
            self.toggle_cell(event.x, event.y)
        self.request_redraw()  # redo the last frame at full resample quality

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
            self._redraw_job = self.after(16, self.redraw)

    def redraw(self) -> None:
        self._redraw_job = None
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


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(
        title="Choose a photo", initialdir=desktop_dir(), filetypes=OPEN_FILETYPES
    )
    root.destroy()
    if not path:
        return 0

    try:
        image = Image.open(path)
        image.load()
    except Exception as exc:  # noqa: BLE001
        messagebox.showerror("Could not open image", f"{path}\n\n{exc}")
        return 1
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")

    RasterApp(Path(path), image).mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
