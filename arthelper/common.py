"""Bits both modes need: file types, colours, the backdrop, image loading."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

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

# The paper the drawings go on: (width, height) in mm, each way round.
PAPER_FORMATS = {
    "A4 portrait": (210, 297),
    "A4 landscape": (297, 210),
    "A3 portrait": (297, 420),
    "A3 landscape": (420, 297),
}
PAPER_DPI = 300  # what a paper format becomes in pixels for compose mode


def paper_pixels(size_mm: tuple[int, int], dpi: int = PAPER_DPI) -> tuple[int, int]:
    """A paper size in mm as whole pixels at *dpi* - A4 is 2480 x 3508 at 300."""
    return tuple(round(mm / 25.4 * dpi) for mm in size_mm)  # type: ignore[return-value]


MIN_ZOOM = 0.02
MAX_ZOOM = 16.0

BG = "#2b2b2b"
BG_RGB = (43, 43, 43)


FROZEN = getattr(sys, "frozen", False)  # running as the released ArtHelper.exe


def script_dir() -> str:
    """The project folder - where the photos are kept.

    This module lives in the ``arthelper`` package, so the folder to start a
    dialog in is its parent, not its own. In the released exe it is the folder
    holding ArtHelper.exe (the package sits out of sight in ``_internal``).
    """
    if FROZEN:
        return str(Path(sys.executable).resolve().parent)
    return str(Path(__file__).resolve().parent.parent)


def load_image(path: str | Path) -> Image.Image:
    """Open *path* as an RGB / RGBA image with the pixels already decoded."""
    image = Image.open(path)
    image.load()
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    return image
