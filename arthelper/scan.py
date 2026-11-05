"""Pure scan clean-up: turn a hand-held photo of a drawing into a clean image.

No tkinter here, so it can be exercised headlessly. The pipeline is:

1. `detect_corners` finds the four corners of the sheet of paper (paper is
   nearly colourless, the table behind it is not).
2. `straighten` fixes the perspective and crops to the paper.
3. `flatten_lighting` fits a smooth surface to the blank paper and divides it
   out, so the paper ends up an even, neutral white.
4. `flatten_blacks` does the same for the black level (glare turns ink grey
   in places), using the darkest ink as reference.
5. `set_black_point` stretches the darkest ink to true black.

`clean_scan` runs 2-5 for one photo and `clean_folder` the whole lot for a
folder of them. This began life as the stand-alone ``wobbly_fix.py``, written
against OpenCV; the image operations it needed are reimplemented here with
Pillow + numpy so the app has one fewer heavy dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from .common import load_image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
MAX_PAPER_SATURATION = 45  # HSV saturation (0-255); paper ~5-20, wood ~90+
DETECT_SIZE = 1200  # corners are searched for on a copy at most this big

Corners = tuple[tuple[float, float], ...]  # TL, TR, BR, BL in image pixels


class ScanError(RuntimeError):
    """A step could not make sense of the photo; the message says why."""


@dataclass(frozen=True)
class ScanSettings:
    """Everything `clean_scan` needs besides the photo and its corners.

    Attributes:
        inset: Fraction of the paper width trimmed off every edge, so no
            background or paper-edge shadow survives.
        white: Target brightness for the paper (0-255).
        ratio: Known long/short side ratio of the paper (1.414 for A sizes),
            or None to measure it from the photo.
        lighting / blacks / black_point: Switch the individual tone steps.
    """

    inset: float = 0.005
    white: int = 250
    ratio: float | None = None
    lighting: bool = True
    blacks: bool = True
    black_point: bool = True


# --------------------------------------------------------------------------- #
# Building blocks: square min / max filters
# --------------------------------------------------------------------------- #
def _filter_axis(a: np.ndarray, size: int, axis: int, op: np.ufunc) -> np.ndarray:
    """Running min or max over `size` samples along one axis, centred.

    Van Herk / Gil-Werman: split into blocks of `size`, take running results
    forwards and backwards inside each block, and every window is then the
    combination of one suffix and one prefix - O(n) whatever the size, which
    matters for the 61 px windows on a full-size photo. Samples beyond the
    edge are ignored, as in OpenCV's erode / dilate.
    """
    if size <= 1:
        return a
    a = np.moveaxis(a, axis, -1)
    n = a.shape[-1]
    r = size // 2
    info = np.iinfo(a.dtype) if a.dtype.kind in "ui" else np.finfo(a.dtype)
    fill = info.max if op is np.minimum else info.min
    m = -(-(n + 2 * r) // size) * size
    padded = np.full(a.shape[:-1] + (m,), fill, dtype=a.dtype)
    padded[..., r : r + n] = a
    blocks = padded.reshape(a.shape[:-1] + (m // size, size))
    forward = op.accumulate(blocks, axis=-1).reshape(padded.shape)
    backward = op.accumulate(blocks[..., ::-1], axis=-1)[..., ::-1].reshape(padded.shape)
    out = op(backward[..., :n], forward[..., size - 1 : size - 1 + n])
    return np.moveaxis(out, -1, axis)


def min_filter(a: np.ndarray, size: int) -> np.ndarray:
    """Grey erosion with a `size` x `size` square."""
    return _filter_axis(_filter_axis(a, size, 0, np.minimum), size, 1, np.minimum)


def max_filter(a: np.ndarray, size: int) -> np.ndarray:
    """Grey dilation with a `size` x `size` square."""
    return _filter_axis(_filter_axis(a, size, 0, np.maximum), size, 1, np.maximum)


def _saturation(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB").convert("HSV"))[..., 1]


def _gray(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("L"))  # same 0.299 / 0.587 / 0.114 weights as OpenCV


# --------------------------------------------------------------------------- #
# 1. Paper detection
# --------------------------------------------------------------------------- #
def largest_component(mask: np.ndarray) -> list[tuple[int, int, int]]:
    """The largest 8-connected True region of `mask`, as (row, start, end) runs.

    Labels runs of True per row and merges runs that touch the row above with
    a union-find, which keeps the Python loop to one step per run rather than
    per pixel.
    """
    parent: list[int] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    runs: list[tuple[int, int, int]] = []
    prev: list[int] = []  # run indices on the row above
    for y, row in enumerate(mask):
        edges = np.flatnonzero(np.diff(np.concatenate(([0], row.view(np.int8), [0]))))
        here: list[int] = []
        k = 0
        for s, e in zip(edges[0::2].tolist(), edges[1::2].tolist()):
            index = len(runs)
            runs.append((y, s, e))
            parent.append(index)
            here.append(index)
            # 8-connected: a run touches one above that reaches s-1 .. e.
            while k < len(prev) and runs[prev[k]][2] < s:
                k += 1
            j = k
            while j < len(prev) and runs[prev[j]][1] <= e:
                a, b = find(index), find(prev[j])
                if a != b:
                    parent[a] = b
                j += 1
            if j > k:
                k = j - 1  # the last one may touch the next run as well
        prev = here

    if not runs:
        return []
    sizes: dict[int, int] = {}
    for i, (_y, s, e) in enumerate(runs):
        root = find(i)
        sizes[root] = sizes.get(root, 0) + e - s
    best = max(sizes, key=sizes.__getitem__)
    return [run for i, run in enumerate(runs) if find(i) == best]


def convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Andrew's monotone chain; counter-clockwise in maths axes, no repeats."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _simplify(chain: np.ndarray, eps: float) -> list[int]:
    """Douglas-Peucker on an open chain: indices of the points it keeps."""
    keep = [0, len(chain) - 1]
    stack = [(0, len(chain) - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        a, b = chain[i], chain[j]
        seg = b - a
        length = float(np.hypot(*seg)) or 1.0
        mid = chain[i + 1 : j]
        dist = np.abs(seg[0] * (mid[:, 1] - a[1]) - seg[1] * (mid[:, 0] - a[0])) / length
        k = int(np.argmax(dist))
        if dist[k] > eps:
            keep.append(i + 1 + k)
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return sorted(keep)


def approx_polygon(hull: list[tuple[float, float]], eps: float) -> np.ndarray:
    """Simplify a closed outline, splitting it at its two farthest points."""
    pts = np.asarray(hull, dtype=np.float64)
    i = int(np.argmax(np.hypot(*(pts - pts[0]).T)))
    j = int(np.argmax(np.hypot(*(pts - pts[i]).T)))
    i, j = sorted((i, j))
    first = pts[i : j + 1]
    second = np.concatenate((pts[j:], pts[: i + 1]))
    a = first[_simplify(first, eps)]
    b = second[_simplify(second, eps)]
    return np.concatenate((a[:-1], b[:-1]))


def order_corners(pts: np.ndarray) -> Corners:
    """Order four points as top-left, top-right, bottom-right, bottom-left.

    Sorted by angle around their centre, then rotated so the one nearest the
    top-left comes first - unlike picking extremes of x+y and y-x, this can
    never return the same point twice for a sheet held at 45 degrees.
    """
    pts = np.asarray(pts, dtype=np.float64)
    centre = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - centre[1], pts[:, 0] - centre[0])
    pts = pts[np.argsort(angles)]  # clockwise on screen, since y points down
    start = int(np.argmin(pts.sum(axis=1)))
    pts = np.roll(pts, -start, axis=0)
    return tuple((float(x), float(y)) for x, y in pts)


def detect_corners(image: Image.Image) -> Corners:
    """Locate the four corners of the sheet of paper.

    The paper is found as the largest low-saturation region of a reduced copy.
    Its convex hull ignores dents where ink or colour touches the edge, and is
    simplified to a quadrilateral; the drawing itself does not matter.

    Raises:
        ScanError: If no paper-like quadrilateral is found.
    """
    w, h = image.size
    scale = min(1.0, DETECT_SIZE / max(w, h))
    small = image if scale == 1.0 else image.resize(
        (max(1, round(w * scale)), max(1, round(h * scale))), Image.BILINEAR
    )
    sw, sh = small.size
    mask = (_saturation(small) < MAX_PAPER_SATURATION).astype(np.uint8)
    k = max(3, int(round(9 * scale)) | 1)
    mask = max_filter(min_filter(mask, k), k).astype(bool)  # open: drop specks

    runs = largest_component(mask)
    area = sum(e - s for _y, s, e in runs)
    if not runs:
        raise ScanError("No paper found - is the background as colourless as the paper?")
    if area < 0.2 * sw * sh:
        raise ScanError("The paper region is too small - is the whole sheet in the photo?")

    points = [(float(s), float(y)) for y, s, _e in runs]
    points += [(float(e - 1), float(y)) for y, _s, e in runs]
    hull = convex_hull(points)
    perimeter = float(sum(
        np.hypot(hull[i][0] - hull[i - 1][0], hull[i][1] - hull[i - 1][1])
        for i in range(len(hull))
    ))
    for eps in np.linspace(0.005, 0.05, 30):
        quad = approx_polygon(hull, eps * perimeter)
        if len(quad) == 4:
            full = (quad + 0.5) / scale - 0.5  # pixel centres back to full size
            return order_corners(full)
    raise ScanError("The paper outline is not a clean four-sided shape.")


def whole_image_corners(size: tuple[int, int]) -> Corners:
    """Corners at the photo's own edges, for when detection gives up."""
    w, h = size
    return ((0.0, 0.0), (w - 1.0, 0.0), (w - 1.0, h - 1.0), (0.0, h - 1.0))


