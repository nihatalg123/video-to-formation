"""Putting the screen and its lights into Skybrush Studio (DEVELOPMENT.md §6).

Written against the Skybrush Studio for Blender 4.1.1 source (``sbstudio``):

* ``sbstudio.plugin.model.formation.create_formation(name, points)`` — one marker
  (empty) per point, **in our order**, so marker k is screen drone k;
* ``scene.skybrush.storyboard.add_new_entry(...)`` — the screen in the storyboard;
* ``scene.skybrush.light_effects.append_new_entry(...)`` — the light effect:
  ``type = "FUNCTION"`` with ``color_function.path`` / ``.name`` (our generated
  ``vf_lights.py``), or ``type = "IMAGE"`` with Output X = Temporal and Output Y =
  Indexed by formation.

Every call is guarded: without Skybrush the add-on still builds a plain mesh of
the screen and writes the light file, and says what to do.
"""

from __future__ import annotations

import re

import bpy

FALLBACK_COLLECTION = "VideoFormation"


def available(context) -> bool:
    try:
        import sbstudio.plugin.model.formation  # noqa: F401
    except Exception:
        return False
    sb = getattr(context.scene, "skybrush", None)
    return sb is not None and hasattr(sb, "light_effects") and hasattr(sb, "storyboard")


def find_formation(*names: str):
    """The screen's formation: the first of ``names`` found under Formations, else
    one Blender renamed on creation ("Video Screen.001" when another collection was
    already called "Video Screen")."""
    formations = bpy.data.collections.get("Formations")
    if formations is None:
        return None
    for name in names:
        if name and formations.children.get(name) is not None:
            return formations.children.get(name)
    for name in names:
        if not name:
            continue
        pattern = re.compile(re.escape(name) + r"\.\d{3}$")
        renamed = sorted(c.name for c in formations.children if pattern.match(c.name))
        if renamed:
            return formations.children.get(renamed[-1])
    return None


def _marker_count(formation) -> int:
    try:
        from sbstudio.plugin.model.formation import count_markers_in_formation

        return int(count_markers_in_formation(formation))
    except Exception:
        return len(formation.objects)


def put_formation(name: str, positions, old=None) -> tuple[object, str]:
    """Create or update the screen's Skybrush formation (``old``, if it exists).
    Returns (collection, what happened). Same marker count: markers are moved in
    place, so storyboard entries and their drone mappings stay. Different count: the
    formation is rebuilt and storyboard entries that used it are pointed at the new
    one. The caller keeps ``collection.name``: Blender may have added ".001"."""
    from mathutils import Vector
    from sbstudio.plugin.model.formation import create_formation

    pts = [Vector((float(x), float(y), float(z))) for x, y, z in positions]
    if old is not None:
        markers = list(old.objects)
        same = (_marker_count(old) == len(pts) and len(markers) == len(pts)
                and all(getattr(m, "type", "") == "EMPTY" for m in markers))
        if same:
            for marker, p in zip(markers, pts):
                marker.location = p
            return old, "updated (markers moved in place)"
        name = old.name
    users = _entries_using(name)
    formation = create_formation(name, pts)
    for entry in users:
        try:
            entry.formation = formation
        except Exception:
            pass
    return formation, "created" if old is None else "rebuilt (drone count changed)"


def _entries_using(name: str) -> list:
    out = []
    for scene in bpy.data.scenes:
        sb = getattr(scene, "skybrush", None)
        storyboard = getattr(sb, "storyboard", None) if sb else None
        for entry in getattr(storyboard, "entries", ()) or ():
            f = getattr(entry, "formation", None)
            if f is not None and getattr(f, "name", None) == name:
                out.append(entry)
    return out


def entry_of(context, formation):
    """The storyboard entry that shows ``formation``, or None."""
    for entry in context.scene.skybrush.storyboard.entries:
        if entry.formation == formation:
            return entry
    return None


def add_storyboard_entry(context, formation, frame_start, duration: int):
    """Add the screen to the storyboard. ``frame_start`` None lets Skybrush place it
    after the last entry plus its default transition time (never on top of the
    takeoff)."""
    storyboard = context.scene.skybrush.storyboard
    entry = storyboard.add_new_entry(
        name=formation.name,
        frame_start=None if frame_start is None else int(frame_start),
        duration=int(duration),
        formation=formation,
        select=True,
        context=context,
    )
    if entry is None:
        entry = entry_of(context, formation)
    if entry is None:
        return None, "WARN could not add a storyboard entry; add the screen formation yourself"
    return entry, (f"Storyboard entry '{entry.name}' added at frame {int(entry.frame_start)} "
                   f"for {int(entry.duration)} frames")


def put_light_effect(context, name: str, frame_start: int, duration: int, *, mode: str,
                     script_path: str = "", function_name: str = "color_function", image=None):
    """Create or update the light effect ``name``."""
    effects = context.scene.skybrush.light_effects
    effect = None
    for e in effects.entries:
        if e.name == name:
            effect = e
            break
    if effect is None:
        effect = effects.append_new_entry(name, int(frame_start), int(duration), select=True,
                                          context=context)
        what = "created"
    else:
        what = "updated"
    effect.frame_start = int(frame_start)
    effect.duration = int(duration)
    effect.enabled = True
    effect.influence = 1.0
    # Temporal is one common value per frame: Skybrush skips the per-drone sorting a
    # gradient output would cost (it computes Output X even for Function effects)
    effect.output = "TEMPORAL"
    if mode == "IMAGE":
        effect.type = "IMAGE"
        effect.color_image = image
        effect.output_y = "INDEXED_BY_FORMATION"
        try:
            effect.invalidate_color_image()
        except Exception:
            pass
    else:
        effect.type = "FUNCTION"
        effect.color_function.path = script_path
        effect.color_function.name = function_name
    return effect, what


def fallback_mesh(name: str, positions, colors_linear=None):
    """Without Skybrush: a mesh with one vertex per screen drone (and the colours of
    one frame as a ``Col`` attribute), in our own collection."""
    import numpy as np

    coll = bpy.data.collections.get(FALLBACK_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(FALLBACK_COLLECTION)
        bpy.context.scene.collection.children.link(coll)
    obj = bpy.data.objects.get(name)
    if obj is not None and obj.type == "MESH":
        old_mesh = obj.data
        mesh = bpy.data.meshes.new(name)
        obj.data = old_mesh  # keep until the new one is filled
    else:
        mesh = bpy.data.meshes.new(name)
        obj = bpy.data.objects.new(name, mesh)
        coll.objects.link(obj)
        old_mesh = None
    p = np.asarray(positions, dtype=np.float32)
    mesh.vertices.add(p.shape[0])
    mesh.vertices.foreach_set("co", p.ravel())
    if colors_linear is not None:
        rgba = np.ones((p.shape[0], 4), dtype=np.float32)
        rgba[:, :3] = np.asarray(colors_linear, dtype=np.float32)
        attr = mesh.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="POINT")
        attr.data.foreach_set("color", rgba.ravel())
    mesh.update()
    obj.data = mesh
    if old_mesh is not None and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    return obj
