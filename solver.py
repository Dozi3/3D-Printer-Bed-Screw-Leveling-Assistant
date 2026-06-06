from __future__ import annotations

import math
from math import gcd
from typing import Sequence

import numpy as np

from models import EdgeReference, MeshGrid, PlaneFit, ResidualStats, ScrewInstruction, ScrewTurnConfig

HOLD_THRESHOLD_MM = 0.01
DEFAULT_TURN_FRACTION_DENOMINATOR = 16
LOCAL_RESIDUAL_PROXIMITY_RADIUS_MM = 8.0


def measurement_to_internal(
    left_mm: float,
    y_measure_mm: float,
    bed_height_mm: float,
    screw_y_reference_edge: EdgeReference = "top",
) -> tuple[float, float]:
    _require_finite("left_mm", left_mm)
    _require_finite("y_measure_mm", y_measure_mm)
    _require_finite("bed_height_mm", bed_height_mm)
    if screw_y_reference_edge not in {"top", "bottom"}:
        raise ValueError("screw_y_reference_edge must be 'top' or 'bottom'.")
    if screw_y_reference_edge == "bottom":
        return float(left_mm), float(y_measure_mm)
    return float(left_mm), float(bed_height_mm - y_measure_mm)


def fit_plane(x_points: Sequence[float], y_points: Sequence[float], z_points: Sequence[float]) -> PlaneFit:
    x = np.asarray(x_points, dtype=float)
    y = np.asarray(y_points, dtype=float)
    z = np.asarray(z_points, dtype=float)
    if x.size != y.size or x.size != z.size:
        raise ValueError("Plane-fit coordinate arrays must have the same length.")
    if x.size < 3:
        raise ValueError("Plane fit requires at least three points.")
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y)) and np.all(np.isfinite(z))):
        raise ValueError("Plane-fit inputs must be finite numbers.")
    design = np.column_stack((x, y, np.ones_like(x)))
    coefficients, _, _, _ = np.linalg.lstsq(design, z, rcond=None)
    return PlaneFit(a=float(coefficients[0]), b=float(coefficients[1]), c=float(coefficients[2]))


def fit_plane_to_mesh(mesh: MeshGrid) -> PlaneFit:
    x_grid, y_grid = np.meshgrid(mesh.x_coordinates(), mesh.y_coordinates())
    return fit_plane(x_grid.ravel(), y_grid.ravel(), mesh.z_array().ravel())


def evaluate_plane(plane_fit: PlaneFit, x_mm: float, y_mm: float) -> float:
    _require_finite("plane_fit.a", plane_fit.a)
    _require_finite("plane_fit.b", plane_fit.b)
    _require_finite("plane_fit.c", plane_fit.c)
    _require_finite("x_mm", x_mm)
    _require_finite("y_mm", y_mm)
    return plane_fit.a * x_mm + plane_fit.b * y_mm + plane_fit.c


def evaluate_plane_surface(mesh: MeshGrid, plane_fit: PlaneFit) -> np.ndarray:
    x_grid, y_grid = np.meshgrid(mesh.x_coordinates(), mesh.y_coordinates())
    return plane_fit.a * x_grid + plane_fit.b * y_grid + plane_fit.c


def compute_residual_stats(residual_surface: np.ndarray, plane_fit: PlaneFit) -> ResidualStats:
    residuals = np.asarray(residual_surface, dtype=float)
    if residuals.size == 0 or not np.all(np.isfinite(residuals)):
        raise ValueError("Residual surface must contain finite values.")
    return ResidualStats(
        max_abs_mm=float(np.max(np.abs(residuals))),
        rms_mm=float(np.sqrt(np.mean(np.square(residuals)))),
        peak_to_valley_mm=float(np.max(residuals) - np.min(residuals)),
        plane_slope_magnitude=float(math.hypot(plane_fit.a, plane_fit.b)),
    )


