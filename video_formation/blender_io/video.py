"""Reading the video inside Blender (DEVELOPMENT.md §5).

Two decoders behind one interface:

* **FFmpeg** (``core/decode.py``) when it is installed — one pipe, fastest;
* **Blender** — the sequencer of a temporary scene renders each needed frame,
  already scaled down, to a small PNG that is read back and deleted. Uses
  Blender's own FFmpeg libraries, so it reads whatever Blender's Video Sequencer
  reads (mp4, mov, mkv, avi, ...) with nothing installed. Frames are rendered as
  animation chunks (one render call per 120 frames). Slower than FFmpeg, so it is
  the fallback.

The user's scene is never touched: the temporary scene is removed afterwards,
even on errors.
"""

from __future__ import annotations

import math
import os
import shutil
import tempfile
from typing import Callable, Iterator

import bpy
import numpy as np

from ..core import decode
from ..core.decode import VideoInfo

DECODERS = ("AUTO", "FFMPEG", "BLENDER")
#: Frames per render call with Blender's reader.
CHUNK = 120


def ffmpeg_hint() -> str:
    """The FFmpeg file or folder chosen in the panel (may be empty)."""
    try:
        raw = bpy.context.scene.video_formation.ffmpeg_path
    except Exception:
        return ""
    if not raw:
        return ""
    full = bpy.path.abspath(raw)
    return full if isinstance(full, str) else ""


_STATUS: dict = {}


def ffmpeg_status() -> tuple[str, str]:
    """(kind, text) for the panel: kind is BUNDLED / CHOSEN / SYSTEM / MISSING.
    Remembered per FFmpeg field value, so drawing the panel stays cheap."""
    hint = ffmpeg_hint()
    if hint in _STATUS:
        return _STATUS[hint]
    tool = decode.find_tool("ffmpeg", hint)
    if not tool:
        result = ("MISSING", "FFmpeg not found: Blender's reader is used (slower)")
    else:
        ver = decode.version(tool)
        if not ver:
            result = ("MISSING", "FFmpeg found but it does not run: " + tool)
        elif os.path.dirname(tool) == decode.BUNDLED_DIR:
            result = ("BUNDLED", f"FFmpeg {ver} (included with the add-on)")
        elif hint:
            result = ("CHOSEN", f"FFmpeg {ver}: {tool}")
        else:
            result = ("SYSTEM", f"FFmpeg {ver}: {tool}")
    _STATUS.clear()
    _STATUS[hint] = result
    return result


def choose_decoder(choice: str) -> str:
    choice = str(choice).upper()
    _STATUS.clear()  # the panel looks again after a run (FFmpeg may have been installed)
    have = decode.find_tool("ffmpeg", ffmpeg_hint()) is not None
    if choice == "FFMPEG":
        if not have:
            raise ValueError(
                "FFmpeg not found (looked in " + decode.searched_places() + "). Install the "
                "add-on build that includes FFmpeg, install FFmpeg, or choose the ffmpeg file "
                "in the FFmpeg field of the panel."
            )
        return "FFMPEG"
    if choice == "BLENDER":
        return "BLENDER"
    return "FFMPEG" if have else "BLENDER"


def probe(path: str, decoder: str) -> VideoInfo:
    if decoder == "FFMPEG":
        hint = ffmpeg_hint()
        return decode.probe(path, decode.find_tool("ffprobe", hint), decode.find_tool("ffmpeg", hint))
    clip = bpy.data.movieclips.load(path, check_existing=False)
    try:
        w, h = int(clip.size[0]), int(clip.size[1])
        fps = float(clip.fps) if clip.fps else 0.0
        frames = int(clip.frame_duration)
    finally:
        bpy.data.movieclips.remove(clip)
    if not (w > 0 and h > 0 and frames > 0):
        raise ValueError(f"Blender could not read the video {os.path.basename(path)}.")
    if not fps > 0:
        fps = 30.0
    return VideoInfo(w, h, fps, frames / fps, frames)


def read_frames(path: str, info: VideoInfo, times: np.ndarray, light_fps: float,
                size: tuple[int, int], decoder: str,
                progress: Callable[[int, int], None] | None = None) -> Iterator[np.ndarray]:
    if decoder == "FFMPEG":
        start = float(times[0]) if len(times) else 0.0
        yield from decode.read_frames(path, start, len(times), light_fps, size,
                                      decode.find_tool("ffmpeg", ffmpeg_hint()))
        return
    yield from _read_frames_vse(path, info, times, size, progress)


def _strips(editor):
    strips = getattr(editor, "strips", None)
    if strips is None:  # Blender < 4.4
        strips = editor.sequences
    return strips


