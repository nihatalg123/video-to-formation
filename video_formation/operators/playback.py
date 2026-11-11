"""Playback helpers: show/hide the viewport preview, a light viewport mode, real-time playback."""

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator


class VIDEOFORMATION_OT_toggle_preview(Operator):
    bl_idname = "video_formation.toggle_preview"
    bl_label = "Show Preview"
    bl_description = (
        "Show or hide the viewport preview of the screen. Hide it once the drones show "
        "the video: then it costs nothing during playback"
    )
    bl_options = {"REGISTER", "UNDO"}

    show: BoolProperty(default=True, options={"SKIP_SAVE"})

    def execute(self, context):
        from ..blender_io import viewport

        if bpy.data.collections.get(viewport.COLLECTION) is None:
            self.report({"INFO"}, "No preview yet: press Generate Screen")
            return {"CANCELLED"}
        viewport.set_preview_visible(context, self.show)
        return {"FINISHED"}


class VIDEOFORMATION_OT_fast_playback(Operator):
    bl_idname = "video_formation.fast_playback"
    bl_label = "Fast Playback Setup"
    bl_description = (
        "Solid view with the drones' own colours (what Skybrush recommends; much lighter "
        "than Material Preview) and real-time playback that drops frames instead of "
        "slowing down"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        done = []
        scene = context.scene
        try:
            scene.sync_mode = "FRAME_DROP"
            done.append("playback drops frames to keep real time")
        except (AttributeError, TypeError):
            pass
        screen = context.screen
        for area in screen.areas if screen else ():
            if area.type != "VIEW_3D":
                continue
            shading = area.spaces.active.shading
            shading.type = "SOLID"
            try:
                shading.color_type = "OBJECT"
            except TypeError:
                pass
            done.append("3D view: Solid, Object colours")
            break
        self.report({"INFO"}, "; ".join(done) or "Nothing to change")
        return {"FINISHED"}


classes = (VIDEOFORMATION_OT_toggle_preview, VIDEOFORMATION_OT_fast_playback)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
