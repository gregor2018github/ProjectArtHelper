"""Compose mode: a fixed output frame, a photo in it, and blocking-out shapes."""

from __future__ import annotations

import math
import os
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageTk

from .common import BG_RGB, OPEN_FILETYPES, script_dir
from .compose import (
    BACKGROUND_COLOR,
    DEFAULT_ERASER_PX,
    Background,
    FRAME_PRESETS,
    MAX_ERASER_PX,
    MIN_ERASER_PX,
    MAX_FRAME,
    MIN_FRAME,
    Item,
    Placement,
    SHAPE_COLOR,
    Shape,
    default_shape_size,
    default_thickness,
    fit_scale,
    flatten,
    format_size,
    parse_frame_size,
    render_composition,
    shape_mask,
    step_thickness,
)
from .view import CanvasView

if TYPE_CHECKING:
    from .app import RasterApp

# Blending towards the dark backdrop instead would bury dark photos completely;
# a mid grey leaves the cut-off part as a faint ghost of itself.
FADE = 0.75
MUTE_RGB = (120, 120, 120)


class ComposeMode(CanvasView):
    """Plan a new picture: a fixed output frame, a photo and blocking-out shapes."""

    fit_padding = 0.88
    clamp_margin = 0.75  # the photo may hang well outside, so let the view follow
    grab_px = 5  # how near an outline the cursor has to be, in screen pixels

    def __init__(self, app: RasterApp) -> None:
        super().__init__(app)
        self.items: list[Item] = []
        self.active: Item | None = None
        self.background = Background()
        self.shape_color = SHAPE_COLOR  # what the next new shape gets
        self._frame_size = FRAME_PRESETS[3]
        self.background.fit_frame(self._frame_size)
        self._item_drag = None
        self._toggle_off = False
        self._erasing = False
        self._pending_select: Item | None = None

        self.var_eraser = tk.BooleanVar(value=False)
        self.var_eraser_size = tk.IntVar(value=DEFAULT_ERASER_PX)
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
        ttk.Label(side, text="Active item", font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(4, 2)
        )
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
            text="Left-click a photo or shape to activate it, then wheel or +/- to "
                 "resize and drag to move; arrow keys nudge. Delete removes what is "
                 "active, and a right-click offers the same. Click it again, or the "
                 "backdrop, to deselect.",
            foreground="#777", wraplength=200,
        ).pack(anchor="w", pady=(0, 12))

        ttk.Separator(side).pack(fill="x", pady=4)
        ttk.Label(side, text="Shapes", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(4, 2))
        shape_row = ttk.Frame(side)
        shape_row.pack(anchor="w", fill="x")
        ttk.Button(
            shape_row, text="Rectangle", width=10,
            command=lambda: self.add_shape("rectangle"),
        ).pack(side="left")
        ttk.Button(
            shape_row, text="Circle", width=8, command=lambda: self.add_shape("circle")
        ).pack(side="left", padx=4)
        color_row = ttk.Frame(side)
        color_row.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Button(color_row, text="Colour...", width=10, command=self.choose_color).pack(
            side="left"
        )
        ttk.Button(
            color_row, text="Background", width=11, command=self.select_background
        ).pack(side="left", padx=4)
        thick_row = ttk.Frame(side)
        thick_row.pack(anchor="w", fill="x", pady=(4, 6))
        ttk.Button(
            thick_row, text="-", width=3, command=lambda: self.step_shape_thickness(False)
        ).pack(side="left")
        ttk.Button(
            thick_row, text="+", width=3, command=lambda: self.step_shape_thickness(True)
        ).pack(side="left", padx=4)
        ttk.Label(thick_row, text="line thickness").pack(side="left")
        ttk.Label(
            side,
            text="Shapes start hollow: grab them by the outline, not the middle, so "
                 "the photo underneath stays reachable. Ctrl+wheel over an active "
                 "shape changes its thickness, up to a solid one (and zooms the view "
                 "otherwise). Colour opens the colour wheel for whatever is active - "
                 "a shape, or the frame's background.",
            foreground="#777", wraplength=200,
        ).pack(anchor="w", pady=(0, 8))

        erase_row = ttk.Frame(side)
        erase_row.pack(anchor="w", fill="x")
        ttk.Checkbutton(
            erase_row, text="Eraser", variable=self.var_eraser, command=self._on_eraser_toggle,
        ).pack(side="left")
        ttk.Spinbox(
            erase_row, from_=MIN_ERASER_PX, to=MAX_ERASER_PX, width=4,
            textvariable=self.var_eraser_size,
        ).pack(side="left", padx=(6, 4))
        ttk.Label(erase_row, text="px").pack(side="left")
        ttk.Button(side, text="Reset eraser", command=self.reset_eraser).pack(
            anchor="w", pady=(4, 0)
        )
        ttk.Label(
            side,
            text="Scrub over a shape to scratch its outline away - handy for "
                 "pretending it passes behind the subject. Reset puts back what "
                 "the active shape lost (or every shape, with none active).",
            foreground="#777", wraplength=200,
        ).pack(anchor="w", pady=(2, 12))

        ttk.Separator(side).pack(fill="x", pady=8)
        zoom_row = ttk.Frame(side)
        zoom_row.pack(anchor="w", pady=(0, 8))
        ttk.Button(zoom_row, text="-", width=3, command=lambda: self.zoom_by(1 / 1.25)).pack(side="left")
        ttk.Button(zoom_row, text="+", width=3, command=lambda: self.zoom_by(1.25)).pack(side="left", padx=4)
        ttk.Button(zoom_row, text="Fit", width=5, command=self.fit_to_window).pack(side="left")
        ttk.Button(zoom_row, text="100%", width=6, command=lambda: self.set_zoom(1.0)).pack(side="left", padx=4)
        ttk.Label(side, text="View zoom, not the item", foreground="#777").pack(anchor="w")

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
        canvas.bind("<Button-3>", self.on_right_click)
        # Delete has to work even when a sidebar control holds the focus, so it
        # is bound on the window too - but not while a text field has it, where
        # the key means "delete a character".
        self.winfo_toplevel().bind("<Delete>", self._on_delete_key, add="+")
        canvas.bind("<Left>", lambda e: self.nudge(-1, 0, e))
        canvas.bind("<Right>", lambda e: self.nudge(1, 0, e))
        canvas.bind("<Up>", lambda e: self.nudge(0, -1, e))
        canvas.bind("<Down>", lambda e: self.nudge(0, 1, e))

    @property
    def frame_size(self) -> tuple[int, int]:
        return self._frame_size

    @frame_size.setter
    def frame_size(self, size: tuple[int, int]) -> None:
        self._frame_size = size
        self.background.fit_frame(size)  # the fill always covers exactly the frame

    def content_size(self) -> tuple[int, int]:
        return self.frame_size

    def fit_bounds(self) -> tuple[float, float, float, float]:
        """The frame, widened to hold any photo hanging over its edges.

        Fitting the frame alone would push a photo larger than the frame half
        off screen, which is exactly the moment you need to see all of it.
        """
        fw, fh = self.frame_size
        x0, y0, x1, y1 = 0.0, 0.0, float(fw), float(fh)
        for item in self.items:
            bx0, by0, bx1, by1 = item.box
            x0, y0, x1, y1 = min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)
        return x0, y0, x1, y1

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
        # one photo for now, but the shapes already on the plan must survive it
        self.items = [item] + [i for i in self.items if not isinstance(i, Placement)]
        self.active = item
        self.var_info.set(f"{path.name}\n{image.width} x {image.height} px")
        self.request_fit()

    def add_shape(self, kind: str) -> None:
        """Drop a hollow shape in the middle of the frame and activate it."""
        side = default_shape_size(self.frame_size)
        shape = Shape(
            name=kind.capitalize(), kind=kind, w=side, h=side,
            thickness=default_thickness(self.frame_size), color=self.shape_color,
        )
        shape.center_in(*self.frame_size)
        self.items.append(shape)
        self.active = shape
        self.canvas.focus_set()  # so Delete and the arrows work straight away
        self.request_redraw()

    @property
    def eraser_radius(self) -> float:
        """Brush radius in frame pixels: a fixed size on screen, whatever the zoom."""
        try:
            px = int(self.var_eraser_size.get())
        except (tk.TclError, ValueError):
            px = DEFAULT_ERASER_PX
        return max(MIN_ERASER_PX, min(px, MAX_ERASER_PX)) / max(self.zoom, 1e-6)

    def _on_eraser_toggle(self) -> None:
        self.canvas.config(cursor="circle" if self.var_eraser.get() else "")
        self.request_redraw()

    def erase_at(self, cx: float, cy: float) -> None:
        """Take a bite out of every shape under the brush."""
        px, py = self.to_image(cx, cy)
        radius = self.eraser_radius
        for item in self.items:
            if isinstance(item, Shape) and item.near(px, py, radius):
                item.erase(px, py, radius)
        self.request_redraw()

    def reset_eraser(self) -> None:
        """Give back what was scratched off: the active shape, or all of them."""
        targets = (
            [self.active]
            if isinstance(self.active, Shape)
            else [i for i in self.items if isinstance(i, Shape)]
        )
        for shape in targets:
            shape.erased.clear()
        self.var_status.set(
            f"Eraser reset on {len(targets)} shape{'' if len(targets) == 1 else 's'}"
        )
        self.request_redraw()

    def select_background(self) -> None:
        """Make the frame's fill the active item, so colour and eraser hit it."""
        self.active = self.background
        self.canvas.focus_set()
        self.request_redraw()

    def choose_color(self) -> None:
        """Pick a colour for the active shape or background, from the colour wheel."""
        item = self.active
        if not isinstance(item, Shape):  # Background is a Shape; a photo is not
            self.var_status.set("Select a shape or the background first, then Colour.")
            return
        rgb, _hex = colorchooser.askcolor(
            color="#%02x%02x%02x" % item.color, parent=self, title=f"Colour of {item.name}"
        )
        if rgb is None:
            return
        item.color = tuple(int(round(v)) for v in rgb)
        if not isinstance(item, Background):
            self.shape_color = item.color  # the next shape inherits the choice
        self.request_redraw()

    def step_shape_thickness(self, grow: bool) -> None:
        """Thicken or thin the active shape's outline."""
        item = self.active
        if not isinstance(item, Shape):
            return
        item.thickness = step_thickness(item.thickness, grow, cap=item.max_thickness)
        self.request_redraw()

    def fit_item(self, cover: bool) -> None:
        item = self.active
        if not isinstance(item, Placement):
            return
        item.rescale(fit_scale(item.image.width, item.image.height, *self.frame_size, cover=cover))
        item.center_in(*self.frame_size)
        self.request_redraw()

    def center_item(self) -> None:
        if self.active is None or not self.active.movable:
            return
        self.active.center_in(*self.frame_size)
        self.request_redraw()

    def scale_item(self, factor: float, anchor: tuple[float, float] | None = None) -> None:
        if self.active is None or not self.active.movable:
            return
        self.active.resize(factor, anchor)
        self.request_redraw()

    def remove_item(self) -> None:
        if self.active is None or not self.active.removable:
            return
        self.items.remove(self.active)
        self.active = None
        if not any(isinstance(i, Placement) for i in self.items):
            self.var_info.set("No photo placed")
        self.request_redraw()

    def nudge(self, dx: int, dy: int, event=None) -> None:
        """Move the active item; a screen pixel at a time, ten with Shift."""
        item = self.active
        if item is None or not item.movable:
            return
        shift = bool(event and event.state & 0x0001)
        step = max(1.0, (10 if shift else 1) / self.zoom)
        item.x += dx * step
        item.y += dy * step
        self.request_redraw()

    def _on_delete_key(self, _event=None) -> None:
        if not self.winfo_ismapped():
            return  # the other mode is on screen
        focused = self.focus_get()
        if isinstance(focused, (ttk.Entry, ttk.Spinbox, tk.Entry, tk.Spinbox)):
            return  # a combobox or spinbox is being edited; leave the text alone
        self.remove_item()

    def on_right_click(self, event) -> None:
        """Select whatever was right-clicked and offer to delete it."""
        hit = self.item_at(event.x, event.y)
        if hit is None:
            return
        self.active = hit
        self.request_redraw()
        menu = tk.Menu(self, tearoff=0)
        if isinstance(hit, Shape):
            menu.add_command(label=f"Colour of {hit.name}...", command=self.choose_color)
        if hit.removable:
            menu.add_command(label=f"Delete {hit.name}", command=self.remove_item)
        self._menu = menu  # keep it alive until it is dismissed
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def item_at(self, cx: float, cy: float) -> Item | None:
        """Topmost item under a canvas point, shapes before the photo they sit on."""
        px, py = self.to_image(cx, cy)
        tol = self.grab_px / self.zoom  # a few screen pixels, in frame units
        for item in reversed(self.items):
            if item.contains(px, py, tol):
                return item
        # Nothing on top: inside the frame that is the background itself, which
        # is how it gets picked without a photo being in the way.
        return self.background if self.background.contains(px, py) else None

    # ---------------------------------------------------------------- events

    def on_press(self, event) -> None:
        self.canvas.focus_set()
        self._press = (event.x, event.y)
        if self.var_eraser.get():
            self._item_drag = None
            self._drag = None
            self._erasing = True
            self.erase_at(event.x, event.y)
            return
        hit = self.item_at(event.x, event.y)
        # Pressing the active item again deactivates it, but only if the press
        # turns out to be a click: dragging the active item must still move it.
        self._toggle_off = hit is not None and hit is self.active
        if hit is None or not hit.movable:
            # The backdrop, or the background: either way the drag pans, and
            # the selection is settled at release if it was a click.
            self._item_drag = None
            self._pending_select = hit
            super().on_press(event)
            return
        self.active = hit
        self._item_drag = (event.x, event.y, hit.x, hit.y)
        self._drag = None
        self.canvas.config(cursor="fleur")
        self.request_redraw()

    def on_drag(self, event) -> None:
        if self._erasing:
            self.erase_at(event.x, event.y)
            return
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
        if self._erasing:
            self._erasing = False
            self.request_redraw()
            return
        px, py = self._press
        clicked = abs(event.x - px) < 3 and abs(event.y - py) < 3
        if clicked:
            if self._toggle_off:
                self.active = None  # clicked what was already active
            elif self._item_drag is None:
                self.active = self._pending_select  # the background, or nothing
        self._pending_select = None
        self._item_drag = None
        self._toggle_off = False
        self._drag = None
        self.canvas.config(cursor="circle" if self.var_eraser.get() else "")
        self.request_redraw()  # redo the last frame at full resample quality

    def on_wheel(self, event, delta: int | None = None) -> None:
        """Wheel resizes the active item; Ctrl+wheel is its thickness, else zoom."""
        step = delta if delta is not None else event.delta
        ctrl = bool(event.state & 0x0004)
        if ctrl and isinstance(self.active, Shape):
            self.step_shape_thickness(step > 0)
        elif self.active is not None and not ctrl:
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
        if tile.mode not in ("RGB", "RGBA"):  # keep alpha; see-through stays see-through
            tile = tile.convert("RGB")
        return tile, (int(round(dx0 + sx0 * sc)), int(round(dy0 + sy0 * sc)))

    def _render_preview(self, cw: int, ch: int, resample: int) -> Image.Image:
        """Backdrop, the frame's fill, photos and shapes - the spill faded."""
        base = Image.new("RGB", (cw, ch), BG_RGB)
        fx0, fy0 = self.to_canvas(0, 0)
        fx1, fy1 = self.to_canvas(*self.frame_size)
        rect = [int(round(fx0)), int(round(fy0)), int(round(fx1)) - 1, int(round(fy1)) - 1]
        frame_mask = Image.new("L", (cw, ch), 0)
        if rect[2] >= rect[0] and rect[3] >= rect[1]:
            ImageDraw.Draw(frame_mask).rectangle(rect, fill=255)
        # The frame's fill is an item like any other: its colour, and its holes
        # where the eraser has been, which show the backdrop through.
        origin = (self.offset_x, self.offset_y)
        base.paste(
            Image.new("RGB", (cw, ch), self.background.color),
            (0, 0),
            shape_mask(self.background, (cw, ch), self.zoom, origin, min_width=1),
        )

        layer = Image.new("RGB", (cw, ch), BG_RGB)
        drawn = Image.new("L", (cw, ch), 0)  # where a photo or a shape landed
        for item in self.items:
            if not isinstance(item, Placement):
                continue  # shapes come after, over the photos
            tile = self._tile(item, cw, ch, resample)
            if tile is None:
                continue
            img, pos = tile
            if img.mode == "RGBA":
                # A photo with transparency shows what is behind it, and only
                # counts as covered where it is actually opaque.
                layer.paste(img, pos, img)
                drawn.paste(img.getchannel("A"), pos)
            else:
                layer.paste(img, pos)
                drawn.paste(Image.new("L", img.size, 255), pos)
        # Shapes go over the photos, through the same mask, so that the spill
        # outside the frame fades for them too. `min_width` keeps a thin
        # outline one screen pixel wide however far out the view is zoomed.
        for item in self.items:
            if not isinstance(item, Shape):
                continue
            mask = shape_mask(item, (cw, ch), self.zoom, origin, min_width=1)
            layer.paste(Image.new("RGB", (cw, ch), item.color), (0, 0), mask)
            drawn = ImageChops.lighter(drawn, mask)
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

    def render(self) -> None:
        self.clamp_offsets()
        cw, ch = self.canvas_size()
        self.canvas.delete("all")

        resample = Image.BILINEAR if self._drag else Image.LANCZOS
        key = (
            cw, ch, round(self.offset_x, 2), round(self.offset_y, 2), round(self.zoom, 6),
            self.frame_size, resample,
            self.background.color, len(self.background.erased),
            tuple(
                (id(i.image), round(i.x, 2), round(i.y, 2), round(i.scale, 6))
                if isinstance(i, Placement)
                else (id(i), round(i.x, 2), round(i.y, 2), round(i.w, 2), round(i.h, 2),
                      i.thickness, len(i.erased))
                for i in self.items
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
            if isinstance(item, Background):
                detail = "frame fill - colour #%02x%02x%02x" % item.color
            elif not isinstance(item, Shape):
                detail = f"{item.scale * 100:.1f}%"
            elif item.filled:
                detail = "filled"
            else:
                detail = f"{item.thickness} px outline"
            self.var_scale.set(
                f"{item.name} - active\n{detail} - covers {w:.0f} x {h:.0f} px "
                f"of the {fw} x {fh} frame"
            )
        elif self.items:
            self.var_scale.set("Nothing active - click a photo or an outline")
        else:
            self.var_scale.set("Open a photo, or add a shape, to start")
        self.var_status.set(f"Frame {fw} x {fh} px  -  view zoom {self.zoom * 100:.0f}%")

    # ------------------------------------------------------------------ save

    def save_as(self) -> None:
        untouched = self.background.color == BACKGROUND_COLOR and not self.background.erased
        if not self.items and untouched:
            messagebox.showinfo("Nothing to save", "Place a photo or a shape first.", parent=self)
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
            result = render_composition(self.frame_size, self.items, self.background)
            if Path(target).suffix.lower() in (".jpg", ".jpeg", ".bmp"):
                flatten(result).save(target, quality=95, subsampling=0)
            else:
                result.save(target)  # PNG and friends keep the erased holes clear
        except Exception as exc:  # noqa: BLE001 - surface any save failure to the user
            messagebox.showerror("Save failed", str(exc), parent=self)
            return
        self.var_status.set(f"Saved: {os.path.basename(target)}")
