"""Video frames -> one LED colour per drone (DEVELOPMENT.md §3).

Pure numpy. A frame arrives as ``(H, W, 3)`` uint8, sRGB-encoded, row 0 at the top
(what every decoder gives). For each drone:

1. its screen cell (``Screen.uv`` +- ``cell_uv / 2``) is placed on the frame by the
   fit mode — FILL crops the video to fill the screen, FIT shows the whole video
   with black bars, STRETCH distorts it to the screen;
2. the frame is converted to **linear** light and the cell is **averaged** with a
   summed-area table (4 lookups per drone), so a drone shows its whole patch of
   the picture — no flicker from single pixels, no aliasing on fine detail;
3. grading in linear light: brightness gain, saturation, black cut (dark noise ->
   LED off), a floor so the screen never fully disappears, and an LED maximum.

Colours stay linear, like Image to Formation and like Skybrush's own video light
effects (sRGB video -> linear). Stored as uint8 (0..255 linear) — what an LED
receives in the end anyway.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FITS = ("FILL", "FIT", "STRETCH")
REC709 = np.array([0.2126, 0.7152, 0.0722])


def srgb_to_linear_lut() -> np.ndarray:
    v = np.arange(256, dtype=np.float64) / 255.0
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


_LUT = srgb_to_linear_lut()


@dataclass
class Grade:
    brightness: float = 1.0   # gain in linear light
    saturation: float = 1.0
    black_cut: float = 0.0    # linear luma below this -> off
    floor: float = 0.0        # every drone at least this (linear luma), hue kept
    max_led: float = 1.0      # cap per channel
    smoothing: float = 0.0    # 0..0.9: share of the previous frame kept (flicker)


def cell_boxes(uv: np.ndarray, cell_uv: np.ndarray, screen_aspect: float, frame_w: int,
               frame_h: int, fit: str) -> np.ndarray:
    """(N, 4) float pixel boxes x0, y0, x1, y1 on the frame for each drone's cell."""
    fit = str(fit).upper()
    if fit not in FITS:
        raise ValueError(f"Fit must be one of {', '.join(FITS)}, got {fit!r}.")
    uv = np.asarray(uv, dtype=np.float64)
    half = 0.5 * np.asarray(cell_uv, dtype=np.float64)
    u0, u1 = uv[:, 0] - half[0], uv[:, 0] + half[0]
    v0, v1 = uv[:, 1] - half[1], uv[:, 1] + half[1]
    a_s = float(screen_aspect)
    a_v = float(frame_w) / float(frame_h)
    sx = sy = 1.0  # share of the frame the screen spans, per axis (1 = all of it)
    if fit == "FILL":
        if a_s > a_v:
            sy = a_v / a_s
        else:
            sx = a_s / a_v
    elif fit == "FIT":
        if a_s > a_v:
            sx = a_s / a_v
        else:
            sy = a_v / a_s

    def to_px(u, s, size):
        return (0.5 + (u - 0.5) * s) * size

    return np.stack(
        [to_px(u0, sx, frame_w), to_px(v0, sy, frame_h), to_px(u1, sx, frame_w), to_px(v1, sy, frame_h)],
        axis=1,
    )


