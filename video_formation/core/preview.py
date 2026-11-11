"""A picture of the screen at one moment: glowing dots on a night sky. Pure numpy.

Used by the Preview button (shown in Blender's Image Editor) and by the tests.
"""

from __future__ import annotations

import numpy as np

SKY = np.array([0.012, 0.014, 0.022])


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def render(positions: np.ndarray, colors_linear: np.ndarray, spacing: float, width_px: int = 900,
           margin: float = 0.06, dot: float = 0.30, glow: float = 0.9) -> np.ndarray:
    """(H, W, 3) uint8 sRGB, row 0 at the top. Dots are ``dot`` x spacing in radius
    with a soft glow; X to the right, Z up (seen from the front)."""
    p = np.asarray(positions, dtype=np.float64)
    c = np.asarray(colors_linear, dtype=np.float64)
    x, z = p[:, 0], p[:, 2]
    span_x = max(float(np.ptp(x)), spacing)
    span_z = max(float(np.ptp(z)), spacing)
    pad = margin * max(span_x, span_z) + spacing
    scale = (width_px - 1) / (span_x + 2 * pad)
    h = int(np.ceil((span_z + 2 * pad) * scale)) + 1
    w = int(width_px)
    img = np.zeros((h, w, 3), dtype=np.float64)
    img[:] = SKY
    px = (x - x.min() + pad) * scale
    py = (z.max() + pad - z) * scale
    r_core = max(dot * spacing * scale, 0.8)
    r_glow = r_core * (1.0 + 2.5 * glow)
    rad = int(np.ceil(r_glow)) + 1
    oy, ox = np.mgrid[-rad:rad + 1, -rad:rad + 1]
    for (cx, cy), col in zip(np.stack([px, py], 1), c):
        if col.max() <= 1e-4:
            continue
        ix, iy = int(round(cx)), int(round(cy))
        dx = ox + (ix - cx)
        dy = oy + (iy - cy)
        d = np.hypot(dx, dy)
        core = np.clip(r_core + 0.5 - d, 0.0, 1.0)
        halo = glow * 0.35 * np.exp(-(d / max(r_glow * 0.5, 1e-6)) ** 2)
        wgt = np.maximum(core, halo)
        y0, y1 = iy - rad, iy + rad + 1
        x0, x1 = ix - rad, ix + rad + 1
        sy0, sx0 = max(0, -y0), max(0, -x0)
        y0c, x0c = max(y0, 0), max(x0, 0)
        y1c, x1c = min(y1, h), min(x1, w)
        if y1c <= y0c or x1c <= x0c:
            continue
        wv = wgt[sy0:sy0 + (y1c - y0c), sx0:sx0 + (x1c - x0c)]
        img[y0c:y1c, x0c:x1c] += wv[:, :, None] * col[None, None, :]
    return (linear_to_srgb(img) * 255.0 + 0.5).astype(np.uint8)
