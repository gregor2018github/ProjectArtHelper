"""Art Helper - launcher.

The program itself lives in the `arthelper` package; this keeps
`python art_helper.py` (and run.bat) working as the way to start it.
"""

from __future__ import annotations

import sys

from arthelper.app import main

if __name__ == "__main__":
    sys.exit(main())
