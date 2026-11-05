"""The Art Helper logo and its intro animation, drawn with Pillow + numpy.

No tkinter here, so the logo can be rendered and checked headlessly. The
splash window (`splash.py`) only asks `LogoAnimation.frame(t)` for pictures.

The logo: a red ring (the WobblyWerk circle), "Art" written in a cursive
script inside it, and "helper" in a pixel terminal font cutting through the
ring's lower right, followed by a red block cursor.

The animation, in seconds:
    RING  the ring draws itself clockwise from the top, like a pen stroke
    ART   "Art" is revealed left to right along a slanted edge (handwriting)
    TYPE  "helper" is typed letter by letter; the cursor clears the ring
          in front of it as it goes
    BUTTONS  the three mode buttons (grid / compose / scan) fade in below
    then  the cursor blinks until DURATION

The buttons are part of the picture: `button_at()` hit-tests them and
`frame(t, hover)` draws the hovered one highlighted, so the splash window
needs no widgets of its own.

Every layer is rendered once, supersampled, as an alpha mask; a frame is just
a few numpy blends, so playback costs a few ms per frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent / "assets"
SCRIPT_FONT = ASSETS / "PinyonScript-Regular.ttf"
MONO_FONT = ASSETS / "VT323-Regular.ttf"

PAPER = (247, 245, 240)
INK = (24, 24, 24)
RED = (205, 38, 38)
GREY = (150, 146, 140)

SIZE = (640, 400)  # design size of the splash, in logical pixels
SUPERSAMPLE = 3

# Timeline (seconds).
RING = (0.10, 0.95)
ART = (0.60, 1.55)
TYPE = (1.60, 2.25)
BUTTONS = (2.20, 2.60)
DURATION = 3.10
BLINK_PERIOD = 0.40


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=16)
def _font(path: Path, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a bundled font, falling back to Pillow's default if it is missing."""
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        try:
            return ImageFont.load_default(size)  # Pillow >= 10.1
        except TypeError:
            return ImageFont.load_default()


def _progress(t: float, span: tuple[float, float]) -> float:
    """Linear 0..1 progress of `t` through `span`."""
    start, end = span
    return float(np.clip((t - start) / (end - start), 0.0, 1.0))


def _ease(p: float) -> float:
    """Ease-in-out (smoothstep), so strokes start and land gently."""
    return p * p * (3 - 2 * p)


Box = tuple[int, int, int, int]  # x0, y0, x1, y1 (exclusive)


def _bbox(alpha: np.ndarray) -> Box:
    """Bounding box of the non-zero part of a mask."""
    rows = np.nonzero(alpha.max(axis=1) > 0)[0]
    cols = np.nonzero(alpha.max(axis=0) > 0)[0]
    if len(rows) == 0:
        return 0, 0, 0, 0
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def _rect_box(x0: float, y0: float, x1: float, y1: float, w: int, h: int) -> Box:
    """Integer box covering a float rectangle, clipped to the canvas."""
    return (max(0, int(x0)), max(0, int(y0)),
            min(w, int(np.ceil(x1))), min(h, int(np.ceil(y1))))


def _mask(size: tuple[int, int], s: int, draw_fn) -> np.ndarray:
    """Draw at `s`x into an 'L' image, downsample, return float alpha 0..1."""
    big = Image.new("L", (size[0] * s, size[1] * s), 0)
    draw_fn(ImageDraw.Draw(big), s)
    small = big.resize(size, Image.Resampling.LANCZOS)
    return np.asarray(small, dtype=np.float32) / 255.0


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Layout:
    """Positions of every element, in logical pixels at scale 1."""

    cx: float = 243
    cy: float = 182
    r: float = 126
    ring_width: float = 10
    art_size: int = 186
    art_pos: tuple[float, float] = (233, 222)  # baseline-middle of "Art"
    mono_size: int = 94
    helper_pos: tuple[float, float] = (265, 300)  # baseline-left of "helper"
    cut_pad: float = 9  # paper kept clear around "helper" where it crosses
    buttons: tuple[str, ...] = ("grid", "compose", "scan")
    button_size: tuple[float, float] = (150, 42)
    button_gap: float = 18
    button_top: float = 338
    button_radius: float = 10
    button_outline: float = 2
    button_text_size: int = 32


