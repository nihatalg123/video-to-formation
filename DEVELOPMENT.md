# Video to Formation — development notes

v0.3.0, 2026-11-10. A separate Blender 5.0 extension (`id = "video_formation"`), sidebar
tab *Video Formation*. Shares nothing at runtime with Image to Formation; conventions
(coordinates, linear colours, CSV format) are the same on purpose.

## 1. Goal

Turn a video (30 fps or less) into a drone grid, like two example drone-show videos: one fixed
screen of ~1000–2000 drones (varies per show), Grid or Rings, and the video carried onto
its lights, at 15 or 30 fps, without making Blender stutter. Example A: a round screen of
concentric rings; example B: a rectangular grid.

## 2. Screen layouts (`core/layout.py`)

* **Grid**: C x R with C/R ≈ the screen aspect (video's, or custom), C·R ≤ Drone Count,
  most drones; ties broken against aspect error (>3 % aspect error costs like 3 % drones).
  2000 → 58 x 34 = 1972 (16:9), 51 x 39 = 1989 (4:3), 44 x 45 = 1980 (1:1).
* **Rings**: a centre drone + ring k at radius k·spacing with n_k = ⌊π / asin(1/2k)⌋ drones,
  the most for which the chord between neighbours is ≥ the spacing (so the minimum spacing
  holds along rings too: measured closest pair = spacing exactly). Odd rings are rotated
  half a step so no radial seam lines up. Leftover drones form one more evenly spread
  outer ring if they are ≥ 75 % of a full ring (spacing along it ≤ 1.33x): 2000 → 24 full
  rings + 127 = 2000 exactly; 1000 → 953 (17 rings).
* Count never above Drone Count; rows, columns and rings are never trimmed or nudged.
* X right, Y depth, Z up; bottom row at *Bottom Altitude*; reads correctly from the front
  (−Y), like Image to Formation. Warnings for spacing under *Minimum Spacing* and a top
  above *Maximum Altitude*.

## 3. Video → drone colours (`core/sampling.py`, `core/bake.py`)

* Every drone owns a square cell of the screen (UV). The fit mode maps the screen onto the
  frame: FILL crops (default), FIT letterboxes (cells off the video are black), STRETCH.
* Frames are decoded already scaled down so a cell is ~4 px across (2000-drone grid on a
  1080p video: 242 x 136; Rings of 2000: 364 x 206), converted sRGB → **linear**, and each cell is **averaged** with a
  summed-area table (4 lookups per drone per frame). Averaging per cell means no flicker
  from single pixels and no aliasing on fine detail.
* Grading in linear light: Brightness (gain), Saturation, Black Cut (dark noise → off),
  Minimum LED (default 0.01 linear: dark parts stay faintly lit so the screen's shape
  stays visible, as in the examples; 0 turns them off), Maximum LED, Smoothing (blend with
  the previous light frame against flicker).
* Stored as uint8 linear 0..255 — the same convention as Image to Formation's CSV and as
  Skybrush's own handling of video light effects (sRGB → linear since Studio 3.11.2).

Timing: light frames every 1/fps (15, 30 or scene fps, never above the scene fps) from
*Start At* for *Length*; scene frame f shows light frame ⌊(f − start)·light_fps/scene_fps⌋
(15 fps lights in a 30 fps scene: each held 2 frames; 30 in 25: evenly skipped).

## 4. Light table and how Skybrush gets it (`core/lighttable.py`)

One uncompressed `.npz` per screen in `<Output Folder>/<Name>/vf_lights.npz`: colours
(F, N, 3), marker positions, start frame / fps / spacing. Two delivery modes:

* **Function light effect (default)**: the generated `vf_lights.py` next to it. Read from
  Skybrush 4.1.1 source: `LightEffect.color_function_ref` calls `load_module(path)`, which
  re-executes the file **every frame**, then calls `color_function(frame=…,
  time_fraction=…, drone_index=…, formation_index=…, position=…, drone_count=…)` once per
  drone. So the file does almost nothing at import; the table is cached in a module object
  in `sys.modules` (keyed by path, reloaded when the file's mtime/size change) and one list
  of RGBA tuples is built per light frame. Measured: 3.0 ms per frame for 2000 drones here.
  Drone → screen drone: `formation_index` (Skybrush's mapping to the current storyboard
  entry's formation) when the drone stands within half a spacing of that marker;
  otherwise the nearest marker by position (spacing-sized hash, within 0.75 spacing);
  otherwise, if the index is valid, the index (the screen was moved after baking);
  otherwise alpha 0 (leave the drone's colour alone).
* **Image light effect**: width = scene frames, height = markers, `Linear Rec.709`,
  packed; Output X = Temporal, Output Y = Indexed by formation. Checked against
  Skybrush's pixel pick (`x = int(width·t)`, `y = int(height·output_y)`, t = (f −
  start)/(duration − 1)): exact for every frame when width == duration and height ==
  marker count. Skybrush caches the pixels as a Python tuple of floats (~32 bytes per
  channel), hence "heavy".

## 5. Decoding (`core/decode.py`, `blender_io/video.py`)

* FFmpeg when found (PATH, /opt/homebrew/bin, /usr/local/bin, /opt/local/bin): one pipe,
  `-ss start`, `fps=light_fps`, `scale=W:H:flags=area`, rgb24. 2000 drones, 13 s video at
  30 fps: baked in ~2 s.
* Otherwise Blender: a temporary scene whose fps equals the video's, one movie strip
  (STRETCH) at the decode size, `Standard` view transform, each needed frame rendered to a
  small PNG, read back and deleted; the scene is removed afterwards. Not run yet (§7).

## 6. Skybrush hookup (`blender_io/skybrush.py`, `operators/generate.py`)

API read from the Skybrush Studio for Blender **4.1.1** source (tag 4.1.1, 2026-01-23):

* `sbstudio.plugin.model.formation.create_formation(name, points)` → markers (empties)
  in our order, so marker k = screen drone k (Indexed by formation and `formation_index`
  rely on that). Same name and same count on Generate: markers are moved in place, so the
  storyboard entry and its mapping stay; different count: rebuilt and storyboard entries
  re-pointed.
* `storyboard.add_new_entry(name, frame_start, duration, formation=…, select=True,
  context=…)` — only if no entry uses the screen yet; an existing entry is kept and the
  video starts where it starts.
* `light_effects.append_new_entry(name, frame_start, duration, select=True, context=…)`,
  then `type = "FUNCTION"`, `color_function.path` (relative `//` when the .blend is saved)
  and `.name = "color_function"`; or `type = "IMAGE"` with the image, Output X/Y as above.
* Without Skybrush: a mesh `VideoFormation/<Name>` with one vertex per drone (first frame
  as a `Col` attribute) and the light file, plus instructions in the report.

Generate decodes and bakes **before** touching the scene, so a failed decode changes
nothing.

## 6.4 v0.1.1 — "Generate Screen shows nothing"

The first test in Blender showed nothing in Blender. Not reproducible here (no Blender), so
every way that could happen was closed:

* **Unsaved .blend** used to stop Generate with an error only in the status bar. Now the
  lights go to the add-on's user folder (`bpy.utils.extension_path_user`, absolute path)
  with a NOTE; saving and Update Lights moves them next to the file.
* **Errors** also open a popup and stay in the Report panel.
* **Storyboard placement**: the default *Start* is *After Last Entry* — Skybrush's own
  automatic placement (`add_new_entry(frame_start=None)`: last entry end + its default
  transition time), not frame 1 on top of the takeoff. The video starts where the entry
  starts; an existing entry is kept and its start used. *At Frame* keeps the old behaviour.
* **Nothing lights up until transitions run**: Skybrush colours drones, not markers. A
  viewport preview object (`blender_io/viewport.py`): one vertex per screen drone,
  Geometry Nodes put a small sphere on each, an emission material reads the `vf_color`
  attribute, and a `frame_change_post` handler writes the light table's colours for the
  current frame (dark outside the video). Visible at once (grey dots in Solid view,
  colours in Material Preview); never exported. Built after everything else and guarded,
  so a preview failure cannot undo the screen.
* The scene's end frame is extended to the video's end, and the timeline jumps to the
  video's start.
* Blender's own decoder renders the needed frames as animation chunks (120 frames per
  render call, frame step = gcd of the frame gaps) instead of one still render per frame,
  and Generate prints progress to the system console.

`tools/tests/test_operator_mock.py` runs the operator end to end against a fake bpy and a
fake Skybrush built to the 4.1.1 signatures: 18 checks, all pass (unsaved file, placement
after the takeoff, start frame, Function effect, end frame, re-Generate keeps the
formation and entry, relative path once saved, Update Lights refusing a changed screen,
At Frame, missing video popup, preview colours).

## 6.5 v0.1.2 — FFmpeg without Homebrew

On the test Mac, Blender's own reader stopped with "did not write a frame" (not
reproduced here; the cause is still open), and Homebrew wanted to compile FFmpeg with 18
dependencies on an older macOS. So the add-on now needs **only the ffmpeg program**:

