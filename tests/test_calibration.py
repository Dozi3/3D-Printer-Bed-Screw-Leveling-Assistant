from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

import numpy as np

from analysis import analyse_project
from calibration import CalibrationError, fit_calibration_trials
from mechanics import build_coupling_matrix
from mesh_io import build_mesh_grid
from models import (
    BedConfig,
    CalibrationTrial,
    CoordinateConvention,
    EnvironmentMetadata,
    MechanicalModelConfig,
    ProjectData,
    ScrewMeasurement,
    ScrewTurnConfig,
)


class CalibrationTests(unittest.TestCase):
    def test_synthetic_calibration_recovers_known_coupling(self) -> None:
        known = MechanicalModelConfig(
            enabled=True,
            preset_name="other",
            self_gain=0.9,
            neighbor_gain=0.1,
            decay_length_mm=150.0,
            use_advanced_override=True,
        )
        trials = _synthetic_trials(known)

        result = fit_calibration_trials(trials, MechanicalModelConfig(preset_name="other"))

        self.assertAlmostEqual(result.mechanical_model.self_gain, 0.9, delta=0.02)
        self.assertAlmostEqual(result.mechanical_model.neighbor_gain, 0.1, delta=0.02)
        self.assertAlmostEqual(result.mechanical_model.decay_length_mm, 150.0, delta=2.0)
        self.assertTrue(result.mechanical_model.use_advanced_override)
        self.assertLess(result.residual_rms_mm, 0.001)

    def test_applying_fitted_calibration_does_not_change_baseline_instructions(self) -> None:
        known = MechanicalModelConfig(
            enabled=True,
            preset_name="other",
            self_gain=0.9,
            neighbor_gain=0.1,
            decay_length_mm=150.0,
            use_advanced_override=True,
        )
        trials = _synthetic_trials(known)
        mesh = build_mesh_grid(
            [[0.2, 0.1, 0.0], [0.1, 0.0, -0.1], [0.0, -0.1, -0.2]],
            0.0,
            200.0,
            0.0,
            200.0,
        )
        project = ProjectData(
            bed=trials[0].bed,
            screws=trials[0].screws,
            turn_config=trials[0].turn_config,
            reference_screw_name="A",
            coordinate_convention=trials[0].coordinate_convention,
            mechanical_model=MechanicalModelConfig(enabled=True, preset_name="other"),
            mesh=mesh,
            calibration_trials=trials,
        )
        before = analyse_project(project)
        fitted = fit_calibration_trials(trials, project.mechanical_model).mechanical_model
        after = analyse_project(replace(project, mechanical_model=fitted))

        before_map = {instruction.name: instruction.delta_height_mm for instruction in before.baseline_instructions}
        after_map = {instruction.name: instruction.delta_height_mm for instruction in after.baseline_instructions}
        self.assertEqual(before_map, after_map)

    def test_fitted_calibration_enables_physical_model(self) -> None:
        trials = _synthetic_trials(MechanicalModelConfig(self_gain=0.9, neighbor_gain=0.1, decay_length_mm=150.0))

        result = fit_calibration_trials(trials, MechanicalModelConfig(enabled=False, preset_name="other"))

        self.assertTrue(result.mechanical_model.enabled)
        self.assertTrue(result.mechanical_model.use_advanced_override)

    def test_fitted_calibration_persists_in_project_file(self) -> None:
        from project_io import load_project, save_project

        trials = _synthetic_trials(MechanicalModelConfig(self_gain=0.9, neighbor_gain=0.1, decay_length_mm=150.0))
        fitted = fit_calibration_trials(trials, MechanicalModelConfig(enabled=False, preset_name="other")).mechanical_model
        project = ProjectData(
            bed=trials[0].bed,
            screws=trials[0].screws,
            turn_config=trials[0].turn_config,
            reference_screw_name="A",
            coordinate_convention=trials[0].coordinate_convention,
            mechanical_model=fitted,
            mesh=trials[0].before_mesh,
            calibration_trials=trials,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "calibrated.json"
            save_project(path, project)
            loaded = load_project(path)

        self.assertTrue(loaded.mechanical_model.enabled)
        self.assertTrue(loaded.mechanical_model.use_advanced_override)
        self.assertAlmostEqual(loaded.mechanical_model.self_gain, fitted.self_gain)
        self.assertAlmostEqual(loaded.mechanical_model.neighbor_gain, fitted.neighbor_gain)
        self.assertAlmostEqual(loaded.mechanical_model.decay_length_mm, fitted.decay_length_mm)

    def test_calibration_rejects_duplicate_screw_names(self) -> None:
        trials = _synthetic_trials(MechanicalModelConfig(self_gain=0.9, neighbor_gain=0.1, decay_length_mm=150.0))
        bad_screws = [
            ScrewMeasurement("A", 0.0, 200.0),
            ScrewMeasurement("A", 200.0, 200.0),
            ScrewMeasurement("C", 0.0, 0.0),
        ]

        with self.assertRaisesRegex(CalibrationError, "duplicate screw names"):
            fit_calibration_trials([replace(trials[0], screws=bad_screws)], MechanicalModelConfig())

    def test_calibration_rejects_duplicate_internal_positions(self) -> None:
        trials = _synthetic_trials(MechanicalModelConfig(self_gain=0.9, neighbor_gain=0.1, decay_length_mm=150.0))
        bad_screws = [
            ScrewMeasurement("A", 0.0, 200.0),
            ScrewMeasurement("B", 0.0, 200.0),
            ScrewMeasurement("C", 0.0, 0.0),
        ]

        with self.assertRaisesRegex(CalibrationError, "duplicate internal screw positions"):
            fit_calibration_trials(
                [replace(trials[0], screws=bad_screws, applied_turns={"B": 0.2})],
                MechanicalModelConfig(),
            )

    def test_calibration_rejects_mismatched_before_after_mesh_bounds(self) -> None:
        trials = _synthetic_trials(MechanicalModelConfig(self_gain=0.9, neighbor_gain=0.1, decay_length_mm=150.0))
        mismatched_after = build_mesh_grid(
            [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            0.0,
            180.0,
            0.0,
            200.0,
        )

        with self.assertRaisesRegex(CalibrationError, "matching bounds"):
            fit_calibration_trials([replace(trials[0], after_mesh=mismatched_after)], MechanicalModelConfig())

    def test_calibration_rejects_screws_outside_trial_mesh(self) -> None:
        trials = _synthetic_trials(MechanicalModelConfig(self_gain=0.9, neighbor_gain=0.1, decay_length_mm=150.0))
        bad_screws = [
            ScrewMeasurement("A", 0.0, 200.0),
            ScrewMeasurement("B", 250.0, 200.0),
            ScrewMeasurement("C", 0.0, 0.0),
        ]

        with self.assertRaisesRegex(CalibrationError, "outside the before calibration mesh bounds"):
            fit_calibration_trials(
                [replace(trials[0], screws=bad_screws, applied_turns={"B": 0.2})],
                MechanicalModelConfig(),
            )

    def test_calibration_rejects_non_finite_applied_turns(self) -> None:
        trials = _synthetic_trials(MechanicalModelConfig(self_gain=0.9, neighbor_gain=0.1, decay_length_mm=150.0))

        with self.assertRaisesRegex(CalibrationError, "must be finite"):
            fit_calibration_trials(
                [replace(trials[0], applied_turns={"B": float("inf")})],
                MechanicalModelConfig(),
            )


def _synthetic_trials(config: MechanicalModelConfig) -> list[CalibrationTrial]:
    bed = BedConfig(200.0, 200.0)
    screws = [
        ScrewMeasurement("A", 0.0, 200.0),
        ScrewMeasurement("B", 200.0, 200.0),
        ScrewMeasurement("C", 0.0, 0.0),
        ScrewMeasurement("D", 200.0, 0.0),
        ScrewMeasurement("E", 100.0, 100.0),
    ]
    positions = [
        ("A", 0.0, 0.0),
        ("B", 200.0, 0.0),
        ("C", 0.0, 200.0),
        ("D", 200.0, 200.0),
        ("E", 100.0, 100.0),
    ]
    turn_config = ScrewTurnConfig(pitch_mm_per_turn=0.5)
    matrix = build_coupling_matrix(positions, config)
    command_sets = [
        {"B": 0.2, "C": -0.1, "E": 0.1},
        {"B": -0.15, "D": 0.1},
        {"C": 0.25, "B": 0.05, "D": -0.05},
        {"A": 0.1, "D": 0.2, "E": -0.1},
        {"E": 0.3},
    ]
    trials: list[CalibrationTrial] = []
    before_mesh = build_mesh_grid(
        [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        0.0,
        200.0,
        0.0,
        200.0,
    )
    for index, turns in enumerate(command_sets, start=1):
        command_mm = np.asarray(
            [turns.get(name, 0.0) * turn_config.pitch_mm_per_turn for name, _, _ in positions],
            dtype=float,
        )
        achieved = matrix @ command_mm
        after_mesh = build_mesh_grid(
            [
                [float(achieved[2]), 0.0, float(achieved[3])],
                [0.0, float(achieved[4]), 0.0],
                [float(achieved[0]), 0.0, float(achieved[1])],
            ],
            0.0,
            200.0,
            0.0,
            200.0,
        )
        trials.append(
            CalibrationTrial(
                name=f"Trial {index}",
                before_mesh=before_mesh,
                after_mesh=after_mesh,
                applied_turns=turns,
                bed=bed,
                screws=screws,
                turn_config=turn_config,
                reference_screw_name="A",
                coordinate_convention=CoordinateConvention("top", "top"),
                metadata=EnvironmentMetadata(),
            )
        )
    return trials


if __name__ == "__main__":
    unittest.main()