class Sampler:
    """Precomputes the integer box corners once; then ``colors(frame)`` is a few
    vectorised lookups per frame."""

    def __init__(self, boxes: np.ndarray, frame_w: int, frame_h: int):
        b = np.asarray(boxes, dtype=np.float64)
        x0 = np.clip(np.floor(b[:, 0] + 0.5), 0, frame_w).astype(np.int64)
        y0 = np.clip(np.floor(b[:, 1] + 0.5), 0, frame_h).astype(np.int64)
        x1 = np.clip(np.floor(b[:, 2] + 0.5), 0, frame_w).astype(np.int64)
        y1 = np.clip(np.floor(b[:, 3] + 0.5), 0, frame_h).astype(np.int64)
        # a cell smaller than a pixel still reads the pixel under its centre
        cx = np.clip(np.floor(0.5 * (b[:, 0] + b[:, 2])), 0, frame_w - 1).astype(np.int64)
        cy = np.clip(np.floor(0.5 * (b[:, 1] + b[:, 3])), 0, frame_h - 1).astype(np.int64)
        thin_x = x1 <= x0
        thin_y = y1 <= y0
        x0 = np.where(thin_x, cx, x0)
        x1 = np.where(thin_x, cx + 1, x1)
        y0 = np.where(thin_y, cy, y0)
        y1 = np.where(thin_y, cy + 1, y1)
        # a cell wholly off the frame (FIT bars) is black
        centre_x = 0.5 * (b[:, 0] + b[:, 2])
        centre_y = 0.5 * (b[:, 1] + b[:, 3])
        self.outside = (centre_x < 0) | (centre_x >= frame_w) | (centre_y < 0) | (centre_y >= frame_h)
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.area = np.maximum((x1 - x0) * (y1 - y0), 1).astype(np.float64)
        self.w, self.h = int(frame_w), int(frame_h)

    def colors(self, frame: np.ndarray) -> np.ndarray:
        """(N, 3) linear 0..1 colours, ungraded."""
        f = np.asarray(frame)
        if f.shape[:2] != (self.h, self.w):
            raise ValueError(f"frame is {f.shape[1]}x{f.shape[0]}, expected {self.w}x{self.h}")
        lin = _LUT[f[:, :, :3]] if f.dtype == np.uint8 else np.clip(f[:, :, :3], 0, 1)
        sat = np.zeros((self.h + 1, self.w + 1, 3), dtype=np.float64)
        np.cumsum(np.cumsum(lin, axis=0), axis=1, out=sat[1:, 1:])
        s = sat[self.y1, self.x1] - sat[self.y0, self.x1] - sat[self.y1, self.x0] + sat[self.y0, self.x0]
        out = s / self.area[:, None]
        out[self.outside] = 0.0
        return np.clip(out, 0.0, 1.0)


def grade(colors: np.ndarray, g: Grade, previous: np.ndarray | None = None) -> np.ndarray:
    """Linear (N, 3) -> graded linear (N, 3), 0..1."""
    c = np.asarray(colors, dtype=np.float64) * float(g.brightness)
    if g.saturation != 1.0:
        luma = (c @ REC709)[:, None]
        c = luma + (c - luma) * float(g.saturation)
    c = np.clip(c, 0.0, None)
    if g.black_cut > 0:
        c[(c @ REC709) < float(g.black_cut)] = 0.0
    if g.floor > 0:
        luma = c @ REC709
        low = luma < float(g.floor)
        if low.any():
            scale = np.where(luma[low] > 1e-6, float(g.floor) / np.maximum(luma[low], 1e-6), 0.0)
            lifted = c[low] * scale[:, None]
            grey = luma[low] <= 1e-6
            lifted[grey] = float(g.floor)
            c[low] = lifted
    c = np.minimum(c, float(g.max_led))
    if previous is not None and g.smoothing > 0:
        k = min(max(float(g.smoothing), 0.0), 0.9)
        c = (1.0 - k) * c + k * previous
    return np.clip(c, 0.0, 1.0)


def to_u8(colors: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(np.asarray(colors) * 255.0), 0, 255).astype(np.uint8)


# ------------------------------------------------------------------- timing


def light_times(video_duration: float, light_fps: float, start: float = 0.0,
                length: float = 0.0) -> np.ndarray:
    """Times (seconds into the video) of the light frames: every 1/light_fps from
    ``start`` for ``length`` seconds (0 = to the end of the video)."""
    start = max(0.0, float(start))
    end = float(video_duration)
    if length and length > 0:
        end = min(end, start + float(length))
    if end <= start:
        raise ValueError("Nothing to play: the start is at or past the end of the video.")
    n = int(np.floor((end - start) * float(light_fps) + 1e-6))
    return start + np.arange(max(n, 1)) / float(light_fps)


def scene_frames_for(n_light: int, light_fps: float, scene_fps: float) -> int:
    """How many scene frames the video covers."""
    return max(1, int(np.ceil(n_light * float(scene_fps) / float(light_fps) - 1e-6)))


def column_for_scene_frame(offset: np.ndarray | int, light_fps: float, scene_fps: float,
                           n_light: int) -> np.ndarray:
    """Scene frame offset from the start -> light frame index (held, clamped)."""
    col = np.floor(np.asarray(offset, dtype=np.float64) * float(light_fps) / float(scene_fps) + 1e-6)
    return np.clip(col, 0, n_light - 1).astype(np.int64)
