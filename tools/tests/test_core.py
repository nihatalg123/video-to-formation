"""Video to Formation — core tests without Blender.

    python3 tools/tests/test_core.py            (numpy; FFmpeg for the decode part)

Covers the screen layouts, frame sampling, timing, the light table, the Image
light effect layout and the generated light function — the latter called exactly
the way Skybrush Studio 4.1.1 calls it (module re-executed every frame, keyword
arguments, one call per drone), including the fallbacks when Skybrush gives no
formation index.
"""

from __future__ import annotations

import importlib.util
import math
import os
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
# the package's __init__ registers Blender classes; load only its core here
import types  # noqa: E402

_pkg = types.ModuleType("video_formation")
_pkg.__path__ = [os.path.join(ROOT, "video_formation")]
sys.modules.setdefault("video_formation", _pkg)

from video_formation.core import bake, decode, layout, lighttable, plan, sampling  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILS.append(name)


# ------------------------------------------------------------------ layouts


def t_layouts():
    for target in (100, 500, 1000, 1500, 2000, 3000, 5000):
        for aspect in (16 / 9, 4 / 3, 1.0, 2.35, 9 / 16):
            s = layout.make_screen("GRID", target, aspect=aspect, spacing=1.5)
            cols, rows = s.info["columns"], s.info["rows"]
            ok = s.count <= target and s.count >= 0.9 * target
            ok = ok and abs(math.log((cols / rows) / aspect)) < 0.12
            if not ok:
                check(f"grid {target} @ {aspect:.2f}", False, f"{cols}x{rows}={s.count}")
                return
        s = layout.make_screen("RINGS", target, spacing=1.5)
        if not (s.count <= target):
            check(f"rings {target}", False, str(s.count))
            return
    check("grid: count <= target and >= 90 %, aspect within 12 %", True)
    s = layout.make_screen("GRID", 2000, aspect=16 / 9, spacing=1.5)
    check("grid 2000 16:9", s.count <= 2000 and s.count >= 1950,
          f"{s.info['columns']}x{s.info['rows']} = {s.count}")
    check("grid spacing exact", abs(layout.min_distance(s.positions) - 1.5) < 1e-9)
    check("grid bottom at bottom_z", abs(s.positions[:, 2].min() - 0.0) < 1e-9)
    r = layout.make_screen("RINGS", 2000, spacing=1.5, bottom_z=40)
    md = layout.min_distance(r.positions)
    check("rings: spacing holds along and across rings", md >= 1.5 - 1e-9, f"{md:.4f} m, {r.count} drones")
    check("rings bottom at bottom_z", abs(r.positions[:, 2].min() - 40) < 1e-6)
    w = layout.make_screen("GRID", 2000, aspect=16 / 9, width_m=100.0)
    check("size by width", abs(w.width_m - 100.0) < 1e-6, f"{w.width_m:.3f} m, spacing {w.spacing:.3f}")
    uv = s.uv
    check("uv inside 0..1", float(uv.min()) > 0 and float(uv.max()) < 1)


# ----------------------------------------------------------------- sampling


