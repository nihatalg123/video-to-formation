"""Run Generate Screen / Update Lights end to end against a fake bpy and a fake Skybrush.

    python3 tools/tests/test_operator_mock.py      (needs FFmpeg)

The fakes follow the Skybrush Studio 4.1.1 signatures the add-on calls
(create_formation, storyboard.add_new_entry with its automatic placement,
light_effects.append_new_entry with context=..., effect.color_function.path/name)
so the operator's own code paths run: decode, bake, formation, storyboard, start
frame, light file, effect, viewport preview colours, scene end frame. It does not
prove Blender or Skybrush behave like the fakes — test_blender.py does that.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import types

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILS.append(name)


# ------------------------------------------------------------------ fake bpy


class Bag(types.SimpleNamespace):
    pass


class IDColl(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)

    def remove(self, item):
        for k, v in list(self.items()):
            if v is item:
                del self[k]


class FakeColl:
    def __init__(self, name):
        self.name = name
        self.objects = []
        self.children = IDColl()


class Vec(tuple):
    pass


class FakeObj:
    def __init__(self, name, location):
        self.name = name
        self.type = "EMPTY"
        self.location = Vec(location)

    @property
    def matrix_world(self):
        return types.SimpleNamespace(translation=self.location)


class FakeMeshData:
    def __init__(self):
        self.vertices = []


bpy = types.ModuleType("bpy")
props = types.ModuleType("bpy.props")
btypes = types.ModuleType("bpy.types")
utils = types.ModuleType("bpy.utils")
for n in ["BoolProperty", "EnumProperty", "FloatProperty", "IntProperty", "StringProperty",
          "PointerProperty", "CollectionProperty"]:
    setattr(props, n, (lambda name: (lambda **k: ("PROP", name, k)))(n))


class Base:
    pass


for n in ["PropertyGroup", "Panel", "Operator", "Object", "Scene", "Mesh", "Image", "Collection",
          "Material", "NodeTree"]:
    setattr(btypes, n, type(n, (Base,), {}))
utils.register_class = lambda c: None
utils.unregister_class = lambda c: None
BLEND = {"path": ""}
EXT_DIR = tempfile.mkdtemp(prefix="vf_ext_")


def _extension_path_user(pkg, path="", create=False):
    p = os.path.join(EXT_DIR, path)
    os.makedirs(p, exist_ok=True)
    return p


utils.extension_path_user = _extension_path_user


def _abspath(p):
    if p.startswith("//"):
        return os.path.join(os.path.dirname(BLEND["path"]), p[2:])
    return p


def _relpath(p):
    return "//" + os.path.relpath(p, os.path.dirname(BLEND["path"]))


bpy.path = types.SimpleNamespace(abspath=_abspath, relpath=_relpath)
collections = IDColl()
bpy.data = Bag(collections=collections, images=IDColl())
type(bpy.data).filepath = property(lambda self: BLEND["path"])
handlers = types.SimpleNamespace(persistent=lambda f: f, frame_change_post=[], load_post=[])
bpy.app = types.SimpleNamespace(handlers=handlers)
bpy.props, bpy.types, bpy.utils = props, btypes, utils
extras = types.ModuleType("bpy_extras")
io_utils = types.ModuleType("bpy_extras.io_utils")
io_utils.ExportHelper = type("ExportHelper", (), {})
extras.io_utils = io_utils
mathutils = types.ModuleType("mathutils")
mathutils.Vector = lambda t: Vec(t)
sys.modules.update({"bpy": bpy, "bpy.props": props, "bpy.types": btypes, "bpy.utils": utils,
                    "bpy.app": bpy.app, "bpy.app.handlers": handlers, "bpy_extras": extras,
                    "bpy_extras.io_utils": io_utils, "mathutils": mathutils})

# ------------------------------------------------------------- fake Skybrush


def create_formation(name, points):
    formations = collections.setdefault("Formations", FakeColl("Formations"))
    old = formations.children.get(name)
    if old is not None:
        del formations.children[name]
    # Blender: a name taken by any other collection gets ".001", ".002", ...
    final, k = name, 0
    while final in collections or final in formations.children:
        k += 1
        final = f"{name}.{k:03d}"
    name = final
    f = FakeColl(name)
    f.objects = [FakeObj(f"{name} / {i + 1}", p) for i, p in enumerate(points)]
    formations.children[name] = f
    return f


sb_formation = types.ModuleType("sbstudio.plugin.model.formation")
sb_formation.create_formation = create_formation
sb_formation.count_markers_in_formation = lambda f: len(f.objects)
for mod in ("sbstudio", "sbstudio.plugin", "sbstudio.plugin.model"):
    sys.modules[mod] = types.ModuleType(mod)
sys.modules["sbstudio.plugin.model.formation"] = sb_formation


class Storyboard:
    def __init__(self, scene):
        self.entries = []
        self.scene = scene

    @property
    def frame_end(self):
        return max(e.frame_start + e.duration - 1 for e in self.entries)

    def add_new_entry(self, name=None, frame_start=None, duration=None, *, formation=None,
                      select=False, context=None):
        assert context is not None
        if frame_start is None:  # 4.1.1: after the last entry + 20 s transition
            fps = self.scene.render.fps
            frame_start = self.frame_end + fps * 20 if self.entries else self.scene.frame_start
        e = Bag(name=name, frame_start=frame_start, duration=duration, formation=formation)
        self.entries.append(e)
        return e


class ColorFunction(Bag):
    pass


class LightEffects:
    def __init__(self):
        self.entries = []

    def append_new_entry(self, name, frame_start=None, duration=None, *, select=False, context=None):
        assert context is not None
        e = Bag(name=name, frame_start=frame_start, duration=duration, type="COLOR_RAMP",
                color_function=ColorFunction(path="", name=""), output="LAST_COLOR",
                output_y="FIRST_COLOR", enabled=True, influence=1.0)
        self.entries.append(e)
        return e


# ------------------------------------------------------------------- scene


def new_scene():
    scene = Bag(frame_start=1, frame_end=250, frame_current=1)
    scene.render = Bag(fps=30, fps_base=1.0)
    scene.frame_set = lambda f: setattr(scene, "frame_current", f)
    scene.skybrush = Bag(storyboard=Storyboard(scene), light_effects=LightEffects())
    # a takeoff entry, like a real show
    scene.skybrush.storyboard.entries.append(Bag(name="Takeoff", frame_start=1, duration=30,
                                                 formation=FakeColl("Takeoff grid")))
    return scene


sys.path.insert(0, ROOT)
import video_formation  # noqa: E402
from video_formation.core import lighttable  # noqa: E402
from video_formation.operators import generate  # noqa: E402
from video_formation.ui import properties  # noqa: E402

ann = properties.VideoFormationSettings.__annotations__


def settings_defaults():
    s = Bag()
    for k, v in ann.items():
        setattr(s, k, v[2].get("default"))
    return s


def run_op(scene, settings, lights_only=False):
    op = generate.VIDEOFORMATION_OT_generate.__new__(generate.VIDEOFORMATION_OT_generate)
    op.lights_only = lights_only
    msgs = []
    op.report = lambda level, text: msgs.append((level, text))
    wm = Bag(progress_begin=lambda a, b: None, progress_update=lambda v: None,
             progress_end=lambda: None, popup_menu=lambda *a, **k: msgs.append(("POPUP", a)))
    scene.video_formation = settings
    bpy.data.scenes = [scene]
    ctx = Bag(scene=scene, window_manager=wm)
    return op.execute(ctx), msgs


def load_like_skybrush(path):
    spec = importlib.util.spec_from_file_location("colors_module", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    folder = tempfile.mkdtemp(prefix="vf_op_")
    video = os.path.join(folder, "steps.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=red:s=320x180:r=24:d=1",
                    "-f", "lavfi", "-i", "color=c=lime:s=320x180:r=24:d=1",
                    "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=24:d=1",
                    "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0", "-pix_fmt", "yuv420p",
                    "-crf", "1", video], check=True)

    # 1. unsaved .blend, Skybrush present, automatic start
    scene = new_scene()
    s = settings_defaults()
    s.video_path = video
    s.decoder = "FFMPEG"
    s.drone_count = 500
    s.light_fps = "15"
    s.show_preview = False
    result, msgs = run_op(scene, s)
    print("    " + s.last_report.replace("\n", "\n    "))
    check("unsaved .blend: Generate still works", result == {"FINISHED"}, str(msgs[-1:]))
    entry = [e for e in scene.skybrush.storyboard.entries if e.name == "Video Screen"]
    check("storyboard entry placed after the takeoff (not on top of it)",
          len(entry) == 1 and entry[0].frame_start == 30 + 600, str([(e.name, e.frame_start) for e in entry]))
    table = lighttable.load(s.last_table)
    check("video starts where the entry starts", table.start_frame == entry[0].frame_start and s.start_frame == table.start_frame)
    check("lights kept in the add-on's user folder", s.last_table.startswith(EXT_DIR), s.last_table)
    eff = scene.skybrush.light_effects.entries
    check("one Function light effect over the video", len(eff) == 1 and eff[0].type == "FUNCTION"
          and eff[0].frame_start == table.start_frame and eff[0].duration == 90
          and eff[0].color_function.name == "color_function" and eff[0].output == "TEMPORAL",
          str([(e.type, e.frame_start, e.duration, e.color_function.name, e.output) for e in eff]))
    check("scene end frame covers the video", scene.frame_end >= table.start_frame + 89, str(scene.frame_end))
    check("timeline moved to the video", scene.frame_current == table.start_frame)
    f = collections["Formations"].children["Video Screen"]
    check("formation has one marker per screen drone", len(f.objects) == s.result_count == table.n_drones)
    fn = load_like_skybrush(eff[0].color_function.path).color_function
    st = table.start_frame
    reds = fn(frame=st + 10, time_fraction=0, drone_index=0, formation_index=3,
              position=tuple(f.objects[3].location), drone_count=table.n_drones)
    blues = fn(frame=st + 80, time_fraction=0, drone_index=0, formation_index=None,
               position=tuple(f.objects[7].location), drone_count=table.n_drones)
    check("effect file: red at the start, blue at the end", np.argmax(reds[:3]) == 0 and np.argmax(blues[:3]) == 2,
          f"{np.round(reds, 2)} {np.round(blues, 2)}")

    # 2. save the .blend, Generate again: markers moved in place, entry kept, relative path
    BLEND["path"] = os.path.join(folder, "show.blend")
    s.brightness = 0.5
    result, msgs = run_op(scene, s)
    check("saved .blend: Generate again", result == {"FINISHED"}, str(msgs[-1:]))
    f2 = collections["Formations"].children["Video Screen"]
    entries = [e for e in scene.skybrush.storyboard.entries if e.name == "Video Screen"]
    check("same formation object kept, no second storyboard entry", f2 is f and len(entries) == 1)
    check("light file now next to the .blend, relative path",
          eff[0].color_function.path.startswith("//video_formation/") and len(scene.skybrush.light_effects.entries) == 1,
          eff[0].color_function.path)
    t2 = lighttable.load(s.last_table)
    check("brightness 0.5 baked", abs(t2.colors[5].mean() / max(table.colors[5].mean(), 1) - 0.5) < 0.05,
          f"{t2.colors[5].mean():.1f} vs {table.colors[5].mean():.1f}")

    # 3. Update Lights with a changed drone count must refuse, not rebuild
    s.drone_count = 300
    result, msgs = run_op(scene, s, lights_only=True)
    check("Update Lights refuses when the screen size changed", result == {"CANCELLED"}
          and any(m[0] == "POPUP" for m in msgs), s.last_report)
    s.drone_count = 500

    # 4. Start At Frame
    scene2 = new_scene()
    s2 = settings_defaults()
    s2.video_path, s2.decoder, s2.drone_count, s2.show_preview = video, "FFMPEG", 400, False
    s2.start_mode, s2.start_frame, s2.shape = "FRAME", 500, "RINGS"
    result, _ = run_op(scene2, s2)
    t3 = lighttable.load(s2.last_table)
    e3 = [e for e in scene2.skybrush.storyboard.entries if e.name == "Video Screen"][0]
    check("At Frame 500: entry and video at 500", result == {"FINISHED"} and e3.frame_start == 500
          and t3.start_frame == 500, f"{e3.frame_start} {t3.start_frame}")

    # 5. a missing video says so in a popup
    s2.video_path = os.path.join(folder, "missing.mp4")
    result, msgs = run_op(scene2, s2)
    check("missing video: clear error + popup", result == {"CANCELLED"} and any(m[0] == "POPUP" for m in msgs)
          and "not found" in s2.last_report, s2.last_report)

    # 6. viewport preview colours follow the table
    from video_formation.blender_io import viewport

    class Attr:
        def __init__(self, n):
            self.buf = np.zeros(n * 4, np.float32)
            self.data = Bag(foreach_set=lambda key, arr: self.buf.__setitem__(slice(None), arr))

    t_now = lighttable.load(s2.last_table if os.path.exists(s2.last_table) else s.last_table)
    n = t_now.n_drones
    attr = Attr(n)
    mesh = Bag(vertices=[0] * n, attributes={viewport.ATTR: attr}, update=lambda: None)
    obj = {viewport.TABLE_PROP: s2.last_table}
    pobj = Bag(name="VF Preview: test", data=mesh, get=obj.get)
    viewport.update_object(pobj, t_now.start_frame + 50)
    rgba = attr.buf.reshape(n, 4)
    check("viewport preview shows the frame's colours (green in the middle second)",
          np.argmax(rgba[:, :3].mean(axis=0)) == 1 and np.allclose(rgba[:, 3], 1.0), str(rgba[0].round(2)))
    lf = t_now.light_fps / t_now.scene_fps
    a, b = t_now.start_frame + 50, t_now.start_frame + 51
    same = t_now.column(a) == t_now.column(b)
    wrote = viewport.update_object(pobj, b)
    check("viewport preview skips a frame whose light frame did not change",
          (not wrote) if same else wrote, f"light/scene fps {lf:.2f}, same column {same}")
    check("viewport preview does no work when asked for the same light frame again",
          viewport.update_object(pobj, b) is False)
    viewport.update_object(pobj, t_now.start_frame - 5)
    check("viewport preview is dark before the video", float(attr.buf.reshape(n, 4)[:, :3].max()) == 0.0)


def name_clash():
    """Another collection already called "Video Screen": the formation becomes
    "Video Screen.001"; generating again must find it, not make a third one."""
    BLEND["path"] = ""
    collections.clear()
    collections["Video Screen"] = FakeColl("Video Screen")  # e.g. a user collection
    folder = tempfile.mkdtemp(prefix="vf_clash_")
    video = os.path.join(folder, "c.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=160x90:r=24:d=1",
                    "-pix_fmt", "yuv420p", video], check=True)
    scene = new_scene()
    s = settings_defaults()
    s.video_path, s.decoder, s.drone_count, s.show_preview = video, "FFMPEG", 300, False
    for _ in range(3):
        result, _msgs = run_op(scene, s)
    kids = sorted(collections["Formations"].children)
    entries = [e for e in scene.skybrush.storyboard.entries if e.formation is not None
               and e.formation.name.startswith("Video Screen")]
    check("name clash: one formation 'Video Screen.001', reused on every Generate",
          result == {"FINISHED"} and kids == ["Video Screen.001"] and s.formation_name == "Video Screen.001",
          f"{kids} {s.formation_name}")
    check("name clash: one storyboard entry, one light effect",
          len(entries) == 1 and len(scene.skybrush.light_effects.entries) == 1,
          f"{len(entries)} entries, {len(scene.skybrush.light_effects.entries)} effects")


main()
name_clash()
print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
