"""The window: a mode switch on top, one mode frame filling the rest."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image

from .common import OPEN_FILETYPES, load_image, script_dir
from .compose_mode import ComposeMode
from .grid_mode import GridMode
from .scan_mode import ScanMode
from .splash import play_splash, set_app_icon
from .view import CanvasView

# (key, button label, title word) for each mode, in the order of the switch.
MODES = (
    ("grid", "Grid mode", "Grid"),
    ("compose", "Compose mode", "Compose"),
    ("scan", "Scan mode", "Scan"),
)


class ArtHelperApp(tk.Tk):
    """The window: a mode switch on top, one mode frame filling the rest."""

    def __init__(
        self, path: Path | None = None, image: Image.Image | None = None,
        mode: str = "grid",
    ) -> None:
        super().__init__()
        set_app_icon(self)
        self.path: Path | None = None
        self.image: Image.Image | None = None

        self.geometry("1200x760")
        self.minsize(820, 520)

        if mode not in (key for key, _l, _w in MODES):
            mode = "grid"
        self.var_mode = tk.StringVar(value=mode)
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(side="top", fill="x")
        for value, label, _word in MODES:
            ttk.Radiobutton(
                bar, text=label, value=value, variable=self.var_mode,
                style="Toolbutton", width=14, command=self.show_mode,
            ).pack(side="left", padx=(0, 6))
        ttk.Label(
            bar,
            text="Grid: raster over a photo.    Compose: plan a new picture in a frame.    "
            "Scan: clean up a photo of a drawing.",
            foreground="#777",
        ).pack(side="left", padx=12)
        ttk.Separator(self).pack(side="top", fill="x")

        self.body = ttk.Frame(self)
        self.body.pack(side="top", fill="both", expand=True)
        self.grid_mode = GridMode(self)
        self.compose_mode = ComposeMode(self)
        self.scan_mode = ScanMode(self)
        self.modes: dict[str, CanvasView] = {
            "grid": self.grid_mode, "compose": self.compose_mode, "scan": self.scan_mode,
        }
        self.current: CanvasView = self.grid_mode
        self.show_mode()

        self.protocol("WM_DELETE_WINDOW", self.close)
        if path is not None and image is not None:
            self.set_image(path, image)
        else:
            self.update_title()

    # -------------------------------------------------------- mode switching

    def show_mode(self) -> None:
        target = self.modes.get(self.var_mode.get(), self.grid_mode)
        for mode in self.modes.values():
            if mode is not target:
                mode.pack_forget()
        target.pack(fill="both", expand=True)
        self.current = target
        self.update_title()
        target.request_redraw()

    def update_title(self) -> None:
        mode = next((word for key, _l, word in MODES if key == self.var_mode.get()), "Grid")
        if self.path is None or self.image is None:
            self.title(f"Art Helper - {mode} mode")
        else:
            w, h = self.image.size
            self.title(f"Art Helper - {mode} mode - {self.path.name}  ({w} x {h})")

    # ----------------------------------------------------------------- image

    def set_image(self, path: Path, image: Image.Image) -> None:
        """Hand a freshly opened photo to every mode."""
        self.path = path
        self.image = image
        for mode in self.modes.values():
            mode.set_image(path, image)
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

    def maximize(self) -> None:
        """Fill the screen, keeping the title bar and the taskbar.

        Windows and macOS call it "zoomed"; X11 window managers use the
        -zoomed attribute instead. The 1200x760 geometry stays as the size
        to return to when the user un-maximizes.
        """
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                pass  # no maximize support: keep the default size

    def bring_to_front(self) -> None:
        """Put the window in front of whatever the user was looking at.

        The photo dialog runs on a throwaway root that dies before this window
        appears, so Windows has no reason to hand the focus on and the app
        opens behind the other windows. A momentary -topmost lifts it without
        pinning it there.
        """
        self.lift()
        self.attributes("-topmost", True)
        self.after_idle(self.attributes, "-topmost", False)
        self.focus_force()

    def close(self) -> None:
        """Cancel pending redraws so Tk does not fire them on a dead window."""
        for mode in self.modes.values():
            mode.cancel_redraw()
        self.destroy()


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    set_app_icon(root)
    mode = play_splash(root)
    if mode is None:  # Escape on the splash: leave without opening anything
        root.destroy()
        return 0
    word = next((w for key, _l, w in MODES if key == mode), "Grid")
    path = filedialog.askopenfilename(
        title=f"{word} mode: choose a photo (Cancel to start with an empty window)",
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

    app = ArtHelperApp(Path(path) if image is not None else None, image, mode)
    app.maximize()
    app.bring_to_front()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