* ffprobe is optional — without it, size / fps / length are read from what `ffmpeg -i`
  prints (`probe_with_ffmpeg`; agrees with ffprobe on all three test videos);
* the panel has an optional **FFmpeg** field (the file, or its folder) for an ffmpeg that
  is not on PATH or in /opt/homebrew/bin, /usr/local/bin, /usr/local/ffmpeg/bin,
  /opt/local/bin;
* the suggested install is the signed, notarized `ffmpeg.pkg` from ffmpeg.martin-riedl.de
  (a zip-extracted binary is signed but not notarized, so macOS may refuse to run it).

## 6.6 v0.2.0 — playback speed

First feedback: it works, but playback drops to ~8 fps. Per frame, three things run:
Skybrush's light effects (a Python loop over every drone: positions, influence, our
colour function, blending, then `drone.color` for every drone whose colour changed),
our viewport preview, and the viewport drawing (heavy in Material Preview).

* Preview made cheap: **no Realize Instances** any more — Geometry Nodes instance one
  sphere (material set on it) on the points; the GPU draws instances, and the material
  reads the colour as an *Instancer* attribute. Before, 2000 x 42 vertices were rebuilt
  and uploaded every frame. New node group / material names (`… v2`) so an old preview is
  upgraded by Generate / Update Lights.
