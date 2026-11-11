"""The baked video: one colour per screen drone per light frame (DEVELOPMENT.md §4).

Pure numpy. Saved as one ``.npz`` (uncompressed, so loading is a memcpy):

* ``colors``    (F, N, 3) uint8, linear 0..255 — F light frames, N screen drones in
                marker order;
* ``positions`` (N, 3) float64, metres — where each marker was when baked;
* ``meta``      float64: start frame, scene fps, light fps, spacing, format version.

Two ways to hand it to Skybrush:

* **Function light effect** (default, light): Skybrush calls the generated
  ``vf_lights.py`` (``RUNTIME_SOURCE``) once per drone per frame. It keeps the
  table in memory once (3 bytes per drone per light frame — a 60 s, 30 fps,
  2000-drone video is 10.8 MB) and builds one list of colours per frame, so a
  frame costs about a millisecond on top of Skybrush's own work.
* **Image light effect** (no script): ``image_buffer`` lays the table out as an
  image, one column per *scene* frame and one row per marker, for Skybrush's
  native "Temporal" x "Indexed by formation" mapping. Skybrush keeps that image
  as Python floats (~32 bytes per channel), so it is the heavy option.
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass

import numpy as np

from .sampling import column_for_scene_frame, scene_frames_for

FORMAT_VERSION = 1
DATA_NAME = "vf_lights.npz"
SCRIPT_NAME = "vf_lights.py"
FUNCTION_NAME = "color_function"


@dataclass
class LightTable:
    colors: np.ndarray       # (F, N, 3) uint8
    positions: np.ndarray    # (N, 3) float64
    start_frame: int
    scene_fps: float
    light_fps: float
    spacing: float

    @property
    def n_light(self) -> int:
        return int(self.colors.shape[0])

    @property
    def n_drones(self) -> int:
        return int(self.colors.shape[1])

    @property
    def scene_frames(self) -> int:
        return scene_frames_for(self.n_light, self.light_fps, self.scene_fps)

    def validate(self) -> None:
        c = self.colors
        if c.ndim != 3 or c.shape[2] != 3 or c.dtype != np.uint8:
            raise ValueError(f"colors must be (F, N, 3) uint8, got {c.shape} {c.dtype}")
        if self.positions.shape != (c.shape[1], 3):
            raise ValueError(f"positions must be ({c.shape[1]}, 3), got {self.positions.shape}")
        if not (self.scene_fps > 0 and self.light_fps > 0 and self.spacing > 0):
            raise ValueError("fps and spacing must be positive")

    def column(self, frame: int) -> int:
        return int(column_for_scene_frame(int(frame) - self.start_frame, self.light_fps,
                                          self.scene_fps, self.n_light))


def save(table: LightTable, path: str) -> None:
    """Write atomically: a half-written file is never what Skybrush loads."""
    table.validate()
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    meta = np.array([table.start_frame, table.scene_fps, table.light_fps, table.spacing,
                     FORMAT_VERSION], dtype=np.float64)
    fd, tmp = tempfile.mkstemp(prefix=".vf_", suffix=".npz", dir=folder)
    os.close(fd)
    try:
        with open(tmp, "wb") as handle:
            np.savez(handle, colors=table.colors, positions=np.asarray(table.positions, np.float64),
                     meta=meta)
        _replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _replace(src: str, dst: str, tries: int = 5) -> None:
    """os.replace, retried briefly: on Windows a virus scanner or the indexer can
    hold the old file open for a moment."""
    for k in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if k == tries - 1:
                raise
            time.sleep(0.2 * (k + 1))


def load(path: str) -> LightTable:
    with np.load(path, allow_pickle=False) as z:
        meta = np.asarray(z["meta"], dtype=np.float64)
        table = LightTable(
            colors=np.ascontiguousarray(z["colors"]),
            positions=np.asarray(z["positions"], dtype=np.float64),
            start_frame=int(round(meta[0])),
            scene_fps=float(meta[1]),
            light_fps=float(meta[2]),
            spacing=float(meta[3]),
        )
    table.validate()
    return table


def image_buffer(table: LightTable) -> np.ndarray:
    """RGBA float32 buffer for a ``scene_frames`` x ``n_drones`` Blender image, in
    Blender's pixel order (row 0 at the bottom): row k = marker k, column d = scene
    frame start + d. Skybrush reads it with Output X = Temporal (column = frame
    offset exactly when width == duration) and Output Y = Indexed by formation
    (row = marker index exactly when height == marker count)."""
    d = table.scene_frames
    cols = column_for_scene_frame(np.arange(d), table.light_fps, table.scene_fps, table.n_light)
    rgb = table.colors[cols]                      # (D, N, 3)
    out = np.ones((table.n_drones, d, 4), dtype=np.float32)
    out[:, :, :3] = np.transpose(rgb, (1, 0, 2)).astype(np.float32) / 255.0
    return out.reshape(-1)


def write_runtime(folder: str, screen_name: str) -> str:
    """Write the light function file next to the table. Returns its path."""
    path = os.path.join(folder, SCRIPT_NAME)
    text = RUNTIME_SOURCE.replace("@SCREEN@", repr(str(screen_name))).replace("@DATA@", repr(DATA_NAME))
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


# The file Skybrush loads for a Function light effect. Skybrush 4.1.1 re-executes
# it once per frame (sbstudio.utils.load_module) and then calls color_function()
# once per drone, so: module level does almost nothing; the table lives in a cache
# that survives the re-execution (a module object in sys.modules); one list of
# colours is built per light frame.
RUNTIME_SOURCE = '''"""Video to Formation light file for screen @SCREEN@. Generated - do not edit.

