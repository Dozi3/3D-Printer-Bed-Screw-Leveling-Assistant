from __future__ import annotations

from dataclasses import replace
import unittest

import numpy as np

from analysis import AnalysisError, analyse_project, inspect_project_geometry
from mesh_io import build_mesh_grid
from models import (
    BedConfig,
    CoordinateConvention,
    MechanicalModelConfig,
    ProjectData,
    ScrewMeasurement,
    ScrewTurnConfig,
)
from solver import (
    HOLD_THRESHOLD_MM,
    PlaneFit,
    action_for_delta,
    bilinear_interpolate,
    compute_screw_instructions,
    direction_for_action,
    fit_plane,
    format_fractional_turns,
    measurement_to_internal,
    turns_for_delta,
)
from warp import OUTSIDE_MESH_NOTE


class SolverTests(unittest.TestCase):
    def test_measurement_to_internal_top_and_bottom(self) -> None:
        self.assertEqual(measurement_to_internal(12.5, 15.0, 220.0, "top"), (12.5, 205.0))
        self.assertEqual(measurement_to_internal(12.5, 15.0, 220.0, "bottom"), (12.5, 15.0))

    def test_fit_plane_on_synthetic_plane(self) -> None:
        plane = fit_plane(
            [0.0, 1.0, 0.0, 1.0],
            [0.0, 0.0, 1.0, 1.0],
            [1.0, 3.0, 4.0, 6.0],
        )
        self.assertAlmostEqual(plane.a, 2.0)
        self.assertAlmostEqual(plane.b, 3.0)
        self.assertAlmostEqual(plane.c, 1.0)

    def test_analysis_requires_mesh_before_running(self) -> None:
        project = replace(
            _project_with_mesh(build_mesh_grid([[0.0, 0.0], [0.0, 0.0]], 0.0, 200.0, 0.0, 200.0)),
            mesh=None,
        )

        with self.assertRaisesRegex(AnalysisError, "mesh is required"):
            analyse_project(project)

    def test_screw_delta_calculation(self) -> None:
        instructions = compute_screw_instructions(
            PlaneFit(a=0.1, b=-0.05, c=0.0),
            [("A", 0.0, 0.0), ("B", 10.0, 0.0), ("C", 0.0, 10.0)],
            "A",
            ScrewTurnConfig(pitch_mm_per_turn=0.5, clockwise_effect="raise", viewpoint="above"),
            source_model="baseline",
        )
        by_name = {instruction.name: instruction for instruction in instructions}
        self.assertAlmostEqual(by_name["A"].delta_height_mm, 0.0)
        self.assertAlmostEqual(by_name["B"].delta_height_mm, -1.0)
        self.assertAlmostEqual(by_name["C"].delta_height_mm, 0.5)
        self.assertEqual(by_name["B"].action, "lower")
        self.assertEqual(by_name["C"].action, "raise")

    def test_turn_conversion_and_direction_mapping(self) -> None:
        raise_config = ScrewTurnConfig(pitch_mm_per_turn=0.5, clockwise_effect="raise", viewpoint="above")
        lower_config = ScrewTurnConfig(pitch_mm_per_turn=0.5, clockwise_effect="lower", viewpoint="below")

        self.assertAlmostEqual(turns_for_delta(0.25, 0.5), 0.5)
        self.assertEqual(action_for_delta(0.25), "raise")
        self.assertEqual(direction_for_action("raise", raise_config), "CW")
        self.assertEqual(direction_for_action("raise", lower_config), "CW")
        self.assertEqual(format_fractional_turns(0.3125), "5/16")

    def test_hold_threshold_behavior(self) -> None:
        self.assertEqual(action_for_delta(HOLD_THRESHOLD_MM / 2.0), "hold")
        self.assertAlmostEqual(turns_for_delta(HOLD_THRESHOLD_MM / 2.0, 0.5), 0.0)
        custom = ScrewTurnConfig(pitch_mm_per_turn=0.5, hold_threshold_mm=0.05)
        instruction = compute_screw_instructions(
            PlaneFit(a=0.0, b=0.0, c=0.0),
            [("A", 0.0, 0.0), ("B", 1.0, 0.0)],
            "A",
            custom,
            source_model="baseline",
            delta_override_mm={"A": 0.0, "B": 0.03},
        )[1]
        self.assertEqual(instruction.action, "hold")

    def test_invalid_turn_fraction_denominator_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "denominator"):
            format_fractional_turns(0.25, 0)
        with self.assertRaisesRegex(ValueError, "denominator"):
            compute_screw_instructions(
                PlaneFit(a=0.0, b=0.0, c=0.0),
                [("A", 0.0, 0.0), ("B", 1.0, 0.0)],
                "A",
                ScrewTurnConfig(pitch_mm_per_turn=0.5, fraction_denominator=0),
                source_model="baseline",
            )

    def test_bilinear_interpolation(self) -> None:
        value = bilinear_interpolate([0.0, 10.0], [0.0, 10.0], [[0.0, 10.0], [10.0, 20.0]], 5.0, 5.0)
        self.assertAlmostEqual(value, 10.0)

    def test_plane_plus_bowl_warp_keeps_plane_driven_baseline_turns(self) -> None:
        mesh = _mesh_from_plane_and_residual(
            lambda x, y: 0.001 * x + 0.002 * y + 0.1,
            lambda u, v: 0.08 * (u**2 + v**2),
        )
        project = _project_with_mesh(mesh)
        result = analyse_project(project)
        by_name = {instruction.name: instruction for instruction in result.baseline_instructions}

        self.assertAlmostEqual(by_name["Front Left"].delta_height_mm, 0.0, places=6)
        self.assertAlmostEqual(by_name["Front Right"].delta_height_mm, -0.2, places=6)
        self.assertAlmostEqual(by_name["Rear Left"].delta_height_mm, -0.4, places=6)
        self.assertEqual(result.warp_report.classification, "bowl/dish")

    def test_duplicate_internal_positions_fail_before_analysis(self) -> None:
        mesh = build_mesh_grid(
            [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            0.0,
            200.0,
            0.0,
            200.0,
            top_row_is_y_max=True,
        )
        project = ProjectData(
            bed=BedConfig(width_mm=300.0, height_mm=300.0),
            screws=[
                ScrewMeasurement("Front Left", 35.0, 275.0),
                ScrewMeasurement("Front Right", 35.0, 275.0),
                ScrewMeasurement("Rear Left", 275.0, 35.0),
                ScrewMeasurement("Rear Right", 275.0, 35.0),
            ],
            turn_config=ScrewTurnConfig(pitch_mm_per_turn=0.5, clockwise_effect="lower", viewpoint="above"),
            reference_screw_name="Rear Left",
            mesh=mesh,
        )

        with self.assertRaisesRegex(AnalysisError, "share the same internal position"):
            analyse_project(project)

    def test_outside_probe_screws_still_use_plane_based_correction(self) -> None:
        values = []
        for y_mm in np.linspace(235.0, 0.0, 5):
            row = []
            for x_mm in np.linspace(0.0, 235.0, 5):
                row.append((0.001 * x_mm) + (0.002 * y_mm) + 0.1)
            row = [float(cell) for cell in row]
            values.append(row)
        mesh = build_mesh_grid(values, 0.0, 235.0, 0.0, 235.0, top_row_is_y_max=True)
        project = ProjectData(
            bed=BedConfig(width_mm=300.0, height_mm=300.0),
            screws=[
                ScrewMeasurement("Front Left", 35.0, 275.0),
                ScrewMeasurement("Front Right", 265.0, 275.0),
                ScrewMeasurement("Rear Left", 35.0, 35.0),
                ScrewMeasurement("Rear Right", 265.0, 35.0),
            ],
            turn_config=ScrewTurnConfig(pitch_mm_per_turn=0.5, clockwise_effect="lower", viewpoint="above"),
            reference_screw_name="Rear Left",
            mechanical_model=MechanicalModelConfig(enabled=True, preset_name="springs"),
            mesh=mesh,
        )

        result = analyse_project(project)
        baseline = {instruction.name: instruction for instruction in result.baseline_instructions}
        physical = {instruction.name: instruction for instruction in result.physical_instructions}

        self.assertAlmostEqual(baseline["Front Left"].delta_height_mm, 0.48, places=6)
        self.assertAlmostEqual(baseline["Front Right"].delta_height_mm, 0.25, places=6)
        self.assertAlmostEqual(baseline["Rear Right"].delta_height_mm, -0.23, places=6)
        self.assertEqual(baseline["Front Right"].action, "raise")
        self.assertNotEqual(physical["Front Right"].signed_turns, 0.0)
        self.assertIn(OUTSIDE_MESH_NOTE, baseline["Front Right"].notes)
        self.assertIn(OUTSIDE_MESH_NOTE, baseline["Rear Left"].notes)
        self.assertIn(
            "Plane correction still computed; local residual note skipped outside mesh bounds.",
            result.warnings,
        )
        self.assertIn(
            "Plane correction is extrapolated for screw positions outside the probed area.",
            result.warnings,
        )

    def test_mesh_bounds_over_bed_clamp_probe_coverage_and_warn(self) -> None:
        mesh = build_mesh_grid(
            [[0.0, 0.0], [0.0, 0.0]],
            -10.0,
            250.0,
            -10.0,
            250.0,
            top_row_is_y_max=True,
        )
        project = ProjectData(
            bed=BedConfig(width_mm=200.0, height_mm=200.0),
            screws=[
                ScrewMeasurement("A", 20.0, 180.0),
                ScrewMeasurement("B", 180.0, 180.0),
                ScrewMeasurement("C", 20.0, 20.0),
            ],
            turn_config=ScrewTurnConfig(pitch_mm_per_turn=0.5),
            reference_screw_name="A",
            mesh=mesh,
        )

        result = analyse_project(project)
        self.assertAlmostEqual(result.probe_area_summary.coverage_ratio, 1.0)
        self.assertIn(
            "Mesh bounds exceed the physical bed bounds; probe coverage is computed from the overlap only.",
            result.warnings,
        )

    def test_geometry_report_tracks_internal_coordinates_and_probe_status(self) -> None:
        mesh = build_mesh_grid(
            [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            0.0,
            100.0,
            0.0,
            100.0,
            top_row_is_y_max=True,
        )
        project = ProjectData(
            bed=BedConfig(width_mm=200.0, height_mm=200.0),
            screws=[
                ScrewMeasurement("A", 20.0, 180.0),
                ScrewMeasurement("B", 150.0, 50.0),
                ScrewMeasurement("C", 20.0, 180.0),
            ],
            turn_config=ScrewTurnConfig(pitch_mm_per_turn=0.5, clockwise_effect="raise", viewpoint="above"),
            reference_screw_name="A",
            mesh=mesh,
        )

        report = inspect_project_geometry(project)
        by_name = {status.name: status for status in report.screw_statuses}

        self.assertEqual((by_name["A"].x_mm, by_name["A"].y_mm), (20.0, 20.0))
        self.assertTrue(by_name["A"].inside_bed)
        self.assertTrue(by_name["A"].inside_mesh)
        self.assertFalse(by_name["B"].inside_mesh)
        self.assertIn("C", by_name["A"].duplicate_with)
        self.assertTrue(
            any("share the same internal position" in message for message in report.blocking_errors)
        )

    def test_display_front_edge_does_not_change_solver_output(self) -> None:
        mesh = _mesh_from_plane_and_residual(lambda x, y: 0.001 * x + 0.002 * y, lambda u, v: 0.0)
        top_project = _project_with_mesh(mesh)
        bottom_project = replace(
            top_project,
            coordinate_convention=CoordinateConvention(
                screw_y_reference_edge="top",
                display_front_edge="bottom",
            ),
        )

        top_result = analyse_project(top_project)
        bottom_result = analyse_project(bottom_project)

        top_map = {instruction.name: instruction.delta_height_mm for instruction in top_result.baseline_instructions}
        bottom_map = {
            instruction.name: instruction.delta_height_mm for instruction in bottom_result.baseline_instructions
        }
        self.assertEqual(top_map, bottom_map)

    def test_row_order_toggle_changes_mesh_interpretation_not_screw_coordinates(self) -> None:
        values = [
            [0.30, 0.10, -0.10],
            [0.20, 0.00, -0.20],
            [0.10, -0.10, -0.30],
        ]
        top_mesh = build_mesh_grid(values, 0.0, 200.0, 0.0, 200.0, top_row_is_y_max=True)
        bottom_mesh = build_mesh_grid(values, 0.0, 200.0, 0.0, 200.0, top_row_is_y_max=False)
        top_project = _project_with_mesh(top_mesh, mechanical_enabled=False)
        bottom_project = _project_with_mesh(bottom_mesh, mechanical_enabled=False)

        top_geometry = inspect_project_geometry(top_project)
        bottom_geometry = inspect_project_geometry(bottom_project)
        top_coordinates = [(status.name, status.x_mm, status.y_mm) for status in top_geometry.screw_statuses]
        bottom_coordinates = [(status.name, status.x_mm, status.y_mm) for status in bottom_geometry.screw_statuses]

        top_result = analyse_project(top_project)
        bottom_result = analyse_project(bottom_project)
        top_plane = {instruction.name: instruction.delta_height_mm for instruction in top_result.baseline_instructions}
        bottom_plane = {
            instruction.name: instruction.delta_height_mm for instruction in bottom_result.baseline_instructions
        }

        self.assertEqual(top_coordinates, bottom_coordinates)
        self.assertNotEqual(top_mesh.y_coordinates().tolist(), bottom_mesh.y_coordinates().tolist())
        self.assertNotEqual(top_plane, bottom_plane)

    def test_baseline_plane_result_is_unchanged_when_physical_model_is_enabled(self) -> None:
        mesh = _mesh_from_plane_and_residual(
            lambda x, y: 0.0015 * x - 0.0005 * y + 0.05,
            lambda u, v: 0.06 * (u**2 + v**2),
        )
        baseline_project = _project_with_mesh(mesh, mechanical_enabled=False)
        physical_project = _project_with_mesh(mesh, mechanical_enabled=True)

        baseline_result = analyse_project(baseline_project)
        physical_result = analyse_project(physical_project)
        baseline_map = {
            instruction.name: (instruction.delta_height_mm, instruction.signed_turns)
            for instruction in baseline_result.baseline_instructions
        }
        physical_map = {
            instruction.name: (instruction.delta_height_mm, instruction.signed_turns)
            for instruction in physical_result.baseline_instructions
        }

        self.assertEqual(baseline_map, physical_map)


def _project_with_mesh(mesh, *, mechanical_enabled: bool = True) -> ProjectData:
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


if __name__ == "__main__":
    unittest.main()