def _set(obj, attr: str, value) -> None:
    try:
        setattr(obj, attr, value)
    except (AttributeError, TypeError, ValueError):
        pass


def _read_frames_vse(path: str, info: VideoInfo, times: np.ndarray, size: tuple[int, int],
                     progress: Callable[[int, int], None] | None) -> Iterator[np.ndarray]:
    w, h = int(size[0]), int(size[1])
    scene = bpy.data.scenes.new("VF_Decode")
    folder = tempfile.mkdtemp(prefix="vf_decode_")
    try:
        render = scene.render
        fps_round = max(1, int(round(info.fps)))
        render.fps = fps_round
        render.fps_base = fps_round / info.fps
        render.resolution_x = w
        render.resolution_y = h
        render.resolution_percentage = 100
        render.pixel_aspect_x = 1.0
        render.pixel_aspect_y = 1.0
        _set(render, "use_sequencer", True)
        _set(render, "use_compositing", False)
        _set(render, "film_transparent", False)
        settings = render.image_settings
        _set(settings, "file_format", "PNG")
        _set(settings, "color_mode", "RGB")
        _set(settings, "color_depth", "8")
        _set(settings, "compression", 0)
        # what the video stores, not a film look
        _set(scene.view_settings, "view_transform", "Standard")
        _set(scene.view_settings, "look", "None")
        _set(scene.view_settings, "exposure", 0.0)
        _set(scene.view_settings, "gamma", 1.0)
        _set(scene.display_settings, "display_device", "sRGB")
        seq_cs = getattr(scene, "sequencer_colorspace_settings", None)
        if seq_cs is not None:
            _set(seq_cs, "name", "sRGB")

        editor = scene.sequence_editor_create()
        strips = _strips(editor)
        try:
            strip = strips.new_movie(name="vf_video", filepath=path, channel=1, frame_start=1,
                                     fit_method="STRETCH")
        except TypeError:
            strip = strips.new_movie(name="vf_video", filepath=path, channel=1, frame_start=1)
            _set(strip, "fit_method", "STRETCH")
        n_src = max(1, int(strip.frame_final_duration))
        scene.frame_start = 1
        scene.frame_end = n_src

        # Render the needed source frames as an animation, in chunks: one render call
        # per chunk, not per frame (a still render costs ~0.1 s of setup each).
        needed = [min(max(int(math.floor(float(t) * info.fps + 0.5)), 0), n_src - 1) for t in times]
        diffs = [b - a for a, b in zip(needed, needed[1:]) if b > a]
        step = diffs[0] if diffs else 1
        for d in diffs:
            step = math.gcd(step, d)
        step = max(1, step)
        render.filepath = os.path.join(folder, "f_")
        total = len(times)
        done = 0
        i = 0
        while i < total:
            first = needed[i]
            last = min(first + step * (CHUNK - 1), needed[-1])
            scene.frame_start = 1 + first
            scene.frame_end = 1 + last
            scene.frame_step = step
            bpy.ops.render.render(animation=True, scene=scene.name)
            while i < total and needed[i] <= last:
                target = render.frame_path(frame=1 + needed[i])
                if not os.path.exists(target):
                    raise RuntimeError(
                        "Blender's own video reader did not deliver a frame. Use the add-on "
                        "build that includes FFmpeg (or install FFmpeg) and generate again."
                    )
                frame = _read_png(target, w, h)
                i += 1
                done += 1
                if progress is not None:
                    progress(done, total)
                yield frame
            for name in os.listdir(folder):
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    pass
    finally:
        try:
            bpy.data.scenes.remove(scene)
        except (ReferenceError, RuntimeError):
            pass
        shutil.rmtree(folder, ignore_errors=True)


def _read_png(path: str, w: int, h: int) -> np.ndarray:
    img = bpy.data.images.load(path, check_existing=False)
    try:
        iw, ih = int(img.size[0]), int(img.size[1])
        ch = int(img.channels or 4)
        buf = np.empty(iw * ih * ch, dtype=np.float32)
        img.pixels.foreach_get(buf)
    finally:
        bpy.data.images.remove(img)
    px = buf.reshape(ih, iw, ch)[::-1, :, :3]
    frame = np.clip(px * 255.0 + 0.5, 0, 255).astype(np.uint8)
    if (iw, ih) != (w, h):
        frame = _resize_nearest(frame, w, h)
    return frame


def _resize_nearest(frame: np.ndarray, w: int, h: int) -> np.ndarray:
    ys = np.minimum((np.arange(h) * frame.shape[0] / h).astype(int), frame.shape[0] - 1)
    xs = np.minimum((np.arange(w) * frame.shape[1] / w).astype(int), frame.shape[1] - 1)
    return frame[ys][:, xs]
