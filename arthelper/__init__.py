"""Art Helper - three tools for preparing and publishing a drawing.

* `grid` / `grid_mode` - overlay a reference raster on a photo.
* `compose` / `compose_mode` - plan a new picture inside a fixed frame.
* `scan` / `scan_mode` - turn a photo of a finished drawing into a clean,
  straightened image for the website.

The `grid`, `compose` and `scan` modules are pure: no tkinter, no display, so
the maths can be exercised headlessly. Everything that draws lives in the `_mode`
modules on top of the shared `view.CanvasView`.
"""
