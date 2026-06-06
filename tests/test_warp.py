from __future__ import annotations

import unittest

import numpy as np

from analysis import analyse_project
from mesh_io import build_mesh_grid
from models import BedConfig, MechanicalModelConfig, ProjectData, ScrewMeasurement, ScrewTurnConfig
from warp import classify_warp


class WarpTests(unittest.TestCase):
    def test_bowl_classification(self) -> None:
        mesh, residual = _residual_mesh(lambda u, v: 0.08 * (u**2 + v**2))
        report = classify_warp(mesh, residual)
        self.assertTrue(report.enabled)
        self.assertEqual(report.classification, "bowl/dish")

    def test_saddle_classification(self) -> None:
        mesh, residual = _residual_mesh(lambda u, v: 0.08 * (u * v))
        report = classify_warp(mesh, residual)
        self.assertEqual(report.classification, "saddle/twist-like")

    def test_local_defect_flagged_without_over_correcting_baseline(self) -> None:
        plane_only = _mesh_from_plane_and_residual(lambda x, y: 0.001 * x - 0.0015 * y + 0.2, lambda u, v: 0.0)
        defect_mesh = _mesh_from_plane_and_residual(
            lambda x, y: 0.001 * x - 0.0015 * y + 0.2,
            lambda u, v: 0.18 if abs(u) < 0.01 and abs(v) < 0.01 else 0.0,
        )
        plane_result = analyse_project(_project_with_mesh(plane_only))
        defect_result = analyse_project(_project_with_mesh(defect_mesh))
        plane_by_name = {instruction.name: instruction for instruction in plane_result.baseline_instructions}
        defect_by_name = {instruction.name: instruction for instruction in defect_result.baseline_instructions}

        self.assertEqual(defect_result.warp_report.classification, "local defect / isolated bump or dip")
        self.assertIn("high local residual nearby", defect_by_name["Centre"].notes)
        self.assertAlmostEqual(
            defect_by_name["Front Right"].delta_height_mm,
            plane_by_name["Front Right"].delta_height_mm,
            places=6,
        )

    def test_physical_model_does_not_change_warp_classification(self) -> None:
        mesh = _mesh_from_plane_and_residual(lambda x, y: 0.001 * x + 0.002 * y, lambda u, v: 0.08 * (v**2))
        baseline_project = _project_with_mesh(mesh, mechanical_enabled=False)
        physical_project = _project_with_mesh(mesh, mechanical_enabled=True)
        baseline_result = analyse_project(baseline_project)
        physical_result = analyse_project(physical_project)
        self.assertEqual(baseline_result.warp_report.classification, physical_result.warp_report.classification)

    def test_classification_disabled_for_sparse_mesh(self) -> None:
        mesh = build_mesh_grid([[0.0, 0.0], [0.0, 0.0]], 0.0, 10.0, 0.0, 10.0, top_row_is_y_max=True)
        report = classify_warp(mesh, mesh.z_values)
        self.assertFalse(report.enabled)


def _residual_mesh(residual_func):
    x_coords = np.linspace(0.0, 200.0, 5)
    y_coords = np.linspace(200.0, 0.0, 5)
    residual = []
    for y_mm in y_coords:
        row = []
        for x_mm in x_coords:
            u = (x_mm - 100.0) / 100.0
            v = (y_mm - 100.0) / 100.0
            row.append(residual_func(u, v))
        residual.append(row)
    mesh = build_mesh_grid(residual, 0.0, 200.0, 0.0, 200.0, top_row_is_y_max=True)
    return mesh, residual


def _mesh_from_plane_and_residual(plane_func, residual_func):
    x_coords = np.linspace(0.0, 200.0, 5)
    y_coords = np.linspace(200.0, 0.0, 5)
    values = []
    for y_mm in y_coords:
        row = []
        for x_mm in x_coords:
            u = (x_mm - 100.0) / 100.0
            v = (y_mm - 100.0) / 100.0
            row.append(plane_func(x_mm, y_mm) + residual_func(u, v))
        values.append(row)
    return build_mesh_grid(values, 0.0, 200.0, 0.0, 200.0, top_row_is_y_max=True)


def _project_with_mesh(mesh, *, mechanical_enabled: bool = False) -> ProjectData:
    return ProjectData(
        bed=BedConfig(width_mm=200.0, height_mm=200.0),
        screws=[
            ScrewMeasurement("Front Left", 0.0, 200.0),
            ScrewMeasurement("Front Right", 200.0, 200.0),
            ScrewMeasurement("Rear Left", 0.0, 0.0),
            ScrewMeasurement("Rear Right", 200.0, 0.0),
            ScrewMeasurement("Centre", 100.0, 100.0),
        ],
        turn_config=ScrewTurnConfig(pitch_mm_per_turn=0.5, clockwise_effect="raise", viewpoint="above"),
        reference_screw_name="Front Left",
        mechanical_model=MechanicalModelConfig(enabled=mechanical_enabled, preset_name="springs"),
        mesh=mesh,
    )


if __name__ == "__main__":
    unittest.main()
