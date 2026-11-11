"""Settings -> screen + timing, shared by the Blender operators and the tests.

Pure numpy / stdlib. ``Job`` mirrors the panel; ``read_settings`` copies a
PropertyGroup (or anything with the same attribute names) into one.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

import numpy as np

from . import layout, sampling

LIGHT_FPS = {"15": 15.0, "30": 30.0}


@dataclass
class Job:
    video_path: str = ""
    shape: str = "GRID"
    drone_count: int = 2000
    size_mode: str = "SPACING"   # SPACING | WIDTH
    spacing: float = 1.5
    width: float = 80.0
    aspect_mode: str = "VIDEO"   # VIDEO | CUSTOM (grid only)
    aspect: float = 16.0 / 9.0
    fit: str = "FILL"
    centre_x: float = 0.0
    depth_y: float = 0.0
    bottom_z: float = 40.0
    min_spacing: float = 1.5
    max_altitude: float = 120.0
    start_frame: int = 1
    video_start: float = 0.0
    video_length: float = 0.0    # 0 = to the end
    light_fps: str = "30"        # "15" | "30" | "SCENE"
    brightness: float = 1.0
    saturation: float = 1.0
    black_cut: float = 0.0
    floor: float = 0.01          # dark parts stay faintly lit, like the examples
    max_led: float = 1.0
    smoothing: float = 0.0


def read_settings(settings) -> Job:
    job = Job()
    for f in fields(Job):
        if hasattr(settings, f.name):
            value = getattr(settings, f.name)
            try:
                setattr(job, f.name, type(getattr(job, f.name))(value))
            except (TypeError, ValueError):
                pass
    return job


def screen_aspect(job: Job, video_w: int, video_h: int) -> float:
    if str(job.shape).upper() == "RINGS":
        return 1.0
    if str(job.aspect_mode).upper() == "CUSTOM" and job.aspect > 0:
        return float(job.aspect)
    return float(video_w) / float(max(video_h, 1))


def build_screen(job: Job, video_w: int, video_h: int) -> layout.Screen:
    aspect = screen_aspect(job, video_w, video_h)
    by_width = str(job.size_mode).upper() == "WIDTH"
    return layout.make_screen(
        job.shape,
        int(job.drone_count),
        aspect=aspect,
        spacing=None if by_width else float(job.spacing),
        width_m=float(job.width) if by_width else None,
        centre_x=float(job.centre_x),
        depth_y=float(job.depth_y),
        bottom_z=float(job.bottom_z),
    )


def light_fps_value(job: Job, scene_fps: float) -> float:
    return LIGHT_FPS.get(str(job.light_fps), float(scene_fps))


def grade_of(job: Job) -> sampling.Grade:
    return sampling.Grade(
        brightness=float(job.brightness),
        saturation=float(job.saturation),
        black_cut=float(job.black_cut),
        floor=float(job.floor),
        max_led=float(job.max_led),
        smoothing=float(job.smoothing),
    )


def check_screen(job: Job, screen: layout.Screen) -> list[str]:
    """Warnings (strings starting WARN / NOTE) the report shows."""
    notes = []
    if screen.spacing < job.min_spacing - 1e-6:
        notes.append(
            f"WARN drones are {screen.spacing:.2f} m apart, under Minimum Spacing "
            f"{job.min_spacing:.2f} m. Raise the spacing (or lower the width / drone count)."
        )
    top = float(np.max(screen.positions[:, 2])) if screen.count else 0.0
    if top > job.max_altitude + 1e-6:
        notes.append(
            f"WARN the top of the screen is at {top:.1f} m, above Maximum Altitude "
            f"{job.max_altitude:.0f} m. Lower the bottom altitude or the spacing."
        )
    if screen.count < job.drone_count:
        what = "full rows and columns" if screen.shape == "GRID" else "full rings"
        notes.append(
            f"NOTE the screen uses {screen.count} drones ({what} closest to "
            f"{job.drone_count}, never more). Set the show to {screen.count} drones or "
            "fill the rest with another formation."
        )
    return notes
