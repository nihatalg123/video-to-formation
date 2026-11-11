"""The Video Formation tab in the 3D View sidebar (separate from Image Formation)."""

from __future__ import annotations

import bpy
from bpy.types import Panel

from ..blender_io import video


class VIDEOFORMATION_PT_base(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Video Formation"


class VIDEOFORMATION_PT_main(VIDEOFORMATION_PT_base):
    bl_idname = "VIDEOFORMATION_PT_main"
    bl_label = "Video to Formation"

    def draw(self, context):
        s = context.scene.video_formation
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(s, "video_path")
        col = layout.column(align=True)
        col.prop(s, "video_start")
        col.prop(s, "video_length")
        layout.prop(s, "light_fps")
        layout.prop(s, "decoder")
        if s.decoder != "BLENDER":
            layout.prop(s, "ffmpeg_path")
            try:
                kind, text = video.ffmpeg_status()
            except Exception as exc:  # drawing must never fail
                kind, text = "MISSING", f"FFmpeg check failed: {exc}"
            row = layout.row()
            row.alignment = "RIGHT"
            row.label(text=text, icon="ERROR" if kind == "MISSING" else "CHECKMARK")

        row = layout.row(align=True)
        row.scale_y = 1.4
        row.operator("video_formation.generate", text="Generate Screen", icon="SEQUENCE").lights_only = False
        row = layout.row(align=True)
        row.operator("video_formation.generate", text="Update Lights", icon="LIGHT").lights_only = True
        row.operator("video_formation.preview", icon="IMAGE_DATA")
        layout.operator("video_formation.export_csv", icon="EXPORT")

        if s.result_count:
            layout.label(
                text=f"Screen: {s.result_count} drones, {s.result_frames} frames", icon="INFO"
            )


class VIDEOFORMATION_PT_screen(VIDEOFORMATION_PT_base):
    bl_idname = "VIDEOFORMATION_PT_screen"
    bl_label = "Screen"
    bl_parent_id = "VIDEOFORMATION_PT_main"

    def draw(self, context):
        s = context.scene.video_formation
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(s, "shape", expand=True)
        layout.prop(s, "drone_count")
        layout.prop(s, "size_mode", expand=True)
        layout.prop(s, "spacing" if s.size_mode == "SPACING" else "width")
        if s.shape == "GRID":
            layout.prop(s, "aspect_mode", expand=True)
            if s.aspect_mode == "CUSTOM":
                layout.prop(s, "aspect")
        layout.prop(s, "fit", expand=True)
        col = layout.column(align=True)
        col.prop(s, "centre_x")
        col.prop(s, "depth_y")
        col.prop(s, "bottom_z")
        col = layout.column(align=True)
        col.prop(s, "min_spacing")
        col.prop(s, "max_altitude")


class VIDEOFORMATION_PT_colour(VIDEOFORMATION_PT_base):
    bl_idname = "VIDEOFORMATION_PT_colour"
    bl_label = "Colour"
    bl_parent_id = "VIDEOFORMATION_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = context.scene.video_formation
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        col = layout.column(align=True)
        col.prop(s, "brightness")
        col.prop(s, "saturation")
        col = layout.column(align=True)
        col.prop(s, "black_cut")
        col.prop(s, "floor")
        col.prop(s, "max_led")
        layout.prop(s, "smoothing")


class VIDEOFORMATION_PT_skybrush(VIDEOFORMATION_PT_base):
    bl_idname = "VIDEOFORMATION_PT_skybrush"
    bl_label = "Skybrush"
    bl_parent_id = "VIDEOFORMATION_PT_main"

    def draw(self, context):
        s = context.scene.video_formation
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(s, "screen_name")
        layout.prop(s, "start_mode")
        row = layout.row(align=True)
        row.enabled = s.start_mode == "FRAME"
        row.prop(s, "start_frame")
        row.operator("video_formation.use_current_frame", text="", icon="TIME")
        layout.prop(s, "add_storyboard")
        layout.prop(s, "show_preview")
        layout.prop(s, "light_mode")
        layout.prop(s, "output_folder")


class VIDEOFORMATION_PT_playback(VIDEOFORMATION_PT_base):
    bl_idname = "VIDEOFORMATION_PT_playback"
    bl_label = "Playback"
    bl_parent_id = "VIDEOFORMATION_PT_main"

    def draw(self, context):
        s = context.scene.video_formation
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        row = layout.row(align=True)
        row.operator("video_formation.toggle_preview", text="Show Preview", icon="HIDE_OFF").show = True
        row.operator("video_formation.toggle_preview", text="Hide Preview", icon="HIDE_ON").show = False
        layout.operator("video_formation.fast_playback", icon="PLAY")
        layout.prop(context.scene, "sync_mode", text="Sync")
        layout.prop(s, "light_fps")
        col = layout.column(align=True)
        col.label(text="Smoothest: hide the preview once the drones", icon="INFO")
        col.label(text="show the video; Solid view, Object colours;")
        col.label(text="Light FPS 15.")


class VIDEOFORMATION_PT_report(VIDEOFORMATION_PT_base):
    bl_idname = "VIDEOFORMATION_PT_report"
    bl_label = "Report"
    bl_parent_id = "VIDEOFORMATION_PT_main"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.video_formation.last_report)

    def draw(self, context):
        box = self.layout.box()
        col = box.column(align=True)
        for line in context.scene.video_formation.last_report.splitlines():
            icon = "ERROR" if line.startswith(("WARN", "ERROR")) else "NONE"
            col.label(text=line, icon=icon)


classes = (
    VIDEOFORMATION_PT_main,
    VIDEOFORMATION_PT_screen,
    VIDEOFORMATION_PT_colour,
    VIDEOFORMATION_PT_skybrush,
    VIDEOFORMATION_PT_playback,
    VIDEOFORMATION_PT_report,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
