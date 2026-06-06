from __future__ import annotations

import unittest

from materials import make_library_choice
from mechanics import (
    MechanicalModelError,
    build_coupling_matrix,
    default_mechanical_config,
    build_turn_plan,
    coupling_warnings,
    effective_mechanical_config,
    resolve_effective_mechanical_model,
    solve_physical_response,
)
from models import (
    BedAssemblyConfig,
    BedConfig,
    EnvironmentMetadata,
    FastenerConfig,
    MechanicalModelConfig,
    SupportAssemblyConfig,
)
from solver import HOLD_THRESHOLD_MM, build_instruction


class MechanicsTests(unittest.TestCase):
    def test_weak_coupling_approximately_matches_baseline(self) -> None:
        positions = _positions()
        config = MechanicalModelConfig(
            enabled=True,
            preset_name="other",
            self_gain=1.0,
            neighbor_gain=0.001,
            decay_length_mm=1000.0,
            max_step_turns=0.125,
            regularization_lambda=1e-5,
            use_advanced_override=True,
        )
        baseline_delta = {
            "Front Left": 0.0,
            "Front Right": -0.03,
            "Rear Left": 0.05,
            "Rear Right": 0.02,
        }
        command_mm, achieved, warnings, suppressed = solve_physical_response(
            positions,
            baseline_delta,
            "Front Left",
            config,
        )
        self.assertFalse(warnings)
        self.assertFalse(suppressed)
        self.assertAlmostEqual(command_mm["Front Right"], -0.03, places=3)
        self.assertAlmostEqual(command_mm["Rear Left"], 0.05, places=3)
        self.assertAlmostEqual(achieved["Rear Right"], baseline_delta["Rear Right"], places=3)

    def test_higher_coupling_changes_magnitudes_without_sign_reversal(self) -> None:
        positions = _positions()
        baseline_delta = {
            "Front Left": 0.0,
            "Front Right": -0.03,
            "Rear Left": 0.05,
            "Rear Right": 0.02,
        }
        config = MechanicalModelConfig(
            enabled=True,
            preset_name="springs",
            self_gain=0.8,
            neighbor_gain=0.25,
            decay_length_mm=180.0,
            max_step_turns=0.125,
            regularization_lambda=1e-5,
            use_advanced_override=True,
        )
        command_mm, achieved, warnings, suppressed = solve_physical_response(
            positions,
            baseline_delta,
            "Front Left",
            config,
        )
        self.assertFalse(suppressed)
        self.assertEqual(command_mm["Front Left"], 0.0)
        self.assertLess(command_mm["Front Right"], 0.0)
        self.assertGreaterEqual(command_mm["Rear Left"], 0.0)
        self.assertGreaterEqual(command_mm["Rear Right"], 0.0)
        self.assertNotAlmostEqual(command_mm["Rear Right"], baseline_delta["Rear Right"], places=4)
        self.assertFalse(any("direction conflict" in warning for warning in warnings))
        self.assertEqual(achieved["Front Left"], 0.0)

    def test_reference_screw_remains_exactly_zero(self) -> None:
        baseline_delta = {
            "Front Left": 0.0,
            "Front Right": -0.03,
            "Rear Left": 0.05,
            "Rear Right": 0.02,
        }
        command_mm, achieved, _, _ = solve_physical_response(
            _positions(),
            baseline_delta,
            "Front Left",
            MechanicalModelConfig(
                enabled=True,
                preset_name="silicone",
                self_gain=0.85,
                neighbor_gain=0.15,
                decay_length_mm=140.0,
                max_step_turns=0.0625,
                regularization_lambda=1e-5,
                use_advanced_override=True,
            ),
        )
        self.assertEqual(command_mm["Front Left"], 0.0)
        self.assertEqual(achieved["Front Left"], 0.0)

    def test_conflict_suppression_recomputes_achieved_deltas(self) -> None:
        positions = [
            ("A", 0.0, 0.0),
            ("B", 20.0, 0.0),
            ("C", 0.0, 20.0),
            ("D", 200.0, 200.0),
        ]
        config = MechanicalModelConfig(
            enabled=True,
            preset_name="other",
            self_gain=0.1,
            neighbor_gain=0.084,
            decay_length_mm=50.0,
            max_step_turns=0.1,
            regularization_lambda=1e-5,
            use_advanced_override=True,
        )
        command_mm, achieved, warnings, suppressed = solve_physical_response(
            positions,
            {"A": 0.0, "B": -0.2, "C": -0.05, "D": 0.05},
            "A",
            config,
        )
        self.assertEqual(suppressed, ["C"])
        self.assertTrue(any("direction conflict" in warning for warning in warnings))
        matrix = build_coupling_matrix(positions, config)
        names = [name for name, _, _ in positions]
        commanded = [command_mm[name] for name in names]
        absolute = matrix @ commanded
        expected = {name: absolute[index] - absolute[0] for index, name in enumerate(names)}
        for name in names:
            self.assertAlmostEqual(achieved[name], expected[name])

    def test_invalid_parameters_are_rejected(self) -> None:
        with self.assertRaises(MechanicalModelError):
            effective_mechanical_config(
            MechanicalModelConfig(
                enabled=True,
                preset_name="other",
                self_gain=0.1,
                    neighbor_gain=0.2,
                    decay_length_mm=140.0,
                    max_step_turns=0.0625,
                    regularization_lambda=1e-5,
                    use_advanced_override=True,
                ),
                _metadata(),
            )

    def test_aggressive_coupling_emits_warning(self) -> None:
        warnings = coupling_warnings(
            MechanicalModelConfig(
                enabled=True,
                preset_name="other",
                self_gain=0.5,
                neighbor_gain=0.35,
                decay_length_mm=500.0,
                max_step_turns=0.0625,
                regularization_lambda=1e-5,
                use_advanced_override=True,
            ),
            _positions(),
        )
        self.assertTrue(any("aggressive" in warning for warning in warnings))

    def test_advanced_override_replaces_preset_values_deterministically(self) -> None:
        override = effective_mechanical_config(
            MechanicalModelConfig(
                enabled=True,
                preset_name="springs",
                self_gain=0.91,
                neighbor_gain=0.11,
                decay_length_mm=222.0,
                max_step_turns=0.09,
                regularization_lambda=2e-5,
                use_advanced_override=True,
            ),
            _metadata(mount_type="springs", plate="cast_aluminum"),
        )
        preset = effective_mechanical_config(
            MechanicalModelConfig(
                enabled=True,
                preset_name="springs",
                self_gain=0.91,
                neighbor_gain=0.11,
                decay_length_mm=222.0,
                max_step_turns=0.09,
                regularization_lambda=2e-5,
                use_advanced_override=False,
            ),
            _metadata(mount_type="springs", plate="cast_aluminum"),
        )

        self.assertAlmostEqual(override.self_gain, 0.91, places=3)
        self.assertAlmostEqual(override.neighbor_gain, 0.11, places=3)
        self.assertAlmostEqual(override.decay_length_mm, 222.0)
        self.assertAlmostEqual(override.max_step_turns, 0.09)
        self.assertAlmostEqual(override.regularization_lambda, 2e-5)
        self.assertAlmostEqual(preset.self_gain, 0.80)
        self.assertAlmostEqual(preset.neighbor_gain, 0.25)
        self.assertAlmostEqual(preset.decay_length_mm, 180.0)

    def test_turn_plan_scales_proportionally_and_alternates_diagonally(self) -> None:
        instructions = [
            build_instruction("Front Left", 0.0, 0.0, 0.0, 0.12, _turn_config(), source_model="baseline"),
            build_instruction("Front Right", 200.0, 0.0, 0.0, 0.08, _turn_config(), source_model="baseline"),
            build_instruction("Rear Left", 0.0, 200.0, 0.0, -0.06, _turn_config(), source_model="baseline"),
            build_instruction("Rear Right", 200.0, 200.0, 0.0, -0.10, _turn_config(), source_model="baseline"),
        ]
        plan = build_turn_plan("baseline", instructions, "Centre", 0.125, BedConfig(200.0, 200.0))
        self.assertEqual(plan.first_pass_steps[0].screw_name, "Front Left")
        self.assertEqual(plan.first_pass_steps[1].screw_name, "Rear Right")
        self.assertAlmostEqual(
            plan.first_pass_steps[2].turns_this_pass / plan.first_pass_steps[0].turns_this_pass,
            instructions[1].decimal_turns / instructions[0].decimal_turns,
            places=3,
        )

    def test_turn_plan_skips_reference_and_hold_screws(self) -> None:
        instructions = [
            build_instruction("Front Left", 0.0, 0.0, 0.0, 0.0, _turn_config(), source_model="baseline"),
            build_instruction(
                "Front Right",
                200.0,
                0.0,
                0.0,
                HOLD_THRESHOLD_MM / 2.0,
                _turn_config(),
                source_model="baseline",
            ),
            build_instruction("Rear Left", 0.0, 200.0, 0.0, -0.08, _turn_config(), source_model="baseline"),
            build_instruction("Rear Right", 200.0, 200.0, 0.0, 0.05, _turn_config(), source_model="baseline"),
        ]
        plan = build_turn_plan("baseline", instructions, "Front Left", 0.125, BedConfig(200.0, 200.0))

        self.assertEqual([step.screw_name for step in plan.first_pass_steps], ["Rear Left", "Rear Right"])
        self.assertEqual(plan.total_target_turns["Front Left"], 0.0)
        self.assertEqual(plan.total_target_turns["Front Right"], 0.0)

    def test_brittle_bed_material_clamps_max_step_turns(self) -> None:
        springs_glass = effective_mechanical_config(
            MechanicalModelConfig(enabled=True, preset_name="springs"),
            _metadata(mount_type="springs", plate="borosilicate_glass"),
        )
        springs_aluminum = effective_mechanical_config(
            MechanicalModelConfig(enabled=True, preset_name="springs"),
            _metadata(mount_type="springs", plate="cast_aluminum"),
        )

        self.assertAlmostEqual(springs_glass.max_step_turns, 1.0 / 32.0)
        self.assertAlmostEqual(springs_aluminum.max_step_turns, 0.125)

    def test_preset_caps_follow_expected_ordering(self) -> None:
        springs = default_mechanical_config(_metadata(mount_type="springs"), enabled=True)
        silicone = default_mechanical_config(_metadata(mount_type="silicone"), enabled=True)
        rigid = default_mechanical_config(_metadata(mount_type="rigid spacers"), enabled=True)
        shims = default_mechanical_config(_metadata(mount_type="shims"), enabled=True)

        self.assertGreater(springs.max_step_turns, silicone.max_step_turns)
        self.assertGreater(silicone.max_step_turns, rigid.max_step_turns)
        self.assertEqual(rigid.max_step_turns, shims.max_step_turns)

    def test_steel_plate_increases_neighbour_gain_over_cast_aluminum(self) -> None:
        aluminum = effective_mechanical_config(
            MechanicalModelConfig(enabled=True, preset_name="springs"),
            _metadata(mount_type="springs", plate="cast_aluminum"),
        )
        steel = effective_mechanical_config(
            MechanicalModelConfig(enabled=True, preset_name="springs"),
            _metadata(mount_type="springs", plate="steel"),
        )
        self.assertGreater(steel.neighbor_gain, aluminum.neighbor_gain)

    def test_hot_music_wire_degrades_more_than_hot_chrome_silicon(self) -> None:
        hot_music = effective_mechanical_config(
            MechanicalModelConfig(enabled=True, preset_name="springs"),
            _metadata(
                mount_type="springs",
                support="music_wire",
                bed_temp=110.0,
                chamber_temp=80.0,
            ),
        )
        hot_chrome = effective_mechanical_config(
            MechanicalModelConfig(enabled=True, preset_name="springs"),
            _metadata(
                mount_type="springs",
                support="chrome_silicon",
                bed_temp=110.0,
                chamber_temp=80.0,
            ),
        )
        self.assertLess(hot_music.max_step_turns, hot_chrome.max_step_turns)

    def test_polymer_screws_reduce_confidence_and_step_cap(self) -> None:
        _, _, steel_confidence, _ = resolve_effective_mechanical_model(
            MechanicalModelConfig(enabled=True, preset_name="rigid spacers"),
            _metadata(mount_type="rigid spacers", support="steel", screw="steel"),
            _positions(),
        )
        nylon_model, _, nylon_confidence, _ = resolve_effective_mechanical_model(
            MechanicalModelConfig(enabled=True, preset_name="rigid spacers"),
            _metadata(mount_type="rigid spacers", support="steel", screw="nylon"),
            _positions(),
        )
        self.assertLess(nylon_model.max_step_turns, 0.03125)
        self.assertLess(nylon_confidence.score, steel_confidence.score)

    def test_shims_preset_emits_warning(self) -> None:
        warnings = coupling_warnings(
            MechanicalModelConfig(
                enabled=True,
                preset_name="shims",
                self_gain=1.0,
                neighbor_gain=0.02,
                decay_length_mm=80.0,
                max_step_turns=0.03125,
                regularization_lambda=1e-5,
                use_advanced_override=False,
            ),
            _positions(),
        )
        self.assertTrue(any("Shim workflows" in warning for warning in warnings))


