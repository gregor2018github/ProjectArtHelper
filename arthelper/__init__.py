"""Art Helper - two tools for preparing a drawing.

* `grid` / `grid_mode` - overlay a reference raster on a photo.
* `compose` / `compose_mode` - plan a new picture inside a fixed frame.

The `grid` and `compose` modules are pure: no tkinter, no display, so the
maths can be exercised headlessly. Everything that draws lives in the `_mode`
modules on top of the shared `view.CanvasView`.
"""
