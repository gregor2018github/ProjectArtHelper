"""Release check: start the window, go through every mode, quit.

`build_tools/Release/build_release.py` starts ArtHelper.exe with
``ART_HELPER_SMOKE_TEST=<seconds>`` set. `app.main` then skips the splash and
the photo dialog (both wait for a person) and calls `run` instead, which opens
the real window on a made-up photo of a sheet of paper, shows each mode,
cleans the scan and closes after *seconds*. Any exception, including one in a
Tk callback, ends in crash.log next to the exe and exit code 1, so a module, a
font or a Tcl file that did not make it into the build fails the release
instead of the first user.
"""

from __future__ import annotations

import traceback
from pathlib import Path

from PIL import Image, ImageDraw

ENV = "ART_HELPER_SMOKE_TEST"


def sample_photo() -> Image.Image:
    """A sheet of paper with a few strokes on it, lying askew on a dark desk."""
    image = Image.new("RGB", (1600, 1200), (92, 64, 40))
    draw = ImageDraw.Draw(image)
    draw.polygon([(260, 180), (1330, 230), (1290, 1010), (230, 960)], fill=(236, 232, 224))
    for i in range(8):
        draw.line([(400 + 80 * i, 350), (500 + 60 * i, 850)], fill=(30, 30, 30), width=6)
    return image


def run(seconds: float) -> int:
    """Drive the window for *seconds*; raise if anything went wrong."""
    from .app import ArtHelperApp
    from .common import script_dir
    from .logo import DURATION, MONO_FONT, SCRIPT_FONT, LogoAnimation

    errors: list[str] = []
    # The splash falls back to Pillow's font without a word, so look for them
    errors += [f"Font missing: {font}" for font in (SCRIPT_FONT, MONO_FONT) if not font.is_file()]
    LogoAnimation().frame(DURATION)  # the splash: loads the bundled fonts

    app = ArtHelperApp(Path(script_dir()) / "smoke-test.png", sample_photo(), "grid")
    app.wm_attributes("-alpha", 0.0)  # keep it off the screen
    app.report_callback_exception = (  # type: ignore[method-assign]
        lambda *exc: errors.append("".join(traceback.format_exception(*exc)))
    )

    def show(mode: str) -> None:
        app.var_mode.set(mode)
        app.show_mode()

    def scan_result() -> None:
        app.scan_mode.var_view.set("result")
        app.scan_mode._on_view_change()  # noqa: SLF001
        if app.scan_mode.result() is None:
            errors.append("Scan mode produced no result for the sample photo.")

    steps = [(0.2, lambda: show("compose")), (0.4, lambda: show("scan")), (0.6, scan_result)]
    for at, step in steps:
        app.after(int(min(at, 0.9) * seconds * 1000), step)
    app.after(int(seconds * 1000), app.close)
    app.mainloop()

    if errors:
        raise RuntimeError("Smoke test failed:\n\n" + "\n".join(errors))
    return 0
