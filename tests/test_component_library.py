from __future__ import annotations

from copy import deepcopy
import unittest

from analysis import analyse_project
from component_library import (
    ComponentProfileLibrary,
    ComponentLibraryError,
    apply_profile_to_project,
    build_profile_suggestions,
    get_printer_profiles,
    is_missing_component_value,
    load_bundled_component_profile_library,
    query_sqlite_relation,
    validate_component_profile_library,
)
from mechanics import PRESET_DEFAULTS
from mesh_io import build_mesh_grid
from models import BedConfig, MechanicalModelConfig, ProjectData, ScrewMeasurement, ScrewTurnConfig


class ComponentLibraryTests(unittest.TestCase):
    def test_bundled_component_library_validates(self) -> None:
        library = load_bundled_component_profile_library()
        self.assertEqual(library.schema_version, 1)
        self.assertEqual(len(get_printer_profiles(library)), 11)

    def test_missing_required_top_level_key_is_rejected(self) -> None:
        data = deepcopy(load_bundled_component_profile_library().data)
        del data["source_evidence"]
        with self.assertRaisesRegex(ComponentLibraryError, "missing required keys"):
            validate_component_profile_library(data)

    def test_malformed_array_key_is_rejected(self) -> None:
        data = deepcopy(load_bundled_component_profile_library().data)
        data["printer_component_profiles"] = {}
        with self.assertRaisesRegex(ComponentLibraryError, "must be a list"):
            validate_component_profile_library(data)

    def test_negative_solver_numeric_values_are_rejected(self) -> None:
        data = deepcopy(load_bundled_component_profile_library().data)
        data["app_calibration_profiles"][0]["recommended_max_step_turns"] = "-0.25"
        with self.assertRaisesRegex(ComponentLibraryError, "Negative value"):
            validate_component_profile_library(data)

    def test_unknown_and_not_applicable_are_missing_not_false_or_zero(self) -> None:
        self.assertTrue(is_missing_component_value("-"))
        self.assertTrue(is_missing_component_value("n/a"))
        self.assertFalse(is_missing_component_value("0"))

    def test_fixed_bed_unknown_and_zero_do_not_become_solver_values(self) -> None:
        library = load_bundled_component_profile_library()
        project = _project_with_mesh()
        suggestions = build_profile_suggestions(project, "P001", library)
        by_key = {suggestion.field_key: suggestion for suggestion in suggestions}

        self.assertFalse(by_key["bed_plate_material"].applicable)
        self.assertFalse(by_key["mount_preset"].applicable)
        self.assertFalse(by_key["max_step_turns"].applicable)

        result = apply_profile_to_project(
            "P001",
            {"bed_plate_material", "mount_preset", "max_step_turns"},
            project,
            library,
        )
        self.assertFalse(result.applied)
        self.assertEqual(result.project.metadata.support_assembly.mount_type, project.metadata.support_assembly.mount_type)
        self.assertEqual(result.project.mechanical_model.max_step_turns, project.mechanical_model.max_step_turns)

    def test_positive_max_step_requires_advanced_override(self) -> None:
        library = load_bundled_component_profile_library()
        project = _project_with_mesh()
        result = apply_profile_to_project("P004", {"max_step_turns"}, project, library)
        self.assertTrue(result.applied)
        self.assertTrue(result.project.mechanical_model.use_advanced_override)
        self.assertAlmostEqual(result.project.mechanical_model.max_step_turns, 0.25)

    def test_max_step_survives_when_mount_and_override_are_applied_together(self) -> None:
        base = load_bundled_component_profile_library()
        data = deepcopy(base.data)
        for row in data["app_calibration_profiles"]:
            if row["printer_id"] == "P004":
                row["recommended_mount_preset"] = "shims"
        library = ComponentProfileLibrary(data=data, source_label="Synthetic")
        project = _project_with_mesh()
        result = apply_profile_to_project("P004", {"mount_preset", "max_step_turns"}, project, library)
        self.assertEqual(result.project.metadata.support_assembly.mount_type, "shims")
        self.assertTrue(result.project.mechanical_model.use_advanced_override)
        self.assertAlmostEqual(result.project.mechanical_model.max_step_turns, 0.25)
        preset = PRESET_DEFAULTS["shims"]
        self.assertAlmostEqual(result.project.mechanical_model.self_gain, preset.self_gain)
        self.assertAlmostEqual(result.project.mechanical_model.neighbor_gain, preset.neighbor_gain)
        self.assertAlmostEqual(result.project.mechanical_model.decay_length_mm, preset.decay_length_mm)
        self.assertAlmostEqual(result.project.mechanical_model.regularization_lambda, preset.regularization_lambda)

    def test_metadata_profile_application_does_not_change_baseline_solver_output(self) -> None:
        library = load_bundled_component_profile_library()
        project = _project_with_mesh()
        before = analyse_project(project)
        applied = apply_profile_to_project("P001", {"surface_material"}, project, library).project
        after = analyse_project(applied)

        before_map = {instruction.name: instruction.delta_height_mm for instruction in before.baseline_instructions}
        after_map = {instruction.name: instruction.delta_height_mm for instruction in after.baseline_instructions}
        self.assertEqual(before_map, after_map)
        self.assertEqual(applied.metadata.bed_assembly.surface_material.library_key, "pei_on_spring_steel")

    def test_sqlite_browser_queries_gui_view_read_only(self) -> None:
        rows = query_sqlite_relation("v_gui_app_calibration_profiles", search_text="Bambu", limit=5)
        self.assertGreaterEqual(len(rows), 1)
        self.assertIn("model_name", rows[0])


def _project_with_mesh() -> ProjectData:
    mesh = build_mesh_grid(
        [
            [0.30, 0.10, -0.10],
            [0.20, 0.00, -0.20],
            [0.10, -0.10, -0.30],
        ],
        0.0,
        200.0,
        0.0,
        200.0,
        top_row_is_y_max=True,
    )
    return ProjectData(
        bed=BedConfig(width_mm=200.0, height_mm=200.0),
        screws=[
            ScrewMeasurement("Front Left", 0.0, 200.0),
            ScrewMeasurement("Front Right", 200.0, 200.0),
            ScrewMeasurement("Rear Left", 0.0, 0.0),
            ScrewMeasurement("Rear Right", 200.0, 0.0),
        ],
        turn_config=ScrewTurnConfig(pitch_mm_per_turn=0.5, clockwise_effect="raise", viewpoint="above"),
        reference_screw_name="Front Left",
        mechanical_model=MechanicalModelConfig(enabled=False, preset_name="springs"),
        mesh=mesh,
    )


if __name__ == "__main__":
    unittest.main()
