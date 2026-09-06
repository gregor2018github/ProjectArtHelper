# Raster Lines

A small desktop tool that draws a reference grid onto a photo, so you can
sketch difficult subjects square by square instead of building the grid by hand
in an image editor.

## Features

- Pick any `.png` / `.jpg` / `.jpeg` / `.bmp` / `.tif` / `.webp`; the file
  dialog opens on your Desktop.
- Adjustable line thickness (default 2 px) and colour (default red).
- Grid spacing suggestions computed from the image size. Every suggestion
  divides both edges exactly, so there are no half cells at the border — e.g.
  `250 px (4 x 8)` for a 1000 x 2000 photo. You can still type any spacing you
  like; the status line then tells you the edge cells are partial.
- Live preview with mouse-wheel zoom (anchored at the cursor) and drag to pan.
- Saves a copy in the original format, with the save dialog opening in the
  folder the photo came from.

## Requirements

- Python 3.10+ with tkinter (included in the standard Windows installer)
- [Pillow](https://python-pillow.org/)

## Setup

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Usage

```powershell
.venv\Scripts\python.exe raster_lines.py
```

On Windows you can also double-click `run.bat`.

1. Choose a photo in the file dialog.
2. Set thickness, spacing and colour in the left panel — the preview updates as
   you type.
3. Zoom with the mouse wheel or the `-` / `+` / `Fit` / `100%` buttons; drag to
   pan.
4. **Save as…** writes a new file, defaulting to `<name>_raster.<same ext>` next
   to the original.

The preview keeps thin lines at least one screen pixel wide so they remain
visible when zoomed out; the saved file always uses the exact thickness you
chose at full resolution.

## License

MIT
