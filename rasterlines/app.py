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
from .view import CanvasView


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
