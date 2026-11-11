"""Video to Formation — test inside Blender 5.0 (with Skybrush Studio if installed).

    "/Applications/Blender 2.app/Contents/MacOS/Blender" -b --factory-startup \
        --python tools/tests/test_blender.py

(--factory-startup is optional; without it the installed add-ons, Skybrush
included, are loaded and the Skybrush part runs too.)

1. Blender writes a 3-second test video: red, green, blue, one second each.
2. The add-on is loaded from this folder (or the installed extension is used).
3. Generate Screen with Blender's own decoder (and FFmpeg's, if installed):
   screen size, light table, colours red -> green -> blue at the right frames.
4. With Skybrush: the formation has one marker per screen drone, the storyboard
   entry and the Function light effect exist, and the light file Skybrush loads
   returns the video's colours. Then the same with an Image light effect.
5. Preview Frame makes its image.
"""

import importlib.util
import os
import sys
import tempfile
import traceback

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILS.append(name)


def addon_module():
    """The installed extension if it is enabled, else the copy next to this test."""
    for name, mod in list(sys.modules.items()):
        if name.endswith("video_formation") and hasattr(mod, "register") and hasattr(mod, "_MODULES"):
            if hasattr(bpy.types.Scene, "video_formation"):
                return mod
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import video_formation

    if not hasattr(bpy.types.Scene, "video_formation"):
        video_formation.register()
    return video_formation


def _new_color_strip(strips, name, color, start, length):
    try:
        s = strips.new_effect(name=name, type="COLOR", channel=1, frame_start=start, length=length)
    except TypeError:
        s = strips.new_effect(name=name, type="COLOR", channel=1, frame_start=start, frame_end=start + length)
    s.color = color
    return s


def write_test_video(folder):
    path = os.path.join(folder, "rgb_steps.mp4")
    scene = bpy.data.scenes.new("VF_TestVideo")
    try:
        r = scene.render
        r.fps, r.fps_base = 24, 1.0
        r.resolution_x, r.resolution_y, r.resolution_percentage = 320, 180, 100
        r.use_sequencer = True
        ed = scene.sequence_editor_create()
        strips = getattr(ed, "strips", None) or ed.sequences
        _new_color_strip(strips, "red", (1, 0, 0), 1, 24)
        _new_color_strip(strips, "green", (0, 1, 0), 25, 24)
        _new_color_strip(strips, "blue", (0, 0, 1), 49, 24)
        scene.frame_start, scene.frame_end = 1, 72
        im = r.image_settings
        try:
            im.media_type = "VIDEO"  # Blender 5.0
        except (AttributeError, TypeError):
            pass
        im.file_format = "FFMPEG"
        r.ffmpeg.format = "MPEG4"
        r.ffmpeg.codec = "H264"
        r.ffmpeg.constant_rate_factor = "LOSSLESS"
        scene.view_settings.view_transform = "Standard"
        r.filepath = path
        bpy.ops.render.render(animation=True, scene=scene.name)
    finally:
        bpy.data.scenes.remove(scene)
    if not os.path.exists(path):
        cand = [f for f in os.listdir(folder) if f.startswith("rgb_steps")]
        if cand:
            path = os.path.join(folder, cand[0])
    return path


