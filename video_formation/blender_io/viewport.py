"""The screen in the viewport, playing the video, right after Generate (DEVELOPMENT.md §6.4).

Skybrush only colours *drones*, and only once the transitions bring them to the
screen; until then the screen formation is a cloud of small empties and nothing
plays. So Generate also builds a preview object: one vertex per screen drone,
Geometry Nodes put a small sphere *instance* on each (no Realize: the GPU draws one
sphere many times), and an emission material reads each instance's colour
(``vf_color``, Attribute node type Instancer). A frame-change handler writes the
light table's colours for the current frame.

Kept cheap for playback (§6.6): nothing is done while the preview collection is
hidden, and nothing when the light frame did not change since the last update (15 fps
lights in a 30 fps scene change every other frame). Never exported. Hide the
collection "Video Formation Preview" once the drones themselves show the video.
"""

import os

import bpy
import numpy as np
from bpy.app.handlers import persistent

COLLECTION = "Video Formation Preview"
ATTR = "vf_color"
NODE_GROUP = "VF Preview Dots v2"
MATERIAL = "VF Preview Glow v2"
TABLE_PROP = "vf_light_table"

_tables: dict = {}
_last: dict = {}  # object name -> (table path, column) last written


def _table(path: str):
    from ..core import lighttable

    try:
        st = os.stat(path)
    except OSError:
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _tables.get(path)
    if hit is None or hit[0] != stamp:
        try:
            hit = (stamp, lighttable.load(path))
        except Exception:
            return None
        _tables[path] = hit
        for key in [k for k, v in _last.items() if v[0] == path]:
            del _last[key]
    return hit[1]


def _material() -> bpy.types.Material:
    mat = bpy.data.materials.get(MATERIAL)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(MATERIAL)
    mat.use_nodes = True
    mat.diffuse_color = (0.85, 0.85, 0.85, 1.0)
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_type = "INSTANCER"
    attr.attribute_name = ATTR
    emit.inputs["Strength"].default_value = 3.0
    nt.links.new(attr.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    out.location, emit.location, attr.location = (300, 0), (100, 0), (-150, 0)
    return mat


def _node_group(radius: float) -> bpy.types.NodeTree:
    ng = bpy.data.node_groups.get(NODE_GROUP)
    if ng is None:
        ng = bpy.data.node_groups.new(NODE_GROUP, "GeometryNodeTree")
        ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        n = ng.nodes
        gi = n.new("NodeGroupInput")
        go = n.new("NodeGroupOutput")
        ico = n.new("GeometryNodeMeshIcoSphere")
        ico.name = "VF Dot"
        setm = n.new("GeometryNodeSetMaterial")
        setm.name = "VF Material"
        iop = n.new("GeometryNodeInstanceOnPoints")
        ico.inputs["Subdivisions"].default_value = 1
        # material on the one sphere, then instance it: the point colours become
        # instance attributes, read by the material's Instancer attribute
        ng.links.new(ico.outputs["Mesh"], setm.inputs["Geometry"])
        ng.links.new(gi.outputs[0], iop.inputs["Points"])
        ng.links.new(setm.outputs["Geometry"], iop.inputs["Instance"])
        ng.links.new(iop.outputs["Instances"], go.inputs[0])
        for node, loc in ((gi, (-400, 0)), (ico, (-400, -200)), (setm, (-200, -200)),
                          (iop, (0, 0)), (go, (200, 0))):
            node.location = loc
    ng.nodes["VF Dot"].inputs["Radius"].default_value = float(radius)
    ng.nodes["VF Material"].inputs["Material"].default_value = _material()
    return ng


def _layer_collection(layer_coll, name):
    if layer_coll.name == name:
        return layer_coll
    for child in layer_coll.children:
        found = _layer_collection(child, name)
        if found is not None:
            return found
    return None


def preview_visible(context=None) -> bool:
    coll = bpy.data.collections.get(COLLECTION)
    if coll is None or coll.hide_viewport:
        return False
    try:
        ctx = context or bpy.context
        lc = _layer_collection(ctx.view_layer.layer_collection, COLLECTION)
    except Exception:
        return True
    return lc is None or not (lc.exclude or lc.hide_viewport)


def set_preview_visible(context, visible: bool) -> None:
    lc = _layer_collection(context.view_layer.layer_collection, COLLECTION)
    if lc is not None:
        lc.hide_viewport = not visible
        if visible:
            _last.clear()
            on_frame_change(context.scene)


def build(name: str, positions: np.ndarray, spacing: float, table_path: str, scene) -> bpy.types.Object:
    """Create or replace the preview object for screen ``name``."""
    coll = bpy.data.collections.get(COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(COLLECTION)
    if coll.name not in scene.collection.children:
        scene.collection.children.link(coll)
    obj_name = f"VF Preview: {name}"
    p = np.asarray(positions, dtype=np.float32)
    mesh = bpy.data.meshes.new(obj_name)
    mesh.vertices.add(p.shape[0])
    mesh.vertices.foreach_set("co", p.ravel())
    attr = mesh.color_attributes.new(name=ATTR, type="FLOAT_COLOR", domain="POINT")
    mesh.color_attributes.active_color = attr
    mesh.update()
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        obj = bpy.data.objects.new(obj_name, mesh)
        coll.objects.link(obj)
    else:
        old = obj.data
        obj.data = mesh
        if old is not None and old.users == 0:
            bpy.data.meshes.remove(old)
        if obj.name not in coll.objects:
            coll.objects.link(obj)
    mod = obj.modifiers.get("VF Dots") or obj.modifiers.new("VF Dots", "NODES")
    mod.node_group = _node_group(0.25 * float(spacing))
    obj[TABLE_PROP] = table_path
    obj.hide_select = True
    _last.pop(obj.name, None)
    update_object(obj, scene.frame_current)
    return obj


def update_object(obj, frame: int) -> bool:
    """Write the colours of ``frame``; False when nothing had to change."""
    path = obj.get(TABLE_PROP)
    mesh = obj.data
    if not path or mesh is None or ATTR not in mesh.attributes:
        return False
    table = _table(path)
    if table is None or table.n_drones != len(mesh.vertices):
        return False
    inside = table.start_frame <= frame < table.start_frame + table.scene_frames
    col = table.column(frame) if inside else -1
    key = (path, col)
    if _last.get(obj.name) == key:
        return False
    if inside:
        rgb = table.colors[col].astype(np.float32) * (1.0 / 255.0)
    else:
        rgb = np.zeros((table.n_drones, 3), dtype=np.float32)  # outside the video: dark
    rgba = np.ones((table.n_drones, 4), dtype=np.float32)
    rgba[:, :3] = rgb
    mesh.attributes[ATTR].data.foreach_set("color", rgba.ravel())
    mesh.update()
    _last[obj.name] = key
    return True


@persistent
def on_frame_change(scene, depsgraph=None):
    coll = bpy.data.collections.get(COLLECTION)
    if coll is None or not coll.objects or not preview_visible():
        return
    for obj in coll.objects:
        if obj.type == "MESH" and obj.get(TABLE_PROP):
            try:
                update_object(obj, scene.frame_current)
            except Exception as exc:  # never break playback
                print(f"[video_formation] preview: {exc}")


@persistent
def on_load(_dummy=None):
    _last.clear()


def register() -> None:
    if on_frame_change not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(on_frame_change)
    if on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load)


def unregister() -> None:
    while on_frame_change in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(on_frame_change)
    while on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load)