class LogoAnimation:
    """Pre-rendered logo layers; `frame(t)` composes the picture at time t."""

    def __init__(self, scale: float = 1.0, layout: Layout | None = None) -> None:
        """Render all layers.

        Args:
            scale: Output size relative to the 640x400 design (for HiDPI).
            layout: Element positions; the default is the shipped logo.
        """
        self.scale = scale
        self.lay = layout or Layout()
        self.size = (round(SIZE[0] * scale), round(SIZE[1] * scale))
        w, h = self.size
        lay, k, ss = self.lay, scale, SUPERSAMPLE

        # Ring + the clockwise-from-top angle of every pixel, for the sweep.
        def ring(d: ImageDraw.ImageDraw, s: int) -> None:
            c, r, rw = (lay.cx * k * s, lay.cy * k * s), lay.r * k * s, lay.ring_width * k * s
            d.ellipse((c[0] - r, c[1] - r, c[0] + r, c[1] + r), outline=255, width=round(rw))

        self.ring = _mask(self.size, ss, ring)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        self.ring_angle = (
            (np.arctan2(xx - lay.cx * k, -(yy - lay.cy * k)) / (2 * np.pi)) % 1.0
        )

        # "Art" + a slanted coordinate for the writing wipe.
        script = _font(SCRIPT_FONT, round(lay.art_size * k * ss))

        def art(d: ImageDraw.ImageDraw, s: int) -> None:
            d.text((lay.art_pos[0] * k * s, lay.art_pos[1] * k * s), "Art",
                   font=script, fill=255, anchor="ms")

        self.art = _mask(self.size, ss, art)
        cols = np.nonzero(self.art.max(axis=0) > 0.02)[0]
        rows = np.nonzero(self.art.max(axis=1) > 0.02)[0]
        slant = 0.35  # matches the script's lean: the wipe edge leans too
        u = xx + slant * (yy - rows.mean())
        self.art_u = (u - (cols[0] - slant * (rows[-1] - rows.mean()))) / (
            (cols[-1] - cols[0]) + slant * (rows[-1] - rows[0])
        )

        # "helper", one letter boundary per typed step.
        mono = _font(MONO_FONT, round(lay.mono_size * k * ss))
        hx, hy = lay.helper_pos[0] * k, lay.helper_pos[1] * k
        probe = ImageDraw.Draw(Image.new("L", (1, 1)))
        word = "helper"
        self.letter_edges = [
            hx + probe.textlength(word[:i], font=mono) / ss for i in range(len(word) + 1)
        ]

        def helper(d: ImageDraw.ImageDraw, s: int) -> None:
            d.text((hx * s, hy * s), word, font=mono, fill=255, anchor="ls")

        self.helper = _mask(self.size, ss, helper)
        top, bottom = probe.textbbox((0, 0), "h", font=mono, anchor="ls")[1::2]
        self.text_top = hy + top / ss
        self.text_bottom = hy + bottom / ss
        self.cursor_w = 0.36 * lay.mono_size * k
        self.cursor_gap = 0.10 * lay.mono_size * k

        # The mode buttons, a centred row under everything. Each gets an
        # outline, a fill and a label mask, so hover is only a choice of
        # colours at frame time.
        small = _font(MONO_FONT, round(lay.button_text_size * k * ss))
        bw, bh = lay.button_size
        n = len(lay.buttons)
        left = (SIZE[0] - (n * bw + (n - 1) * lay.button_gap)) / 2
        self.button_boxes: list[tuple[float, float, float, float]] = []
        self.button_masks: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        for i, label in enumerate(lay.buttons):
            x0 = left + i * (bw + lay.button_gap)
            box = (x0 * k, lay.button_top * k, (x0 + bw) * k, (lay.button_top + bh) * k)
            self.button_boxes.append(box)

            def shape(d: ImageDraw.ImageDraw, s: int, box=box, **kw) -> None:
                d.rounded_rectangle([v * s for v in box], radius=lay.button_radius * k * s, **kw)

            def text(d: ImageDraw.ImageDraw, s: int, box=box, label=label) -> None:
                # VT323 sits high on its baseline; nudge the middle down a touch.
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2 + 0.02 * bh * k
                d.text((cx * s, cy * s), label, font=small, fill=255, anchor="mm")

            self.button_masks.append((
                _mask(self.size, ss, lambda d, s, f=shape: f(
                    d, s, outline=255, width=max(1, round(lay.button_outline * k * s)))),
                _mask(self.size, ss, lambda d, s, f=shape: f(d, s, fill=255)),
                _mask(self.size, ss, text),
            ))
        self._xx = xx

        # Each layer only touches its own bounding box per frame (keeps a
        # frame at a few ms instead of ~35 ms of full-canvas blending).
        self.ring_box = _bbox(self.ring)
        self.art_box = _bbox(self.art)
        self.helper_box = _bbox(self.helper)
        self.button_crop = [
            _rect_box(x0 - 1, y0 - 1, x1 + 1, y1 + 1, w, h)
            for x0, y0, x1, y1 in self.button_boxes
        ]

    def button_at(self, x: float, y: float) -> int | None:
        """Index of the button under (x, y) in output pixels, or None."""
        for i, (x0, y0, x1, y1) in enumerate(self.button_boxes):
            if x0 <= x < x1 and y0 <= y < y1:
                return i
        return None

    # ------------------------------------------------------------------ frame
    def _cursor_box(self, typed: int) -> tuple[float, float, float, float]:
        x0 = self.letter_edges[typed] + (self.cursor_gap if typed else 0.0)
        return x0, self.text_top + 0.08 * self.lay.mono_size * self.scale, x0 + self.cursor_w, self.text_bottom

    def buttons_shown(self, t: float) -> bool:
        """Whether the buttons have started fading in (and can be clicked)."""
        return t >= BUTTONS[0]

    def frame(self, t: float, hover: int | None = None) -> Image.Image:
        """The logo at time `t` seconds (t >= DURATION gives the final logo).

        Args:
            t: Seconds since the start of the animation.
            hover: Index of the button to draw highlighted, if any.
        """
        w, h = self.size
        out = np.empty((h, w, 3), np.float32)
        out[:] = PAPER

        def paint(alpha: np.ndarray, color: tuple[int, int, int], box: Box) -> None:
            """Blend `color` in with `alpha` (a crop matching `box`)."""
            x0, y0, x1, y1 = box
            if x1 <= x0 or y1 <= y0:
                return
            a = alpha[..., None]
            region = out[y0:y1, x0:x1]
            region[:] = region * (1 - a) + np.asarray(color, np.float32) * a

        def crop(arr: np.ndarray, box: Box) -> np.ndarray:
            x0, y0, x1, y1 = box
            return arr[y0:y1, x0:x1]

        # Ring: swept clockwise from the top, soft leading edge.
        rb = self.ring_box
        sweep = _ease(_progress(t, RING)) * 1.02
        ring = crop(self.ring, rb) * np.clip((sweep - crop(self.ring_angle, rb)) * 60, 0, 1)

        # Typing state; the cursor clears the ring in front of the text.
        p_type = _progress(t, TYPE)
        typing = t >= TYPE[0]
        typed = min(len(self.letter_edges) - 1, int(p_type * len(self.letter_edges)))
        if typing:
            pad = self.lay.cut_pad * self.scale
            cx0, cy0, cx1, cy1 = _rect_box(
                self.letter_edges[0] - pad, self.text_top - pad,
                self._cursor_box(typed)[2] + pad, self.text_bottom + pad, w, h,
            )
            # Same rectangle, in the ring crop's coordinates.
            ring = ring.copy()
            ring[max(0, cy0 - rb[1]): max(0, cy1 - rb[1]),
                 max(0, cx0 - rb[0]): max(0, cx1 - rb[0])] = 0
        paint(ring, RED, rb)

        # "Art": written along a slanted wipe with a soft nib.
        p_art = _ease(_progress(t, ART))
        if p_art > 0:
            ab = self.art_box
            nib = np.clip((p_art * 1.08 - crop(self.art_u, ab)) * 25, 0, 1)
            paint(crop(self.art, ab) * nib, INK, ab)

        # "helper": the letters typed so far.
        if typing and typed:
            hb = self.helper_box
            hb = (hb[0], hb[1], min(hb[2], int(np.ceil(self.letter_edges[typed]))), hb[3])
            paint(crop(self.helper, hb), INK, hb)

        # Cursor: solid while typing, then blinking; always on in the final logo.
        if typing:
            blinking = TYPE[1] < t < DURATION
            if not blinking or ((t - TYPE[1]) % BLINK_PERIOD) < BLINK_PERIOD / 2:
                cb = _rect_box(*self._cursor_box(typed), w, h)
                paint(np.ones((cb[3] - cb[1], cb[2] - cb[0]), np.float32), RED, cb)

        # Buttons fade in; the hovered one is filled red with paper text.
        p_btn = _progress(t, BUTTONS)
        if p_btn > 0:
            for i, (outline, fill, label) in enumerate(self.button_masks):
                bb = self.button_crop[i]
                if i == hover:
                    paint(crop(fill, bb) * p_btn, RED, bb)
                    paint(crop(label, bb) * p_btn, PAPER, bb)
                else:
                    paint(crop(outline, bb) * p_btn, GREY, bb)
                    paint(crop(label, bb) * p_btn, INK, bb)

        return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def render_logo(scale: float = 1.0) -> Image.Image:
    """The finished logo (last frame of the animation)."""
    return LogoAnimation(scale).frame(DURATION)


def render_icon(size: int = 64) -> Image.Image:
    """Square app icon: the red ring with a cursive "A", on transparency.

    Args:
        size: Edge length in pixels.

    Returns:
        RGBA image.
    """
    s = 4
    big = size * s
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad, rw = 0.06 * big, 0.085 * big
    d.ellipse((pad, pad, big - pad, big - pad), fill=PAPER + (255,),
              outline=RED + (255,), width=round(rw))
    d.text((big * 0.47, big * 0.72), "A", font=_font(SCRIPT_FONT, round(big * 0.74)),
           fill=INK + (255,), anchor="ms")
    return img.resize((size, size), Image.Resampling.LANCZOS)
