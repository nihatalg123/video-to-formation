"""Generate: video -> screen formation + baked lights in Skybrush (DEVELOPMENT.md §6).

``Generate Screen`` builds (or updates) the screen formation, its storyboard entry,
the light effect and a viewport preview. ``Update Lights`` only re-bakes the video
onto the existing screen — brightness, timing, a new video — without touching the
formation or the storyboard.

The video is decoded and baked first; the scene is only changed once that worked.
Errors are shown in a popup as well as in the status bar, so they cannot be missed.
"""

# No `from __future__ import annotations`: Blender reads property annotations
# as real objects when registering the class.

import os
import re
import tempfile
import time
import traceback

import bpy
import numpy as np
from bpy.props import BoolProperty
from bpy.types import Operator

from ..core import bake, lighttable, plan, sampling
from ..core.decode import VIDEO_EXTENSIONS

_ADDON = __package__.rpartition(".")[0]


def scene_fps(scene) -> float:
    return float(scene.render.fps) / float(scene.render.fps_base or 1.0)


def safe_name(name: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(name)).strip(" .")
    return text or "Video Screen"


def resolve_video(path: str) -> str:
    if not path:
        raise ValueError("Choose a video file first.")
    full = os.path.normpath(bpy.path.abspath(path))
    if not os.path.isfile(full):
        raise ValueError(f"Video not found: {full}")
    if os.path.splitext(full)[1].lower() not in VIDEO_EXTENSIONS:
        raise ValueError(
            f"{os.path.basename(full)} does not look like a video "
            f"({', '.join(VIDEO_EXTENSIONS)})."
        )
    return full


def _user_folder() -> str:
    try:
        return bpy.utils.extension_path_user(_ADDON, path="lights", create=True)
    except Exception:
        path = os.path.join(tempfile.gettempdir(), "video_formation")
        os.makedirs(path, exist_ok=True)
        return path


def output_folder(settings) -> tuple[str, str]:
    """(folder for this screen, note). A // folder needs a saved .blend; without one
    the lights go to the add-on's own user folder (absolute path), so Generate
    never fails just because the file was not saved yet."""
    raw = settings.output_folder or "//video_formation/"
    note = ""
    if raw.startswith("//") and not bpy.data.filepath:
        base = _user_folder()
        note = (f"NOTE the .blend is not saved, so the lights are in {base}. Save the "
                "file and press Update Lights to keep them next to it.")
    else:
        base = os.path.normpath(bpy.path.abspath(raw))
    return os.path.join(base, safe_name(settings.screen_name)), note


def _effect_name(settings) -> str:
    return f"Video: {settings.screen_name}"


def _popup(context, lines, title, icon):
    def draw(menu, _context):
        for line in lines[:12]:
            menu.layout.label(text=line)

    try:
        context.window_manager.popup_menu(draw, title=title, icon=icon)
    except Exception:
        pass


