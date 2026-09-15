"""Bits both modes need: file types, colours, the backdrop, image loading."""

from __future__ import annotations

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

MIN_ZOOM = 0.02
MAX_ZOOM = 16.0

BG = "#2b2b2b"
BG_RGB = (43, 43, 43)


def script_dir() -> str:
    """The project folder - where the photos are kept.

    This module lives in the ``arthelper`` package, so the folder to start a
    dialog in is its parent, not its own.
    """
    return str(Path(__file__).resolve().parent.parent)


def load_image(path: str | Path) -> Image.Image:
    """Open *path* as an RGB / RGBA image with the pixels already decoded."""
    image = Image.open(path)
    image.load()
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    return image
