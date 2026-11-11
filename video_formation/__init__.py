"""Video to Formation — play a video on a drone screen in Skybrush Studio.

A separate extension from Image to Formation, with its own sidebar tab. Builds one
fixed screen formation (Grid or Rings) and bakes the video onto its LEDs as a
Skybrush light effect. See DEVELOPMENT.md.
"""

from __future__ import annotations

from .blender_io import viewport
from .operators import export_csv, generate, playback, preview
from .ui import panel, properties

_MODULES = (properties, generate, preview, export_csv, playback, panel, viewport)


def register() -> None:
    for module in _MODULES:
        module.register()


def unregister() -> None:
    for module in reversed(_MODULES):
        module.unregister()
