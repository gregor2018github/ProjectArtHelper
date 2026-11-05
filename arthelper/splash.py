"""Start-up splash: plays the logo animation, then waits for a mode button.

All drawing comes from `logo.LogoAnimation`; this module only shows the
frames and turns clicks into a choice. Playback follows the wall clock, so a
slow frame is skipped rather than stretching the animation.

The finished logo stays up with its three mode buttons (grid / compose /
scan). Clicking one (or pressing 1 / 2 / 3) fades the splash out quickly and
`play_splash` returns that mode; the caller then asks for the photo. A click
elsewhere or any other key skips the animation to its end; Escape quits.
"""

from __future__ import annotations

import time
import tkinter as tk

from PIL import ImageTk

from .logo import DURATION, GREY, LogoAnimation, render_icon

FRAME_MS = 16       # ~60 fps, so hover and the fade-out feel immediate
FADE_S = 0.18       # quick fade after a choice, straight into the photo dialog
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
    """Borderless, centred window: plays the intro, then offers the modes."""

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

        self.choice: str | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._start = time.perf_counter()
        self._finished = False   # animation at its end, waiting for a choice
        self._closing = False
        self._hover: int | None = None
        self._job: str | None = None  # the pending tick / fade step
        self.label.bind("<Motion>", self._on_motion)
        self.label.bind("<Leave>", lambda _e: self._set_hover(None))
        self.label.bind("<Button-1>", self._on_click)
        self.bind("<Key>", self._on_key)
        self.focus_force()
        self._tick()

    # ------------------------------------------------------------- playback
    def _set_alpha(self, value: float) -> None:
        try:
            self.attributes("-alpha", value)
        except tk.TclError:
            pass  # window managers without transparency just show it

    def _now(self) -> float:
        return DURATION if self._finished else time.perf_counter() - self._start

    def _show(self) -> None:
        t = min(self._now(), DURATION)
        self._photo = ImageTk.PhotoImage(self.anim.frame(t, self._hover), master=self)
        self.label.configure(image=self._photo)

    def _tick(self) -> None:
        if self._finished or self._closing:  # skipped: nothing left to animate
            return
        t = self._now()
        self._set_alpha(min(1.0, t / FADE_IN_S))
        if t >= DURATION:
            self._finished = True
        self._show()
        if not self._finished:
            self._job = self.after(FRAME_MS, self._tick)

    def skip(self) -> None:
        """Jump to the finished logo, buttons and all."""
        if self._finished or self._closing:
            return
        self._finished = True
        self._set_alpha(1.0)
        self._show()

    # ------------------------------------------------------------- input
    def _set_hover(self, index: int | None) -> None:
        if self._closing or index == self._hover:
            return
        self._hover = index
        self.label.configure(cursor="hand2" if index is not None else "")
        if self._finished:  # mid-animation the next tick picks it up
            self._show()

    def _button_at(self, x: int, y: int) -> int | None:
        if not self.anim.buttons_shown(self._now()):
            return None
        return self.anim.button_at(x, y)

    def _on_motion(self, event: tk.Event) -> None:
        self._set_hover(self._button_at(event.x, event.y))

    def _on_click(self, event: tk.Event) -> None:
        index = self._button_at(event.x, event.y)
        if index is None:
            self.skip()
        else:
            self.choose(index)

    def _on_key(self, event: tk.Event) -> None:
        if event.keysym == "Escape":
            self.cancel()
        elif event.char in ("1", "2", "3")[: len(self.anim.lay.buttons)]:
            self.choose(int(event.char) - 1)
        else:
            self.skip()

    # ------------------------------------------------------------- closing
    def choose(self, index: int) -> None:
        """Pick a mode: show it pressed and fade out quickly."""
        if self._closing:
            return
        self.choice = self.anim.lay.buttons[index]
        self._finished = True
        self._hover = None
        self._set_hover(index)
        self._set_alpha(1.0)
        if self._job is not None:  # a pending animation tick would just return
            self.after_cancel(self._job)
        self._fade_out(time.perf_counter())

    def cancel(self) -> None:
        """Close without a choice (the caller quits)."""
        if not self._closing:
            self._closing = True
            self.destroy()

    def destroy(self) -> None:
        """Cancel the pending frame so Tk does not fire it on a dead window."""
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        super().destroy()

    def _fade_out(self, started: float) -> None:
        self._closing = True
        p = (time.perf_counter() - started) / FADE_S
        if p >= 1.0:
            self.destroy()
            return
        self._set_alpha(1.0 - p * p)  # ease in: the button lingers, then goes
        self._job = self.after(FRAME_MS, self._fade_out, started)


def play_splash(master: tk.Misc) -> str | None:
    """Show the intro and wait for the user to pick a mode.

    Args:
        master: Any Tk widget; usually the (withdrawn) root window.

    Returns:
        The chosen button's label ("grid", "compose" or "scan"), or None if
        the splash was dismissed with Escape.
    """
    splash = Splash(master)
    master.wait_window(splash)
    return splash.choice
