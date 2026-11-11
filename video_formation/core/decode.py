"""Reading a video with FFmpeg, when it is installed (DEVELOPMENT.md §5).

No bpy. FFmpeg is the fast path: one pipe, frames already scaled and resampled to
the light fps. Without it the add-on decodes with Blender's own sequencer
(``blender_io/decode_vse.py``), which needs nothing installed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Iterator

import numpy as np

WINDOWS = os.name == "nt"

#: The FFmpeg shipped inside the add-on (platform builds only): video_formation/ffmpeg/.
BUNDLED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ffmpeg")


def _candidates() -> tuple[str, ...]:
    """Where FFmpeg is usually installed. Blender started from the Dock / Start menu
    does not always see the shell's PATH."""
    if WINDOWS:
        env = os.environ.get
        return tuple(p for p in (
            os.path.join(env("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links") if env("LOCALAPPDATA") else "",
            os.path.join(env("ProgramFiles", r"C:\Program Files"), "ffmpeg", "bin"),
            r"C:\ffmpeg\bin",
            os.path.join(env("ProgramData", r"C:\ProgramData"), "chocolatey", "bin"),
            os.path.join(env("USERPROFILE", ""), "scoop", "shims") if env("USERPROFILE") else "",
        ) if p)
    return (
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/local/ffmpeg/bin",
        "/opt/local/bin",
        "/usr/bin",
    )


#: Extra arguments for every FFmpeg call: on Windows no console window flashes up.
POPEN_EXTRA: dict = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)} if WINDOWS else {}

VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpg", ".mpeg", ".wmv", ".flv")


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    duration: float  # seconds
    frames: int


def _file_names(name: str) -> tuple[str, ...]:
    return (name + ".exe", name) if WINDOWS else (name,)


def _runnable(path: str) -> bool:
    """A file that can be started. A Blender extension zip does not keep the
    executable bit, so the bundled copy gets it back here (macOS / Linux)."""
    if not os.path.isfile(path):
        return False
    if WINDOWS or os.access(path, os.X_OK):
        return True
    try:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        return False
    return os.access(path, os.X_OK)


def _in_folder(folder: str, name: str, fix_mode: bool = False) -> str | None:
    for file_name in _file_names(name):
        path = os.path.join(folder, file_name)
        if fix_mode:
            if _runnable(path):
                return path
        elif os.path.isfile(path) and (WINDOWS or os.access(path, os.X_OK)):
            return path
    return None


def bundled_tool(name: str) -> str | None:
    """The FFmpeg that came with the add-on, if this is a platform build."""
    return _in_folder(BUNDLED_DIR, name, fix_mode=True)


def find_tool(name: str, hint: str = "") -> str | None:
    """``name`` (ffmpeg / ffprobe): the file or folder the user chose (``hint``) first,
    then the copy bundled with the add-on, then PATH, then the usual install folders."""
    if hint:
        hint = os.path.expanduser(hint)
        base = os.path.basename(hint).lower()
        if os.path.isfile(hint) and base.startswith(name) and _runnable(hint):
            return hint
        folder = hint if os.path.isdir(hint) else os.path.dirname(hint)
        found = _in_folder(folder, name, fix_mode=True) if folder else None
        if found:
            return found
    found = bundled_tool(name)
    if found:
        return found
    found = shutil.which(name)
    if found:
        return found
    for folder in _candidates():
        found = _in_folder(folder, name)
        if found:
            return found
    return None


def searched_places() -> str:
    return "the add-on's own ffmpeg folder, PATH, " + ", ".join(_candidates())


def _run_text(cmd: list[str], timeout: float = 60) -> subprocess.CompletedProcess:
    """Run and capture the output as text. FFmpeg prints UTF-8 whatever the system's
    code page is (Windows), so decode it as UTF-8."""
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, **POPEN_EXTRA)


def version(tool: str) -> str:
    """'8.1.1' or similar, '' when it does not run."""
    try:
        out = _run_text([tool, "-hide_banner", "-version"], timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"version\s+(\S+)", out.stdout or "")
    return m.group(1) if (m and out.returncode == 0) else ""


