"""Scrolling text on a drone screen (DEVELOPMENT.md §6.9).

Pure numpy. The text is drawn once as a *strip*: a (rows, W) array of how lit each
drone-sized cell is (0..1), one column per drone column. The screen is a grid
exactly as tall as the strip (plus optional empty margin rows) and as wide as the
drone count allows, so the text fills the screen's height. The strip then slides
from right to left: it enters at the right edge, crosses the screen and leaves on
the left, once or several times.

Letters (``style``):

* ``LED``   — the 5 x 7 dot-matrix font of ``ledfont``, scaled by whole numbers
  (7, 14, 21 ... rows): crisp, readable from 7 drones high.
* ``BLOCK`` — the 5-row blocky capitals of ``ledfont`` (10, 15, 20 ... rows).
* ``FONT``  — any font, rendered smooth (anti-aliased) at the screen's height. The
  outline comes from Blender (``blender_io.textfont``); here it arrives as a
  strip-making function ``render_font(text, rows) -> (rows, W) array``.

Screen (``layout``):

* ``BANNER`` — wide: the tallest text that still shows about ``MIN_VISIBLE``
  letters at once. For sentences.
* ``BIG``    — about square: the letters as big as the screen, one or two at a
  time. For short words on few drones (100 drones: 10 x 10 with BLOCK).

Speed: letters per second, or automatic (``speed`` 0): 2 letters/s on a wide banner,
slower when only a letter or two fit (each letter then stays about 3 s on screen).
"""

from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import layout, ledfont, sampling

STYLES = ("LED", "BLOCK", "FONT")
LAYOUTS = ("BANNER", "BIG")
COLOUR_MODES = ("SOLID", "RAINBOW")
#: Letters on screen at once that the BANNER size aims for.
MIN_VISIBLE = 4.5
#: The lowest smooth-font text; below it the dot fonts read better.
MIN_FONT_ROWS = 7
MAX_SCALE = 12


@dataclass
class TextJob:
    text: str = "VIDEO TO FORMATION"
    style: str = "LED"           # LED | BLOCK | FONT
    layout: str = "BANNER"       # BANNER | BIG
    height: int = 0              # text rows; 0 = automatic
    margin: int = 0              # empty rows above and below the text
    speed: float = 0.0           # letters per second; 0 = automatic
    loops: int = 1               # passes across the screen
    gap: float = 3.0             # empty space between passes, in letters
    smooth: bool = True          # move by fractions of a column (else whole columns)
    colour_mode: str = "SOLID"   # SOLID | RAINBOW
    colour: tuple = (1.0, 1.0, 1.0)      # text, linear RGB
    background: tuple = (0.0, 0.0, 0.0)  # the rest of the screen, linear RGB


@dataclass
class TextPlan:
    """Everything the bake needs, decided before anything is drawn."""

    rows: int                 # screen rows (text + margins)
    cols: int                 # screen columns
    text_rows: int
    margin: int
    scale: int                # dot fonts: a font dot is scale x scale drones (FONT: 1)
    strip: np.ndarray         # (text_rows, W) one pass of the text, 0..1
    advance: float            # columns per letter, on average
    speed_cols: float         # columns per second
    loop_strip: np.ndarray    # (text_rows, W_all) all passes with their gaps
    duration: float           # seconds from entering on the right to gone on the left
    info: dict = field(default_factory=dict)

    @property
    def count(self) -> int:
        return self.rows * self.cols

    @property
    def visible_letters(self) -> float:
        return self.cols / max(self.advance, 1e-6)

    @property
    def letters_per_second(self) -> float:
        return self.speed_cols / max(self.advance, 1e-6)


def clean(text: str) -> str:
    return ledfont.clean_text(text).strip()


def letters_per_second(speed: float, visible: float) -> float:
    """``speed`` when given; automatic: 2 letters/s, slower when few letters fit
    (a letter then stays about 3 s on screen, entering to leaving)."""
    if speed and speed > 0:
        return float(speed)
    return min(2.0, (visible + 1.0) / 3.0)


def dot_scale(n_drones: int, font: str, advance: float, margin: int, layout_: str,
              height: int = 0, widest: int = 5) -> int:
    """How many drones a font dot is (k x k). ``height`` given: the nearest whole
    multiple of the font's rows. BANNER: the largest that keeps ``MIN_VISIBLE``
    letters on screen. BIG: the largest whose screen is still at least as wide as
    high (and fits the widest letter)."""
    base = ledfont.font_rows(font)
    if height and height > 0:
        return max(1, int(round(height / base)))
    best = 1
    for k in range(1, MAX_SCALE + 1):
        rows = base * k + 2 * margin
        cols = n_drones // rows
        if cols < 1:
            break
        if str(layout_).upper() == "BIG":
            ok = cols >= rows and cols >= widest * k
        else:
            ok = cols / (advance * k) >= MIN_VISIBLE
        if ok:
            best = k
    return best