def direction_for_action(action: str, turn_config: ScrewTurnConfig) -> str:
    if action == "hold":
        return "-"
    direction = "CW" if action == turn_config.clockwise_effect else "CCW"
    if turn_config.viewpoint == "below":
        return "CCW" if direction == "CW" else "CW"
    return direction


def turns_for_delta(
    delta_height_mm: float,
    pitch_mm_per_turn: float,
    hold_threshold_mm: float = HOLD_THRESHOLD_MM,
) -> float:
    _require_positive_finite("pitch_mm_per_turn", pitch_mm_per_turn)
    _require_non_negative_finite("hold_threshold_mm", hold_threshold_mm)
    _require_finite("delta_height_mm", delta_height_mm)
    return 0.0 if abs(delta_height_mm) < hold_threshold_mm else delta_height_mm / pitch_mm_per_turn


def action_for_delta(delta_height_mm: float, hold_threshold_mm: float = HOLD_THRESHOLD_MM) -> str:
    _require_non_negative_finite("hold_threshold_mm", hold_threshold_mm)
    _require_finite("delta_height_mm", delta_height_mm)
    if abs(delta_height_mm) < hold_threshold_mm:
        return "hold"
    return "raise" if delta_height_mm > 0.0 else "lower"


def format_fractional_turns(turns: float, denominator: int = DEFAULT_TURN_FRACTION_DENOMINATOR) -> str:
    _require_finite("turns", turns)
    if denominator <= 0:
        raise ValueError("Turn fraction denominator must be greater than zero.")
    rounded = round(abs(turns) * denominator) / denominator
    whole = int(rounded)
    numerator = int(round((rounded - whole) * denominator))
    if numerator == denominator:
        whole += 1
        numerator = 0
    if numerator == 0:
        return str(whole)

    factor = gcd(numerator, denominator)
    numerator //= factor
    reduced_denominator = denominator // factor
    if whole == 0:
        return f"{numerator}/{reduced_denominator}"
    return f"{whole} {numerator}/{reduced_denominator}"


def build_instruction(
    name: str,
    x_mm: float,
    y_mm: float,
    plane_height_mm: float,
    delta_height_mm: float,
    turn_config: ScrewTurnConfig,
    *,
    source_model: str,
    expected_achieved_delta_mm: float | None = None,
    notes: Sequence[str] = (),
) -> ScrewInstruction:
    validate_turn_config(turn_config)
    action = action_for_delta(delta_height_mm, turn_config.hold_threshold_mm)
    signed_turns = turns_for_delta(
        delta_height_mm,
        turn_config.pitch_mm_per_turn,
        turn_config.hold_threshold_mm,
    )
    return ScrewInstruction(
        name=name,
        x_mm=float(x_mm),
        y_mm=float(y_mm),
        plane_height_mm=float(plane_height_mm),
        delta_height_mm=float(delta_height_mm),
        action=action,
        direction=direction_for_action(action, turn_config),
        signed_turns=float(signed_turns),
        decimal_turns=float(abs(signed_turns)),
        rounded_turns=format_fractional_turns(signed_turns, turn_config.fraction_denominator),
        source_model=source_model,  # type: ignore[arg-type]
        expected_achieved_delta_mm=float(expected_achieved_delta_mm)
        if expected_achieved_delta_mm is not None
        else None,
        notes=list(notes),
    )


def compute_screw_instructions(
    plane_fit: PlaneFit,
    screw_positions: Sequence[tuple[str, float, float]],
    reference_screw_name: str,
    turn_config: ScrewTurnConfig,
    *,
    source_model: str = "baseline",
    delta_override_mm: dict[str, float] | None = None,
    achieved_override_mm: dict[str, float] | None = None,
    note_map: dict[str, Sequence[str]] | None = None,
) -> list[ScrewInstruction]:
    validate_turn_config(turn_config)
    plane_values = {
        name: evaluate_plane(plane_fit, x_mm, y_mm) for name, x_mm, y_mm in screw_positions
    }
    reference_height = plane_values[reference_screw_name]
    instructions: list[ScrewInstruction] = []

    for name, x_mm, y_mm in screw_positions:
        plane_height = plane_values[name]
        delta_height = (
            delta_override_mm[name]
            if delta_override_mm is not None and name in delta_override_mm
            else reference_height - plane_height
        )
        achieved_height = (
            achieved_override_mm.get(name) if achieved_override_mm is not None else delta_height
        )
        instructions.append(
            build_instruction(
                name,
                x_mm,
                y_mm,
                plane_height,
                delta_height,
                turn_config,
                source_model=source_model,
                expected_achieved_delta_mm=achieved_height,
                notes=note_map.get(name, ()) if note_map is not None else (),
            )
        )

    return instructions


