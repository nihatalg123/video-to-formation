"""Export the screen as a Skybrush static CSV, coloured like the current frame.

Same file format as Image to Formation (Name, x, y, z, Red, Green, Blue; colours
linear 0-255), for workflows that import formations from CSV. The video itself
lives in the light effect, not in this file.
"""

# No `from __future__ import annotations`: Blender reads property annotations
# as real objects when registering the class.

import csv
import os

import bpy
import numpy as np
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper

from ..core import lighttable

HEADER = ("Name", "x [m]", "y [m]", "z [m]", "Red", "Green", "Blue")


def _fmt(v: float) -> str:
    text = f"{float(v):.3f}"
    return "0.000" if text == "-0.000" else text


def write_csv(path: str, positions: np.ndarray, colors_u8: np.ndarray) -> int:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle, lineterminator="\n")
        w.writerow(HEADER)
        for i, ((x, y, z), (r, g, b)) in enumerate(zip(positions.tolist(), colors_u8.astype(int).tolist())):
            w.writerow((f"Drone {i + 1}", _fmt(x), _fmt(y), _fmt(z), r, g, b))
    return int(positions.shape[0])


class VIDEOFORMATION_OT_export_csv(Operator, ExportHelper):
    bl_idname = "video_formation.export_csv"
    bl_label = "Export Screen CSV"
    bl_description = "Write the screen as a Skybrush static CSV, coloured like the current frame"
    filename_ext = ".csv"
    filter_glob: StringProperty(default="*.csv", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        path = context.scene.video_formation.last_table
        return bool(path) and os.path.isfile(path)

    def execute(self, context):
        settings = context.scene.video_formation
        try:
            table = lighttable.load(settings.last_table)
            col = table.column(context.scene.frame_current)
            n = write_csv(self.filepath, table.positions, table.colors[col])
        except (OSError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Wrote {n} drones to {self.filepath} (colours of light frame {col + 1})")
        return {"FINISHED"}


classes = (VIDEOFORMATION_OT_export_csv,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