def _positions():
    return [
        ("Front Left", 0.0, 0.0),
        ("Front Right", 200.0, 0.0),
        ("Rear Left", 0.0, 200.0),
        ("Rear Right", 200.0, 200.0),
    ]


def _metadata(
    *,
    mount_type: str = "other",
    plate: str = "cast_aluminum",
    support: str | None = None,
    screw: str = "steel",
    bed_temp: float | None = None,
    chamber_temp: float | None = None,
    stack_height: float | None = None,
) -> EnvironmentMetadata:
    support_key = support or {
        "springs": "spring_steel",
        "silicone": "silicone_elastomer",
        "rigid spacers": "steel",
        "shims": "steel",
    }.get(mount_type, "other")
    default_height = {
        "springs": 15.0,
        "silicone": 10.0,
        "rigid spacers": 8.0,
        "shims": 1.0,
    }.get(mount_type, 12.0)
    return EnvironmentMetadata(
        bed_assembly=BedAssemblyConfig(
            plate_material=make_library_choice("plate", plate),
            surface_material=make_library_choice("surface", "none"),
        ),
        support_assembly=SupportAssemblyConfig(
            mount_type=mount_type,
            support_material=make_library_choice("support", support_key),
            support_stack_height_mm=default_height if stack_height is None else stack_height,
        ),
        fastener=FastenerConfig(
            screw_material=make_library_choice("screw", screw),
        ),
        bed_temperature_c=bed_temp,
        chamber_temperature_c=chamber_temp,
    )


def _turn_config():
    from models import ScrewTurnConfig

    return ScrewTurnConfig(pitch_mm_per_turn=0.5, clockwise_effect="raise", viewpoint="above")


if __name__ == "__main__":
    unittest.main()