def _fps(text: str) -> float:
    try:
        if "/" in text:
            a, b = text.split("/", 1)
            return float(a) / float(b) if float(b) else 0.0
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def probe(path: str, ffprobe: str | None = None, ffmpeg: str | None = None) -> VideoInfo:
    """Size, fps and length of the video. Uses ffprobe when there is one, otherwise
    reads what ``ffmpeg -i`` prints — so a lone ffmpeg is enough."""
    tool = ffprobe or find_tool("ffprobe")
    if not tool:
        return probe_with_ffmpeg(path, ffmpeg)
    out = _run_text(
        [tool, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,duration:format=duration",
         "-of", "json", path],
    )
    if out.returncode != 0:
        raise ValueError(f"Could not read the video: {out.stderr.strip() or path}")
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        raise ValueError(f"No video stream in {os.path.basename(path)}.")
    s = streams[0]
    fps = _fps(s.get("avg_frame_rate", "")) or _fps(s.get("r_frame_rate", ""))
    duration = float(s.get("duration") or (data.get("format") or {}).get("duration") or 0.0)
    frames = int(s.get("nb_frames") or 0) or int(round(duration * fps))
    if not (fps > 0 and duration > 0):
        raise ValueError(f"Could not read the frame rate or length of {os.path.basename(path)}.")
    return VideoInfo(int(s["width"]), int(s["height"]), fps, duration, frames)


_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_SIZE = re.compile(r"[ ,](\d{2,5})x(\d{2,5})[ ,\[]")
_FPS = re.compile(r"([\d.]+)\s*fps")
_TBR = re.compile(r"([\d.]+)k?\s*tbr")


def probe_with_ffmpeg(path: str, ffmpeg: str | None = None) -> VideoInfo:
    tool = ffmpeg or find_tool("ffmpeg")
    if not tool:
        raise RuntimeError("ffmpeg not found")
    out = _run_text([tool, "-hide_banner", "-nostdin", "-i", path])
    text = out.stderr or ""
    video = next((line for line in text.splitlines() if "Video:" in line), "")
    d = _DURATION.search(text)
    size = _SIZE.search(video + " ")
    rate = _FPS.search(video) or _TBR.search(video)
    if not (d and size and rate):
        msg = text.strip().splitlines()[-1] if text.strip() else path
        raise ValueError(f"Could not read the video: {msg}")
    duration = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))
    fps = float(rate.group(1))
    if not (fps > 0 and duration > 0):
        raise ValueError(f"Could not read the frame rate or length of {os.path.basename(path)}.")
    return VideoInfo(int(size.group(1)), int(size.group(2)), fps, duration, int(round(duration * fps)))


def read_frames(path: str, start: float, count: int, light_fps: float, size: tuple[int, int],
                ffmpeg: str | None = None) -> Iterator[np.ndarray]:
    """Yield ``count`` frames (H, W, 3) uint8 sRGB at ``start + i / light_fps``.

    The fps filter picks the source frame nearest each output time; ``area``
    scaling averages the pixels each output pixel covers (no aliasing)."""
    tool = ffmpeg or find_tool("ffmpeg")
    if not tool:
        raise RuntimeError("ffmpeg not found")
    w, h = int(size[0]), int(size[1])
    cmd = [
        tool, "-v", "error", "-nostdin",
        "-ss", f"{max(0.0, float(start)):.6f}", "-i", path,
        "-frames:v", str(int(count)),
        "-vf", f"fps={float(light_fps):.6f},scale={w}:{h}:flags=area,format=rgb24",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    frame_bytes = w * h * 3
    # FFmpeg's messages go to a temporary file, not a pipe: a pipe nobody reads while
    # the frames are read fills up and stalls FFmpeg (smaller pipes on Windows).
    err_file = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err_file, stdin=subprocess.DEVNULL,
                            **POPEN_EXTRA)
    try:
        assert proc.stdout is not None
        for _ in range(int(count)):
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
    finally:
        if proc.stdout:
            proc.stdout.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        try:
            err_file.seek(0)
            err = err_file.read(4000).decode("utf-8", "replace").strip()
        except OSError:
            err = ""
        err_file.close()
        if proc.returncode not in (0, None, -9, -15) and err:
            # surfaced only when nothing at all came out (bake_colors raises then)
            print(f"[video_formation] ffmpeg: {err[:500]}")
