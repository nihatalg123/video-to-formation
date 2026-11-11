"""Turn a downloaded FFmpeg build into a bundle folder for build_release.py.

    python3 tools/prepare_ffmpeg.py windows SRC OUT_DIR   # gyan.dev "release essentials" zip
    python3 tools/prepare_ffmpeg.py macos   SRC OUT_DIR   # ffmpeg.martin-riedl.de macOS arm64 zip

SRC is the downloaded zip or the folder it unpacked to. OUT_DIR gets:
ffmpeg(.exe), LICENSE.txt and SOURCE.txt (what the build is, its configuration, where
its source is). Checks the program is for the right platform, and refuses builds
configured with --enable-nonfree (those may not be passed on).
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import sys
import tempfile
import zipfile

GPL3_TEXT = "/usr/share/common-licenses/GPL-3"
LGPL3_TEXT = "/usr/share/common-licenses/LGPL-3"
GPL2_TEXT = "/usr/share/common-licenses/GPL-2"
LGPL21_TEXT = "/usr/share/common-licenses/LGPL-2.1"


def unpack(src: str) -> str:
    if os.path.isdir(src):
        return src
    out = tempfile.mkdtemp(prefix="ffmpeg_src_")
    with zipfile.ZipFile(src) as zf:
        for info in zf.infolist():  # no absolute / parent paths
            name = os.path.normpath(info.filename)
            if name.startswith(("..", os.sep)) or os.path.isabs(name):
                raise SystemExit(f"unsafe path in zip: {info.filename}")
        zf.extractall(out)
    return out


def find(folder: str, names: tuple[str, ...]) -> str | None:
    hits = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f in names:
                hits.append(os.path.join(root, f))
    hits.sort(key=lambda p: (p.count(os.sep), p))
    return hits[0] if hits else None


def strings_of(path: str, min_len: int = 6) -> list[str]:
    with open(path, "rb") as handle:
        data = handle.read()
    return [m.decode("ascii", "replace") for m in re.findall(rb"[\x20-\x7e]{%d,}" % min_len, data)]


def configuration(strs: list[str]) -> str:
    best = ""
    for s in strs:
        if s.count("--enable-") + s.count("--disable-") >= 5 and len(s) > len(best):
            best = s
    return best[best.find("--"):] if "--" in best else best


def version_of(strs: list[str], fallback: str = "") -> str:
    """FFMPEG_VERSION, e.g. '9.0.2-essentials_build-www.gyan.dev' (from the banner)."""
    for s in strs:
        m = re.search(r"FFmpeg version (\S+)", s)
        if m:
            return m.group(1)
    for s in strs:
        m = re.match(r"^(n?\d+\.\d+(?:\.\d+)?(?:-[\w.\-]+)?|N-\d+-g[0-9a-f]+(?:-[\w.\-]+)?)$", s.strip())
        if m:
            return m.group(1)
    return fallback


def licence(conf: str) -> tuple[str, str]:
    if "--enable-nonfree" in conf:
        raise SystemExit("this FFmpeg build is configured with --enable-nonfree: it may not be redistributed")
    gpl, v3 = "--enable-gpl" in conf, "--enable-version3" in conf
    if gpl:
        return ("GPL-3.0-or-later", GPL3_TEXT) if v3 else ("GPL-2.0-or-later", GPL2_TEXT)
    return ("LGPL-3.0-or-later", LGPL3_TEXT) if v3 else ("LGPL-2.1-or-later", LGPL21_TEXT)


def pe_machine(path: str) -> str:
    with open(path, "rb") as h:
        head = h.read(4096)
    if head[:2] != b"MZ":
        return "not a Windows program"
    off = struct.unpack_from("<I", head, 0x3C)[0]
    with open(path, "rb") as h:
        h.seek(off)
        sig = h.read(6)
    if sig[:4] != b"PE\0\0":
        return "not a Windows program"
    machine = struct.unpack_from("<H", sig, 4)[0]
    return {0x8664: "x64", 0xAA64: "arm64", 0x14C: "x86"}.get(machine, hex(machine))


def macho_info(path: str) -> dict:
    """Architecture, signature present, minimum macOS — read from the load commands."""
    with open(path, "rb") as h:
        data = h.read(1 << 16)
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic == 0xBEBAFECA or magic == 0xCAFEBABE:
        return {"arch": "universal (fat)", "signed": None, "min_macos": None}
    if magic != 0xFEEDFACF:
        return {"arch": "not a 64-bit Mach-O program", "signed": None, "min_macos": None}
    cputype, _sub, _ftype, ncmds, _size, _flags = struct.unpack_from("<iiIIII", data, 4)
    arch = {0x0100000C: "arm64", 0x01000007: "x86_64"}.get(cputype, hex(cputype))
    off, signed, min_os = 32, False, None
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        if cmd == 0x1D:  # LC_CODE_SIGNATURE
            signed = True
        elif cmd == 0x32:  # LC_BUILD_VERSION
            _plat, minos = struct.unpack_from("<II", data, off + 8)
            min_os = f"{minos >> 16}.{(minos >> 8) & 0xFF}"
        elif cmd == 0x24:  # LC_VERSION_MIN_MACOSX
            v = struct.unpack_from("<I", data, off + 8)[0]
            min_os = f"{v >> 16}.{(v >> 8) & 0xFF}"
        off += size
    return {"arch": arch, "signed": signed, "min_macos": min_os}


def main(kind: str, src: str, out: str) -> None:
    folder = unpack(src)
    os.makedirs(out, exist_ok=True)
    if kind == "windows":
        exe = find(folder, ("ffmpeg.exe",))
        if not exe:
            raise SystemExit("ffmpeg.exe not found")
        machine = pe_machine(exe)
        if machine != "x64":
            raise SystemExit(f"ffmpeg.exe is {machine}, expected x64")
        target = os.path.join(out, "ffmpeg.exe")
        provider = ("gyan.dev (Gyan Doshi) — FFmpeg release \"essentials\" build for Windows",
                    "https://www.gyan.dev/ffmpeg/builds/")
        detail = f"Windows x64 program"
    elif kind == "macos":
        exe = find(folder, ("ffmpeg",))
        if not exe:
            raise SystemExit("ffmpeg not found")
        info = macho_info(exe)
        if info["arch"] != "arm64":
            raise SystemExit(f"ffmpeg is {info['arch']}, expected arm64")
        if not info["signed"]:
            raise SystemExit("ffmpeg has no code signature: Apple Silicon Macs will not run it")
        target = os.path.join(out, "ffmpeg")
        provider = ("Martin Riedl's FFmpeg Build Server — macOS arm64 release build",
                    "https://ffmpeg.martin-riedl.de/")
        detail = f"macOS arm64 program, code signature present, minimum macOS {info['min_macos']}"
    else:
        raise SystemExit("kind must be windows or macos")
    shutil.copyfile(exe, target)
    os.chmod(target, 0o755)

    strs = strings_of(exe)
    conf = configuration(strs)
    ver = version_of(strs)
    spdx, text_path = licence(conf)
    lic_src = find(folder, ("LICENSE", "LICENSE.txt", "COPYING.GPLv3", "COPYING"))
    shutil.copyfile(lic_src if lic_src else text_path, os.path.join(out, "LICENSE.txt"))
    readme = find(folder, ("README.txt",))
    if readme:
        shutil.copyfile(readme, os.path.join(out, "BUILD-INFO.txt"))
    release = re.match(r"^n?(\d+\.\d+(?:\.\d+)?)", ver)
    tarball = f"https://ffmpeg.org/releases/ffmpeg-{release.group(1)}.tar.xz" if release else \
        "https://git.ffmpeg.org/ffmpeg.git (the commit in the version above)"
    with open(os.path.join(out, "SOURCE.txt"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(f"""FFmpeg included with Video to Formation
=======================================

This folder holds FFmpeg, a separate program made by the FFmpeg developers
(https://ffmpeg.org). Video to Formation runs it to read video files. It is passed on
unmodified, exactly as published by the build provider below.

Program:   {os.path.basename(target)} ({detail})
Version:   {ver or 'see `ffmpeg -version`'}
Built by:  {provider[0]}
           {provider[1]}
Licence:   {spdx} — full text in LICENSE.txt

Source code
-----------
FFmpeg source of this version: {tarball}
The build provider lists the exact source of FFmpeg and of every library compiled
into this program on the page above{' and in BUILD-INFO.txt' if readme else ''}.
If any of these stops being available, ask the developer of Video to Formation
(@nihatalg) and you will be given a copy of the corresponding source.

Configuration of this build
---------------------------
{conf or '(not found in the program)'}

FFmpeg is a trademark of Fabrice Bellard, originator of the FFmpeg project.
""")
    print(f"{kind}: {target}  version={ver!r}  licence={spdx}  {detail}")
    print(f"   configuration: {conf[:160]}{'...' if len(conf) > 160 else ''}")
    print(f"   size {os.path.getsize(target) / 1e6:.1f} MB; files: {sorted(os.listdir(out))}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
