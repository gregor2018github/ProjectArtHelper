"""Scan mode: straighten, crop and clean up a photo of a drawing."""

from __future__ import annotations

import os
import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from PIL import Image

from .common import OPEN_FILETYPES, script_dir
from .scan import (
    Corners,
    ScanError,
    ScanSettings,
    clean_folder,
    clean_scan,
    detect_corners,
    whole_image_corners,
)
from .view import CanvasView

if TYPE_CHECKING:
    from .app import ArtHelperApp

FROM_PHOTO = "From the photo"
RATIO_CHOICES = [
    FROM_PHOTO,
    "1.414   (A4, A3 ... paper)",
    "1.5   (3 : 2)",
    "1.333   (4 : 3)",
    "1.25   (5 : 4)",
    "1   (square)",
]
OUTLINE = "#33dd66"
SETTLE_MS = 350  # wait this long after a settings change before re-processing


class ScanMode(CanvasView):
    """Find the paper in a photo, square it up and even out paper and ink.

    Two views of one job: *Photo* shows the original with the paper corners as
    draggable handles (detection is a starting point, not the last word), and
    *Result* shows what will be saved. The result is worked out only when it
    is looked at or saved, and kept until the photo, corners or settings
    change.
    """

    handle_px = 9  # grab radius of a corner handle, in screen pixels

    def __init__(self, app: ArtHelperApp) -> None:
        super().__init__(app)
        self.image: Image.Image | None = None
        self.path: Path | None = None
        self.corners: Corners | None = None
        self._result: Image.Image | None = None
        self._result_key = None
        self._result_error: str | None = None
        self._corner_drag: int | None = None
        self._grab_offset = (0.0, 0.0)  # handle centre minus press point, on screen
        self._settle_job = None

        self.var_view = tk.StringVar(value="photo")
        self.var_inset = tk.StringVar(value="0.5")
        self.var_white = tk.StringVar(value="250")
        self.var_ratio = tk.StringVar(value=FROM_PHOTO)
        self.var_lighting = tk.BooleanVar(value=True)
        self.var_blacks = tk.BooleanVar(value=True)
        self.var_black_point = tk.BooleanVar(value=True)
        self.var_info = tk.StringVar(value="No photo loaded")
        self.var_detect = tk.StringVar(value="")
        self.var_status = tk.StringVar(value="")

        self._build_ui()

    # ---------------------------------------------------------------- layout

    def _build_ui(self) -> None:
        side = self.make_sidebar()
        ttk.Label(side, text="Scan clean-up", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(side, textvariable=self.var_info, foreground="#555").pack(anchor="w", pady=(4, 6))
        ttk.Button(side, text="Open photo...", command=self.app.open_image).pack(
            anchor="w", fill="x", pady=(0, 12)
        )

        ttk.Label(side, text="Show").pack(anchor="w")
        view_row = ttk.Frame(side)
        view_row.pack(anchor="w", fill="x", pady=(2, 12))
        for value, label in (("photo", "Photo + corners"), ("result", "Result")):
            ttk.Radiobutton(
                view_row, text=label, value=value, variable=self.var_view,
                style="Toolbutton", command=self._on_view_change,
            ).pack(side="left", padx=(0, 4))

        ttk.Label(side, text="Paper corners").pack(anchor="w")
        corner_row = ttk.Frame(side)
        corner_row.pack(anchor="w", pady=(2, 2))
        ttk.Button(corner_row, text="Detect again", command=self.detect).pack(side="left")
        ttk.Button(corner_row, text="Whole photo", command=self.use_whole_photo).pack(
            side="left", padx=(4, 0)
        )
        ttk.Label(
            side, text="Drag a handle in the photo view to move a corner.",
            foreground="#777", wraplength=210,
        ).pack(anchor="w", pady=(2, 2))
        ttk.Label(
            side, textvariable=self.var_detect, foreground="#b35300", wraplength=210
        ).pack(anchor="w", pady=(0, 6))

        ttk.Label(side, text="Paper shape (long : short side)").pack(anchor="w")
        ratio_box = ttk.Combobox(side, width=24, textvariable=self.var_ratio, values=RATIO_CHOICES)
        ratio_box.pack(anchor="w", pady=(2, 12))

        ttk.Label(side, text="Trim each edge (% of width)").pack(anchor="w")
        ttk.Spinbox(
            side, from_=0, to=10, increment=0.1, width=10, textvariable=self.var_inset,
        ).pack(anchor="w", pady=(2, 12))

        ttk.Label(side, text="Paper white (0-255)").pack(anchor="w")
        ttk.Spinbox(
            side, from_=150, to=255, increment=1, width=10, textvariable=self.var_white,
        ).pack(anchor="w", pady=(2, 12))

        for text, var in (
            ("Even out the lighting", self.var_lighting),
            ("Even out the blacks", self.var_blacks),
            ("Make the darkest ink black", self.var_black_point),
        ):
            ttk.Checkbutton(side, text=text, variable=var).pack(anchor="w")

        for var in (self.var_inset, self.var_white, self.var_ratio, self.var_lighting,
                    self.var_blacks, self.var_black_point):
            var.trace_add("write", lambda *_: self._settings_changed())

        ttk.Separator(side).pack(fill="x", pady=8)
        zoom_row = ttk.Frame(side)
        zoom_row.pack(anchor="w", pady=(0, 8))
        ttk.Button(zoom_row, text="-", width=3, command=lambda: self.zoom_by(1 / 1.25)).pack(side="left")
        ttk.Button(zoom_row, text="+", width=3, command=lambda: self.zoom_by(1.25)).pack(side="left", padx=4)
        ttk.Button(zoom_row, text="Fit", width=5, command=self.fit_to_window).pack(side="left")
        ttk.Button(zoom_row, text="100%", width=6, command=lambda: self.set_zoom(1.0)).pack(side="left", padx=4)
        ttk.Label(side, text="Wheel = zoom, drag = pan", foreground="#777").pack(anchor="w")

        ttk.Separator(side).pack(fill="x", pady=8)
        ttk.Button(side, text="Save result as...", command=self.save_as).pack(fill="x", ipady=4)
        ttk.Button(side, text="Clean a whole folder...", command=self.process_folder).pack(
            fill="x", pady=(6, 0)
        )
        ttk.Label(side, textvariable=self.var_status, foreground="#237", wraplength=210).pack(
            anchor="w", pady=(8, 0)
        )

        self.make_canvas()
        self.canvas.bind("<Motion>", self._on_motion)

    # ----------------------------------------------------------------- image

    def set_image(self, path: Path, image: Image.Image) -> None:
        self.image = image
        self.path = path
        w, h = image.size
        self.var_info.set(f"{path.name}\n{w} x {h} px")
        self.var_status.set("")
        self._cache_key = None
        self.detect()
        self.request_fit()

    def content_size(self) -> tuple[int, int]:
        shown = self._shown_image()
        return shown.size if shown is not None else (0, 0)

    def _shown_image(self) -> Image.Image | None:
        if self.var_view.get() == "result" and self._result is not None:
            return self._result
        return self.image

    def _on_view_change(self) -> None:
        self._cache_key = None
        self.request_fit()

    # --------------------------------------------------------------- corners

    def detect(self) -> None:
        """Find the paper again, falling back to the whole photo."""
        if self.image is None:
            return
        try:
            self.corners = detect_corners(self.image)
        except ScanError as exc:
            self.corners = whole_image_corners(self.image.size)
            self.var_detect.set(
                f"{exc}\nThe corners start at the photo's edges - drag them onto the paper."
            )
        else:
            self.var_detect.set("")
        self.request_redraw()

    def use_whole_photo(self) -> None:
        if self.image is None:
            return
        self.corners = whole_image_corners(self.image.size)
        self.var_detect.set("")
        self.request_redraw()

    def corner_at(self, cx: float, cy: float) -> int | None:
        """The corner handle within `handle_px` of a canvas point, if any."""
        if self.corners is None or self.var_view.get() != "photo":
            return None
        best, best_d = None, self.handle_px ** 2
        for i, (x, y) in enumerate(self.corners):
            hx, hy = self.to_canvas(x, y)
            d = (hx - cx) ** 2 + (hy - cy) ** 2
            if d <= best_d:
                best, best_d = i, d
        return best

    def _move_corner(self, index: int, cx: float, cy: float) -> None:
        w, h = self.image.size
        x, y = self.to_image(cx, cy)
        moved = list(self.corners)
        moved[index] = (min(max(x, 0.0), w - 1.0), min(max(y, 0.0), h - 1.0))
        self.corners = tuple(moved)
        self.var_detect.set("")
        self.request_redraw()

    # ---------------------------------------------------------------- events

    def on_press(self, event) -> None:
        self._corner_drag = self.corner_at(event.x, event.y)
        if self._corner_drag is None:
            super().on_press(event)
        else:
            # Keep the handle where it was grabbed rather than snapping its
            # centre to the pointer - corners get placed to the pixel.
            hx, hy = self.to_canvas(*self.corners[self._corner_drag])
            self._grab_offset = (hx - event.x, hy - event.y)
            self.canvas.focus_set()
            self.canvas.config(cursor="crosshair")

    def on_drag(self, event) -> None:
        if self._corner_drag is not None:
            gx, gy = self._grab_offset
            self._move_corner(self._corner_drag, event.x + gx, event.y + gy)
        else:
            super().on_drag(event)

    def on_release(self, event) -> None:
        self._corner_drag = None
        super().on_release(event)
        self._on_motion(event)

    def _on_motion(self, event) -> None:
        if self._drag or self._corner_drag is not None:
            return
        self.canvas.config(cursor="hand2" if self.corner_at(event.x, event.y) is not None else "")

    # -------------------------------------------------------------- settings

    @property
    def settings(self) -> ScanSettings:
        return ScanSettings(
            inset=_number(self.var_inset.get(), 0.5, 0.0, 10.0) / 100,
            white=int(_number(self.var_white.get(), 250, 150, 255)),
            ratio=parse_ratio(self.var_ratio.get()),
            lighting=self.var_lighting.get(),
            blacks=self.var_blacks.get(),
            black_point=self.var_black_point.get(),
        )

    def _settings_changed(self) -> None:
        """Re-process once the user stops fiddling, not on every spinbox step."""
        if self._settle_job is not None:
            self.after_cancel(self._settle_job)
        self._settle_job = self.after(SETTLE_MS, self._settled)

    def _settled(self) -> None:
        self._settle_job = None
        self.request_redraw()

    def cancel_redraw(self) -> None:
        super().cancel_redraw()
        if self._settle_job is not None:
            self.after_cancel(self._settle_job)
            self._settle_job = None

    # ---------------------------------------------------------------- result

    def result(self) -> Image.Image | None:
        """The cleaned image for the current photo, corners and settings.

        Worked out on demand and cached; a failure leaves None and the reason
        in `_result_error`.
        """
        if self.image is None or self.corners is None:
            return None
        settings = self.settings
        key = (id(self.image), self.corners, settings)
        if key != self._result_key:
            self._result_key = key
            self._result, self._result_error = None, None
            top = self.winfo_toplevel()
            top.config(cursor="watch")
            top.update_idletasks()
            try:
                self._result = clean_scan(self.image, self.corners, settings)
            except ScanError as exc:
                self._result_error = str(exc)
            except Exception as exc:  # noqa: BLE001 - show it rather than lose it
                self._result_error = f"Processing failed: {exc}"
            finally:
                top.config(cursor="")
            self._cache_key = None
        return self._result

    # --------------------------------------------------------------- drawing

    def render(self) -> None:
        if self.image is None:
            self.placeholder("Open a photo of a drawing to start")
            self.var_status.set("")
            return
        if self.var_view.get() == "result":
            self._render_result()
        else:
            self._render_photo()

    def _render_photo(self) -> None:
        self.clamp_offsets()
        self.canvas.delete("all")
        self.show_image(self.image)
        if self.corners is not None:
            points = [self.to_canvas(x, y) for x, y in self.corners]
            flat = [v for p in points + points[:1] for v in p]
            self.canvas.create_line(*flat, fill="#000", width=4)
            self.canvas.create_line(*flat, fill=OUTLINE, width=2)
            r = 6
            for x, y in points:
                self.canvas.create_oval(x - r, y - r, x + r, y + r, fill="#fff", outline="#000", width=2)
        self.var_status.set(f"Zoom {self.zoom * 100:.0f}%  -  drag the corners onto the paper")

    def _render_result(self) -> None:
        before = self._result.size if self._result is not None else None
        result = self.result()
        if result is None:
            self.placeholder(self._result_error or "Nothing to show")
            self.var_status.set("")
            return
        if result.size != before:
            self.request_fit()  # a different shape of paper: start from a fresh fit
        self.clamp_offsets()
        self.canvas.delete("all")
        self.show_image(result)
        w, h = result.size
        self.var_status.set(f"Result {w} x {h} px  -  zoom {self.zoom * 100:.0f}%")

    # ------------------------------------------------------------------ save

    def save_as(self) -> None:
        if self.image is None or self.path is None:
            messagebox.showinfo("Nothing to save", "Open a photo first.", parent=self)
            return
        result = self.result()
        if result is None:
            messagebox.showerror("Nothing to save", self._result_error or "No result.", parent=self)
            return
        target = filedialog.asksaveasfilename(
            parent=self,
            title="Save the cleaned drawing",
            initialdir=str(self.path.parent),
            initialfile=f"{self.path.stem}_clean.png",
            defaultextension=".png",
            filetypes=OPEN_FILETYPES,
        )
        if not target:
            return
        try:
            if Path(target).suffix.lower() in (".jpg", ".jpeg"):
                result.save(target, quality=95, subsampling=0)
            else:
                result.save(target)
        except Exception as exc:  # noqa: BLE001 - surface any save failure to the user
            messagebox.showerror("Save failed", str(exc), parent=self)
            return
        self.var_status.set(f"Saved: {os.path.basename(target)}")

    def process_folder(self) -> None:
        """Clean every photo in a folder with the current settings.

        Corners are detected per photo, so a photo the detection gets wrong is
        reported and is best redone one at a time in this view.
        """
        start = str(self.path.parent) if self.path else script_dir()
        in_dir = filedialog.askdirectory(
            parent=self, title="Choose the folder of drawing photos", initialdir=start
        )
        if not in_dir:
            return
        out_dir = filedialog.askdirectory(
            parent=self, title="Choose where the cleaned images go", initialdir=in_dir
        )
        if not out_dir:
            return

        top = self.winfo_toplevel()

        def progress(done: int, total: int, name: str) -> None:
            self.var_status.set(f"Cleaning {done + 1} of {total}: {name}")
            top.update_idletasks()

        top.config(cursor="watch")
        try:
            report = clean_folder(Path(in_dir), Path(out_dir), self.settings, progress)
        except Exception as exc:  # noqa: BLE001 - e.g. an unwritable output folder
            messagebox.showerror("Clean-up failed", str(exc), parent=self)
            return
        finally:
            top.config(cursor="")

        failed = [(name, err) for name, err in report if err]
        done = len(report) - len(failed)
        self.var_status.set(f"Cleaned {done} of {len(report)} photos")
        if not report:
            messagebox.showinfo("No photos", f"No images found in\n{in_dir}", parent=self)
            return
        text = f"Cleaned {done} of {len(report)} photos into\n{out_dir}"
        if failed:
            lines = "\n".join(f"- {name}: {err}" for name, err in failed[:15])
            more = f"\n... and {len(failed) - 15} more" if len(failed) > 15 else ""
            text += f"\n\nCould not clean:\n{lines}{more}\n\nOpen those one at a time and place the corners by hand."
            messagebox.showwarning("Folder cleaned, with problems", text, parent=self)
        else:
            messagebox.showinfo("Folder cleaned", text, parent=self)


def parse_ratio(text: str) -> float | None:
    """The long / short paper ratio in *text*, or None to measure it.

    Reads the first number, or a pair like ``3:2`` / ``297 x 210``; anything
    without a usable number (such as "From the photo") means measure it.
    """
    text = text.replace(",", ".")
    pair = re.match(r"\s*(\d+(?:\.\d+)?)\s*[:x/]\s*(\d+(?:\.\d+)?)", text)
    if pair:
        a, b = float(pair.group(1)), float(pair.group(2))
        value = a / b if b else 0.0
    else:
        first = re.search(r"\d+(?:\.\d+)?", text)
        value = float(first.group()) if first else 0.0
    if value <= 0:
        return None
    return value if value >= 1 else 1 / value


def _number(text: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(str(text).replace(",", "."))
    except ValueError:
        return default
    return min(max(value, lo), hi)
