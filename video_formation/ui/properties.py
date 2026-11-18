"""Settings of the Video Formation panel: ``scene.video_formation``."""

# No `from __future__ import annotations`: Blender reads property annotations
# as real objects when registering the class.

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


class VideoFormationSettings(PropertyGroup):
    source: EnumProperty(
        name="Source",
        description="What the screen shows",
        items=[
            ("VIDEO", "Video", "Play a video file on a Grid or Rings screen", "SEQUENCE", 0),
            ("TEXT", "Text", "Scroll a text from right to left on a screen sized to the text",
             "FONT_DATA", 1),
        ],
        default="VIDEO",
    )

    # ----------------------------------------------------------------- video
    video_path: StringProperty(
        name="Video",
        description="The video to play on the drones (mp4, mov, ...). 30 fps or less is plenty",
        subtype="FILE_PATH",
    )
    video_start: FloatProperty(
        name="Start At (s)",
        description="Start this many seconds into the video",
        default=0.0, min=0.0, soft_max=600.0,
    )
    video_length: FloatProperty(
        name="Length (s)",
        description="Play this many seconds of the video (0 = to the end)",
        default=0.0, min=0.0, soft_max=600.0,
    )
    light_fps: EnumProperty(
        name="Light FPS",
        description="How many times a second the drone colours change",
        items=[
            ("15", "15 fps", "Colours change 15 times a second: half the data, lighter to play back", 0),
            ("30", "30 fps", "Colours change 30 times a second: smoothest", 1),
            ("SCENE", "Scene fps", "Every frame of the scene", 2),
        ],
        default="30",
    )
    decoder: EnumProperty(
        name="Decoder",
        description="How the video is read",
        items=[
            ("AUTO", "Auto", "FFmpeg if it is installed, otherwise Blender's own video reader", 0),
            ("FFMPEG", "FFmpeg", "Fastest; needs FFmpeg installed (brew install ffmpeg)", 1),
            ("BLENDER", "Blender", "Blender's own video reader; nothing to install, slower", 2),
        ],
        default="AUTO",
    )

    ffmpeg_path: StringProperty(
        name="FFmpeg",
        description=(
            "Optional: the ffmpeg program, if it is not found by itself (PATH, "
            "/opt/homebrew/bin, /usr/local/bin). ffprobe is not needed"
        ),
        subtype="FILE_PATH",
        default="",
    )

    # ------------------------------------------------------------------ text
    text: StringProperty(
        name="Text",
        description=(
            "The text that scrolls across the screen (one line). English and Turkish letters, "
            "digits, punctuation and ♥"
        ),
        default="VIDEO TO FORMATION",
    )
    text_style: EnumProperty(
        name="Letters",
        description="How the letters are drawn",
        items=[
            ("LED", "LED", "Dot-matrix letters, 7 drones high (or 14, 21 ...), thin strokes; "
             "upper and lower case", 0),
            ("BLOCK", "Block", "Chunky capitals, 5 drones high (or 10, 15 ...); with Big "
             "Letters 100 drones make a 10 x 10 screen with 2-drone strokes", 1),
            ("FONT", "Font", "Smooth letters from any font file (.ttf / .otf), any height; "
             "best from about 10 rows", 2),
        ],
        default="LED",
    )
    text_layout: EnumProperty(
        name="Screen",
        description="The shape of the text screen",
        items=[
            ("BANNER", "Banner", "Wide: the biggest letters that still show about 4-5 at "
             "once. For sentences", 0),
            ("BIG", "Big Letters", "About square: letters as big as the screen, one or two at "
             "a time. For short words", 1),
        ],
        default="BANNER",
    )
    text_font: StringProperty(
        name="Font File",
        description="A .ttf / .otf font for the Font letters (empty = Blender's built-in font)",
        subtype="FILE_PATH",
        default="",
    )
    text_height: IntProperty(
        name="Text Height",
        description=(
            "Rows of drones the letters are high (0 = automatic, from the Screen shape and the "
            "drone count). LED letters use multiples of 7, Block multiples of 5"
        ),
        default=0, min=0, soft_max=60,
    )
    text_margin: IntProperty(
        name="Margin Rows",
        description="Empty rows of drones above and below the text",
        default=0, min=0, max=10,
    )
    text_speed: FloatProperty(
        name="Speed",
        description=(
            "Letters per second (0 = automatic: 2 on a banner, slower when only a letter or "
            "two fit so each stays about 3 s on screen)"
        ),
        default=0.0, min=0.0, soft_max=10.0,
    )
    text_loops: IntProperty(
        name="Passes",
        description="How many times the text crosses the screen",
        default=1, min=1, soft_max=20,
    )
    text_gap: FloatProperty(
        name="Gap",
        description="Empty space between two passes, in letters",
        default=3.0, min=0.0, soft_max=20.0,
    )
    text_smooth: BoolProperty(
        name="Smooth Motion",
        description=(
            "Move the letters by fractions of a drone, so they glide (off: they jump one "
            "drone at a time, like an LED sign)"
        ),
        default=True,
    )
    text_colour_mode: EnumProperty(
        name="Colour",
        items=[
            ("SOLID", "Solid", "One colour for the text", 0),
            ("RAINBOW", "Rainbow", "The colours of the rainbow along the text", 1),
        ],
        default="SOLID",
    )
    text_colour: FloatVectorProperty(
        name="Text Colour", subtype="COLOR_GAMMA", size=3, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0),
    )
    text_background: FloatVectorProperty(
        name="Background", subtype="COLOR_GAMMA", size=3, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0),
        description="Colour of the drones that are not part of a letter (Minimum LED still applies)",
    )
    text_screen_name: StringProperty(
        name="Name", description="Name of the text screen's formation and of its light effect",
        default="Text Screen",
    )
    text_formation_name: StringProperty(
        default="", options={"HIDDEN"},
        description="The text screen's formation as Skybrush named it (may end in .001)",
    )

    # ---------------------------------------------------------------- screen
    shape: EnumProperty(
        name="Shape",
        description="The drone screen the video plays on",
        items=[
            ("GRID", "Grid", "Rows and columns: a rectangular screen", 0),
            ("RINGS", "Rings", "Concentric circles: a round screen", 1),
        ],
        default="GRID",
    )
    drone_count: IntProperty(
        name="Drone Count",
        description=(
            "Drones for the screen. It uses the closest full grid or full set of rings "
            "at or under this number"
        ),
        default=2000, min=1, soft_max=10000,
    )
    size_mode: EnumProperty(
        name="Size By",
        items=[
            ("SPACING", "Spacing", "Set the distance between neighbouring drones", 0),
            ("WIDTH", "Width", "Set the screen's width; the spacing follows", 1),
        ],
        default="SPACING",
    )
    spacing: FloatProperty(
        name="Spacing", description="Distance between neighbouring drones",
        default=1.5, min=0.3, soft_min=1.0, soft_max=5.0, unit="LENGTH",
    )
    width: FloatProperty(
        name="Width", description="Width of the screen (diameter for Rings)",
        default=80.0, min=1.0, soft_max=400.0, unit="LENGTH",
    )
    aspect_mode: EnumProperty(
        name="Aspect",
        items=[
            ("VIDEO", "Video", "The grid has the video's aspect ratio", 0),
            ("CUSTOM", "Custom", "Choose the grid's width / height", 1),
        ],
        default="VIDEO",
    )
    aspect: FloatProperty(
        name="Width / Height", default=16.0 / 9.0, min=0.1, max=10.0,
    )
    fit: EnumProperty(
        name="Fit",
        description="How the video is placed on the screen when their shapes differ",
        items=[
            ("FILL", "Fill", "Crop the video so it fills the whole screen", 0),
            ("FIT", "Fit", "Show the whole video; the rest of the screen stays dark", 1),
            ("STRETCH", "Stretch", "Stretch the video to the screen", 2),
        ],
        default="FILL",
    )
    centre_x: FloatProperty(name="Centre X", default=0.0, unit="LENGTH")
    depth_y: FloatProperty(name="Depth Y", default=0.0, unit="LENGTH")
    bottom_z: FloatProperty(
        name="Bottom Altitude", description="Altitude of the screen's lowest drones",
        default=40.0, min=0.0, unit="LENGTH",
    )
    min_spacing: FloatProperty(
        name="Minimum Spacing", description="Warn when drones are closer than this",
        default=1.5, min=0.1, unit="LENGTH",
    )
    max_altitude: FloatProperty(
        name="Maximum Altitude", description="Warn when the screen goes higher",
        default=120.0, min=1.0, unit="LENGTH",
    )

    # ---------------------------------------------------------------- colour
    brightness: FloatProperty(
        name="Brightness", description="Multiplies the video's light", default=1.0, min=0.0, soft_max=4.0,
    )
    saturation: FloatProperty(
        name="Saturation", default=1.0, min=0.0, soft_max=2.0,
    )
    black_cut: FloatProperty(
        name="Black Cut",
        description="Drones darker than this turn off (hides dark noise of the video)",
        default=0.0, min=0.0, max=0.5,
    )
    floor: FloatProperty(
        name="Minimum LED",
        description=(
            "Every drone glows at least this much (linear), so the screen's shape stays "
            "visible in dark scenes. 0 = black parts of the video turn drones off"
        ),
        default=0.01, min=0.0, max=0.5,
    )
    max_led: FloatProperty(
        name="Maximum LED", description="Cap on every colour channel", default=1.0, min=0.05, max=1.0,
    )
    smoothing: FloatProperty(
        name="Smoothing",
        description="Blend each light frame with the last one: calms flicker of noisy videos",
        default=0.0, min=0.0, max=0.9,
    )

    # -------------------------------------------------------------- skybrush
    screen_name: StringProperty(
        name="Name", description="Name of the formation and of its light effect", default="Video Screen",
    )
    start_mode: EnumProperty(
        name="Start",
        items=[
            ("AUTO", "After Last Entry",
             "Skybrush places the screen after the last storyboard entry (plus its "
             "transition time); the video starts there", 0),
            ("FRAME", "At Frame", "Start the screen and the video at Start Frame", 1),
        ],
        default="AUTO",
    )
    start_frame: IntProperty(
        name="Start Frame", description="Scene frame where the video starts", default=1,
    )
    show_preview: BoolProperty(
        name="Viewport Preview",
        description=(
            "Also build a preview object that plays the video in the viewport right away "
            "(Material Preview), before the drones reach the screen"
        ),
        default=True,
    )
    add_storyboard: BoolProperty(
        name="Add to Storyboard",
        description="Put the screen formation in the storyboard for the length of the video",
        default=True,
    )
    light_mode: EnumProperty(
        name="Lights As",
        items=[
            ("FUNCTION", "Light Table (fast)",
             "A Function light effect reads the baked colours: small and quick to play back", 0),
            ("IMAGE", "Image",
             "An Image light effect (no script); uses much more memory for long videos", 1),
        ],
        default="FUNCTION",
    )
    output_folder: StringProperty(
        name="Output Folder",
        description="Where the baked light table is kept (// = next to the .blend)",
        default="//video_formation/", subtype="DIR_PATH",
    )

    # --------------------------------------------------------------- results
    formation_name: StringProperty(
        default="", options={"HIDDEN"},
        description="The screen's formation as Skybrush named it (may end in .001)",
    )
    result_count: IntProperty(default=0, options={"HIDDEN"})
    result_frames: IntProperty(default=0, options={"HIDDEN"})
    last_table: StringProperty(default="", options={"HIDDEN"})
    last_report: StringProperty(default="", options={"HIDDEN"})


classes = (VideoFormationSettings,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.video_formation = PointerProperty(type=VideoFormationSettings)


def unregister() -> None:
    del bpy.types.Scene.video_formation
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
