"""The screen: a fixed drone layout the video is played on (DEVELOPMENT.md §2).

Pure numpy, no bpy, so it can be tested outside Blender.

Two shapes, as in the user's two example videos:

* ``GRID``  — rows and columns, a rectangular screen with the video's aspect ratio
  (or one the user chooses). Every drone owns one square cell of the picture.
* ``RINGS`` — concentric circles around a centre drone, a round screen. Ring *k*
  has radius *k* x spacing and as many drones as fit with neighbours at least one
  spacing apart along the ring (chord >= spacing), so the spacing rule holds
  everywhere, not just between rings.

Both pick the drone count closest to the requested one **without going over** it
(the formation keeps its own count; nothing is parked). Rows/columns and rings are
never trimmed or nudged, so the screen is always a clean shape.

Coordinates follow Image to Formation: X to the right, Y depth (0 = the screen
plane), Z up; the picture reads correctly from the front (-Y). Each drone also
gets its cell in *screen UV* (u to the right, v downwards, both 0..1 across the
screen) — that is what the video is sampled with.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

SHAPES = ("GRID", "RINGS")


@dataclass
class Screen:
    """A finished layout. ``positions`` (N, 3) metres; ``uv`` (N, 2) cell centres;
    ``cell_uv`` (2,) the size of one drone's cell in UV (u, v)."""

    shape: str
    positions: np.ndarray
    uv: np.ndarray
    cell_uv: np.ndarray
    spacing: float
    width_m: float
    height_m: float
    aspect: float  # screen width / height (1.0 for rings)
    info: dict = field(default_factory=dict)

    @property
    def count(self) -> int:
        return int(self.positions.shape[0])


# --------------------------------------------------------------------- grid


def grid_dims(target: int, aspect: float) -> tuple[int, int]:
    """(columns, rows) with columns x rows <= target, columns / rows ~ aspect,
    and the most drones. A cell is square, so a C x R grid has aspect C / R."""
    target = max(1, int(target))
    aspect = float(aspect) if aspect and math.isfinite(aspect) and aspect > 0 else 1.0
    best = (1, 1)
    best_key = None
    r0 = math.sqrt(target / aspect)
    for rows in range(max(1, int(r0) - 6), int(r0) + 8):
        base = aspect * rows
        for cols in {max(1, int(math.floor(base))), max(1, int(math.ceil(base))), max(1, int(round(base)))}:
            if cols * rows > target:
                cols = target // rows
            if cols < 1:
                continue
            err = abs(math.log((cols / rows) / aspect))
            # most drones first; an aspect error over 3 % costs more than 3 % drones
            key = (cols * rows * (1.0 - max(0.0, err - 0.03)), -err)
            if best_key is None or key > best_key:
                best_key, best = key, (cols, rows)
    return best


def make_grid(target: int, aspect: float, spacing: float, *, centre_x: float = 0.0,
              depth_y: float = 0.0, bottom_z: float = 0.0) -> Screen:
    cols, rows = grid_dims(target, aspect)
    p = float(spacing)
    c = np.arange(cols, dtype=np.float64)
    r = np.arange(rows, dtype=np.float64)
    rr, cc = np.meshgrid(r, c, indexing="ij")  # row-major: top row first
    cc = cc.ravel()
    rr = rr.ravel()
    pos = np.empty((cc.size, 3), dtype=np.float64)
    pos[:, 0] = centre_x + (cc - (cols - 1) / 2.0) * p
    pos[:, 1] = depth_y
    pos[:, 2] = bottom_z + (rows - 1 - rr) * p
    uv = np.stack([(cc + 0.5) / cols, (rr + 0.5) / rows], axis=1)
    return Screen(
        shape="GRID",
        positions=pos,
        uv=uv,
        cell_uv=np.array([1.0 / cols, 1.0 / rows]),
        spacing=p,
        width_m=(cols - 1) * p,
        height_m=(rows - 1) * p,
        aspect=cols / rows,
        info={"columns": cols, "rows": rows},
    )


# -------------------------------------------------------------------- rings


def ring_size(k: int) -> int:
    """Drones on ring k (radius k x spacing) so neighbours are >= one spacing apart:
    the chord 2 k sin(pi / n) must be >= 1, i.e. n <= pi / asin(1 / 2k)."""
    if k <= 0:
        return 1
    return max(1, int(math.floor(math.pi / math.asin(1.0 / (2.0 * k)) + 1e-9)))


#: The drones left over after the last full ring form one more, sparser ring when
#: they are at least this share of a full one (spacing along it <= 1.33 x).
PARTIAL_RING = 0.75