def load_like_skybrush(path):
    spec = importlib.util.spec_from_file_location("colors_module", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    folder = tempfile.mkdtemp(prefix="vf_test_")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(folder, "test.blend"))
    video = write_test_video(folder)
    check("Blender wrote the test video", os.path.exists(video), video)
    mod = addon_module()
    from importlib import import_module

    core = import_module(mod.__name__ + ".core.lighttable")
    vio = import_module(mod.__name__ + ".blender_io.video")
    sky = import_module(mod.__name__ + ".blender_io.skybrush")

    scene = bpy.context.scene
    scene.render.fps, scene.render.fps_base = 30, 1.0
    s = scene.video_formation
    s.video_path = video
    s.shape = "GRID"
    s.drone_count = 500
    s.light_fps = "15"
    s.start_mode = "FRAME"
    s.start_frame = 1
    has_sb = sky.available(bpy.context)
    print(f"INFO Skybrush Studio {'found' if has_sb else 'not found'}")

    decoders = ["BLENDER"] + (["FFMPEG"] if vio.decode.find_tool("ffmpeg") else [])
    for dec in decoders:
        s.decoder = dec
        s.screen_name = f"Test {dec.title()}"
        result = bpy.ops.video_formation.generate(lights_only=False)
        print(s.last_report)
        check(f"{dec}: Generate Screen finished", "FINISHED" in result, str(result))
        table = core.load(s.last_table)
        check(f"{dec}: 45 light frames (3 s at 15 fps)", table.n_light == 45, str(table.n_light))
        check(f"{dec}: 90 scene frames (3 s at 30 fps)", table.scene_frames == 90, str(table.scene_frames))
        mean = table.colors.astype(float).mean(axis=1)
        dom = mean.argmax(axis=1)
        check(f"{dec}: red, then green, then blue",
              (dom[2:13] == 0).all() and (dom[17:28] == 1).all() and (dom[32:43] == 2).all(),
              str(dom.tolist()))
        check(f"{dec}: colours are full and pure", mean[7, 0] > 230 and mean[7, 1] < 12 and mean[22, 1] > 230,
              str(mean[[7, 22, 37]].round(0).tolist()))
        prev = bpy.data.objects.get(f"VF Preview: {s.screen_name}")
        check(f"{dec}: viewport preview object with one point per drone",
              prev is not None and len(prev.data.vertices) == table.n_drones and "VF Dots" in prev.modifiers)
        if prev is not None:
            scene.frame_set(45)
            col = np.empty(table.n_drones * 4, np.float32)
            prev.data.attributes["vf_color"].data.foreach_get("color", col)
            check(f"{dec}: preview is green at frame 45", int(np.argmax(col.reshape(-1, 4)[:, :3].mean(0))) == 1)
        script = os.path.join(os.path.dirname(s.last_table), core.SCRIPT_NAME)
        fn = load_like_skybrush(script).color_function
        for frame, ch in ((10, 0), (45, 1), (80, 2)):
            got = fn(frame=frame, time_fraction=0.0, drone_index=0, formation_index=0,
                     position=tuple(table.positions[0]), drone_count=table.n_drones)
            check(f"{dec}: light file at frame {frame} is {'RGB'[ch]}", np.argmax(got[:3]) == ch and got[3] == 1.0,
                  str(np.round(got, 3)))

        if has_sb:
            f = sky.find_formation(s.screen_name)
            check(f"{dec}: Skybrush formation with one marker per drone",
                  f is not None and len(f.objects) == table.n_drones,
                  f"{len(f.objects) if f else None} vs {table.n_drones}")
            effects = [e for e in scene.skybrush.light_effects.entries if e.name == f"Video: {s.screen_name}"]
            check(f"{dec}: Function light effect", len(effects) == 1 and effects[0].type == "FUNCTION"
                  and effects[0].color_function.name == "color_function"
                  and effects[0].duration == 90, str([(e.type, e.duration) for e in effects]))
            entries = [e for e in scene.skybrush.storyboard.entries if e.formation == f]
            check(f"{dec}: storyboard entry", len(entries) == 1, str(len(entries)))

    if has_sb:
        s.light_mode = "IMAGE"
        result = bpy.ops.video_formation.generate(lights_only=True)
        check("Image mode: Update Lights finished", "FINISHED" in result, s.last_report)
        img = bpy.data.images.get(f"VF {s.screen_name}")
        check("Image mode: image is scene frames x drones",
              img is not None and tuple(img.size) == (90, s.result_count), str(img.size[:] if img else None))
        eff = [e for e in scene.skybrush.light_effects.entries if e.name == f"Video: {s.screen_name}"][0]
        check("Image mode: Temporal x Indexed by formation",
              eff.type == "IMAGE" and eff.output == "TEMPORAL" and eff.output_y == "INDEXED_BY_FORMATION")
        s.light_mode = "FUNCTION"

    s.shape = "RINGS"
    scene.frame_set(50)
    result = bpy.ops.video_formation.preview()
    check("Preview Frame", "FINISHED" in result and bpy.data.images.get("Video Formation Preview") is not None)


try:
    main()
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print()
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