def bilinear_interpolate(
    x_coords: Sequence[float],
    y_coords: Sequence[float],
    z_values: Sequence[Sequence[float]],
    x_mm: float,
    y_mm: float,
) -> float:
    x = np.asarray(x_coords, dtype=float)
    y = np.asarray(y_coords, dtype=float)
    z = np.asarray(z_values, dtype=float)
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y)) and np.all(np.isfinite(z))):
        raise ValueError("Interpolation inputs must be finite numbers.")

    if x.ndim != 1 or y.ndim != 1:
        raise ValueError("Coordinates must be one-dimensional.")
    if x.size != z.shape[1] or y.size != z.shape[0]:
        raise ValueError("Coordinate lengths must match the grid dimensions.")

    if x[0] > x[-1]:
        x = x[::-1]
        z = z[:, ::-1]
    if y[0] > y[-1]:
        y = y[::-1]
        z = z[::-1, :]

    if not (x[0] <= x_mm <= x[-1] and y[0] <= y_mm <= y[-1]):
        raise ValueError("Interpolation point lies outside the mesh bounds.")

    x_index = min(np.searchsorted(x, x_mm, side="right") - 1, x.size - 2)
    y_index = min(np.searchsorted(y, y_mm, side="right") - 1, y.size - 2)
    x_index = max(0, x_index)
    y_index = max(0, y_index)

    x0, x1 = x[x_index], x[x_index + 1]
    y0, y1 = y[y_index], y[y_index + 1]
    z00 = z[y_index, x_index]
    z10 = z[y_index, x_index + 1]
    z01 = z[y_index + 1, x_index]
    z11 = z[y_index + 1, x_index + 1]

    x_weight = 0.0 if x1 == x0 else (x_mm - x0) / (x1 - x0)
    y_weight = 0.0 if y1 == y0 else (y_mm - y0) / (y1 - y0)

    lower = z00 * (1.0 - x_weight) + z10 * x_weight
    upper = z01 * (1.0 - x_weight) + z11 * x_weight
    return float(lower * (1.0 - y_weight) + upper * y_weight)


def validate_turn_config(turn_config: ScrewTurnConfig) -> None:
    _require_positive_finite("pitch_mm_per_turn", turn_config.pitch_mm_per_turn)
    _require_non_negative_finite("hold_threshold_mm", turn_config.hold_threshold_mm)
    if isinstance(turn_config.fraction_denominator, bool) or not isinstance(turn_config.fraction_denominator, int):
        raise ValueError("Turn fraction denominator must be an integer.")
    if turn_config.fraction_denominator <= 0:
        raise ValueError("Turn fraction denominator must be greater than zero.")
    if turn_config.clockwise_effect not in {"raise", "lower"}:
        raise ValueError("clockwise_effect must be 'raise' or 'lower'.")
    if turn_config.viewpoint not in {"above", "below"}:
        raise ValueError("viewpoint must be 'above' or 'below'.")


def _require_finite(label: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{label} must be a finite number.")


def _require_positive_finite(label: str, value: float) -> None:
    _require_finite(label, value)
    if float(value) <= 0.0:
        raise ValueError(f"{label} must be greater than zero.")


def _require_non_negative_finite(label: str, value: float) -> None:
    _require_finite(label, value)
    if float(value) < 0.0:
        raise ValueError(f"{label} must be non-negative.")