def t_sampling():
    s = layout.make_screen("GRID", 200, aspect=2.0, spacing=1.5)  # 20 x 10
    h, w = 100, 200
    frame = np.zeros((h, w, 3), np.uint8)
    frame[:, : w // 2] = (255, 0, 0)
    frame[:, w // 2:] = (0, 0, 255)
    boxes = sampling.cell_boxes(s.uv, s.cell_uv, s.aspect, w, h, "FILL")
    c = sampling.Sampler(boxes, w, h).colors(frame)
    left = s.uv[:, 0] < 0.5
    check("left half red, right half blue",
          np.allclose(c[left], [1, 0, 0]) and np.allclose(c[~left], [0, 0, 1]))
    # mid-grey sRGB 128 -> linear 0.2158
    frame[:] = 128
    c = sampling.Sampler(boxes, w, h).colors(frame)
    check("sRGB 128 -> linear 0.216", np.allclose(c, 0.2158605, atol=1e-4), f"{c[0, 0]:.4f}")
    # FIT on a square screen with a 2:1 video: top and bottom quarter dark
    sq = layout.make_screen("GRID", 400, aspect=1.0, spacing=1.0)  # 20 x 20
    frame[:] = 255
    c = sampling.Sampler(sampling.cell_boxes(sq.uv, sq.cell_uv, 1.0, w, h, "FIT"), w, h).colors(frame)
    lit = c[:, 0] > 0.5
    rows_lit = np.unique(np.round(sq.uv[lit, 1], 3)).size
    check("FIT: 2:1 video on a square screen lights half the rows", rows_lit == 10, f"{rows_lit} rows")
    c = sampling.Sampler(sampling.cell_boxes(sq.uv, sq.cell_uv, 1.0, w, h, "FILL"), w, h).colors(frame)
    check("FILL: square screen fully lit", bool((c[:, 0] > 0.99).all()))
    # FILL crops the sides: a red left quarter must not show
    frame[:] = 255
    frame[:, : w // 4] = (255, 0, 0)
    frame[:, w // 4 * 3:] = (255, 0, 0)
    c = sampling.Sampler(sampling.cell_boxes(sq.uv, sq.cell_uv, 1.0, w, h, "FILL"), w, h).colors(frame)
    check("FILL crops the sides of a wide video", bool((c[:, 1] > 0.99).all()))
    # grading
    g = sampling.grade(np.array([[0.5, 0.25, 0.0], [0.001, 0.001, 0.001]]),
                       sampling.Grade(brightness=2.0, black_cut=0.01, max_led=0.9))
    check("grade: gain, black cut, cap", np.allclose(g, [[0.9, 0.5, 0.0], [0, 0, 0]]), str(g.round(3).tolist()))
    g = sampling.grade(np.array([[0.0, 0.0, 0.0], [0.02, 0.0, 0.0]]), sampling.Grade(floor=0.05))
    luma = g @ sampling.REC709
    check("grade: minimum LED keeps hue", np.allclose(luma, 0.05) and g[1, 1] == 0 and g[1, 0] > 0,
          str(g.round(3).tolist()))


# ------------------------------------------------------------------- timing


def t_timing():
    t = sampling.light_times(10.0, 30.0)
    check("10 s at 30 fps -> 300 light frames", len(t) == 300 and abs(t[-1] - 299 / 30) < 1e-9)
    t = sampling.light_times(10.0, 15.0, start=2.0, length=4.0)
    check("start 2 s, 4 s at 15 fps -> 60 frames from 2.0", len(t) == 60 and t[0] == 2.0)
    n = sampling.scene_frames_for(60, 15.0, 30.0)
    check("15 fps lights over a 30 fps scene: 120 scene frames", n == 120)
    cols = sampling.column_for_scene_frame(np.arange(6), 15.0, 30.0, 60)
    check("each light frame held for 2 scene frames", cols.tolist() == [0, 0, 1, 1, 2, 2])
    cols = sampling.column_for_scene_frame(np.arange(5), 30.0, 25.0, 300)
    check("30 fps lights over a 25 fps scene skip evenly", cols.tolist() == [0, 1, 2, 3, 4])
    cols = sampling.column_for_scene_frame(np.array([0, 24, 25, 49]), 30.0, 25.0, 300)
    check("1 s of 25 fps scene = 30 light frames", cols.tolist() == [0, 28, 30, 58], str(cols.tolist()))


# -------------------------------------------------------------- light table


def _table(n_light=20, scene_fps=30.0, light_fps=15.0, start=100):
    s = layout.make_screen("GRID", 60, aspect=1.5, spacing=2.0, bottom_z=30)
    rng = np.random.default_rng(1)
    colors = rng.integers(0, 256, size=(n_light, s.count, 3), dtype=np.uint8)
    return s, lighttable.LightTable(colors, s.positions, start, scene_fps, light_fps, s.spacing)


def t_table_and_image():
    s, tab = _table()
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, lighttable.DATA_NAME)
    lighttable.save(tab, path)
    back = lighttable.load(path)
    check("light table round trip", np.array_equal(back.colors, tab.colors)
          and back.start_frame == 100 and back.light_fps == 15.0)
    # Image light effect: emulate Skybrush 4.1.1 exactly (light_effects.py apply_on_colors)
    buf = lighttable.image_buffer(tab)
    width, height = tab.scene_frames, tab.n_drones
    pixels = buf.tolist()
    duration = width
    ok = True
    for frame in range(tab.start_frame, tab.start_frame + duration):
        time_fraction = (frame - tab.start_frame) / max(duration - 1, 1)
        for marker in (0, 7, height - 1):
            output_y = marker / max(height - 1, 1)
            x = int(width * time_fraction) if time_fraction < 1 else width - 1
            y = int(height * output_y) if output_y < 1 else height - 1
            off = (x + y * width) * 4
            got = np.round(np.array(pixels[off:off + 3]) * 255).astype(int)
            want = tab.colors[tab.column(frame), marker].astype(int)
            if not np.array_equal(got, want):
                ok = False
    check("Image light effect: Skybrush's pixel pick = our colour, every frame", ok)
    return folder, s, tab


def _load_like_skybrush(path):
    spec = importlib.util.spec_from_file_location("colors_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def t_runtime(folder, s, tab):
    script = lighttable.write_runtime(folder, "Test Screen")
    ok_index = ok_pos = True
    order = np.random.default_rng(3).permutation(tab.n_drones)  # drone i sits on marker order[i]
    for frame in range(tab.start_frame, tab.start_frame + tab.scene_frames):
        fn = getattr(_load_like_skybrush(script), lighttable.FUNCTION_NAME)  # re-executed per frame
        col = tab.column(frame)
        for drone, marker in enumerate(order[:12]):
            pos = tuple(tab.positions[marker])
            want = tuple(np.append(tab.colors[col, marker] / 255.0, 1.0))
            got = fn(frame=frame, time_fraction=0.0, drone_index=drone, formation_index=int(marker),
                     position=pos, drone_count=tab.n_drones)
            ok_index &= np.allclose(got, want)
            got = fn(frame=frame, time_fraction=0.0, drone_index=drone, formation_index=None,
                     position=pos, drone_count=tab.n_drones)
            ok_pos &= np.allclose(got, want)
    check("light function: formation index -> right colour, every frame", ok_index)
    check("light function: no formation index -> found by position", ok_pos)
    fn = _load_like_skybrush(script).color_function
    far = (500.0, 0.0, 500.0)
    got = fn(frame=tab.start_frame, time_fraction=0, drone_index=0, formation_index=None,
             position=far, drone_count=tab.n_drones)
    check("light function: a drone off the screen is left alone (alpha 0)", got[3] == 0.0)
    # screen moved after baking: positions do not match, index is trusted
    moved = tuple(np.asarray(tab.positions[5]) + (0.0, 0.0, 37.0))
    got = fn(frame=tab.start_frame, time_fraction=0, drone_index=0, formation_index=5,
             position=moved, drone_count=tab.n_drones)
    check("light function: screen moved -> formation index still works",
          np.allclose(got[:3], tab.colors[0, 5] / 255.0))
    # wrong index (another formation active): position wins
    got = fn(frame=tab.start_frame, time_fraction=0, drone_index=0, formation_index=3,
             position=tuple(tab.positions[9]), drone_count=tab.n_drones)
    check("light function: index of another formation -> position wins",
          np.allclose(got[:3], tab.colors[0, 9] / 255.0))
    # speed: one frame of 2000 drones
    big_s = layout.make_screen("GRID", 2000, aspect=16 / 9, spacing=1.5)
    big = lighttable.LightTable(np.zeros((900, big_s.count, 3), np.uint8), big_s.positions, 1, 30.0, 30.0, 1.5)
    f2 = tempfile.mkdtemp()
    lighttable.save(big, os.path.join(f2, lighttable.DATA_NAME))
    script2 = lighttable.write_runtime(f2, "Big")
    import time

    _load_like_skybrush(script2)  # first load reads the table
    t0 = time.perf_counter()
    frames = 30
    for frame in range(1, 1 + frames):
        fn = _load_like_skybrush(script2).color_function
        for i in range(big_s.count):
            fn(frame=frame, time_fraction=0.0, drone_index=i, formation_index=i,
               position=tuple(big_s.positions[i]), drone_count=big_s.count)
    ms = (time.perf_counter() - t0) * 1000 / frames
    check("light function: 2000 drones cost a few ms per frame", ms < 40, f"{ms:.1f} ms/frame here")
    # rewriting the table is picked up (no stale cache)
    tab2 = lighttable.LightTable(np.full_like(tab.colors, 200), tab.positions, tab.start_frame,
                                 tab.scene_fps, tab.light_fps, tab.spacing)
    import time as _t

    _t.sleep(0.01)
    lighttable.save(tab2, os.path.join(folder, lighttable.DATA_NAME))
    fn = _load_like_skybrush(script).color_function
    got = fn(frame=tab.start_frame, time_fraction=0, drone_index=0, formation_index=0,
             position=tuple(tab.positions[0]), drone_count=tab.n_drones)
    check("light function: a new bake is picked up", np.allclose(got[:3], 200 / 255.0))


# -------------------------------------------------------------- with FFmpeg


def t_decode():
    if not (decode.find_tool("ffmpeg") and decode.find_tool("ffprobe")):
        print("SKIP decode tests: no FFmpeg")
        return
    folder = tempfile.mkdtemp()
    video = os.path.join(folder, "steps.mp4")
    # 3 s at 24 fps: red / green / blue, one second each, 320x180
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "lavfi", "-i", "color=c=red:s=320x180:r=24:d=1",
           "-f", "lavfi", "-i", "color=c=lime:s=320x180:r=24:d=1",
           "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=24:d=1",
           "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0", "-pix_fmt", "yuv420p", "-crf", "1", video]
    subprocess.run(cmd, check=True)
    info = decode.probe(video)
    check("probe", info.width == 320 and info.height == 180 and abs(info.fps - 24) < 0.01
          and abs(info.duration - 3.0) < 0.1, str(info))
    lone = decode.probe_with_ffmpeg(video)
    check("probe with ffmpeg alone (no ffprobe) agrees", (lone.width, lone.height) == (320, 180)
          and abs(lone.fps - 24) < 0.01 and abs(lone.duration - info.duration) < 0.05, str(lone))
    hint_dir = tempfile.mkdtemp()
    fake = os.path.join(hint_dir, "ffmpeg")
    os.symlink(decode.find_tool("ffmpeg"), fake)
    check("FFmpeg path chosen in the panel is used (file or folder)",
          decode.find_tool("ffmpeg", fake) == fake and decode.find_tool("ffmpeg", hint_dir) == fake)
    job = plan.Job(video_path=video, shape="RINGS", drone_count=300, light_fps="15")
    s = plan.build_screen(job, info.width, info.height)
    times = sampling.light_times(info.duration, 15.0)
    size = bake.decode_size(s, job.fit, info.width, info.height)
    colors = bake.bake_colors(s, decode.read_frames(video, 0.0, len(times), 15.0, size), len(times),
                              size, job.fit, plan.grade_of(job))
    check("45 light frames for 3 s at 15 fps", colors.shape[0] == 45, str(colors.shape))
    dom = colors.reshape(colors.shape[0], -1, 3).mean(axis=1).argmax(axis=1)
    check("second 1 red, 2 green, 3 blue (one frame of slack at the cuts)",
          (dom[1:14] == 0).all() and (dom[16:29] == 1).all() and (dom[31:44] == 2).all(), str(dom.tolist()))
    lin = colors[5].astype(float).mean(axis=0)
    check("pure red stays pure in linear", lin[0] > 240 and lin[1] < 8 and lin[2] < 8, str(lin.round(1)))
    # start / length trimming
    times = sampling.light_times(info.duration, 15.0, start=1.0, length=1.0)
    colors = bake.bake_colors(s, decode.read_frames(video, 1.0, len(times), 15.0, size), len(times),
                              size, job.fit, plan.grade_of(job))
    dom = colors.mean(axis=1).argmax(axis=1)
    check("Start At 1 s, Length 1 s: the green second only", (dom[1:-1] == 1).all() and len(dom) == 15,
          str(dom.tolist()))


def t_find_tool():
    """Bundled FFmpeg first; executable bit restored (extension zips drop it);
    Windows names (.exe) and folders; a non-UTF-8 code page cannot break probing."""
    import stat as _stat
    real = decode.find_tool("ffmpeg")
    old_dir, old_win = decode.BUNDLED_DIR, decode.WINDOWS
    try:
        bundle = tempfile.mkdtemp()
        decode.BUNDLED_DIR = bundle
        check("no bundled ffmpeg: falls back to the system one", decode.bundled_tool("ffmpeg") is None
              and decode.find_tool("ffmpeg") == real)
        if real:
            copy = os.path.join(bundle, "ffmpeg")
            with open(real, "rb") as src, open(copy, "wb") as dst:
                dst.write(src.read())
            os.chmod(copy, 0o644)  # what an extension zip leaves behind
            got = decode.find_tool("ffmpeg")
            check("bundled ffmpeg is found first and made runnable again",
                  got == copy and os.stat(copy).st_mode & _stat.S_IXUSR and decode.version(copy) != "",
                  f"{got} {decode.version(copy)!r}")
            hint_dir = tempfile.mkdtemp()
            fake = os.path.join(hint_dir, "ffmpeg")
            os.symlink(real, fake)
            check("the panel's FFmpeg field still wins over the bundled one",
                  decode.find_tool("ffmpeg", fake) == fake and decode.find_tool("ffmpeg", hint_dir) == fake)
        decode.WINDOWS = True
        win = tempfile.mkdtemp()
        exe = os.path.join(win, "ffmpeg.exe")
        open(exe, "wb").close()
        check("Windows: ffmpeg.exe is looked for", decode._file_names("ffmpeg")[0] == "ffmpeg.exe"
              and decode._in_folder(win, "ffmpeg") == exe and decode.find_tool("ffmpeg", win) == exe)
        os.environ.setdefault("LOCALAPPDATA", r"C:\Users\x\AppData\Local")
        places = decode._candidates()
        check("Windows: winget / Program Files / C:\\ffmpeg are searched",
              any("WinGet" in p for p in places) and any(p.endswith(os.path.join("ffmpeg", "bin")) for p in places)
              and r"C:\ffmpeg\bin" in places, str(places))
    finally:
        decode.BUNDLED_DIR, decode.WINDOWS = old_dir, old_win
    if real:
        folder = tempfile.mkdtemp()
        video = os.path.join(folder, "çekim İstanbul.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x36:r=10:d=1",
                        "-pix_fmt", "yuv420p", video], check=True)
        env_lang = os.environ.get("LC_ALL")
        os.environ["LC_ALL"] = "C"  # ASCII locale: the output is still decoded as UTF-8
        try:
            info = decode.probe_with_ffmpeg(video)
        finally:
            if env_lang is None:
                os.environ.pop("LC_ALL", None)
            else:
                os.environ["LC_ALL"] = env_lang
        check("non-ASCII video path (Turkish letters) probes fine", info.width == 64, str(info))


if __name__ == "__main__":
    t_find_tool()
    t_layouts()
    t_sampling()
    t_timing()
    folder, s, tab = t_table_and_image()
    t_runtime(folder, s, tab)
    t_decode()
    print()
    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)
