"""Smooth letters for the Text source: Blender's own font engine draws the outline.

A temporary text object (any font Blender can load: .ttf, .otf, or the built-in
one) is evaluated to a filled mesh; its triangles are handed to
``textscreen.rasterize_triangles``, which turns them into drone-sized cells. The
temporary object, curve and (when nothing else uses it) the loaded font are removed
again.

Three fonts come with the add-on (``fonts/``, DejaVu, see LICENSE_DEJAVU.txt):
Sans, Serif and Mono, all bold.
"""

from __future__ import annotations

import os

import bpy
import numpy as np

from ..core import textscreen

_TMP = "VF Text (temporary)"
_cache: dict = {}

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
#: Letters choice -> font file that comes with the add-on.
BUNDLED = {
    "SANS": "DejaVuSans-Bold.ttf",
    "SERIF": "DejaVuSerif-Bold.ttf",
    "MONO": "DejaVuSansMono-Bold.ttf",
}


def font_path_for(style: str, custom: str = "") -> str:
    """The font file for a Letters choice ("" = Blender's built-in font)."""
    style = str(style).upper()
    if style in BUNDLED:
        path = os.path.join(FONT_DIR, BUNDLED[style])
        if not os.path.isfile(path):
            raise ValueError(f"The add-on's font {BUNDLED[style]} is missing; reinstall Video to Formation.")
        return path
    return custom or ""


def _font(path: str):
    if not path:
        return None
    full = os.path.normpath(bpy.path.abspath(path))
    if not os.path.isfile(full):
        raise ValueError(f"Font file not found: {full}")
    try:
        return bpy.data.fonts.load(full, check_existing=True)
    except (RuntimeError, OSError) as exc:
        raise ValueError(f"Blender cannot read the font {os.path.basename(full)}: {exc}") from exc


def triangles(text: str, font_path: str = "", scene=None) -> np.ndarray:
    """(T, 3, 2) filled triangles of ``text`` (one line, size 1, Y up)."""
    key = (text, font_path)
    if key in _cache:
        return _cache[key]
    scene = scene or bpy.context.scene
    font = _font(font_path)
    curve = bpy.data.curves.new(_TMP, type="FONT")
    obj = None
    try:
        curve.body = text
        if font is not None:
            curve.font = font
        curve.size = 1.0
        curve.resolution_u = 8
        obj = bpy.data.objects.new(_TMP, curve)
        scene.collection.objects.link(obj)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        ev = obj.evaluated_get(depsgraph)
        mesh = ev.to_mesh()
        try:
            if hasattr(mesh, "calc_loop_triangles"):
                mesh.calc_loop_triangles()
            n_v, n_t = len(mesh.vertices), len(mesh.loop_triangles)
            co = np.empty(n_v * 3, dtype=np.float64)
            mesh.vertices.foreach_get("co", co)
            idx = np.empty(n_t * 3, dtype=np.int64)
            mesh.loop_triangles.foreach_get("vertices", idx)
        finally:
            ev.to_mesh_clear()
    finally:
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.curves.remove(curve)
        if font is not None and getattr(font, "users", 1) == 0:
            bpy.data.fonts.remove(font)
    tris = co.reshape(-1, 3)[idx.reshape(-1, 3)][:, :, :2]
    if tris.shape[0] == 0:
        name = os.path.basename(font_path) if font_path else "Blender's built-in font"
        raise ValueError(f"{name} drew nothing for this text (letters it does not have?).")
    if len(_cache) > 8:
        _cache.clear()
    _cache[key] = tris
    return tris


def renderer(font_path: str = "", scene=None):
    """``render_font(text, rows) -> (rows, W)`` for ``textscreen.plan``."""
    def render_font(text: str, rows: int) -> np.ndarray:
        return textscreen.rasterize_triangles(triangles(text, font_path, scene), rows)
    return render_font
