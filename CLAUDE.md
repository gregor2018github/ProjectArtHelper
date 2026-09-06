# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A small single-purpose desktop tool: load a photo, overlay a regular grid
("raster") of coloured lines, and save a copy with the grid baked in. It exists
to replace doing the same job by hand in GIMP before drawing a subject.

Single user, single developer. Keep it simple — no packaging, no plugin system,
no config files.

## Layout

- [raster_lines.py](raster_lines.py) — the whole program (~300 lines).
  - Module-level pure functions (`spacing_options`, `default_spacing`,
    `grid_positions`, `draw_grid`) hold all the grid maths and are testable
    without a display.
  - `RasterApp(tk.Tk)` is the single window: settings panel on the left, live
    preview canvas on the right.
- [requirements.txt](requirements.txt) — Pillow only; tkinter ships with Python.
- `.venv/` — local virtual environment (git-ignored).

## Running

```powershell
.venv\Scripts\python.exe raster_lines.py
```

Or double-click [run.bat](run.bat).

## Key design decisions

- **The preview draws the grid as Tk canvas line items, not baked pixels.**
  Baking a 2 px line into a downscaled preview makes it disappear; canvas lines
  are clamped to a minimum width of 1 px so the grid stays visible at any zoom.
  Saving uses `draw_grid()` on the full-resolution image instead, so the output
  is exact even though it is not pixel-identical to a zoomed-out preview.
- **Grid lines are `ImageDraw.rectangle`, not `line`.** Rectangles give exact
  pixel thickness; `line` width rounding is unreliable.
- **Only interior lines are drawn** (`grid_positions` starts at `spacing`, not
  0) — the image border is already an edge.
- **Spacing choices come from `gcd(width, height)`** so the grid divides the
  image evenly, plus round fallbacks (25/50/100/…). The combobox is editable,
  so any integer is still allowed; `RasterApp.spacing` parses and clamps it.
- **Zoom is anchored at the cursor**; the view is stored as an image-space
  offset plus a zoom factor, and only the visible crop is resized per frame, so
  large photos stay responsive. Redraws are debounced through `request_redraw`.

## Testing

There is no test suite. Verify changes headlessly by importing the pure
functions, and smoke-test the window by constructing `RasterApp`, calling
`app.after(...)` to drive zoom/pan, then `app.destroy()`.

## Conventions

- Python 3.13, `from __future__ import annotations`, type hints on function
  signatures.
- Standard library + Pillow only. Do not add dependencies without asking.
- Note that `.gitignore` excludes `*.png` and `*.jpg`, so sample images are not
  committed.
