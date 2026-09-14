# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A small desktop tool for preparing drawings, with two modes in one window:

- **Grid mode** — load a photo, overlay a regular grid ("raster") of coloured
  lines, save a copy with the grid baked in. Replaces doing the same job by
  hand in GIMP before drawing a subject.
- **Compose mode** — plan a new picture: pick the final frame size, place a
  photo in it, block areas out with hollow rectangles and circles, and move /
  scale everything until the composition works.

Single user, single developer. Keep it simple — no packaging, no plugin system,
no config files.

## Layout

- [raster_lines.py](raster_lines.py) — the whole program (~1200 lines).
  - Module-level pure functions hold all the maths and are testable without a
    display: `spacing_options`, `default_spacing`, `grid_positions`,
    `draw_grid` for the grid; `parse_frame_size`, `fit_scale`, `Item` with its
    `Placement` / `Shape` subclasses, `draw_shape` and `render_composition` for
    the composition.
  - `CanvasView(ttk.Frame)` is the shared sidebar + canvas: zoom, pan, the
    throttled redraw, and the coordinate helpers. Subclasses supply
    `content_size()` (the world they live in) and `render()` — `draw()` itself
    belongs to the base, which uses it to honour a pending fit first.
  - `GridMode` and `ComposeMode` subclass it, one per mode.
  - `RasterApp(tk.Tk)` is the shell: the mode switch across the top, both mode
    frames built up front and `pack`/`pack_forget`-ed as the mode changes, and
    the shared "open a photo" action that hands the image to both.
- [requirements.txt](requirements.txt) — Pillow only; tkinter ships with Python.
- `.venv/` — local virtual environment (git-ignored).
- `examples/screenshot.png` — the README screenshot. `.gitignore` excludes
  `*.png` but re-includes `examples/*.png`; regenerate it by driving
  `RasterApp` and grabbing `winfo_rootx/rooty/width/height` with
  `PIL.ImageGrab`.

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
- **Spacing choices are the divisors of `gcd(width, height)`**, so every
  suggestion tiles the image with no partial cells. Round fallbacks
  (`ROUND_SPACINGS`) are used *only* when the dimensions are coprime and the
  exact set would be empty. The combobox stays editable, so any integer is
  allowed; the status line then warns about partial edge cells.
- **Per-cell refinement** (`subdivisions`: `(col, row) -> factor`) splits single
  cells further for hands and faces. Line positions are *rounded* fractions of
  the spacing, so a spacing not divisible by the factor still works, and lines
  falling outside a partial edge cell are dropped. Because cell indices only
  mean something for one spacing, `redraw` clears the dict when the spacing
  changes. Picking a cell reuses button 1: `on_release` treats a release within
  3 px of the press as a click and anything further as a pan, so dragging is
  unaffected.
- **Compose mode keeps one list of `Item`s**: `Placement` (a photo) and `Shape`
  (a hollow rectangle or ellipse) side by side, ordered back to front. Position
  and size live on the item in frame pixels. `Item.resize` does the anchored
  grow/shrink for both; a subclass only says how far it may go (`_limit`) and
  how to apply it (`_apply`), so the move and the resize stay in step at the
  stops. Loading a photo replaces the `Placement`s and keeps the shapes.
- **A shape is grabbed by its outline, never through its middle** (`Shape.
  contains`), so a shape laid over the photo does not make the photo
  unclickable. Hit tests take a tolerance, which the view passes as
  `grab_px / zoom` — a few screen pixels' worth of frame units, so a thin
  outline stays catchable when zoomed out.
- **Shapes are drawn as canvas items, photos as a bitmap.** Same reason as the
  grid: a 4 px outline baked into a 20% preview disappears, and canvas widths
  clamp to 1 px. That also keeps shapes out of the preview bitmap's cache key,
  so moving one does not re-render the photo. The stroke runs *inwards* from
  the item's box in both paths — `ImageDraw`'s `width` does that natively, and
  `_draw_shape` insets the canvas coordinates by half a stroke to match.
- **Ctrl+wheel is overloaded**: outline thickness over an active shape, view
  zoom otherwise. Thickness steps proportionally (`step_thickness`), because
  1 px at a time is useless on a 4000 px frame.
- **The spill outside the frame is faded in the preview only.** The visible
  part of each photo is resized once per frame, pasted into a full-canvas
  layer, and split by a frame mask: inside goes down untouched, outside goes
  down desaturated and washed most of the way to a mid grey (`MUTE_RGB`).
  Blending towards the dark backdrop instead buries dark photos entirely.
  Saving uses `render_composition()`, which simply crops at the frame edge.
- **Button 1 in compose mode means "grab what is under it"**: a press on a
  photo selects and moves it, a press on the backdrop pans the view, and a
  release within 3 px of the press counts as a click — on the backdrop, or on
  the already-active photo, that clears the selection. Dragging the active
  photo has to keep moving it, hence the `_toggle_off` flag set at press time
  and acted on only at release. The wheel scales the active photo (anchored at
  the cursor) and falls back to view zoom with Ctrl, or when nothing is active.
- **`fit_to_window` centres the view explicitly.** Grid mode's clamp pins the
  photo to the canvas, but compose mode deliberately allows panning far outside
  its frame (`clamp_margin`), so a zoom-only fit would leave the frame
  off-centre. It works on `fit_bounds()`, which compose widens to the frame
  *plus* any photo hanging over its edges; the pan clamp uses the same box.
- **Fitting on load goes through `request_fit`, never a direct call.** The mode
  that is not on screen has an unmapped 1x1 canvas, so fitting immediately
  produces a meaningless zoom that survives until the user presses Fit. The
  request is honoured in `draw` once the canvas has a size, and repeated until
  two draws agree on it, because the first sized draw can still arrive
  mid-layout. `set_zoom` and panning cancel a pending fit.
- **Dialogs start in `script_dir()`**, not the desktop or the last folder used:
  the photos live next to the script.
- **Zoom is anchored at the cursor**; the view is stored as an image-space
  offset plus a zoom factor, and only the visible crop is resized per frame, so
  large photos stay responsive. `request_redraw` **throttles** (leaves a
  pending job to fire) rather than debouncing — cancelling on every event
  starves the redraw during a continuous drag, so panning would only update
  on mouse release. Downscaling uses BILINEAR while `_drag` is set and
  LANCZOS once released; the resample filter is part of the cache key.

## Testing

There is no test suite. Verify changes headlessly by importing the pure
functions, and smoke-test the window by constructing `RasterApp`, calling
`app.after(...)` to drive zoom/pan, then `app.close()`.

The window has to be real for the canvas to report a usable size, but
`app.wm_attributes("-alpha", 0.0)` keeps it off the user's screen — do that,
and always tear the window down in a `finally`, or a failed assertion leaves a
stray window sitting on their desktop. Mouse handlers only read `x`, `y`,
`state` and `delta`, so a tiny stand-in object drives them fine. Compose-mode
rendering can be checked without eyes by calling `_render_preview` and reading
pixels back.

## Conventions

- Python 3.13, `from __future__ import annotations`, type hints on function
  signatures.
- Standard library + Pillow only. Do not add dependencies without asking.
- Note that `.gitignore` excludes `*.png` and `*.jpg`, so sample images are not
  committed.
