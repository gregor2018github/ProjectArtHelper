# Art Helper

A small desktop tool for preparing a drawing. It has three modes, switched
with the buttons in the top left:

- **Grid mode** draws a reference grid onto a photo, so you can sketch
  difficult subjects square by square instead of building the grid by hand in
  an image editor.
- **Compose mode** plans a new picture: you set the final frame size, drop a
  photo into it, block areas out with hollow rectangles and circles, and move
  and scale everything until the composition works.
- **Scan mode** turns a hand-held photo of a finished drawing into a clean
  image for the website: it finds the sheet, squares up the perspective, crops
  away the table and evens out the paper white and the ink black.

![The app showing a 125 px red raster over a drawing](examples/screenshot.png)

*A 125 px raster (8 x 16 cells) over a 1000 x 2000 px drawing, 4 px lines.*

## Grid mode

- Pick any `.png` / `.jpg` / `.jpeg` / `.bmp` / `.tif` / `.webp`; the file
  dialog opens in the folder the script sits in, where the photos live.
- Adjustable line thickness (default 2 px) and colour (default red).
- Grid spacing suggestions computed from the image size. Every suggestion
  divides both edges exactly, so there are no half cells at the border — e.g.
  `250 px (4 x 8)` for a 1000 x 2000 photo. You can still type any spacing you
  like; the status line then tells you the edge cells are partial.
- **Refine cell**: tick the box, pick 2x / 4x / 8x, then click a cell to split
  it further — useful for hands and faces. Clicking the same cell with the same
  factor removes it again, and **Reset refinements** clears all of them.
  Dragging still pans, so only a click without movement picks a cell.
- Live preview with mouse-wheel zoom (anchored at the cursor) and drag to pan.
- Saves a copy in the original format, with the save dialog opening in the
  folder the photo came from.

## Compose mode

- Choose the final frame size from the presets — 2000 x 2000, 4000 x 2000,
  2000 x 4000, 3000 x 2000, 2000 x 3000, 4000 x 3000, 3000 x 4000 — or type
  your own, e.g. `3500 x 2400` (`3500:2400` and `3500x2400` work too). It is
  always **width first, then height**: the field says so, the dropdown marks
  each preset landscape / portrait / square, and a thumbnail underneath shows
  the shape you are about to get, with its ratio (`3 : 2`) and a plain
  `3000 wide x 2000 high`.
- The photo you opened is dropped into the frame, scaled to fit and centred,
  with the view zoomed so the frame and the photo both fill the window.
- **Left-click a photo or a shape to activate it**, and click it again to
  deactivate. While something is active:
  - the mouse wheel resizes it, anchored at the cursor,
  - `+` / `-` resize it around its own centre,
  - dragging moves it, and the arrow keys nudge it a screen pixel at a time
    (ten with Shift),
  - `Delete` removes it — from anywhere in the window, not just over the
    canvas, though not while you are typing in the frame-size box.
- An active **shape shows eight handles**. Drag a side handle to stretch that
  edge alone, a corner handle to move both edges at once — that is how a square
  becomes any rectangle you like. The opposite edge stays put, so the shape
  reshapes rather than drifting, and dragging anywhere else on it still moves
  it. The wheel keeps scaling the whole shape, aspect ratio and all.
- **Right-click** a photo or an outline to select it and get a **Delete** entry
  for it.
- Clicking the backdrop deactivates it too. With nothing active the wheel zooms
  the view instead, as does `Ctrl`+wheel — except over an active shape, where
  `Ctrl`+wheel sets the outline thickness.
- **Colour…** opens the colour wheel for whatever is active — a rectangle, a
  circle, or the frame's background. New shapes take the colour you last chose.
- **Background** selects the frame's own fill, which you can also pick by
  clicking bare frame. It cannot be moved, resized or deleted, but it takes a
  colour and the eraser like anything else.
- **Eraser**: tick it, set a brush size in pixels, and scrub over a shape to
  scratch its outline away — so a circle can be made to pass *behind* the
  subject. With the **background** active it eats holes in the frame's fill
  instead, and those save out transparent. **Reset eraser** puts back what the
  active item lost, or what everything lost when nothing is active.
