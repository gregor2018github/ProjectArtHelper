"""The sidebar + canvas both modes are built on."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from PIL import ImageTk

from .common import BG, MAX_ZOOM, MIN_ZOOM

if TYPE_CHECKING:
    from .app import ArtHelperApp


class CanvasView(ttk.Frame):
    """Sidebar + canvas with the zoom / pan plumbing both modes share.

    The view is stored as an image-space offset plus a zoom factor; subclasses
    supply `content_size` (the world they live in) and `render`.
    """

    fit_padding = 0.98
    clamp_margin = 0.0  # how far outside the content panning may go, as a fraction

    def __init__(self, app: ArtHelperApp) -> None:
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
        self._sidebar_holder: tk.Canvas | None = None
        self._pending_fit = False
        self._fit_size: tuple[int, int] | None = None

    # ---------------------------------------------------------------- widgets

    def make_sidebar(self) -> ttk.Frame:
        """The controls column, which scrolls when the window is too short.

        The controls go in a frame held inside a canvas window rather than
        packed straight into the mode: the canvas keeps the frame at its
        natural width so nothing reflows, and the scrollbar appears only once
        the controls no longer fit, so a tall enough window looks unchanged.
        """
        outer = ttk.Frame(self)
        outer.pack(side="left", fill="y")
        holder = tk.Canvas(
            outer, highlightthickness=0, takefocus=0, width=1,
            background=ttk.Style().lookup("TFrame", "background") or "#f0f0f0",
        )
        holder.pack(side="left", fill="y", expand=True)
        bar = ttk.Scrollbar(outer, orient="vertical", command=holder.yview)
        holder.configure(yscrollcommand=bar.set)

        side = ttk.Frame(holder, padding=12)
        window = holder.create_window(0, 0, window=side, anchor="nw")

        def sync(_event=None) -> None:
            """Match the canvas to the controls, and show the bar if needed."""
            want = side.winfo_reqwidth()
            holder.configure(width=want, scrollregion=(0, 0, want, side.winfo_reqheight()))
            holder.itemconfigure(window, width=max(holder.winfo_width(), want))
            if side.winfo_reqheight() > holder.winfo_height():
                if not bar.winfo_ismapped():
                    bar.pack(side="right", fill="y")
            elif bar.winfo_ismapped():
                bar.pack_forget()
                holder.yview_moveto(0)  # nothing is hidden, so start from the top

        side.bind("<Configure>", sync)
        holder.bind("<Configure>", sync)
        self._sidebar_holder = holder
        self.bind_all("<MouseWheel>", self._on_sidebar_wheel, add="+")
        self.bind_all("<Button-4>", lambda e: self._on_sidebar_wheel(e, delta=120), add="+")
        self.bind_all("<Button-5>", lambda e: self._on_sidebar_wheel(e, delta=-120), add="+")
        return side

    def _on_sidebar_wheel(self, event, delta: int | None = None) -> str | None:
        """Scroll the sidebar the pointer is actually over, and nothing else.

        The wheel has to be caught application-wide: bindings do not travel up
        to a parent frame, so a wheel over a button inside the sidebar would
        otherwise reach no one. Walking up from the widget under the pointer
        keeps the event with the right sidebar - the other mode's copy of this
        handler sees the same event and does nothing, as does a wheel over a
        drawing canvas, which has already zoomed by the time we are called.
        """
        holder = getattr(self, "_sidebar_holder", None)
        if holder is None or str(holder.cget("scrollregion")) == "":
            return None
        widget = event.widget
        while widget is not None:
            if widget is holder:
                if holder.winfo_height() >= self._sidebar_height():
                    return None  # it all fits; there is nothing to scroll
                step = delta if delta is not None else event.delta
                holder.yview_scroll(-1 if step > 0 else 1, "units")
                return "break"
            widget = getattr(widget, "master", None)
        return None

    def _sidebar_height(self) -> int:
        region = self._sidebar_holder.cget("scrollregion").split()
        return int(float(region[3])) if len(region) == 4 else 0

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
