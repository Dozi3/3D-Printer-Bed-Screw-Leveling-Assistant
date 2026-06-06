from __future__ import annotations

import os
import unittest


class UiSmokeTests(unittest.TestCase):
    def test_main_window_starts_if_pyside6_is_available(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication, QComboBox, QPushButton
        except ImportError:
            self.skipTest("PySide6 is not available in this environment.")
        from widgets.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        self.assertIsNotNone(window)
        menu_titles = [action.text().replace("&", "") for action in window.menuBar().actions()]
        self.assertIn("File", menu_titles)
        self.assertIn("Tools", menu_titles)
        self.assertIn("Help", menu_titles)
        self.assertIn("Calibration", [window.tabs.tabText(index) for index in range(window.tabs.count())])
        file_action_titles = [action.text().replace("&", "") for action in window.file_menu.actions()]
        self.assertIn("GUI Settings...", file_action_titles)

        button_titles = [button.text() for button in window.findChildren(QPushButton)]
        self.assertNotIn("Load Project", button_titles)
        self.assertNotIn("Save Project", button_titles)
        self.assertGreaterEqual(button_titles.count("2D"), 5)
        self.assertGreaterEqual(button_titles.count("3D"), 5)
        self.assertEqual(window.raw_heatmap.stack.count(), 2)
        self.assertEqual(window.analysis_raw_heatmap.stack.count(), 2)
        self.assertIn("QTextEdit", window.styleSheet())
        self.assertIn("color:", window.styleSheet())
        self.assertIn("background-color:", window.styleSheet())
        self.assertIn("color:", window.geometry_status_text.styleSheet())
        self.assertGreaterEqual(window.calibration_turns_table.rowCount(), 4)

        about_dialog = window._create_about_dialog()
        guide_dialog = window._create_user_guide_dialog()
        settings_dialog = window._create_gui_settings_dialog()
        from widgets.component_library_dialog import ComponentLibraryDialog

        component_dialog = ComponentLibraryDialog(window, window)
        self.assertIn("About", about_dialog.windowTitle())
        self.assertIn("User Guide", guide_dialog.windowTitle())
        self.assertEqual(settings_dialog.windowTitle(), "GUI Settings")
        settings_combos = settings_dialog.findChildren(QComboBox)
        self.assertGreaterEqual(len(settings_combos), 2)
        theme_labels = [settings_combos[0].itemText(index) for index in range(settings_combos[0].count())]
        self.assertEqual(theme_labels, ["Light", "Dark", "High contrast"])
        self.assertEqual(component_dialog.windowTitle(), "Component Library")
        self.assertGreater(component_dialog.profile_table.rowCount(), 0)
        component_dialog.search_edit.setText("Bambu")
        component_dialog._populate_profile_table()
        self.assertGreaterEqual(component_dialog.profile_table.rowCount(), 1)
        about_dialog.close()
        guide_dialog.close()
        settings_dialog.close()
        component_dialog.close()
        window.close()
        if QApplication.instance() is app:
            app.quit()

    def test_themes_define_distinct_control_colors(self) -> None:
        try:
            import PySide6  # noqa: F401
        except ImportError:
            self.skipTest("PySide6 is not available in this environment.")
        from widgets.main_window import GuiSettings, _build_gui_stylesheet, _gui_palette

        for theme in ("light", "dark", "high_contrast"):
            with self.subTest(theme=theme):
                colors = _gui_palette(GuiSettings(theme=theme))
                self.assertNotEqual(colors["text"], colors["control"])
                self.assertNotEqual(colors["selection_text"], colors["selection"])
                stylesheet = _build_gui_stylesheet(GuiSettings(theme=theme))
                for selector in (
                    "QLineEdit",
                    "QTextEdit",
                    "QDoubleSpinBox",
                    "QComboBox",
                    "QTableWidget",
                    "QCheckBox::indicator",
                    "QSlider::groove:horizontal",
                    "QScrollBar:vertical",
                    "QPushButton:focus",
                ):
                    self.assertIn(selector, stylesheet)

    def test_mesh_bounds_follow_bed_until_manually_edited(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            self.skipTest("PySide6 is not available in this environment.")

        app = QApplication.instance() or QApplication([])
        window = self._window_with_sample_mesh()

        window.bed_width_spin.setValue(300.0)
        window.bed_height_spin.setValue(300.0)
        self.assertAlmostEqual(window.x_min_spin.value(), 0.0)
        self.assertAlmostEqual(window.x_max_spin.value(), 300.0)
        self.assertAlmostEqual(window.y_min_spin.value(), 0.0)
        self.assertAlmostEqual(window.y_max_spin.value(), 300.0)
        self.assertTrue(window._mesh_bounds_auto_linked)

        project = window.collect_project_data(require_mesh=True)
        from analysis import inspect_project_geometry

        report = inspect_project_geometry(project)
        self.assertTrue(all(status.inside_mesh for status in report.screw_statuses))

        window.x_max_spin.setValue(235.0)
        window.y_max_spin.setValue(235.0)
        self.assertFalse(window._mesh_bounds_auto_linked)
        manual_project = window.collect_project_data(require_mesh=True)
        manual_report = inspect_project_geometry(manual_project)
        self.assertEqual(sum(1 for status in manual_report.screw_statuses if status.inside_mesh), 1)
        self.assertTrue(any("3 of 4 screw positions are outside" in warning for warning in manual_report.warnings))

        window._use_bed_bounds()
        self.assertTrue(window._mesh_bounds_auto_linked)
        self.assertAlmostEqual(window.x_max_spin.value(), 300.0)
        self.assertAlmostEqual(window.y_max_spin.value(), 300.0)
        window.close()
        if QApplication.instance() is app:
            app.quit()

    def test_gui_collects_raw_mechanical_override_not_effective_values(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            self.skipTest("PySide6 is not available in this environment.")

        app = QApplication.instance() or QApplication([])
        window = self._window_with_sample_mesh()
        window.mechanical_override_check.setChecked(True)
        window.self_gain_spin.setValue(0.9)
        window.neighbor_gain_spin.setValue(0.1)
        window.decay_length_spin.setValue(150.0)
        window.max_step_spin.setValue(0.08)
        window.support_material_editor.combo.setCurrentIndex(
            window.support_material_editor.combo.findData("silicone_elastomer")
        )
        window.bed_temp_edit.setText("110")
        project = window.collect_project_data(require_mesh=False)

        self.assertTrue(project.mechanical_model.use_advanced_override)
        self.assertAlmostEqual(project.mechanical_model.self_gain, 0.9)
        self.assertAlmostEqual(project.mechanical_model.neighbor_gain, 0.1)
        self.assertAlmostEqual(project.mechanical_model.decay_length_mm, 150.0)
        self.assertAlmostEqual(project.mechanical_model.max_step_turns, 0.08)
        window.close()
        if QApplication.instance() is app:
            app.quit()

    def test_calibration_trial_saves_with_displayed_mesh_context(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            self.skipTest("PySide6 is not available in this environment.")

        app = QApplication.instance() or QApplication([])
        window = self._window_with_sample_mesh()
        window.bed_width_spin.setValue(300.0)
        window.bed_height_spin.setValue(300.0)
        window.x_min_spin.setValue(10.0)
        window.x_max_spin.setValue(290.0)
        window.y_min_spin.setValue(10.0)
        window.y_max_spin.setValue(290.0)
        window.row_order_combo.setCurrentIndex(window.row_order_combo.findData(False))

        self.assertIn("X 10.000..290.000 mm", window.calibration_bounds_label.text())
        self.assertIn("top row = Y min", window.calibration_bounds_label.text())

        window.calibration_before_edit.setPlainText("0,0,0\n0,0,0\n0,0,0")
        window.calibration_after_edit.setPlainText("0,0,0\n0,0,0\n0,0,0")
        window.calibration_turns_table.item(0, 1).setText("0.1")
        window._add_calibration_trial()

        self.assertEqual(len(window.calibration_trials), 1)
        trial = window.calibration_trials[0]
        self.assertAlmostEqual(trial.before_mesh.x_min_mm, 10.0)
        self.assertAlmostEqual(trial.before_mesh.x_max_mm, 290.0)
        self.assertFalse(trial.before_mesh.top_row_is_y_max)
        self.assertIn("X 10.000..290.000 mm", window.calibration_summary_text.toPlainText())
        window.close()
        if QApplication.instance() is app:
            app.quit()

    def test_fit_and_apply_calibration_enables_disabled_physical_model(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            self.skipTest("PySide6 is not available in this environment.")

        app = QApplication.instance() or QApplication([])
        window = self._window_with_sample_mesh()
        window.calibration_trials = _ui_calibration_trials()
        window.mechanical_enabled_check.setChecked(False)
        window.mechanical_override_check.setChecked(False)

        window._fit_and_apply_calibration()

        self.assertTrue(window.mechanical_enabled_check.isChecked())
        self.assertTrue(window.mechanical_override_check.isChecked())
        self.assertIsNotNone(window.current_project)
        assert window.current_project is not None
        self.assertTrue(window.current_project.mechanical_model.enabled)
        self.assertTrue(window.current_project.mechanical_model.use_advanced_override)
        window.close()
        if QApplication.instance() is app:
            app.quit()

    def _window_with_sample_mesh(self):
        from widgets.main_window import MainWindow

        window = MainWindow()
        window.mesh_text_edit.setPlainText("0,0,0\n0,0,0\n0,0,0")
        screw_values = [
            ("FL", "35", "35"),
            ("RL", "35", "265"),
            ("FR", "265", "35"),
            ("RR", "265", "265"),
        ]
        for row, values in enumerate(screw_values):
            for column, value in enumerate(values):
                item = window.screw_table.item(row, column)
                assert item is not None
                item.setText(value)
        window._refresh_reference_combo()
        window.reference_combo.setCurrentIndex(window.reference_combo.findData("FL"))
        window._refresh_calibration_turn_table()
        return window


def _ui_calibration_trials():
    import numpy as np

    from mechanics import build_coupling_matrix
    from mesh_io import build_mesh_grid
    from models import (
        BedConfig,
        CalibrationTrial,
        CoordinateConvention,
        EnvironmentMetadata,
        MechanicalModelConfig,
        ScrewMeasurement,
        ScrewTurnConfig,
    )

    config = MechanicalModelConfig(
        enabled=True,
        preset_name="other",
        self_gain=0.9,
        neighbor_gain=0.1,
        decay_length_mm=150.0,
        use_advanced_override=True,
    )
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
    before_mesh = build_mesh_grid(
        [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        0.0,
        200.0,
        0.0,
        200.0,
    )
    trials = []
    for index, turns in enumerate(({"B": 0.2, "C": -0.1, "E": 0.1}, {"D": 0.15, "B": -0.1}), start=1):
        command_mm = np.asarray([turns.get(name, 0.0) * turn_config.pitch_mm_per_turn for name, _, _ in positions])
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
                name=f"UI Trial {index}",
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
