from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem

from analysis import AnalysisError
from calibration import CalibrationError, fit_project_calibration, make_trial_from_project
from mesh_io import MeshInputError, build_mesh_grid, parse_text_grid
from widgets.project_binding import apply_mechanical_model_to_controls, format_calibration_mesh_context


def refresh_calibration_turn_table(window) -> None:
    if not hasattr(window, "calibration_turns_table"):
        return
    existing: dict[str, str] = {}
    for row in range(window.calibration_turns_table.rowCount()):
        name_item = window.calibration_turns_table.item(row, 0)
        turns_item = window.calibration_turns_table.item(row, 1)
        if name_item is not None:
            existing[name_item.text()] = turns_item.text() if turns_item is not None else ""
    try:
        screws = window._collect_screws()
    except AnalysisError:
        screws = []
    window.calibration_turns_table.setRowCount(len(screws))
    for row, screw in enumerate(screws):
        name_item = QTableWidgetItem(screw.name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
        window.calibration_turns_table.setItem(row, 0, name_item)
        window.calibration_turns_table.setItem(row, 1, QTableWidgetItem(existing.get(screw.name, "")))
    render_calibration_summary(window)


def add_calibration_trial(window) -> None:
    try:
        project = window.collect_project_data(require_mesh=False)
        before_mesh = build_calibration_mesh(window, window.calibration_before_edit.toPlainText())
        after_mesh = build_calibration_mesh(window, window.calibration_after_edit.toPlainText())
        applied_turns = collect_calibration_turns(window)
        trial = make_trial_from_project(
            project,
            name=window.calibration_name_edit.text(),
            before_mesh=before_mesh,
            after_mesh=after_mesh,
            applied_turns=applied_turns,
        )
    except (AnalysisError, MeshInputError, CalibrationError, ValueError) as exc:
        window._show_error("Calibration Error", str(exc))
        return
    window.calibration_trials.append(trial)
    window.current_project = replace(project, calibration_trials=list(window.calibration_trials))
    window.calibration_name_edit.setText(f"Trial {len(window.calibration_trials) + 1}")
    render_calibration_summary(window)
    window.statusBar().showMessage("Calibration trial saved.", 4000)


def fit_and_apply_calibration(window) -> None:
    try:
        project = window.collect_project_data(require_mesh=False)
        result = fit_project_calibration(project)
    except (AnalysisError, MeshInputError, CalibrationError, ValueError) as exc:
        window._show_error("Calibration Error", str(exc))
        return
    apply_mechanical_model_to_controls(window, result.mechanical_model)
    window.current_project = replace(project, mechanical_model=result.mechanical_model)
    result_line = (
        f"Fitted self gain {result.mechanical_model.self_gain:.3f}, "
        f"neighbour gain {result.mechanical_model.neighbor_gain:.3f}, "
        f"decay {result.mechanical_model.decay_length_mm:.1f} mm. "
        f"RMS residual {result.residual_rms_mm:.4f} mm from {result.sample_count} observations."
    )
    if result.warnings:
        result_line = "\n".join([result_line, *result.warnings])
    render_calibration_summary(window, result_text=result_line)
    window.refresh_geometry_diagnostics()
    window.statusBar().showMessage("Calibration fitted and applied to advanced override.", 5000)


def build_calibration_mesh(window, text: str):
    values = parse_text_grid(text.strip())
    return build_mesh_grid(
        values,
        window.x_min_spin.value(),
        window.x_max_spin.value(),
        window.y_min_spin.value(),
        window.y_max_spin.value(),
        bool(window.row_order_combo.currentData()),
    )


def collect_calibration_turns(window) -> dict[str, float]:
    turns: dict[str, float] = {}
    for row in range(window.calibration_turns_table.rowCount()):
        name_item = window.calibration_turns_table.item(row, 0)
        turns_item = window.calibration_turns_table.item(row, 1)
        if name_item is None or turns_item is None or not turns_item.text().strip():
            continue
        turns[name_item.text()] = float(turns_item.text().strip())
    if not turns:
        raise CalibrationError("Enter at least one applied signed turn.")
    return turns


def render_calibration_summary(window, result_text: str | None = None) -> None:
    if not hasattr(window, "calibration_summary_text"):
        return
    lines = [
        f"Saved calibration trials: {len(window.calibration_trials)}",
        "Signed turns are positive for raise and negative for lower.",
    ]
    if window.calibration_trials:
        lines.append("")
        for index, trial in enumerate(window.calibration_trials, start=1):
            row_order = "top row = Y max" if trial.before_mesh.top_row_is_y_max else "top row = Y min"
            lines.append(
                f"{index}. {trial.name}: {len(trial.applied_turns)} applied screw moves; "
                f"X {trial.before_mesh.x_min_mm:.3f}..{trial.before_mesh.x_max_mm:.3f} mm, "
                f"Y {trial.before_mesh.y_min_mm:.3f}..{trial.before_mesh.y_max_mm:.3f} mm, "
                f"{row_order}"
            )
    if result_text:
        lines.extend(["", result_text])
    window.calibration_summary_text.setPlainText("\n".join(lines))


def update_calibration_mesh_context(window) -> None:
    if not hasattr(window, "calibration_bounds_label"):
        return
    window.calibration_bounds_label.setText(
        format_calibration_mesh_context(
            window.x_min_spin.value(),
            window.x_max_spin.value(),
            window.y_min_spin.value(),
            window.y_max_spin.value(),
            bool(window.row_order_combo.currentData()),
        )
    )
