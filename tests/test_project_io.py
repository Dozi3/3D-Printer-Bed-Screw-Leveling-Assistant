from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from analysis import analyse_project
from materials import make_library_choice
from mesh_io import build_mesh_grid
from models import (
    BedAssemblyConfig,
    BedConfig,
    CalibrationTrial,
    CoordinateConvention,
    EnvironmentMetadata,
    FastenerConfig,
    MechanicalModelConfig,
    ProjectData,
    ScrewMeasurement,
    SupportAssemblyConfig,
    ScrewTurnConfig,
)
from project_io import ProjectDataError, load_project, save_project


class ProjectIoTests(unittest.TestCase):
    def test_schema_v3_round_trip(self) -> None:
        project = ProjectData(
            bed=BedConfig(width_mm=235.0, height_mm=235.0),
            screws=[
                ScrewMeasurement(name="A", left_mm=20.0, y_measure_mm=20.0),
                ScrewMeasurement(name="B", left_mm=215.0, y_measure_mm=20.0),
                ScrewMeasurement(name="C", left_mm=20.0, y_measure_mm=215.0),
            ],
            turn_config=ScrewTurnConfig(
                pitch_mm_per_turn=0.5,
                clockwise_effect="raise",
                viewpoint="above",
                hold_threshold_mm=0.02,
            ),
            reference_screw_name="A",
            coordinate_convention=CoordinateConvention(
                screw_y_reference_edge="bottom",
                display_front_edge="bottom",
            ),
            mechanical_model=MechanicalModelConfig(
                enabled=True,
                preset_name="silicone",
                self_gain=0.85,
                neighbor_gain=0.15,
                decay_length_mm=140.0,
                max_step_turns=0.0625,
                regularization_lambda=1e-5,
                use_advanced_override=True,
            ),
            metadata=EnvironmentMetadata(
                bed_assembly=BedAssemblyConfig(
                    plate_material=make_library_choice("plate", "cast_aluminum"),
                    surface_material=make_library_choice("surface", "pei_on_spring_steel"),
                ),
                support_assembly=SupportAssemblyConfig(
                    mount_type="silicone",
                    support_material=make_library_choice("support", "silicone_elastomer"),
                    support_stack_height_mm=10.0,
                ),
                fastener=FastenerConfig(
                    screw_material=make_library_choice("screw", "steel"),
                ),
                bed_temperature_c=60.0,
                chamber_temperature_c=35.0,
            ),
            mesh=build_mesh_grid(
                [[0.1, 0.0], [0.05, -0.05]],
                0.0,
                235.0,
                0.0,
                235.0,
                top_row_is_y_max=True,
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "project_v4.json"
            save_project(path, project)
            raw_data = json.loads(path.read_text(encoding="utf-8"))
            loaded = load_project(path)

        self.assertEqual(loaded.schema_version, 4)
        self.assertEqual(loaded.coordinate_convention.screw_y_reference_edge, "bottom")
        self.assertTrue(loaded.mechanical_model.use_advanced_override)
        self.assertAlmostEqual(loaded.turn_config.hold_threshold_mm, 0.02)
        self.assertEqual(loaded.mesh.z_values, project.mesh.z_values)
        self.assertEqual(loaded.metadata.bed_temperature_c, 60.0)
        self.assertEqual(loaded.metadata.bed_assembly.surface_material.library_key, "pei_on_spring_steel")
        self.assertEqual(loaded.metadata.support_assembly.support_material.library_key, "silicone_elastomer")
        self.assertEqual(raw_data["schema_version"], 4)
        self.assertIn("y_measure_mm", raw_data["screws"][0])
        self.assertNotIn("top_mm", raw_data["screws"][0])
        self.assertIn("bed_assembly", raw_data["metadata"])
        self.assertNotIn("bed_material", raw_data["metadata"])

    def test_schema_v4_round_trip_preserves_analysis_outputs(self) -> None:
        project = ProjectData(
            bed=BedConfig(width_mm=200.0, height_mm=200.0),
            screws=[
                ScrewMeasurement("A", 20.0, 180.0),
                ScrewMeasurement("B", 180.0, 180.0),
                ScrewMeasurement("C", 20.0, 20.0),
                ScrewMeasurement("D", 180.0, 20.0),
            ],
            turn_config=ScrewTurnConfig(pitch_mm_per_turn=0.5, clockwise_effect="raise", viewpoint="above"),
            reference_screw_name="A",
            mechanical_model=MechanicalModelConfig(enabled=True, preset_name="springs"),
            mesh=build_mesh_grid(
                [
                    [0.4, 0.5, 0.6],
                    [0.2, 0.3, 0.4],
                    [0.0, 0.1, 0.2],
                ],
                0.0,
                200.0,
                0.0,
                200.0,
                top_row_is_y_max=True,
            ),
        )

        before = analyse_project(project)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "project_v4.json"
            save_project(path, project)
            loaded = load_project(path)
        after = analyse_project(loaded)

        self.assertAlmostEqual(after.plane_fit.a, before.plane_fit.a)
        self.assertAlmostEqual(after.plane_fit.b, before.plane_fit.b)
        self.assertAlmostEqual(after.plane_fit.c, before.plane_fit.c)
        before_instructions = [
            (
                instruction.name,
                round(instruction.delta_height_mm, 9),
                round(instruction.signed_turns, 9),
                instruction.action,
                instruction.direction,
                instruction.rounded_turns,
            )
            for instruction in before.baseline_instructions
        ]
        after_instructions = [
            (
                instruction.name,
                round(instruction.delta_height_mm, 9),
                round(instruction.signed_turns, 9),
                instruction.action,
                instruction.direction,
                instruction.rounded_turns,
            )
            for instruction in after.baseline_instructions
        ]
        self.assertEqual(after_instructions, before_instructions)

    def test_save_rejects_non_finite_runtime_values(self) -> None:
        project = ProjectData(
            bed=BedConfig(width_mm=float("nan"), height_mm=100.0),
            screws=[ScrewMeasurement("A", 0.0, 0.0), ScrewMeasurement("B", 100.0, 0.0), ScrewMeasurement("C", 0.0, 100.0)],
            turn_config=ScrewTurnConfig(pitch_mm_per_turn=0.5),
            reference_screw_name="A",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "non_finite.json"
            with self.assertRaises(ProjectDataError):
                save_project(path, project)

    def test_schema_v1_upgrade_defaults(self) -> None:
        schema_v1 = {
            "schema_version": 1,
            "bed": {"width_mm": 300.0, "height_mm": 300.0},
            "screws": [
                {"name": "Front Left", "left_mm": 35.0, "top_mm": 275.0},
                {"name": "Front Right", "left_mm": 265.0, "top_mm": 275.0},
                {"name": "Rear Left", "left_mm": 35.0, "top_mm": 35.0},
            ],
            "turn_config": {
                "pitch_mm_per_turn": 0.5,
                "clockwise_effect": "lower",
                "viewpoint": "above",
            },
            "reference_screw_name": "Rear Left",
            "metadata": {
                "mount_type": "springs",
                "bed_material": "aluminium",
            },
            "mesh": {
                "z_values": [[0.0, 0.0], [0.0, 0.0]],
                "x_min_mm": 0.0,
                "x_max_mm": 235.0,
                "y_min_mm": 0.0,
                "y_max_mm": 235.0,
                "top_row_is_y_max": True,
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "project_v1.json"
            path.write_text(json.dumps(schema_v1), encoding="utf-8")
            loaded = load_project(path)

        self.assertEqual(loaded.schema_version, 4)
        self.assertEqual(loaded.coordinate_convention.screw_y_reference_edge, "top")
        self.assertEqual(loaded.coordinate_convention.display_front_edge, "top")
        self.assertFalse(loaded.mechanical_model.enabled)
        self.assertEqual(loaded.mechanical_model.preset_name, "springs")
        self.assertFalse(loaded.mechanical_model.use_advanced_override)
        self.assertEqual(loaded.screws[0].y_measure_mm, 275.0)
        self.assertEqual(loaded.metadata.bed_assembly.plate_material.library_key, "cast_aluminum")
        self.assertEqual(loaded.metadata.bed_assembly.surface_material.library_key, "none")
        self.assertEqual(loaded.metadata.support_assembly.mount_type, "springs")
        self.assertEqual(loaded.metadata.support_assembly.support_material.library_key, "spring_steel")
        self.assertEqual(loaded.upgraded_from_schema, 1)

    def test_schema_v2_upgrade_preserves_labels_and_sets_review_marker(self) -> None:
        schema_v2 = {
            "schema_version": 2,
            "bed": {"width_mm": 300.0, "height_mm": 300.0},
            "screws": [
                {"name": "Front Left", "left_mm": 35.0, "y_measure_mm": 275.0},
                {"name": "Front Right", "left_mm": 265.0, "y_measure_mm": 275.0},
                {"name": "Rear Left", "left_mm": 35.0, "y_measure_mm": 35.0},
            ],
            "turn_config": {
                "pitch_mm_per_turn": 0.5,
                "clockwise_effect": "lower",
                "viewpoint": "above",
            },
            "reference_screw_name": "Rear Left",
            "coordinate_convention": {
                "screw_y_reference_edge": "top",
                "display_front_edge": "top",
            },
            "mechanical_model": {
                "enabled": True,
                "preset_name": "silicone",
                "self_gain": 0.85,
                "neighbor_gain": 0.15,
                "decay_length_mm": 140.0,
                "max_step_turns": 0.0625,
                "regularization_lambda": 1e-5,
                "use_advanced_override": False,
            },
            "metadata": {
                "mount_type": "silicone",
                "bed_material": "PEI",
                "standoff_material": "silicone",
                "screw_material": "steel",
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "project_v2.json"
            path.write_text(json.dumps(schema_v2), encoding="utf-8")
            loaded = load_project(path)

        self.assertEqual(loaded.schema_version, 4)
        self.assertEqual(loaded.metadata.bed_assembly.plate_material.library_key, "other")
        self.assertEqual(loaded.metadata.bed_assembly.plate_material.label, "PEI")
        self.assertEqual(loaded.metadata.bed_assembly.surface_material.library_key, "none")
        self.assertEqual(loaded.metadata.support_assembly.support_material.library_key, "silicone_elastomer")
        self.assertEqual(loaded.upgraded_from_schema, 2)

    def test_schema_v4_round_trip_preserves_calibration_trials(self) -> None:
        mesh_before = build_mesh_grid([[0.0, 0.0], [0.0, 0.0]], 0.0, 100.0, 0.0, 100.0)
        mesh_after = build_mesh_grid([[0.1, 0.0], [0.0, -0.1]], 0.0, 100.0, 0.0, 100.0)
        trial = CalibrationTrial(
            name="Trial A",
            before_mesh=mesh_before,
            after_mesh=mesh_after,
            applied_turns={"B": 0.125},
            bed=BedConfig(width_mm=100.0, height_mm=100.0),
            screws=[
                ScrewMeasurement("A", 0.0, 100.0),
                ScrewMeasurement("B", 100.0, 100.0),
                ScrewMeasurement("C", 0.0, 0.0),
            ],
            turn_config=ScrewTurnConfig(pitch_mm_per_turn=0.5),
            reference_screw_name="A",
        )
        project = ProjectData(
            bed=trial.bed,
            screws=trial.screws,
            turn_config=trial.turn_config,
            reference_screw_name="A",
            mesh=mesh_before,
            calibration_trials=[trial],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "project_v4.json"
            save_project(path, project)
            loaded = load_project(path)

        self.assertEqual(loaded.schema_version, 4)
        self.assertEqual(len(loaded.calibration_trials), 1)
        self.assertEqual(loaded.calibration_trials[0].name, "Trial A")
        self.assertAlmostEqual(loaded.calibration_trials[0].applied_turns["B"], 0.125)

    def test_invalid_literals_booleans_and_non_finite_values_are_rejected(self) -> None:
        base = _valid_schema_v4_payload()
        base["turn_config"]["clockwise_effect"] = "sideways"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.json"
            path.write_text(json.dumps(base), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "clockwise_effect"):
                load_project(path)

            base["turn_config"]["clockwise_effect"] = "raise"
            base["mechanical_model"]["enabled"] = "yes"
            path.write_text(json.dumps(base), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "boolean"):
                load_project(path)

            path.write_text('{"schema_version": 4, "bed": {"width_mm": NaN}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid JSON numeric constant"):
                load_project(path)

    def test_schema_v4_rejects_strict_numeric_and_required_field_errors(self) -> None:
        cases = (
            ("schema_version", 4.7, "schema_version"),
            ("schema_version", "4", "schema_version"),
            ("bed.width_mm", True, "bed.width_mm"),
            ("turn_config.fraction_denominator", 16.5, "fraction_denominator"),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.json"
            for field_path, value, message in cases:
                with self.subTest(field_path=field_path):
                    payload = _valid_schema_v4_payload()
                    _set_nested(payload, field_path, value)
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        load_project(path)

            payload = _valid_schema_v4_payload()
            del payload["mechanical_model"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mechanical_model is required"):
                load_project(path)

    def test_schema_v4_rejects_malformed_calibration_trial_payloads(self) -> None:
        payload = _valid_schema_v4_payload()
        payload["calibration_trials"] = [
            {
                "name": "bad trial",
                "before_mesh": {
                    "z_values": [[0.0, 0.0], [0.0, 0.0]],
                    "x_min_mm": 0.0,
                    "x_max_mm": 100.0,
                    "y_min_mm": 0.0,
                    "y_max_mm": 100.0,
                    "top_row_is_y_max": True,
                },
                "applied_turns": {"B": 0.1},
                "bed": {"width_mm": 100.0, "height_mm": 100.0},
                "screws": copy.deepcopy(payload["screws"]),
                "turn_config": copy.deepcopy(payload["turn_config"]),
                "reference_screw_name": "A",
                "coordinate_convention": copy.deepcopy(payload["coordinate_convention"]),
                "metadata": {},
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad_trial.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "calibration_trials\\[1\\].after_mesh is required"):
                load_project(path)


def _valid_schema_v4_payload() -> dict:
    return {
        "schema_version": 4,
        "bed": {"width_mm": 100.0, "height_mm": 100.0},
        "screws": [
            {"name": "A", "left_mm": 0.0, "y_measure_mm": 0.0},
            {"name": "B", "left_mm": 100.0, "y_measure_mm": 0.0},
            {"name": "C", "left_mm": 0.0, "y_measure_mm": 100.0},
        ],
        "turn_config": {
            "pitch_mm_per_turn": 0.5,
            "clockwise_effect": "raise",
            "viewpoint": "above",
            "fraction_denominator": 16,
            "hold_threshold_mm": 0.01,
        },
        "reference_screw_name": "A",
        "coordinate_convention": {
            "screw_y_reference_edge": "top",
            "display_front_edge": "top",
        },
        "mechanical_model": {
            "enabled": True,
            "preset_name": "other",
            "self_gain": 0.85,
            "neighbor_gain": 0.12,
            "decay_length_mm": 140.0,
            "max_step_turns": 0.0625,
            "regularization_lambda": 1e-5,
            "use_advanced_override": False,
        },
        "metadata": {},
        "mesh": None,
        "calibration_trials": [],
    }


def _set_nested(payload: dict, dotted_path: str, value) -> None:
    target = payload
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


if __name__ == "__main__":
    unittest.main()