class VIDEOFORMATION_OT_generate(Operator):
    bl_idname = "video_formation.generate"
    bl_label = "Generate Screen"
    bl_description = (
        "Build the drone screen (Grid or Rings) as a Skybrush formation, put it in the "
        "storyboard and bake the video onto its lights as a light effect"
    )
    bl_options = {"REGISTER", "UNDO"}

    lights_only: BoolProperty(
        name="Lights Only",
        description="Re-bake the video onto the existing screen; formation and storyboard are kept",
        default=False,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        return bool(context.scene.video_formation.video_path)

    def execute(self, context):
        settings = context.scene.video_formation
        wm = context.window_manager
        try:
            report = self._run(context, settings, wm)
        except ValueError as exc:
            settings.last_report = f"ERROR {exc}"
            self.report({"ERROR"}, str(exc))
            _popup(context, [str(exc)], "Video to Formation", "ERROR")
            return {"CANCELLED"}
        except Exception as exc:  # pragma: no cover - surfaced to the user
            traceback.print_exc()
            text = f"{exc.__class__.__name__}: {exc}"
            settings.last_report = f"ERROR {text}"
            self.report({"ERROR"}, text)
            _popup(context, [text, "Details: Window > Toggle System Console"], "Video to Formation", "ERROR")
            return {"CANCELLED"}
        finally:
            try:
                wm.progress_end()
            except Exception:
                pass
        settings.last_report = "\n".join(report)
        print("[video_formation]\n" + settings.last_report)
        level = "WARNING" if any(line.startswith("WARN") for line in report) else "INFO"
        self.report({level}, report[0])
        return {"FINISHED"}

    # ------------------------------------------------------------------ work

    def _run(self, context, settings, wm) -> list[str]:
        from ..blender_io import skybrush, video, viewport

        t_start = time.perf_counter()
        scene = context.scene
        job = plan.read_settings(settings)
        path = resolve_video(settings.video_path)
        decoder = video.choose_decoder(settings.decoder)
        info = video.probe(path, decoder)
        fps_scene = scene_fps(scene)
        light_fps = min(plan.light_fps_value(job, fps_scene), fps_scene)

        screen = plan.build_screen(job, info.width, info.height)
        notes = plan.check_screen(job, screen)
        has_sb = skybrush.available(context)
        name = settings.screen_name or "Video Screen"
        formation = skybrush.find_formation(settings.formation_name, name) if has_sb else None
        positions = screen.positions

        if self.lights_only and has_sb:
            if formation is None:
                raise ValueError(f"No formation '{name}' yet. Press Generate Screen first.")
            markers = list(formation.objects)
            if len(markers) != screen.count:
                raise ValueError(
                    f"The screen settings now give {screen.count} drones but formation "
                    f"'{name}' has {len(markers)} markers. Press Generate Screen to rebuild it."
                )
            positions = np.array([tuple(m.matrix_world.translation) for m in markers])

        # ---- decode + bake (the scene is not touched yet)
        times = sampling.light_times(info.duration, light_fps, job.video_start, job.video_length)
        size = bake.decode_size(screen, job.fit, info.width, info.height)
        n = len(times)
        wm.progress_begin(0, n)
        print(f"[video_formation] reading {n} frames of {os.path.basename(path)} with the "
              f"{decoder.lower()} decoder at {size[0]}x{size[1]} ...")
        t0 = time.perf_counter()

        def progress(done, total):
            wm.progress_update(done)
            if done % 100 == 0 or done == total:
                print(f"[video_formation]   {done}/{total} frames")

        frames = video.read_frames(path, info, times, light_fps, size, decoder, None)
        colors = bake.bake_colors(screen, frames, n, size, job.fit, plan.grade_of(job), progress)
        t_decode = time.perf_counter() - t0
        duration = sampling.scene_frames_for(n, light_fps, fps_scene)

        # ---- the scene: formation, storyboard, then the start frame is known
        lines = []
        start = int(job.start_frame)
        if has_sb:
            what_f = "kept"
            if not self.lights_only:
                formation, what_f = skybrush.put_formation(name, screen.positions, formation)
            if formation is not None:
                settings.formation_name = formation.name
            entry = skybrush.entry_of(context, formation) if formation is not None else None
            if entry is None and settings.add_storyboard and not self.lights_only:
                wanted = None if settings.start_mode == "AUTO" else start
                entry, msg = skybrush.add_storyboard_entry(context, formation, wanted, duration)
                lines.append(msg)
            if entry is not None:
                if int(entry.frame_start) != start and settings.start_mode == "FRAME":
                    notes.append(
                        f"NOTE the video starts at frame {int(entry.frame_start)}, where the "
                        f"storyboard entry '{entry.name}' starts (Start Frame was {start})."
                    )
                start = int(entry.frame_start)
                if int(entry.duration) < duration:
                    notes.append(
                        f"WARN the storyboard entry '{entry.name}' lasts {int(entry.duration)} "
                        f"frames but the video needs {duration}; lengthen the entry or the "
                        "screen leaves before the video ends."
                    )
        elif settings.start_mode == "AUTO":
            start = int(scene.frame_start)
        settings.start_frame = start

        table = lighttable.LightTable(colors, np.asarray(positions, dtype=np.float64), start,
                                      fps_scene, light_fps, screen.spacing)
        folder, folder_note = output_folder(settings)
        if folder_note:
            notes.append(folder_note)
        data_path = os.path.join(folder, lighttable.DATA_NAME)
        lighttable.save(table, data_path)
        script_path = lighttable.write_runtime(folder, name)
        settings.last_table = data_path

        if has_sb:
            mode = settings.light_mode
            image = None
            script_ref = script_path
            if mode == "IMAGE":
                image = _light_image(name, table)
            elif bpy.data.filepath and not folder_note:
                script_ref = bpy.path.relpath(script_path)
            _effect, what_e = skybrush.put_light_effect(
                context, _effect_name(settings), start, duration, mode=mode,
                script_path=script_ref, image=image,
            )
            lines.insert(0, f"Formation '{name}' {what_f}; light effect '{_effect_name(settings)}' "
                            f"{what_e} ({'Image' if mode == 'IMAGE' else 'Function'})")
            lines.append("Skybrush colours the drones once they reach the screen: recalculate "
                         "the transitions (Formations tab) if you have not yet.")
        else:
            first = colors[0].astype(np.float32) / 255.0
            skybrush.fallback_mesh(name, screen.positions, first)
            lines.insert(0, f"WARN Skybrush Studio not found: built mesh '{name}' and the light file only.")
            lines.append(
                f"In Skybrush: make '{name}' a formation, then add a Function light effect "
                f"with file {script_path} and function {lighttable.FUNCTION_NAME}."
            )

        end = start + duration - 1
        if scene.frame_end < end:
            scene.frame_end = end
            notes.append(f"NOTE the scene's end frame was moved to {end} so the whole video fits.")
        if settings.show_preview:
            try:
                viewport.build(name, positions, screen.spacing, data_path, scene)
                lines.append("Viewport preview: collection 'Video Formation Preview' (Material "
                             "Preview shows the colours). Hide it once the drones are there.")
            except Exception as exc:  # the screen and lights are done; say what failed
                traceback.print_exc()
                notes.append(f"WARN the viewport preview could not be built ({exc.__class__.__name__}: "
                             f"{exc}); the formation and the light effect are fine.")
        if not (start <= scene.frame_current <= end):
            scene.frame_set(start)

        settings.result_count = screen.count
        settings.result_frames = duration
        mb = colors.nbytes / 1e6
        head = (f"Screen: {screen.count} drones, {screen.shape.title()} "
                f"{_dims(screen)}, {screen.width_m:.1f} x {screen.height_m:.1f} m, "
                f"spacing {screen.spacing:.2f} m")
        timing = (f"Video {info.width}x{info.height} {info.fps:.2f} fps -> {n} light frames at "
                  f"{light_fps:g} fps = scene frames {start}-{end} "
                  f"({duration / fps_scene:.1f} s at {fps_scene:g} fps)")
        cost = (f"Baked in {t_decode:.1f} s ({decoder.lower()} decoder, {size[0]}x{size[1]}); "
                f"light table {mb:.1f} MB in {folder}")
        report = [head, timing, cost] + lines + notes
        report.append(f"Done in {time.perf_counter() - t_start:.1f} s.")
        return report


def _dims(screen) -> str:
    if screen.shape == "GRID":
        return f"{screen.info['columns']}x{screen.info['rows']}"
    return f"{screen.info['rings']} rings"


def _light_image(name: str, table) -> bpy.types.Image:
    """Image light effect texture: width = scene frames, height = markers, linear."""
    img_name = f"VF {name}"
    old = bpy.data.images.get(img_name)
    if old is not None:
        old.name = img_name + " (old)"
    img = bpy.data.images.new(img_name, width=table.scene_frames, height=table.n_drones, alpha=True)
    try:
        img.colorspace_settings.name = "Linear Rec.709"
    except TypeError:
        img.colorspace_settings.is_data = True
    img.pixels.foreach_set(lighttable.image_buffer(table))
    img.update()
    try:
        img.pack()
    except RuntimeError:
        pass
    if old is not None and old.users == 0:
        bpy.data.images.remove(old)
    return img


class VIDEOFORMATION_OT_use_current_frame(Operator):
    bl_idname = "video_formation.use_current_frame"
    bl_label = "Use Current Frame"
    bl_description = "Start the video at the current frame"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.video_formation
        s.start_frame = int(context.scene.frame_current)
        s.start_mode = "FRAME"
        return {"FINISHED"}


classes = (VIDEOFORMATION_OT_generate, VIDEOFORMATION_OT_use_current_frame)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