Skybrush Studio calls color_function() once per drone per frame (a Function light
effect). The colours are in @DATA@ next to this file: one row per screen drone,
one column per light frame. Generate again from the Video Formation panel to
change them.
"""

import os
import sys

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), @DATA@)
_CACHE_KEY = "_video_formation_light_tables"
_CLEAR = (0.0, 0.0, 0.0, 0.0)


class _Table:
    def __init__(self, path, stamp):
        import numpy as np

        with np.load(path, allow_pickle=False) as z:
            self.colors = np.ascontiguousarray(z["colors"])
            self.pos = np.asarray(z["positions"], dtype=np.float64)
            meta = np.asarray(z["meta"], dtype=np.float64)
        self.stamp = stamp
        self.start = int(round(meta[0]))
        self.ratio = float(meta[2]) / float(meta[1])  # light fps / scene fps
        self.spacing = float(meta[3])
        self.n_light = int(self.colors.shape[0])
        self.n = int(self.colors.shape[1])
        self.col = None
        self.rows = None
        cell = self.spacing
        self.cell = cell
        self.x0 = float(self.pos[:, 0].min()) if self.n else 0.0
        self.z0 = float(self.pos[:, 2].min()) if self.n else 0.0
        self.y = float(self.pos[:, 1].mean()) if self.n else 0.0
        buckets = {}
        xs = ((self.pos[:, 0] - self.x0) / cell).round().astype(int).tolist()
        zs = ((self.pos[:, 2] - self.z0) / cell).round().astype(int).tolist()
        for k, key in enumerate(zip(xs, zs)):
            buckets.setdefault(key, []).append(k)
        self.buckets = buckets
        self.px = self.pos[:, 0].tolist()
        self.py = self.pos[:, 1].tolist()
        self.pz = self.pos[:, 2].tolist()
        self.near2 = (0.5 * cell) ** 2
        self.snap2 = (0.75 * cell) ** 2

    def rows_for(self, frame):
        col = int((frame - self.start) * self.ratio + 1e-6)
        if col < 0:
            col = 0
        elif col >= self.n_light:
            col = self.n_light - 1
        if col != self.col:
            rgb = (self.colors[col] * (1.0 / 255.0)).tolist()
            self.rows = [(r, g, b, 1.0) for r, g, b in rgb]
            self.col = col
        return self.rows

    def dist2(self, k, position):
        dx = position[0] - self.px[k]
        dy = position[1] - self.py[k]
        dz = position[2] - self.pz[k]
        return dx * dx + dy * dy + dz * dz

    def nearest(self, position):
        ix = int(round((position[0] - self.x0) / self.cell))
        iz = int(round((position[2] - self.z0) / self.cell))
        best, best_d = -1, self.snap2
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for k in self.buckets.get((ix + dx, iz + dz), ()):
                    d = self.dist2(k, position)
                    if d <= best_d:
                        best, best_d = k, d
        return best


def _table():
    cache = sys.modules.get(_CACHE_KEY)
    if cache is None:
        import types

        cache = types.ModuleType(_CACHE_KEY)
        cache.tables = {}
        sys.modules[_CACHE_KEY] = cache
    try:
        st = os.stat(_DATA)
    except OSError:
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    table = cache.tables.get(_DATA)
    if table is None or table.stamp != stamp:
        table = _Table(_DATA, stamp)
        cache.tables[_DATA] = table
    return table


_T = _table()


def color_function(frame, time_fraction, drone_index, formation_index, position, drone_count):
    t = _T
    if t is None or t.n == 0:
        return _CLEAR
    rows = t.rows_for(frame)
    k = formation_index
    if k is not None and 0 <= k < t.n and t.dist2(k, position) <= t.near2:
        return rows[k]
    j = t.nearest(position)
    if j >= 0:
        return rows[j]
    if k is not None and 0 <= k < t.n:
        # the screen was moved after it was generated: trust the marker index
        return rows[k]
    return _CLEAR
'''
