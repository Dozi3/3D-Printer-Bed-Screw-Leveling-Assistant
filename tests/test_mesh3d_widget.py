from __future__ import annotations

import os
import unittest

from mesh_io import build_mesh_grid

try:
    from widgets.mesh3d_widget import (
        Mesh3DWidget,
        build_mesh_vertices,
        mesh_value_range,
        nearest_projected_vertex,
        project_mesh_vertices,
    )
except ModuleNotFoundError as exc:
    if exc.name == "PySide6":
        raise unittest.SkipTest("PySide6 is not available in this environment.") from exc
    raise


class Mesh3DWidgetTests(unittest.TestCase):
    def test_build_mesh_vertices_preserves_physical_coordinates(self) -> None:
        mesh = build_mesh_grid(
            [[0.3, 0.1], [0.2, 0.0]],
            10.0,
            110.0,
            20.0,
            220.0,
            top_row_is_y_max=True,
        )
        vertices = build_mesh_vertices(mesh, mesh.z_values)

        self.assertEqual(vertices[0][0].x_mm, 10.0)
        self.assertEqual(vertices[0][0].y_mm, 20.0)
        self.assertEqual(vertices[-1][-1].x_mm, 110.0)
        self.assertEqual(vertices[-1][-1].y_mm, 220.0)
        self.assertEqual(vertices[0][0].z_mm, 0.2)
        self.assertEqual(vertices[-1][-1].z_mm, 0.1)

    def test_value_range_and_projection(self) -> None:
        mesh = build_mesh_grid(
            [[0.2, -0.2], [0.1, -0.1]],
            0.0,
            200.0,
            0.0,
            200.0,
            top_row_is_y_max=True,
        )
        vertices = build_mesh_vertices(mesh, mesh.z_values)
        projected = project_mesh_vertices(
            vertices,
            bed_width_mm=200.0,
            bed_height_mm=200.0,
            viewport_width_px=500,
            viewport_height_px=400,
            yaw_degrees=-40.0,
            pitch_degrees=55.0,
            zoom=1.0,
            pan_x_px=0.0,
            pan_y_px=0.0,
            height_scale=1.5,
        )

        self.assertEqual(mesh_value_range(vertices), (-0.2, 0.2))
        self.assertEqual(len(projected), 2)
        self.assertEqual(len(projected[0]), 2)
        self.assertNotEqual(projected[0][0].screen_x, projected[0][1].screen_x)

    def test_nearest_projected_vertex(self) -> None:
        mesh = build_mesh_grid(
            [[0.0, 0.1], [0.2, 0.3]],
            0.0,
            100.0,
            0.0,
            100.0,
            top_row_is_y_max=True,
        )
        projected = project_mesh_vertices(
            build_mesh_vertices(mesh, mesh.z_values),
            bed_width_mm=100.0,
            bed_height_mm=100.0,
            viewport_width_px=400,
            viewport_height_px=400,
            yaw_degrees=0.0,
            pitch_degrees=45.0,
            zoom=1.0,
            pan_x_px=0.0,
            pan_y_px=0.0,
            height_scale=1.0,
        )
        target = projected[0][0]
        nearest = nearest_projected_vertex(projected, target.screen_x + 2.0, target.screen_y + 2.0)

        self.assertIsNotNone(nearest)
        assert nearest is not None
        self.assertEqual((nearest.vertex.row, nearest.vertex.column), (0, 0))

    def test_widget_constructs_and_accepts_surface_offscreen(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            self.skipTest("PySide6 is not available in this environment.")

        app = QApplication.instance() or QApplication([])
        widget = Mesh3DWidget()
        mesh = build_mesh_grid(
            [[0.0, 0.1], [0.2, 0.3]],
            0.0,
            100.0,
            0.0,
            100.0,
            top_row_is_y_max=True,
        )
        widget.set_surface(100.0, 100.0, mesh, mesh.z_values)
        widget.set_height_scale(2.0)
        widget.reset_view()

        self.assertIn("Click", widget.inspect_text())
        widget.close()
        if QApplication.instance() is app:
            app.quit()


if __name__ == "__main__":
    unittest.main()