def font_rows(n_drones: int, advance_per_row: float, margin: int, layout_: str,
              height: int = 0) -> int:
    """Smooth font: the text height in rows (manual; BANNER: the tallest that keeps
    ``MIN_VISIBLE`` letters visible; BIG: about square). At least ``MIN_FONT_ROWS``."""
    if height and height > 0:
        return int(height)
    if str(layout_).upper() == "BIG":
        h = int(math.floor(math.sqrt(n_drones))) - 2 * margin
        return max(MIN_FONT_ROWS, h)
    a = max(float(advance_per_row), 0.05)
    h = int(math.floor(math.sqrt(n_drones / (MIN_VISIBLE * a))))
    while h > MIN_FONT_ROWS and n_drones // (h + 2 * margin) / (a * h) < MIN_VISIBLE:
        h -= 1
    return max(MIN_FONT_ROWS, h)


def plan(job: TextJob, n_drones: int,
         render_font: Callable[[str, int], np.ndarray] | None = None) -> TextPlan:
    text = clean(job.text)
    if not text:
        raise ValueError("Type the text to show first.")
    n_drones = int(n_drones)
    margin = max(0, int(job.margin))
    style = str(job.style).upper()
    style = style if style in STYLES else "LED"
    lay = str(job.layout).upper()
    letters = max(1, len(text))
    if style == "FONT":
        if render_font is None:
            raise ValueError("The Font letters need Blender's font engine.")
        probe = np.asarray(render_font(text, 40), dtype=np.float32)
        per_row = probe.shape[1] / 40.0 / letters
        text_rows = font_rows(n_drones, per_row, margin, lay, int(job.height))
        strip = np.asarray(render_font(text, text_rows), dtype=np.float32)
        scale = 1
        advance = strip.shape[1] / letters
        unknown = []
    else:
        base = ledfont.render(text, style)
        adv1 = (base.shape[1] + ledfont.GAP) / letters
        scale = dot_scale(n_drones, style, adv1, margin, lay, int(job.height), ledfont.widest(style))
        strip = np.kron(base, np.ones((scale, scale), dtype=np.float32))
        text_rows = strip.shape[0]
        advance = adv1 * scale
        unknown = ledfont.unknown_chars(text, style)
    rows = text_rows + 2 * margin
    if rows > n_drones:
        raise ValueError(
            f"The text needs {rows} rows but there are only {n_drones} drones. "
            "Raise the Drone Count or lower the Text Height."
        )
    cols = n_drones // rows
    speed_cols = letters_per_second(float(job.speed), cols / advance) * advance
    loops = max(1, int(job.loops))
    gap_cols = int(round(max(float(job.gap), 0.0) * advance))
    pieces = []
    for i in range(loops):
        if i:
            pieces.append(np.zeros((text_rows, gap_cols), dtype=np.float32))
        pieces.append(strip)
    loop_strip = np.concatenate(pieces, axis=1)
    duration = (cols + loop_strip.shape[1]) / speed_cols
    info = {"style": style, "layout": lay, "letters": letters, "unknown": unknown}
    return TextPlan(rows, cols, text_rows, margin, scale, strip, advance, speed_cols,
                    loop_strip, duration, info)


def make_screen(tp: TextPlan, *, spacing: float | None = None, width_m: float | None = None,
                centre_x: float = 0.0, depth_y: float = 0.0, bottom_z: float = 0.0) -> layout.Screen:
    if spacing is None:
        if width_m is None or not width_m > 0:
            raise ValueError("Give the drone spacing or the screen width.")
        spacing = float(width_m) / max(tp.cols - 1, 1)
    if not spacing > 0:
        raise ValueError("Spacing must be greater than zero.")
    scr = layout.grid_from_dims(tp.cols, tp.rows, float(spacing), centre_x=centre_x,
                                depth_y=depth_y, bottom_z=bottom_z)
    scr.shape = "GRID"
    scr.info.update({"text_rows": tp.text_rows, "scale": tp.scale})
    return scr


def light_times(tp: TextPlan, light_fps: float) -> np.ndarray:
    """From the moment the text starts entering until it has fully left."""
    n = int(math.floor(tp.duration * float(light_fps) + 1e-6)) + 1
    return np.arange(max(n, 2)) / float(light_fps)