* The handler does nothing while the preview collection is hidden (eye icon or
  excluded), and nothing when the light frame is the same as last time (15 fps lights in
  a 30 fps scene: every other frame).
* Playback panel: Show / Hide Preview, **Fast Playback Setup** (Solid view with Object
  colours, which Skybrush 4.0 recommends for drone colours, and `sync_mode =
  FRAME_DROP` so playback keeps real time by skipping frames), Sync, Light FPS.

Not measured inside Blender (no Blender here). If Skybrush's own light-effect loop is
what is slow, the next step is baking the colours onto the drones as keyframes (no
Python per frame), at a memory cost of ~4 keys per drone per light frame.

## 6.7 v0.2.1 — the .skyc that would not open; formation name

* A test show exported as `.skyc` (2000 drones) gave "Failed to load drone show" in
  Skybrush Viewer. Checked offline: all 2000 trajectories valid (linear points, times
  increasing, all end at 71.58 s) and all 2000 light programs decode cleanly
  (SET_COLOR / FADE_TO_COLOR only, 3.5 MB, same length as the trajectories). Three
  variants told it apart: plain-white lights with 2000 drones — did not open; the video
  lights with 200 drones — opened; everything inlined in show.json — did not open. So
  the video lights were fine; the Viewer could not load 2000 drones. Updating Skybrush
  Viewer (2.9.0 made large shows load ~14x faster) fixed it.
  Note for users: Skybrush's .skyc export dialog has its own **Light FPS, default 4**;
  set it to 15 or 30 or the video is sampled 4 times a second.
* The screen formation came out as "Video Screen.001" (another collection already had
  the name). Generate looked it up by the plain name only, so a later Generate could have
  made a second formation and storyboard entry. Now the real name is stored
  (`formation_name`) and the lookup also accepts Blender's ".001" renames; tested with a
  name clash and three Generates: one formation, one entry, one effect.

