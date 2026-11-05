r"""Builds the Windows release: ArtHelper.exe, which needs nothing installed.

Usage:
    py build_tools\Release\build_release.py 0.1.0
    py build_tools\Release\build_release.py 0.1.0 --no-smoke-test

Writes release\ArtHelper-<version>-windows.zip. It holds one folder,
ArtHelper/, with ArtHelper.exe, a short README.txt and _internal/: a
PyInstaller build (one folder, no console) with its own Python, Tcl/Tk,
Pillow, numpy, the arthelper package and its fonts. Unzip it, double-click
the exe.

Only the files git tracks in arthelper/assets go in, so a build here and on
GitHub's runner are the same. The exe's icon is the app's own, drawn by
arthelper.logo.render_icon at build time.

The build runs in its own venv, build_tools/Release/.venv, made on first use
from requirements.txt here (the app's packages plus PyInstaller), so nothing
else from the dev venv is bundled. Before zipping, the exe is started with
ART_HELPER_SMOKE_TEST (see arthelper/smoke.py): it opens the window on a
made-up photo, goes through every mode, cleans the scan and quits, which
catches a module, a font or a Tcl file that did not make it in.

.github/workflows/release.yml runs this on GitHub when a tag like v0.1.0 is
pushed and publishes the zip as a release.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import venv
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VENV = HERE / ".venv"
VENV_PYTHON = VENV / "Scripts" / "python.exe"
NAME = "ArtHelper"
ASSETS = "arthelper/assets"  # repo-relative, and where the package looks for them

SMOKE_TEST_SECONDS = 4
SMOKE_TEST_TIMEOUT_S = 120.0

README = """\
Art Helper {version}

Double-click ArtHelper.exe to start. Nothing needs to be installed.

Windows may say "Windows protected your PC" the first time, because the
program is not signed: click "More info", then "Run anyway".

Keep ArtHelper.exe and the _internal folder together; the program needs
both. The file dialogs start in this folder, so it is a handy place for
your photos. To update, delete this folder and unzip the newer release.

If something goes wrong, a crash.log appears next to the exe.
Please send it along.
"""


def run(command: list[str], **kwargs) -> None:
    """Runs a command, stopping the build if it fails."""
    print("$", " ".join(command), flush=True)
    subprocess.run(command, check=True, **kwargs)


def ensure_build_venv() -> None:
    """Re-runs this script in the build venv, making it first if needed."""
    if Path(sys.prefix).resolve() == VENV.resolve():
        return
    if not VENV_PYTHON.is_file():
        print(f"Making the build venv in {VENV} ...", flush=True)
        venv.create(VENV, with_pip=True)
    run([str(VENV_PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "--quiet",
         "-r", str(HERE / "requirements.txt")])
    sys.exit(subprocess.run([str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]]).returncode)


def stage_assets(target: Path) -> int:
    """Copies the tracked files of arthelper/assets into ``target``.

    Returns:
        How many files were copied.
    """
    listed = subprocess.run(["git", "ls-files", "-z", ASSETS], cwd=ROOT, check=True,
                            capture_output=True).stdout.decode("utf-8")
    copied = 0
    for path in filter(None, listed.split("\0")):
        source = ROOT / path
        if not source.is_file():  # tracked but deleted in the working tree
            continue
        destination = target / Path(path).relative_to(ASSETS)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    if not copied:
        sys.exit(f"No tracked files in {ASSETS}: the splash would have no fonts.")
    return copied


def write_icon(target: Path) -> Path:
    """Draws the app icon as a multi-size .ico for the exe."""
    sys.path.insert(0, str(ROOT))
    from arthelper.logo import render_icon

    sizes = (256, 128, 64, 48, 32, 24, 16)
    render_icon(256).save(target, format="ICO", sizes=[(s, s) for s in sizes])
    return target


def build_exe(assets: Path, icon: Path, work: Path) -> Path:
    """Builds ArtHelper.exe with PyInstaller: one folder, no console.

    Returns:
        The folder holding ArtHelper.exe and _internal/.
    """
    run([sys.executable, "-m", "PyInstaller",
         "--noconfirm", "--clean", "--log-level", "WARN",
         "--onedir", "--windowed",
         "--name", NAME,
         "--icon", str(icon),
         "--distpath", str(work / "dist"),
         "--workpath", str(work / "build"),
         "--specpath", str(work),
         "--paths", str(ROOT),
         "--collect-submodules", "arthelper",
         "--add-data", f"{assets}{os.pathsep}{ASSETS}",
         str(ROOT / "art_helper.py")])
    return work / "dist" / NAME


def smoke_test(folder: Path) -> None:
    """Starts the exe, lets it go through every mode and checks it quit cleanly."""
    exe = folder / f"{NAME}.exe"
    env = {**os.environ, "ART_HELPER_SMOKE_TEST": str(SMOKE_TEST_SECONDS)}
    started = time.monotonic()
    try:
        code = subprocess.run([str(exe)], env=env, timeout=SMOKE_TEST_TIMEOUT_S).returncode
    except subprocess.TimeoutExpired:
        sys.exit(f"Smoke test failed: {exe.name} did not quit within {SMOKE_TEST_TIMEOUT_S:.0f} s.")
    crash_log = folder / "crash.log"
    if code != 0 or crash_log.is_file():
        details = crash_log.read_text(encoding="utf-8") if crash_log.is_file() else "(no crash.log)"
        sys.exit(f"Smoke test failed: {exe.name} exited with {code}.\n{details}")
    print(f"{exe.name} opened every mode, cleaned a scan and quit ({time.monotonic() - started:.0f} s).")


def write_zip(target: Path, entries: list[tuple[Path, str]], readme: str) -> None:
    """Writes the release zip in a fixed order."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(f"{NAME}/README.txt", readme.replace("\n", "\r\n"))
        for source, arcname in sorted(entries, key=lambda e: e[1]):
            archive.write(source, arcname)


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", help="the release's version, e.g. 0.1.0")
    parser.add_argument("--out", type=Path, default=ROOT / "release", help="output folder")
    parser.add_argument("--no-smoke-test", action="store_true",
                        help="zip without starting the exe first")
    parser.add_argument("--work", type=Path,
                        help="build in this (empty) folder and keep it, to look into the build")
    args = parser.parse_args()
    if sys.platform != "win32":
        sys.exit("ArtHelper.exe can only be built on Windows.")
    ensure_build_venv()

    with tempfile.TemporaryDirectory(prefix="art-helper-") as tmp:
        work = args.work.resolve() if args.work else Path(tmp)
        work.mkdir(parents=True, exist_ok=True)
        print(f"Staging the assets ... {stage_assets(work / 'assets')} files.", flush=True)
        icon = write_icon(work / f"{NAME}.ico")
        folder = build_exe(work / "assets", icon, work)
        # Listed before the smoke test, so a crash.log it might write stays out
        entries = [(path, f"{NAME}/{path.relative_to(folder).as_posix()}")
                   for path in sorted(folder.rglob("*")) if path.is_file()]
        if not args.no_smoke_test:
            smoke_test(folder)
        target = args.out / f"{NAME}-{args.version}-windows.zip"
        print(f"Writing {target} ...", flush=True)
        write_zip(target, entries, README.format(version=args.version))
    print(f"{target} ({target.stat().st_size // (1024 * 1024)} MB, {len(entries) + 1} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
