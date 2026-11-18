"""Import the add-on against a fake bpy, register it and draw every panel.

    python3 tools/tests/test_ui_mock.py

Catches import errors, properties the panel draws that do not exist, and settings
the core does not read. Not a Blender test (that is test_blender.py).
"""

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
calls = []
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILS.append(name)


class Any:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, n):
        return Any()

    def __call__(self, *a, **k):
        return Any()


bpy = types.ModuleType("bpy")
props = types.ModuleType("bpy.props")
btypes = types.ModuleType("bpy.types")
utils = types.ModuleType("bpy.utils")
for n in ["BoolProperty", "EnumProperty", "FloatProperty", "FloatVectorProperty", "IntProperty", "StringProperty",
          "PointerProperty", "CollectionProperty"]:
    setattr(props, n, (lambda name: (lambda **k: ("PROP", name, k)))(n))


class Base:
    pass


for n in ["PropertyGroup", "Panel", "Operator", "Object", "Scene", "Mesh", "Image", "Collection", "Material", "NodeTree"]:
    setattr(btypes, n, type(n, (Base,), {}))
utils.register_class = lambda c: calls.append(c.__name__)
utils.unregister_class = lambda c: None
bpy.props, bpy.types, bpy.utils = props, btypes, utils
bpy.path = types.SimpleNamespace(abspath=lambda p: p, relpath=lambda p: p)
bpy.data = Any()
bpy.context = Any()
bpy.app = types.SimpleNamespace(handlers=types.SimpleNamespace(persistent=lambda f: f, frame_change_post=[], load_post=[]))
extras = types.ModuleType("bpy_extras")
io_utils = types.ModuleType("bpy_extras.io_utils")
io_utils.ExportHelper = type("ExportHelper", (), {})
extras.io_utils = io_utils
sys.modules.update({"bpy": bpy, "bpy.props": props, "bpy.types": btypes, "bpy.utils": utils, "bpy.app": types.SimpleNamespace(handlers=None), "bpy.app.handlers": types.SimpleNamespace(persistent=lambda f: f, frame_change_post=[], load_post=[]),
                    "bpy_extras": extras, "bpy_extras.io_utils": io_utils})
sys.path.insert(0, ROOT)

import video_formation  # noqa: E402
from video_formation.core import plan  # noqa: E402
from video_formation.ui import panel, properties  # noqa: E402

video_formation.register()
check("registered", len(calls) >= 9, f"{len(calls)} classes: {calls}")
ann = properties.VideoFormationSettings.__annotations__


class Layout:
    def __init__(self):
        self.drawn = []
        self.use_property_split = False
        self.use_property_decorate = False
        self.enabled = True
        self.scale_y = 1.0

    def __getattr__(self, n):
        if n in ("row", "column", "box"):
            return lambda *a, **k: self
        return lambda *a, **k: None

    def prop(self, obj, name, **k):
        if isinstance(obj, Settings):
            assert name in ann, f"panel draws unknown property {name!r}"
        else:
            assert name in ("sync_mode",), f"panel draws unexpected scene property {name!r}"
        self.drawn.append(name)

    def operator(self, *a, **k):
        return Any()

    def label(self, **k):
        pass


class Settings:
    def __init__(self):
        for k, v in ann.items():
            setattr(self, k, v[2].get("default") if isinstance(v, tuple) else None)


for variant in ({}, {"shape": "RINGS", "size_mode": "WIDTH"}, {"aspect_mode": "CUSTOM"},
                {"last_report": "line\nWARN x", "result_count": 1972, "result_frames": 240},
                {"source": "TEXT"}, {"source": "TEXT", "text_style": "BLOCK", "text_layout": "BIG",
                                     "drone_count": 100, "text_loops": 3},
                {"source": "TEXT", "text_style": "FONT", "text_colour_mode": "RAINBOW"},
                {"source": "TEXT", "text": "Merhaba 🙂", "drone_count": 5}):
    s = Settings()
    for k, v in variant.items():
        setattr(s, k, v)
    ctx = types.SimpleNamespace(scene=types.SimpleNamespace(video_formation=s, sync_mode="AUDIO_SYNC"))
    drawn = []
    for P in panel.classes:
        if hasattr(P, "poll") and "poll" in P.__dict__ and not P.poll(ctx):
            continue
        p = P.__new__(P)
        p.layout = Layout()
        P.draw(p, ctx)
        drawn += p.layout.drawn
    check(f"panels draw {variant or 'defaults'}", len(drawn) > 20, f"{len(drawn)} props")

job = plan.read_settings(Settings())
job_fields = set(plan.Job.__dataclass_fields__)
missing = sorted(f for f in job_fields if f not in ann)
check("every core setting has a panel property", not missing, str(missing))

from video_formation.core import textscreen  # noqa: E402

s = Settings()
s.source, s.text, s.text_style, s.text_layout, s.drone_count = "TEXT", "HELLO", "BLOCK", "BIG", 100
s.text_colour = (1.0, 0.0, 0.0)
tj = plan.read_text_job(s)
tp = textscreen.plan(tj, s.drone_count)
check("text settings reach the core (100 drones, Block, Big -> 10 x 10, red linear)",
      (tp.cols, tp.rows) == (10, 10) and tj.style == "BLOCK" and tj.layout == "BIG"
      and tj.colour == (1.0, 0.0, 0.0), textscreen.describe(tp))
info, warn = panel.text_info(s)
check("panel summary of the text screen", info.startswith("Screen 10 x 10 = 100 drones") and not warn, info)
s.text = "Merhaba 🙂"
s.text_style = "LED"
info, warn = panel.text_info(s)
check("panel warns about characters the font lacks", "🙂" in warn, warn)
s.drone_count = 5
info, warn = panel.text_info(s)
check("panel shows why too few drones do not work", not info and "rows" in warn, warn)
s.text_style = "FONT"
check("Font letters: no live summary (needs Blender's font engine)", panel.text_info(s) == ("", ""))
s2 = Settings()
check("sRGB colour picker -> linear", abs(plan.srgb_to_linear((0.5, 0.5, 0.5))[0] - 0.214) < 0.001)

check("defaults reach the core", job.drone_count == 2000 and job.shape == "GRID" and job.light_fps == "30"
      and abs(job.spacing - 1.5) < 1e-9 and job.bottom_z == 40.0)
print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
