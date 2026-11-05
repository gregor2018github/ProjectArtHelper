---
name: make-release
description: Publish a new Windows release of Art Helper (ArtHelper-<version>-windows.zip on GitHub Releases) and remove the previous one, so only the latest release is kept. Use when the user asks for a new release, a new version, a new build to download, or to "ship"/"publish" the app.
---

# Make a release

A release is a GitHub release holding one zip, `ArtHelper-<version>-windows.zip`
(about 32 MB): an `ArtHelper/` folder with `ArtHelper.exe`, `README.txt` and
`_internal/`, needing nothing installed. The zips are **not** in git
(`/release/` is ignored); they live only as release assets.

The user keeps **only the latest release**: old ones are deleted, release and tag,
once the new one is up. Anyone wanting an old version can build it from the source.

## How it is built

Pushing a tag `v<version>` runs `.github/workflows/release.yml` on a Windows runner:
it runs `build_tools/Release/build_release.py <version>` (PyInstaller one-folder,
windowed build in its own venv, then a smoke test: the exe runs
`arthelper/smoke.py` — every mode on a made-up photo, a scan clean-up — and must
exit 0) and publishes the zip with `gh release create`. If the smoke test fails,
no release is created.

Only git-tracked files of `arthelper/assets/` (the fonts) are bundled. A new data
file the code loads from anywhere else needs an `--add-data` in `build_exe`, and
should be checked for in `smoke.py` if the code would fall back silently without it.

## Steps

1. **Check the tree.** `git status`: everything the release should contain is
   committed and pushed (`main...origin/main` not ahead). If the code loads a file
   that is untracked, say so and get it committed first. There is no test suite;
   run the smoke test from source:
   `ART_HELPER_SMOKE_TEST=3 .venv/Scripts/python.exe art_helper.py; echo $?` → `0`.
2. **Check new kinds of files / dependencies.** `git log <last tag>..HEAD --stat`:
   a new asset outside `arthelper/assets/` or a new package in `requirements.txt`
   may need the build adjusted (see above).
3. **Pick the version.** Find the current one with `gh release list`. Bump the
   minor (`0.1.0` -> `0.2.0`) for a normal release with new features; the patch
   (`0.2.0` -> `0.2.1`) for fixes only; say which you chose. Ask only if the user
   hinted at a big milestone (`1.0.0`).
4. **Tag and push** at the pushed `HEAD` (lightweight tags):
   ```bash
   git tag v<version> && git push origin v<version>
   ```
5. **Watch the build** to the end:
   ```bash
   RUN=$(gh run list --workflow release.yml --limit 1 --json databaseId --jq '.[0].databaseId')
   gh run watch $RUN --exit-status --interval 20 > /dev/null; echo $?
   gh release view v<version> --json url,assets --jq '.url, (.assets[] | "\(.name) \(.size)")'
   ```
   On failure: `gh run view $RUN --log-failed`, fix, then delete the tag
   (`git push origin :refs/tags/v<version>; git tag -d v<version>`) and tag again.
   The old release is still in place, so nothing is lost.
6. **Remove the old release(s)** only after the new one is published with its zip:
   ```bash
   gh release delete v<old> --cleanup-tag --yes
   git tag -d v<old> 2>/dev/null; rm -f release/ArtHelper-<old>-windows.zip
   gh release list; git ls-remote --tags origin  # only the new one left
   ```
7. **Report** the release URL and size, the version chosen and what was removed.

A local build (`py build_tools/Release/build_release.py <version>`) is only needed to
debug a failing CI run; it writes to `release/` and takes about a minute
(`--work <folder>` keeps the PyInstaller build to look into).