- **Rectangle** / **Circle** drop a hollow shape in the middle of the frame.
  They are outlines only, so you grab them *by the outline*, not through the
  middle — the photo underneath stays reachable. `Ctrl`+wheel (or the `-` / `+`
  next to **line thickness**) makes the outline thicker or thinner, all the way
  to a **solid** shape, at which point it stops; the wheel alone resizes the
  shape like anything else. A filled shape can be grabbed anywhere, since it no
  longer has a middle to see through.
- **Fit in** / **Fill** / **Centre** place the photo against the frame in one
  click.
- Whatever hangs over the frame edge is drawn as a faint grey ghost, so the
  part that actually makes it into the picture stays obvious.
- **Save frame as…** writes exactly the frame — frame-sized, everything outside
  it cropped away, the background behind the photo and the shapes over it.
  PNG keeps erased background as transparency; JPEG and BMP cannot, so those
  get white there instead.

## Scan mode

- Open a photo of a drawing lying on a table. The sheet is found
  automatically by its lack of colour (paper is nearly grey, wood or cloth is
  not), so a coloured, reasonably plain background works best.
- **Show** switches between the **original photo (with corners)** and the
  **cleaned result**.
- The **original photo** view shows the four detected paper corners.
  If one is off, drag its handle to the right spot; **Detect again** goes back
  to the automatic guess and **Whole photo** puts the corners on the photo's
  own edges. When detection fails outright the corners start at the edges and
  the sidebar says why.
- The **cleaned result** view shows what will be saved: the sheet squared up
  and cropped, with
  - **Even out the lighting**: the paper becomes one even, neutral white,
    however the light fell on it,
  - **Even out the blacks**: ink that glare turned grey in places is brought
    back to the same black everywhere,
  - **Make the darkest ink black**: a final contrast stretch.

  Each step can be switched off.
- The **loupe** follows the pointer and shows the cleaned version of the spot
  underneath. Over the original photo that makes a before / after
  comparison right where you look; over the result it is a magnifier once
  you raise the zoom.
  Set its **Size** (340 px to start with) and **Zoom** (1x to start with:
  the same scale as the view; raise it to magnify)
  under the checkbox, or untick it. It steps aside over a corner handle and
  while you drag.
- **Paper shape** fixes the long : short ratio when you know it: `1.414` for
  A4 / A3, or type `3:2`, `297 x 210` and so on. Left at *From the photo* the
  ratio is measured, which is a little less exact when the photo is taken at
  a steep angle.
- **Trim each edge** cuts a sliver (0.5 % of the width by default) off every
  side so no table or paper-edge shadow survives; **Paper white** sets how
  bright the paper ends up (250 by default, just shy of pure white).
- **Save result as…** writes `<name>_clean.png` next to the photo.
- **Clean a whole folder…** runs every photo in a folder with the current
  settings and automatic corners, writing `<name>_clean.png` files to a folder
  you choose, and lists any photo it could not handle. Open those one at a
  time and place the corners by hand.

## Requirements

- Python 3.10+ with tkinter (included in the standard Windows installer)
- [Pillow](https://python-pillow.org/)
- [numpy](https://numpy.org/) (scan mode's image maths)

## Setup

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Usage

```powershell
.venv\Scripts\python.exe art_helper.py
```

On Windows you can also double-click `run.bat`.

1. Choose a photo in the file dialog (or Cancel and use **Open photo…** in the
   window; all modes share the photo you open).
2. Set thickness, spacing and colour in the left panel — the preview updates as
   you type.
3. Zoom with the mouse wheel or the `-` / `+` / `Fit` / `100%` buttons; drag to
   pan.
4. For critical areas, tick **Refine cell**, choose a factor, and click the
   cells you want subdivided.
5. **Save as…** writes a new file, defaulting to `<name>_raster.<same ext>` next
   to the original.

For compose mode, switch with **Compose mode** in the top left, pick a frame
size, then click the photo and scale it into place. For scan mode, switch
with **Scan mode**, check the corners, look at **Result** and save.

The preview keeps thin lines at least one screen pixel wide so they remain
visible when zoomed out; the saved file always uses the exact thickness you
chose at full resolution.

## Layout

The launcher is `art_helper.py`; the program itself lives in the
`arthelper/` package — `grid.py`, `compose.py` and `scan.py` hold the maths
with no tkinter in sight, `view.py` the shared canvas, and `grid_mode.py` /
`compose_mode.py` / `scan_mode.py` / `app.py` the interface.

## License

MIT