def ring_counts(target: int) -> list[int]:
    """Drones on rings 1..K: full rings while they fit under ``target``, then the
    rest as one more evenly spread ring if it is at least ``PARTIAL_RING`` of a full
    ring (still a perfect circle, just a little sparser)."""
    total, counts = 1, []
    target = max(1, int(target))
    while True:
        nxt = ring_size(len(counts) + 1)
        if total + nxt > target:
            rest = target - total
            if rest >= PARTIAL_RING * nxt and rest >= 3:
                counts.append(rest)
            return counts
        counts.append(nxt)
        total += nxt


def rings_for(target: int) -> int:
    """Number of rings beyond the centre drone."""
    return len(ring_counts(target))


def make_rings(target: int, spacing: float, *, centre_x: float = 0.0, depth_y: float = 0.0,
               bottom_z: float = 0.0) -> Screen:
    counts = ring_counts(target)
    rings = len(counts)
    p = float(spacing)
    xs, zs = [0.0], [0.0]
    for k, n in enumerate(counts, start=1):
        # alternate rings start half a step round, so no radial seam lines up
        phase = (0.5 * (k % 2)) * (2.0 * math.pi / n) + math.pi / 2.0
        a = phase + np.arange(n) * (2.0 * math.pi / n)
        xs.extend((k * p * np.cos(a)).tolist())
        zs.extend((k * p * np.sin(a)).tolist())
    xs = np.asarray(xs)
    zs = np.asarray(zs)
    radius = rings * p
    half = radius + 0.5 * p  # the screen square includes the outer drones' cells
    pos = np.empty((xs.size, 3), dtype=np.float64)
    pos[:, 0] = centre_x + xs
    pos[:, 1] = depth_y
    pos[:, 2] = bottom_z + radius + zs
    uv = np.stack([0.5 + xs / (2.0 * half), 0.5 - zs / (2.0 * half)], axis=1)
    cell = p / (2.0 * half)
    return Screen(
        shape="RINGS",
        positions=pos,
        uv=uv,
        cell_uv=np.array([cell, cell]),
        spacing=p,
        width_m=2.0 * radius,
        height_m=2.0 * radius,
        aspect=1.0,
        info={"rings": rings, "outer_ring": counts[-1] if counts else 0,
              "outer_full": ring_size(rings) if rings else 0},
    )


# ------------------------------------------------------------------ public


def make_screen(shape: str, target: int, *, aspect: float = 16 / 9, spacing: float | None = None,
                width_m: float | None = None, centre_x: float = 0.0, depth_y: float = 0.0,
                bottom_z: float = 0.0) -> Screen:
    """Build the screen. Give either ``spacing`` (metres between neighbours) or
    ``width_m`` (the screen's width; the spacing follows from it)."""
    shape = str(shape).upper()
    if shape not in SHAPES:
        raise ValueError(f"Screen shape must be one of {', '.join(SHAPES)}, got {shape!r}.")
    if int(target) < 1:
        raise ValueError("Drone Count must be at least 1.")
    if spacing is None:
        if width_m is None or not width_m > 0:
            raise ValueError("Give the drone spacing or the screen width.")
        if shape == "GRID":
            cols, _rows = grid_dims(target, aspect)
            spacing = float(width_m) / max(cols - 1, 1)
        else:
            spacing = float(width_m) / max(2 * rings_for(target), 1)
    if not spacing > 0:
        raise ValueError("Spacing must be greater than zero.")
    kw = dict(centre_x=centre_x, depth_y=depth_y, bottom_z=bottom_z)
    if shape == "GRID":
        return make_grid(target, aspect, spacing, **kw)
    return make_rings(target, spacing, **kw)


def min_distance(points: np.ndarray) -> float:
    """Closest pair, exact (cell hashing). For checks and tests."""
    p = np.asarray(points, dtype=np.float64)
    if p.shape[0] < 2:
        return float("inf")
    xz = p[:, [0, 2]] if p.shape[1] == 3 else p
    span = np.ptp(xz, axis=0).max()
    cell = max(span / max(math.sqrt(p.shape[0]), 1.0), 1e-9)
    keys = np.floor((xz - xz.min(axis=0)) / cell).astype(np.int64)
    buckets: dict[tuple[int, int], list[int]] = {}
    for i, (a, b) in enumerate(keys.tolist()):
        buckets.setdefault((a, b), []).append(i)
    best = float("inf")
    for (a, b), idx in buckets.items():
        cand = []
        for da in (-1, 0, 1):
            for db in (-1, 0, 1):
                cand.extend(buckets.get((a + da, b + db), ()))
        cand = np.asarray(cand)
        mine = np.asarray(idx)
        d = np.hypot(xz[mine, None, 0] - xz[None, cand, 0], xz[mine, None, 1] - xz[None, cand, 1])
        d[mine[:, None] == cand[None, :]] = np.inf
        best = min(best, float(d.min()))
    return best
