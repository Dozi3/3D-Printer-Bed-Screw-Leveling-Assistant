from __future__ import annotations

from models import MechanicalModelConfig


def format_calibration_mesh_context(
    x_min_mm: float,
    x_max_mm: float,
    y_min_mm: float,
    y_max_mm: float,
    top_row_is_y_max: bool,
) -> str:
    row_order = "top row = Y max" if top_row_is_y_max else "top row = Y min"
    return (
        "Trial meshes will be saved with "
        f"X {x_min_mm:.3f}..{x_max_mm:.3f} mm, "
        f"Y {y_min_mm:.3f}..{y_max_mm:.3f} mm, "
        f"{row_order}."
    )


def apply_mechanical_model_to_controls(window, mechanical_model: MechanicalModelConfig) -> None:
    window.mechanical_enabled_check.setChecked(mechanical_model.enabled)
    window._set_combo_data(window.mechanical_preset_combo, mechanical_model.preset_name)
    window.mechanical_override_check.setChecked(mechanical_model.use_advanced_override)
    window.self_gain_spin.setValue(mechanical_model.self_gain)
    window.neighbor_gain_spin.setValue(mechanical_model.neighbor_gain)
    window.decay_length_spin.setValue(mechanical_model.decay_length_mm)
    window.max_step_spin.setValue(mechanical_model.max_step_turns)
    window.regularization_spin.setValue(mechanical_model.regularization_lambda)
    window._sync_mechanical_controls()
