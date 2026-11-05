"""Start-up splash: plays the logo animation in a borderless window.

All drawing comes from `logo.LogoAnimation`; this module only shows the
frames. Playback follows the wall clock, so a slow frame is skipped rather
than stretching the animation. A click or any key skips straight to the end.
"""

from __future__ import annotations

import time
import tkinter as tk

from PIL import ImageTk

from .logo import DURATION, GREY, LogoAnimation, render_icon

FRAME_MS = 33       # ~30 fps
HOLD_S = 0.45       # the finished logo stays this long before fading
FADE_S = 0.30
FADE_IN_S = 0.15


def _ui_scale(widget: tk.Misc) -> float:
    """Pixels per logical pixel (1.0 unless Tk is running DPI-aware)."""
    try:
        return max(1.0, min(3.0, widget.winfo_fpixels("1i") / 96.0))
    except tk.TclError:
        return 1.0


def set_app_icon(window: tk.Tk) -> None:
    """Give `window` (and every later toplevel) the Art Helper icon."""
    icons = [ImageTk.PhotoImage(render_icon(size), master=window) for size in (64, 32, 16)]
    window.iconphoto(True, *icons)
    window._art_helper_icons = icons  # keep references alive  # noqa: SLF001


class Splash(tk.Toplevel):
    """Borderless, centred window that plays the intro once and closes."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.overrideredirect(True)
        self.configure(background="#%02x%02x%02x" % GREY)  # 1 px border colour
        self.anim = LogoAnimation(scale=_ui_scale(self))
        w, h = self.anim.size

        self.label = tk.Label(self, borderwidth=0, highlightthickness=0)
        self.label.pack(padx=1, pady=1)
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w + 2}x{h + 2}+{x}+{y}")
        self.attributes("-topmost", True)
        self._set_alpha(0.0)

        self._photo: ImageTk.PhotoImage | None = None
        self._start = time.perf_counter()
        self._closing = False
        for seq in ("<Button>", "<Key>"):
            self.bind(seq, self.skip)
        self.focus_force()
        self._tick()

    # ------------------------------------------------------------- playback
    def _set_alpha(self, value: float) -> None:
        try:
            self.attributes("-alpha", value)
        except tk.TclError:
            pass  # window managers without transparency just show it

    def _show(self, t: float) -> None:
        self._photo = ImageTk.PhotoImage(self.anim.frame(t), master=self)
        self.label.configure(image=self._photo)

    def _tick(self) -> None:
        if self._closing:  # skipped: the fade-out owns the window now
            return
        t = time.perf_counter() - self._start
        if t < DURATION + HOLD_S:
            self._set_alpha(min(1.0, t / FADE_IN_S))
            self._show(min(t, DURATION))
            self.after(FRAME_MS, self._tick)
        else:
            self._fade_out(time.perf_counter())

    def skip(self, _event: tk.Event | None = None) -> None:
        """Jump to the finished logo and fade out."""
        if self._closing:
            return
        self._set_alpha(1.0)
        self._show(DURATION)
        self._fade_out(time.perf_counter())

    def _fade_out(self, started: float) -> None:
        self._closing = True
        p = (time.perf_counter() - started) / FADE_S
        if p >= 1.0:
            self.destroy()
            return
        self._set_alpha(1.0 - p)
        self.after(FRAME_MS, self._fade_out, started)


def play_splash(master: tk.Misc) -> None:
    """Show the intro and return once it has closed.

    Args:
        master: Any Tk widget; usually the (withdrawn) root window.
    """
    splash = Splash(master)
    master.wait_window(splash)
