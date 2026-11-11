"""Screen + decoded frames -> light table colours (DEVELOPMENT.md §3).

Pure numpy; the decoder (FFmpeg or Blender's sequencer) only has to deliver frames
of the size ``decode_size`` asks for, at the times ``sampling.light_times`` lists.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable

import numpy as np

from . import sampling
from .layout import Screen

#: Pixels across one drone's cell in the decoded frames. Four is enough for a
#: clean average; more only costs decode time.
PX_PER_CELL = 4
MAX_DECODE_WIDTH = 1280


def decode_size(screen: Screen, fit: str, video_w: int, video_h: int,
                px_per_cell: int = PX_PER_CELL, max_width: int = MAX_DECODE_WIDTH) -> tuple[int, int]:
    """Frame size to decode at: the video's aspect, ~``px_per_cell`` pixels per drone
    cell, never above the video's own size or ``max_width``. Even numbers (FFmpeg's
    scalers prefer them)."""
    vw, vh = max(int(video_w), 2), max(int(video_h), 2)
    a_v = vw / vh
    a_s = float(screen.aspect)
    sx = sy = 1.0
    f = str(fit).upper()
    if f == "FILL":
        if a_s > a_v:
            sy = a_v / a_s
        else:
            sx = a_s / a_v
    elif f == "FIT":
        if a_s > a_v:
            sx = a_s / a_v
        else:
            sy = a_v / a_s
    # one cell spans cell_uv * s of the frame (s from the fit, as in sampling.cell_boxes)
    need_w = px_per_cell / max(float(screen.cell_uv[0]) * sx, 1e-9)
    need_h = px_per_cell / max(float(screen.cell_uv[1]) * sy, 1e-9)
    w = max(need_w, need_h * a_v, 32.0)
    w = min(w, float(vw), float(max_width))
    h = w / a_v
    w_i = max(2, int(math.ceil(w / 2.0)) * 2)
    h_i = max(2, int(math.ceil(h / 2.0)) * 2)
    return w_i, h_i


def bake_colors(screen: Screen, frames: Iterable[np.ndarray], n_frames: int, frame_size: tuple[int, int],
                fit: str, grade: sampling.Grade,
                progress: Callable[[int, int], None] | None = None) -> np.ndarray:
    """(F, N, 3) uint8 linear colours. ``frames`` yields (H, W, 3) uint8 sRGB frames;
    if it runs short the last frame is held (a decoder rounding one frame short
    must not shorten the show)."""
    w, h = frame_size
    boxes = sampling.cell_boxes(screen.uv, screen.cell_uv, screen.aspect, w, h, fit)
    sampler = sampling.Sampler(boxes, w, h)
    out = np.zeros((int(n_frames), screen.count, 3), dtype=np.uint8)
    previous = None
    got = 0
    for i, frame in enumerate(frames):
        if i >= n_frames:
            break
        lin = sampler.colors(frame)
        graded = sampling.grade(lin, grade, previous)
        previous = graded
        out[i] = sampling.to_u8(graded)
        got = i + 1
        if progress is not None:
            progress(got, n_frames)
    if got == 0:
        raise ValueError("The video gave no frames. Check the file and the start time.")
    if got < n_frames:
        out[got:] = out[got - 1]
    return out
