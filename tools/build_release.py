"""Build the release zips of Video to Formation.

    python3 tools/build_release.py OUT_DIR [--bundle PLATFORM=FOLDER ...]

* ``video_formation-<version>-no-ffmpeg.zip``: every platform, no FFmpeg inside
  (uses an installed FFmpeg, otherwise Blender's own video reader).
* ``video_formation-<version>-<platform>.zip`` for each ``--bundle``: the same
  add-on plus the files of FOLDER in ``video_formation/ffmpeg/`` (the ffmpeg
  program, its licence and where its source is), and a ``platforms`` line in the
  manifest so Blender only installs it where that program runs.

Platforms are Blender's names: windows-x64, macos-arm64, linux-x64, ...
The Windows build is also offered to windows-arm64 (Windows 11 runs x64 programs).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, "video_formation")
SKIP_DIRS = {"__pycache__", "ffmpeg"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}
#: Blender platforms each bundle is installable on.
PLATFORMS = {
    "windows-x64": ["windows-x64", "windows-arm64"],
    "macos-arm64": ["macos-arm64"],
    "linux-x64": ["linux-x64"],
}
EXECUTABLES = {"ffmpeg", "ffmpeg.exe", "ffprobe", "ffprobe.exe"}


def addon_files() -> list[tuple[str, str]]:
    out = []
    for folder, dirs, files in os.walk(ADDON):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name in SKIP_FILES or name.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(folder, name)
            out.append((full, os.path.relpath(full, ADDON).replace(os.sep, "/")))
    return out


def manifest_text(platforms: list[str] | None) -> str:
    with open(os.path.join(ADDON, "blender_manifest.toml"), encoding="utf-8") as handle:
        text = handle.read()
    if platforms:
        line = "platforms = [" + ", ".join(f'"{p}"' for p in platforms) + "]\n"
        text, n = re.subn(r'(blender_version_min = "[^"]+"\n)', r"\1" + line.replace("\\", "\\\\"), text, count=1)
        if n != 1:
            raise SystemExit("blender_version_min not found in the manifest")
    return text


def version() -> str:
    m = re.search(r'^version = "([^"]+)"', manifest_text(None), re.M)
    return m.group(1)


def _add(zf: zipfile.ZipFile, arcname: str, data: bytes, executable: bool = False) -> None:
    info = zipfile.ZipInfo(arcname, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = ((0o755 if executable else 0o644) | 0o100000) << 16
    zf.writestr(info, data, compresslevel=9)


def build(out_path: str, platforms: list[str] | None, bundle: str | None) -> None:
    with zipfile.ZipFile(out_path, "w") as zf:
        for full, rel in addon_files():
            if rel == "blender_manifest.toml":
                _add(zf, rel, manifest_text(platforms).encode("utf-8"))
                continue
            with open(full, "rb") as handle:
                _add(zf, rel, handle.read())
        if bundle:
            names = sorted(os.listdir(bundle))
            if not any(n in EXECUTABLES and n.startswith("ffmpeg") for n in names):
                raise SystemExit(f"no ffmpeg program in {bundle}")
            for name in names:
                full = os.path.join(bundle, name)
                if not os.path.isfile(full) or name in SKIP_FILES:
                    continue
                with open(full, "rb") as handle:
                    _add(zf, "ffmpeg/" + name, handle.read(), executable=name in EXECUTABLES)
    print(f"{os.path.basename(out_path)}: {os.path.getsize(out_path) / 1e6:.1f} MB"
          + (f"  platforms={platforms}" if platforms else "  (all platforms)"))


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--bundle", action="append", default=[], metavar="PLATFORM=FOLDER")
    args = ap.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    ver = version()
    build(os.path.join(args.out_dir, f"video_formation-{ver}-no-ffmpeg.zip"), None, None)
    for item in args.bundle:
        plat, _, folder = item.partition("=")
        if plat not in PLATFORMS or not os.path.isdir(folder):
            raise SystemExit(f"bad --bundle {item!r} (platforms: {', '.join(PLATFORMS)})")
        build(os.path.join(args.out_dir, f"video_formation-{ver}-{plat}.zip"), PLATFORMS[plat], folder)


if __name__ == "__main__":
    main(sys.argv[1:])
