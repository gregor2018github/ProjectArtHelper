"""Raster Lines - launcher.

The program itself lives in the `rasterlines` package; this keeps
`python raster_lines.py` (and run.bat) working as the way to start it.
"""

from __future__ import annotations

import sys

from rasterlines.app import main

if __name__ == "__main__":
    sys.exit(main())
