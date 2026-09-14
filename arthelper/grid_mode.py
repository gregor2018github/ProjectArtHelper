"""Grid mode: a raster over a photo, saved with the lines baked in."""

from __future__ import annotations

import math
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from PIL import Image, ImageTk

from .common import COLORS, OPEN_FILETYPES
from .grid import (
    SUBDIVISION_FACTORS,
    cell_at,
    cell_bounds,
    cells,
    default_spacing,
    draw_grid,
    grid_positions,
    spacing_options,
    subdivision_lines,
)
from .view import CanvasView

if TYPE_CHECKING:
    from .app import ArtHelperApp


class GridMode(CanvasView):
    """Overlay a raster on a photo and save it baked in at full resolution."""

    def __init__(self, app: ArtHelperApp) -> None:
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
        self.request_fit()
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

    def render(self) -> None:
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