def coverage(tp: TextPlan, t: float, smooth: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """(alpha (rows, cols) 0..1, strip x of each screen column) at ``t`` seconds."""
    offset = tp.cols - tp.speed_cols * float(t)  # where strip column 0 is on the screen
    if not smooth:
        offset = float(np.round(offset))
    x = np.arange(tp.cols, dtype=np.float64) - offset
    s = tp.loop_strip
    w = s.shape[1]
    x0 = np.floor(x).astype(np.int64)
    fx = (x - x0).astype(np.float32)
    padded = np.zeros((s.shape[0], w + 2), dtype=np.float32)
    padded[:, 1:w + 1] = s
    i0 = np.clip(x0 + 1, 0, w + 1)
    i1 = np.clip(x0 + 2, 0, w + 1)
    a = padded[:, i0] * (1.0 - fx) + padded[:, i1] * fx
    alpha = np.zeros((tp.rows, tp.cols), dtype=np.float32)
    alpha[tp.margin:tp.margin + tp.text_rows, :] = a
    return alpha, x


def _rainbow(x: np.ndarray, period: float) -> np.ndarray:
    """Linear RGB along the text: a full spectrum every ``period`` strip columns."""
    hue = np.mod(x / max(period, 1.0), 1.0)
    rgb = np.array([colorsys.hsv_to_rgb(float(h), 1.0, 1.0) for h in np.round(hue, 3)])
    return np.power(rgb, 2.2)


def frame_colors(tp: TextPlan, job: TextJob, t: float, grade: sampling.Grade | None = None) -> np.ndarray:
    """(N, 3) linear 0..1, drones in screen order (row by row, top row first)."""
    alpha, x = coverage(tp, t, bool(job.smooth))
    bg = np.asarray(job.background, dtype=np.float64)[:3]
    if str(job.colour_mode).upper() == "RAINBOW":
        fg = np.broadcast_to(_rainbow(x, tp.cols * 1.2)[None, :, :], (tp.rows, tp.cols, 3))
    else:
        fg = np.broadcast_to(np.asarray(job.colour, dtype=np.float64)[:3], (tp.rows, tp.cols, 3))
    a = alpha[..., None].astype(np.float64)
    c = (bg * (1.0 - a) + fg * a).reshape(-1, 3)
    if grade is not None:
        c = sampling.grade(c, grade)
    return np.clip(c, 0.0, 1.0)


def bake(tp: TextPlan, job: TextJob, times: np.ndarray, grade: sampling.Grade,
         progress: Callable[[int, int], None] | None = None) -> np.ndarray:
    """(F, N, 3) uint8 linear colours, one row per light frame."""
    n = len(times)
    out = np.empty((n, tp.count, 3), dtype=np.uint8)
    for i, t in enumerate(times):
        out[i] = sampling.to_u8(frame_colors(tp, job, float(t), grade))
        if progress is not None and (i % 25 == 0 or i == n - 1):
            progress(i + 1, n)
    return out


def rasterize_triangles(tris: np.ndarray, rows: int, ss: int = 6) -> np.ndarray:
    """Filled triangles (T, 3, 2) of a text outline, Y up, any units -> a (rows, W)
    strip: the text's ink from its lowest to its highest point spans ``rows``
    cells, each cell is how much of it is covered (``ss`` x ``ss`` samples),
    lightly sharpened so thin strokes still light their drone."""
    t = np.asarray(tris, dtype=np.float64).reshape(-1, 3, 2)
    rows = max(1, int(rows))
    if t.shape[0] == 0:
        return np.zeros((rows, 0), dtype=np.float32)
    x_min, y_min = t[..., 0].min(), t[..., 1].min()
    x_max, y_max = t[..., 0].max(), t[..., 1].max()
    scale = rows / max(y_max - y_min, 1e-9)       # cells per unit
    width = max(1, int(math.ceil((x_max - x_min) * scale - 1e-6)))
    hs, ws = rows * ss, width * ss
    # sample space: x right, y down, one unit = one sample
    px = (t[..., 0] - x_min) * scale * ss
    py = (y_max - t[..., 1]) * scale * ss
    mask = np.zeros((hs, ws), dtype=bool)
    for (ax, bx, cx), (ay, by, cy) in zip(px, py):
        x0 = max(int(math.floor(min(ax, bx, cx))), 0)
        x1 = min(int(math.ceil(max(ax, bx, cx))), ws)
        y0 = max(int(math.floor(min(ay, by, cy))), 0)
        y1 = min(int(math.ceil(max(ay, by, cy))), hs)
        if x1 <= x0 or y1 <= y0:
            continue
        gx = np.arange(x0, x1) + 0.5
        gy = (np.arange(y0, y1) + 0.5)[:, None]
        e0 = (bx - ax) * (gy - ay) - (by - ay) * (gx - ax)
        e1 = (cx - bx) * (gy - by) - (cy - by) * (gx - bx)
        e2 = (ax - cx) * (gy - cy) - (ay - cy) * (gx - cx)
        inside = ((e0 >= 0) & (e1 >= 0) & (e2 >= 0)) | ((e0 <= 0) & (e1 <= 0) & (e2 <= 0))
        mask[y0:y1, x0:x1] |= inside
    cov = mask.reshape(rows, ss, width, ss).mean(axis=(1, 3))
    sharp = np.clip((cov - 0.12) / 0.55, 0.0, 1.0)
    return (sharp * sharp * (3.0 - 2.0 * sharp)).astype(np.float32)


def describe(tp: TextPlan) -> str:
    style = tp.info.get("style", "LED")
    name = {"LED": "LED letters", "BLOCK": "Block letters", "FONT": "font"}.get(style, style)
    if style != "FONT" and tp.scale > 1:
        name += f", each dot {tp.scale}x{tp.scale} drones"
    return (f"screen {tp.cols} x {tp.rows} = {tp.count} drones, text {tp.text_rows} rows high "
            f"({name}), about {tp.visible_letters:.1f} letters visible, "
            f"{tp.letters_per_second:.2f} letters/s, {tp.duration:.1f} s")
