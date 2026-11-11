"""Settings of the Video Formation panel: ``scene.video_formation``."""

# No `from __future__ import annotations`: Blender reads property annotations
# as real objects when registering the class.

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


class VideoFormationSettings(PropertyGroup):
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
