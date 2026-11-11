"""Preview: the screen at the current frame, as a picture in the Image Editor.

Decodes just the one video frame the current scene frame shows, so framing (fit,
aspect, shape) and colour settings can be checked in a second, before baking.
"""

from __future__ import annotations

import traceback

import bpy
import numpy as np
from bpy.types import Operator

from ..core import bake, plan, preview, sampling
from .generate import resolve_video, scene_fps

IMAGE_NAME = "Video Formation Preview"


def show_image(context, pixels_u8: np.ndarray) -> bpy.types.Image:
    h, w = pixels_u8.shape[:2]
    img = bpy.data.images.get(IMAGE_NAME)
    if img is None or tuple(img.size) != (w, h):
        if img is not None:
            bpy.data.images.remove(img)
        img = bpy.data.images.new(IMAGE_NAME, width=w, height=h, alpha=True)
    rgba = np.ones((h, w, 4), dtype=np.float32)
    rgba[:, :, :3] = pixels_u8[::-1].astype(np.float32) / 255.0
    img.pixels.foreach_set(rgba.ravel())
    img.update()
    for area in context.screen.areas if context.screen else ():
        if area.type == "IMAGE_EDITOR":
            area.spaces.active.image = img
            area.tag_redraw()
            break
    return img


class VIDEOFORMATION_OT_preview(Operator):
    bl_idname = "video_formation.preview"
    bl_label = "Preview Frame"
    bl_description = (
        "Show the screen at the current frame in the Image Editor "
        f"(image '{IMAGE_NAME}'); decodes only this one frame"
    )

    @classmethod
    def poll(cls, context):
        return bool(context.scene.video_formation.video_path)

    def execute(self, context):
        from ..blender_io import video

        settings = context.scene.video_formation
        try:
            job = plan.read_settings(settings)
            path = resolve_video(settings.video_path)
            decoder = video.choose_decoder(settings.decoder)
            info = video.probe(path, decoder)
            fps = scene_fps(context.scene)
            screen = plan.build_screen(job, info.width, info.height)
            offset = max(0, context.scene.frame_current - int(job.start_frame)) / fps
            end = info.duration if job.video_length <= 0 else min(info.duration, job.video_start + job.video_length)
            t = min(job.video_start + offset, max(job.video_start, end - 1.0 / max(info.fps, 1.0)))
            size = bake.decode_size(screen, job.fit, info.width, info.height)
            frames = list(video.read_frames(path, info, np.array([t]), max(info.fps, 1.0), size, decoder))
            if not frames:
                raise ValueError("Could not read a frame at this time of the video.")
            colors = bake.bake_colors(screen, frames, 1, size, job.fit, plan.grade_of(job))[0]
            pic = preview.render(screen.positions, colors / 255.0, screen.spacing, 900)
            show_image(context, pic)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:  # pragma: no cover
            traceback.print_exc()
            self.report({"ERROR"}, f"{exc.__class__.__name__}: {exc}")
            return {"CANCELLED"}
        notes = plan.check_screen(job, screen)
        self.report(
            {"WARNING" if any(n.startswith("WARN") for n in notes) else "INFO"},
            f"Preview at {t:.2f} s: {screen.count} drones, {screen.width_m:.1f} x "
            f"{screen.height_m:.1f} m — open an Image Editor to see '{IMAGE_NAME}'",
        )
        return {"FINISHED"}


classes = (VIDEOFORMATION_OT_preview,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