# --------------------------------------------------------------------------- #
# 2. Perspective correction
# --------------------------------------------------------------------------- #
def straighten_size(corners: Corners, ratio: float | None) -> tuple[float, float]:
    """The width and height the paper gets once it is a rectangle.

    The width is the average of the top and bottom edges. If the paper ratio
    is known (as long / short side) the height follows from it, respecting
    portrait versus landscape; otherwise it is measured too, which is slightly
    less exact under a strong tilt.
    """
    tl, tr, br, bl = (np.asarray(p) for p in corners)
    width = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    height = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
    if ratio:
        height = width / ratio if width >= height else width * ratio
    return float(width), float(height)


def perspective_coeffs(src: Corners, dst: Corners) -> list[float]:
    """Pillow PERSPECTIVE data mapping each `dst` point back to its `src`."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs += [u, v]
    return np.linalg.solve(np.array(rows, float), np.array(rhs, float)).tolist()


def straighten(
    image: Image.Image, corners: Corners, inset: float, ratio: float | None
) -> Image.Image:
    """Warp the photo so the paper becomes a rectangle, trimmed by `inset`."""
    width, height = straighten_size(corners, ratio)
    out_w, out_h = max(1, int(round(width))), max(1, int(round(height)))
    # Corners are pixel centres (integer coordinates); Pillow puts pixel
    # centres at +0.5 on both sides of the mapping.
    dst = ((0.5, 0.5), (width + 0.5, 0.5), (width + 0.5, height + 0.5), (0.5, height + 0.5))
    src = tuple((x + 0.5, y + 0.5) for x, y in corners)
    warped = image.convert("RGB").transform(
        (out_w, out_h), Image.PERSPECTIVE, perspective_coeffs(src, dst), Image.BICUBIC
    )
    m = _trim(inset, width, out_w, out_h)
    if m == 0:
        return warped
    return warped.crop((m, m, out_w - m, out_h - m))


def _trim(inset: float, width: float, out_w: int, out_h: int) -> int:
    """Pixels `straighten` cuts off each edge; 0 when the trim would eat it all."""
    m = int(round(inset * width))
    return 0 if m <= 0 or 2 * m >= min(out_w, out_h) else m


def photo_to_result(corners: Corners, settings: ScanSettings) -> np.ndarray:
    """3x3 homography taking a photo pixel to the same spot in the result.

    The same mapping `straighten` warps by (corners to the paper rectangle),
    followed by the trim, so the loupe can show the cleaned version of
    whatever is under the pointer in the photo. The tone steps do not move
    anything, so they do not enter into it.
    """
    width, height = straighten_size(corners, settings.ratio)
    rect = ((0.0, 0.0), (width, 0.0), (width, height), (0.0, height))
    a, b, c, d, e, f, g, h = perspective_coeffs(rect, corners)
    m = _trim(settings.inset, width, max(1, int(round(width))), max(1, int(round(height))))
    return np.array([[1, 0, -m], [0, 1, -m], [0, 0, 1]]) @ np.array(
        [[a, b, c], [d, e, f], [g, h, 1.0]]
    )


def map_point(matrix: np.ndarray, x: float, y: float) -> tuple[float, float]:
    """Apply a 3x3 homography to one point."""
    u, v, w = matrix @ (x, y, 1.0)
    return float(u / w), float(v / w)


# --------------------------------------------------------------------------- #
# 3. Tone correction
# --------------------------------------------------------------------------- #
def _poly_exponents(degree: int) -> list[tuple[int, int]]:
    return [(i, j) for i in range(degree + 1) for j in range(degree + 1 - i)]


def _poly_terms(x: np.ndarray, y: np.ndarray, degree: int) -> np.ndarray:
    """Design matrix of 2D polynomial terms up to `degree` (x, y in 0..1)."""
    return np.stack([x**i * y**j for i, j in _poly_exponents(degree)], axis=1)


def _poly_surface(coef: np.ndarray, w: int, h: int, degree: int) -> np.ndarray:
    """Evaluate the fitted polynomial on every pixel, one outer product a term.

    Building the full design matrix would cost six full-size float64 planes;
    the terms are separable, so this needs one float32 plane.
    """
    u = np.arange(w, dtype=np.float32) / w
    v = np.arange(h, dtype=np.float32) / h
    out = np.zeros((h, w), np.float32)
    for c, (i, j) in zip(coef, _poly_exponents(degree)):
        out += np.float32(c) * np.outer(v**j, u**i)
    return out


def flatten_lighting(image: Image.Image, white: int, degree: int = 2) -> Image.Image:
    """Remove the lighting gradient using the blank paper as reference.

    Blank paper pixels (locally brightest, unsaturated, away from ink) get a
    smooth surface fitted on luminance. Dividing by it makes the paper even;
    one global white balance then makes it neutral. Fitting per colour
    channel would tint areas far from any blank paper.

    Raises:
        ScanError: If there is too little blank paper to go on.
    """
    w, h = image.size
    rgb = np.asarray(image.convert("RGB"))
    gray = _gray(image)
    sat = _saturation(image)

    # Paper = locally bright and unsaturated; grow the ink mask so stroke
    # edges and grey washes don't leak into the paper estimate.
    local_bg = max_filter(gray, 41)
    paper = (gray > local_bg.astype(np.int16) - 12) & (sat < 60)
    ink = max_filter((~paper).astype(np.uint8), 25)
    ys, xs = np.nonzero(ink == 0)
    if len(xs) < 1000:
        raise ScanError("Too little blank paper to even out the lighting.")

    step = max(1, len(xs) // 40000)  # a coarse sample is plenty and fast
    xs, ys = xs[::step], ys[::step]
    coef, *_ = np.linalg.lstsq(
        _poly_terms(xs / w, ys / h, degree), gray[ys, xs].astype(np.float64), rcond=None
    )
    surface = np.clip(_poly_surface(coef, w, h, degree), 1, None)

    flat = rgb.astype(np.float32) / surface[..., None]
    gains = white / np.median(flat[ys, xs], axis=0)  # neutral white balance
    return Image.fromarray(np.clip(flat * gains.astype(np.float32), 0, 255).astype(np.uint8))


def flatten_blacks(
    image: Image.Image, white: int, degree: int = 2, window: int = 61, max_black: int = 140
) -> Image.Image:
    """Even out the black level, e.g. ink that looks grey under glare.

    The mirror image of `flatten_lighting`: in every neighbourhood that holds
    ink, the darkest value is taken as "what black looks like here". A smooth
    surface is fitted to the lower envelope of those samples, and each pixel
    is remapped so local black goes to 0 while paper white stays at `white`.
    Local minima brighter than `max_black` are blank paper or light washes,
    and are ignored.
    """
    w, h = image.size
    gray = _gray(image)
    local_min = min_filter(gray, window)

    step = window // 3
    gy, gx = np.mgrid[step // 2 : h : step, step // 2 : w : step]
    vals = local_min[gy, gx].astype(np.float64).ravel()
    keep = vals < max_black
    xs, ys, vals = gx.ravel()[keep] / w, gy.ravel()[keep] / h, vals[keep]
    if len(vals) < 20:
        return image  # hardly any ink - nothing to correct

    # Fit the lower envelope: refit while dropping samples well above the
    # surface (areas with only grey wash, where no true black is nearby).
    design = _poly_terms(xs, ys, degree)
    inliers = np.ones(len(vals), bool)
    for _ in range(4):
        coef, *_ = np.linalg.lstsq(design[inliers], vals[inliers], rcond=None)
        inliers = vals - design @ coef < 10

    black = np.clip(_poly_surface(coef, w, h, degree), 0, white - 80)[..., None]
    rgb = np.asarray(image.convert("RGB")).astype(np.float32)
    out = (rgb - black) * white / (white - black)  # never stretches too hard
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def set_black_point(image: Image.Image, percentile: float = 0.5) -> Image.Image:
    """Stretch so the darkest ink is truly black, keeping paper white."""
    black = float(np.percentile(_gray(image), percentile))
    if black >= 254:
        return image
    rgb = np.asarray(image.convert("RGB")).astype(np.float32)
    out = (rgb - black) * 255.0 / (255.0 - black)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


# --------------------------------------------------------------------------- #
# The whole pipeline
# --------------------------------------------------------------------------- #
def clean_scan(image: Image.Image, corners: Corners, settings: ScanSettings) -> Image.Image:
    """Straighten, crop and tone-correct one photo of a drawing."""
    result = straighten(image, corners, settings.inset, settings.ratio)
    if settings.lighting:
        result = flatten_lighting(result, settings.white)
    if settings.blacks:
        result = flatten_blacks(result, settings.white)
    if settings.black_point:
        result = set_black_point(result)
    return result


def clean_folder(
    in_dir: Path,
    out_dir: Path,
    settings: ScanSettings,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[tuple[str, str | None]]:
    """Clean every photo in `in_dir` into `out_dir` as ``<stem>_clean.png``.

    Corners are detected automatically for each photo. `progress` is told
    (done, total, name) before each one, so a window can stay alive.

    Returns:
        (file name, error message or None) for every photo tried.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in in_dir.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
    report: list[tuple[str, str | None]] = []
    for n, path in enumerate(files):
        if progress is not None:
            progress(n, len(files), path.name)
        try:
            image = load_image(path)
            result = clean_scan(image, detect_corners(image), settings)
            result.save(out_dir / f"{path.stem}_clean.png")
        except Exception as exc:  # noqa: BLE001 - one bad photo must not stop the batch
            report.append((path.name, str(exc) or type(exc).__name__))
        else:
            report.append((path.name, None))
    return report