## 6.8 v0.3.0 — Windows, and FFmpeg inside the add-on

For sharing with the Skybrush community: one zip per platform with FFmpeg included, so
nobody has to install it.

* **Builds** (`tools/build_release.py OUT --bundle windows-x64=DIR --bundle macos-arm64=DIR`):
  `…-windows-x64.zip` (manifest `platforms = ["windows-x64", "windows-arm64"]`; Windows 11
  on ARM runs the x64 ffmpeg.exe), `…-macos-arm64.zip` (Blender 5.0 has no Intel Mac
  build), and `…-no-ffmpeg.zip` (no `platforms`, any OS, uses an installed FFmpeg or
  Blender's reader). The bundle goes to `video_formation/ffmpeg/` with its licence and
  where its source is. Only `ffmpeg` is shipped (ffprobe/ffplay are not needed:
  `probe_with_ffmpeg`, §6.5).
* **Lookup order** (`decode.find_tool`): the panel's FFmpeg field → the bundled copy →
  PATH → usual folders. Bundled before PATH: the shipped build is the one that was
  checked. Windows: `ffmpeg.exe`, and winget (`%LOCALAPPDATA%\Microsoft\WinGet\Links`),
  `%ProgramFiles%\ffmpeg\bin`, `C:\ffmpeg\bin`, Chocolatey, Scoop.
* **Executable bit**: Blender installs an extension with Python's zipfile, which drops
  Unix permissions, so the bundled `ffmpeg` arrives as 0644 on macOS. `_runnable` adds
  +x before use. Verified by extracting the built zip with zipfile and calling
  `find_tool` (found, made executable, `-version` runs).
* **Windows details**: every FFmpeg call gets `CREATE_NO_WINDOW` (no console flashing
  over Blender); FFmpeg's text output is decoded as UTF-8 (the console code page, e.g.
  cp1254 for Turkish, broke names with ğ/İ/ş); FFmpeg's messages go to a temp file
  instead of a pipe that nobody reads while frames are read (could stall FFmpeg once
  the pipe fills, sooner with Windows' small pipes); `stdin` is DEVNULL; the light
  table's atomic replace is retried briefly (a virus scanner may hold the old file).
  Paths were already `os.path` based and the light function finds its table next to
  itself, so Windows paths need nothing else.
* **Panel**: under Decoder a line says which FFmpeg is used ("FFmpeg 8.x (included with
  the add-on)", a found path, or "not found: Blender's reader is used"). Checked once
  per FFmpeg-field value (runs `ffmpeg -version`), again after each Generate.

## 7. Verification

Offline (no Blender): `tools/tests/test_core.py` — 35 checks, all pass: layouts (count,
aspect, spacing, altitude), sampling (halves, sRGB→linear, FILL/FIT), grading, timing,
table round trip, Image mode = Skybrush's pixel pick on every frame, the light function
loaded and called exactly like Skybrush 4.1.1 (index, position fallback, off-screen,
moved screen, wrong formation, re-bake picked up, 3 ms/frame), FFmpeg decode of a
red/green/blue video (colours and timing, Start At / Length).
`tools/tests/test_ui_mock.py` — fake bpy: registers 10 classes, every panel draws, every
core setting has a property.

v0.3.0 adds `t_find_tool`: bundled FFmpeg found first and made runnable after a
permission-dropping unzip, the FFmpeg field still wins, Windows names / folders, and a
video named with Turkish letters probed under an ASCII locale.

In real use (Blender 5.0 + Skybrush Studio 4.1.1 on an Apple M2): Generate,
viewport preview, light effect and .skyc export work, screens up to 5000 drones.
**Not run on Windows yet** — the Windows changes are checked by the tests above, not on
a Windows machine. `tools/tests/test_blender.py` has not been run.

## 8. Known limits

* Re-bake after changing the scene fps (the table stores it).
* The Function mode needs the `video_formation/` folder next to the .blend; moving the
  .blend without it breaks the light effect (Update Lights rewrites it).
* Rings: the leftover drones under 75 % of a ring stay unused (1000 asked → 953).
