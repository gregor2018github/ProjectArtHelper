"""The sidebar + canvas both modes are built on."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from PIL import ImageTk

from .common import BG, MAX_ZOOM, MIN_ZOOM

if TYPE_CHECKING:
    from .app import RasterApp


class CanvasView(ttk.Frame):
    """Sidebar + canvas with the zoom / pan plumbing both modes share.

    The view is stored as an image-space offset plus a zoom factor; subclasses
    supply `content_size` (the world they live in) and `render`.
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
        self._pending_fit = False
        self._fit_size: tuple[int, int] | None = None

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

    def fit_bounds(self) -> tuple[float, float, float, float]:
        """The box a fit should bring into view; the content itself by default."""
        w, h = self.content_size()
        return 0.0, 0.0, float(w), float(h)

    def fit_to_window(self) -> None:
        """Zoom so the fit box fills the canvas, and centre the view on it.

        Centring has to be explicit: compose mode lets the view roam well
        outside its frame, so the clamp alone would leave it wherever it was.
        """
        cw, ch = self.canvas_size()
        x0, y0, x1, y1 = self.fit_bounds()
        w, h = x1 - x0, y1 - y0
        if w < 1 or h < 1:
            return
        self.zoom = max(MIN_ZOOM, min(min(cw / w, ch / h) * self.fit_padding, MAX_ZOOM))
        self.offset_x = (x0 + x1) / 2 - cw / (2 * self.zoom)
        self.offset_y = (y0 + y1) / 2 - ch / (2 * self.zoom)
        self.request_redraw()

    def request_fit(self) -> None:
        """Fit once the canvas has a real, settled size.

        The mode that is not on screen has an unmapped 1x1 canvas, so fitting
        right away would compute a meaningless zoom that survives until the
        user presses Fit. Even the first sized draw can come in before the
        layout has settled, so the request stands until two draws agree on the
        canvas size (see `draw`) or the user moves the view themselves.
        """
        self._pending_fit = True
        self._fit_size = None
        self.request_redraw()

    def set_zoom(self, zoom: float, anchor: tuple[float, float] | None = None) -> None:
        self._pending_fit = False
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
    def _clamp_axis(offset: float, view: float, start: float, size: float, margin: float) -> float:
        lo, hi = start - margin, start + size + margin - view
        if hi < lo:  # the whole box fits on screen: centre it
            return start + (size - view) / 2
        return min(max(offset, lo), hi)

    def clamp_offsets(self) -> None:
        """Keep the fit box on screen, give or take `clamp_margin` of its size."""
        cw, ch = self.canvas_size()
        x0, y0, x1, y1 = self.fit_bounds()
        w, h = x1 - x0, y1 - y0
        self.offset_x = self._clamp_axis(
            self.offset_x, cw / self.zoom, x0, w, w * self.clamp_margin
        )
        self.offset_y = self._clamp_axis(
            self.offset_y, ch / self.zoom, y0, h, h * self.clamp_margin
        )

    # -------------------------------------------------- events (overridable)

    def on_press(self, event) -> None:
        self.canvas.focus_set()
        self._drag = (event.x, event.y, self.offset_x, self.offset_y)
        self._press = (event.x, event.y)
        self.canvas.config(cursor="fleur")

    def on_drag(self, event) -> None:
        if not self._drag:
            return
        self._pending_fit = False
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
        self._redraw_job = None
        size = self.canvas_size()
        if self._pending_fit and size > (1, 1):
            if self._fit_size == size:
                self._pending_fit = False  # the canvas settled; the fit stands
            else:
                self._fit_size = size  # it may still be growing: fit again later
                self.fit_to_window()
        self.render()

    def render(self) -> None:
        raise NotImplementedError

    def placeholder(self, text: str) -> None:
        cw, ch = self.canvas_size()
        self.canvas.delete("all")
        self.canvas.create_text(cw / 2, ch / 2, text=text, fill="#888", font=("Segoe UI", 12))
