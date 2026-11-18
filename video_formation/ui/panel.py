"""The Video Formation tab in the 3D View sidebar (separate from Image Formation)."""

from __future__ import annotations

import bpy
from bpy.types import Panel

from ..blender_io import video
from ..core import plan, textscreen

_TEXT_INFO: dict = {}


def text_info(s) -> tuple[str, str]:
    """(summary, warning) of the text screen the settings give, for the panel. Only
    for the dot fonts (the Font letters need Blender's font engine: after Generate)."""
    if str(s.text_style) == "FONT":
        return "", ""
    key = (s.text, s.text_style, s.text_layout, s.text_height, s.text_margin, s.text_speed,
           s.text_loops, s.text_gap, s.drone_count)
    if key in _TEXT_INFO:
        return _TEXT_INFO[key]
    try:
        tj = plan.read_text_job(s)
        tp = textscreen.plan(tj, int(s.drone_count))
        info = (f"Screen {tp.cols} x {tp.rows} = {tp.count} drones\n"
                f"{tp.visible_letters:.1f} letters visible, {tp.letters_per_second:.1f} letters/s, "
                f"{tp.duration:.1f} s")
        unknown = tp.info.get("unknown") or []
        warn = ("Not in this font (shows as ?): " + " ".join(unknown)) if unknown else ""
    except ValueError as exc:
        info, warn = "", str(exc)
    except Exception as exc:  # drawing must never fail
        info, warn = "", f"{exc.__class__.__name__}: {exc}"
    if len(_TEXT_INFO) > 32:
        _TEXT_INFO.clear()
    _TEXT_INFO[key] = (info, warn)
    return info, warn


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
        row = layout.row()
        row.use_property_split = False
        row.prop(s, "source", expand=True)
        if s.source == "TEXT":
            self._text(layout, s)
        else:
            self._video(layout, s)
        self._buttons(layout, s)

    def _text(self, layout, s):
        layout.prop(s, "text")
        layout.prop(s, "text_style", expand=True)
        if s.text_style == "FONT":
            layout.prop(s, "text_font")
        layout.prop(s, "text_layout", expand=True)
        col = layout.column(align=True)
        col.prop(s, "text_height")
        col.prop(s, "text_margin")
        col = layout.column(align=True)
        col.prop(s, "text_speed")
        col.prop(s, "text_loops")
        if s.text_loops > 1:
            col.prop(s, "text_gap")
        layout.prop(s, "text_smooth")
        layout.prop(s, "text_colour_mode", expand=True)
        if s.text_colour_mode == "SOLID":
            layout.prop(s, "text_colour")
        layout.prop(s, "text_background")
        layout.prop(s, "light_fps")
        info, warn = text_info(s)
        for i, line in enumerate(info.splitlines()):
            layout.label(text=line, icon="INFO" if i == 0 else "BLANK1")
        if warn:
            layout.label(text=warn, icon="ERROR")

    def _video(self, layout, s):
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

    def _buttons(self, layout, s):
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
        text = s.source == "TEXT"
        if not text:
            layout.prop(s, "shape", expand=True)
        layout.prop(s, "drone_count")
        layout.prop(s, "size_mode", expand=True)
        layout.prop(s, "spacing" if s.size_mode == "SPACING" else "width")
        if not text:
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
        text = s.source == "TEXT"
        col = layout.column(align=True)
        col.prop(s, "brightness")
        col.prop(s, "saturation")
        col = layout.column(align=True)
        if not text:
            col.prop(s, "black_cut")
        col.prop(s, "floor")
        col.prop(s, "max_led")
        if not text:
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
        layout.prop(s, "text_screen_name" if s.source == "TEXT" else "screen_name")
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
