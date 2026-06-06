from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Sequence

import numpy as np

from mechanics import MAX_NEIGHBOR_TO_SELF_RATIO, PRESET_DEFAULTS, infer_preset_name, validate_mechanical_config
from models import CalibrationTrial, MechanicalModelConfig, MeshGrid, ProjectData
from solver import bilinear_interpolate, measurement_to_internal, validate_turn_config


class CalibrationError(ValueError):
    pass


@dataclass(frozen=True)
class CalibrationFitResult:
    mechanical_model: MechanicalModelConfig
    residual_rms_mm: float
    sample_count: int
    warnings: list[str]


@dataclass(frozen=True)
class _Observation:
    self_coeff: float
    neighbor_terms: tuple[tuple[float, float], ...]
    observed_mm: float


def fit_project_calibration(project: ProjectData) -> CalibrationFitResult:
    if not project.calibration_trials:
        raise CalibrationError("At least one calibration trial is required.")
    return fit_calibration_trials(project.calibration_trials, project.mechanical_model)


def fit_calibration_trials(
    trials: Sequence[CalibrationTrial],
    base_config: MechanicalModelConfig,
) -> CalibrationFitResult:
    observations: list[_Observation] = []
    spans: list[float] = []
    warnings: list[str] = []
    for trial in trials:
        trial_observations = _trial_observations(trial)
        if not trial_observations:
            warnings.append(f"{trial.name}: no usable non-reference screw observations.")
            continue
        observations.extend(trial_observations)
        spans.append(_median_bed_span(trial))

    if not observations:
        raise CalibrationError("Calibration trials do not contain usable turn observations.")

    decay_candidates = _decay_candidates(spans)
    best: tuple[float, float, float, float, np.ndarray] | None = None
    for decay_length in decay_candidates:
        design_matrix = np.asarray(
            [
                [
                    observation.self_coeff,
                    sum(
                        command_mm * math.exp(-distance_mm / decay_length)
                        for command_mm, distance_mm in observation.neighbor_terms
                    ),
                ]
                for observation in observations
            ],
            dtype=float,
        )
        observed_vector = np.asarray([observation.observed_mm for observation in observations], dtype=float)
        gains, *_ = np.linalg.lstsq(design_matrix, observed_vector, rcond=None)
        self_gain = max(0.001, float(gains[0]))
        neighbor_gain = max(0.0, float(gains[1]))
        if neighbor_gain >= MAX_NEIGHBOR_TO_SELF_RATIO * self_gain:
            neighbor_gain = (MAX_NEIGHBOR_TO_SELF_RATIO * self_gain) - 1e-6
        predicted = design_matrix @ np.asarray([self_gain, neighbor_gain], dtype=float)
        residuals = observed_vector - predicted
        sse = float(np.sum(np.square(residuals)))
        if best is None or sse < best[0]:
            best = (sse, self_gain, neighbor_gain, float(decay_length), residuals)

    assert best is not None
    _, self_gain, neighbor_gain, decay_length_mm, residuals = best
    preset_name = base_config.preset_name if base_config.preset_name in PRESET_DEFAULTS else "other"
    fitted = replace(
        base_config,
        enabled=True,
        preset_name=preset_name,
        self_gain=self_gain,
        neighbor_gain=neighbor_gain,
        decay_length_mm=decay_length_mm,
        use_advanced_override=True,
    )
    validate_mechanical_config(fitted)
    rms = float(np.sqrt(np.mean(np.square(residuals)))) if residuals.size else 0.0
    if rms > 0.05:
        warnings.append("Calibration fit residuals are high; treat fitted physical parameters cautiously.")
    return CalibrationFitResult(
        mechanical_model=fitted,
        residual_rms_mm=rms,
        sample_count=int(residuals.size),
        warnings=warnings,
    )


def make_trial_from_project(
    project: ProjectData,
    *,
    name: str,
    before_mesh,
    after_mesh,
    applied_turns: dict[str, float],
) -> CalibrationTrial:
    if not name.strip():
        raise CalibrationError("Calibration trial name is required.")
    if not applied_turns:
        raise CalibrationError("Calibration trial needs at least one applied turn.")
    normalized_turns = {
        str(key): _finite_float(f"Calibration trial applied turn for {key}", value)
        for key, value in applied_turns.items()
    }
    trial = CalibrationTrial(
        name=name.strip(),
        before_mesh=before_mesh,
        after_mesh=after_mesh,
        applied_turns=normalized_turns,
        bed=project.bed,
        screws=list(project.screws),
        turn_config=project.turn_config,
        reference_screw_name=project.reference_screw_name,
        coordinate_convention=project.coordinate_convention,
        metadata=project.metadata,
    )
    _validated_screw_positions(trial)
    return trial


def _trial_observations(trial: CalibrationTrial) -> list[_Observation]:
    screw_positions = _validated_screw_positions(trial)
    names = [name for name, _, _ in screw_positions]
    reference_index = names.index(trial.reference_screw_name)
    q_by_name = {
        str(name): _finite_float(f"{trial.name}: applied turn for {name}", turns) * trial.turn_config.pitch_mm_per_turn
        for name, turns in trial.applied_turns.items()
    }
    unknown_turns = sorted(set(q_by_name) - set(names))
    if unknown_turns:
        raise CalibrationError(f"{trial.name}: applied turns reference unknown screws: {', '.join(unknown_turns)}.")

    before_heights = _sample_mesh_at_screws(trial.before_mesh, screw_positions)
    after_heights = _sample_mesh_at_screws(trial.after_mesh, screw_positions)
    height_change = after_heights - before_heights
    observed_relative = height_change - float(height_change[reference_index])

    observations: list[_Observation] = []
    coordinates = np.asarray([(x_mm, y_mm) for _, x_mm, y_mm in screw_positions], dtype=float)
    for row_index, (name, _, _) in enumerate(screw_positions):
        if name == trial.reference_screw_name:
            continue
        self_coeff = 0.0
        neighbor_terms: list[tuple[float, float]] = []
        for column_index, column_name in enumerate(names):
            q_mm = q_by_name.get(column_name, 0.0)
            if abs(q_mm) < 1e-12:
                continue
            row_distance = float(np.linalg.norm(coordinates[row_index] - coordinates[column_index]))
            ref_distance = float(np.linalg.norm(coordinates[reference_index] - coordinates[column_index]))
            if row_index == column_index:
                self_coeff += q_mm
            else:
                neighbor_terms.append((q_mm, row_distance))
            if reference_index == column_index:
                self_coeff -= q_mm
            else:
                neighbor_terms.append((-q_mm, ref_distance))
        if abs(self_coeff) < 1e-12 and not neighbor_terms:
            continue
        observations.append(
            _Observation(
                self_coeff=self_coeff,
                neighbor_terms=tuple(neighbor_terms),
                observed_mm=float(observed_relative[row_index]),
            )
        )
    return observations


def _validated_screw_positions(trial: CalibrationTrial) -> list[tuple[str, float, float]]:
    validate_turn_config(trial.turn_config)
    _validate_mesh_pair(trial)
    if len(trial.screws) < 3:
        raise CalibrationError(f"{trial.name}: at least 3 screws are required for calibration.")

    names = [screw.name.strip() for screw in trial.screws]
    if any(not name for name in names):
        raise CalibrationError(f"{trial.name}: all calibration screws must have a name.")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise CalibrationError(f"{trial.name}: duplicate screw names are not allowed: {', '.join(duplicates)}.")
    if trial.reference_screw_name not in names:
        raise CalibrationError(f"{trial.name}: reference screw is missing from the trial screw snapshot.")

    q_names = set()
    for name, turns in trial.applied_turns.items():
        q_names.add(str(name))
        _finite_float(f"{trial.name}: applied turn for {name}", turns)
    unknown_turns = sorted(q_names - set(names))
    if unknown_turns:
        raise CalibrationError(f"{trial.name}: applied turns reference unknown screws: {', '.join(unknown_turns)}.")

    bed_height = _finite_float(f"{trial.name}: bed height", trial.bed.height_mm)
    screw_positions: list[tuple[str, float, float]] = []
    for screw in trial.screws:
        left_mm = _finite_float(f"{trial.name}: screw {screw.name} left_mm", screw.left_mm)
        y_measure_mm = _finite_float(f"{trial.name}: screw {screw.name} y_measure_mm", screw.y_measure_mm)
        try:
            x_mm, y_mm = measurement_to_internal(
                left_mm,
                y_measure_mm,
                bed_height,
                trial.coordinate_convention.screw_y_reference_edge,
            )
        except ValueError as exc:
            raise CalibrationError(f"{trial.name}: {exc}") from exc
        screw_positions.append((screw.name, x_mm, y_mm))

    positions_by_key: dict[tuple[float, float], list[str]] = {}
    for name, x_mm, y_mm in screw_positions:
        positions_by_key.setdefault((round(x_mm, 6), round(y_mm, 6)), []).append(name)
        for label, mesh in (("before", trial.before_mesh), ("after", trial.after_mesh)):
            if not mesh.contains_point(x_mm, y_mm):
                raise CalibrationError(
                    f"{trial.name}: screw '{name}' lies outside the {label} calibration mesh bounds."
                )
    duplicate_positions = [
        duplicate_names
        for duplicate_names in positions_by_key.values()
        if len(duplicate_names) > 1
    ]
    if duplicate_positions:
        joined = "; ".join(", ".join(names_at_position) for names_at_position in duplicate_positions)
        raise CalibrationError(f"{trial.name}: duplicate internal screw positions are not allowed: {joined}.")

    return screw_positions


def _validate_mesh_pair(trial: CalibrationTrial) -> None:
    for label, mesh in (("before", trial.before_mesh), ("after", trial.after_mesh)):
        _validate_trial_mesh(trial.name, label, mesh)
    before = trial.before_mesh
    after = trial.after_mesh
    if before.row_count != after.row_count or before.column_count != after.column_count:
        raise CalibrationError(f"{trial.name}: before and after calibration meshes must have matching dimensions.")
    if before.top_row_is_y_max != after.top_row_is_y_max or not all(
        _close_float(left, right)
        for left, right in (
            (before.x_min_mm, after.x_min_mm),
            (before.x_max_mm, after.x_max_mm),
            (before.y_min_mm, after.y_min_mm),
            (before.y_max_mm, after.y_max_mm),
        )
    ):
        raise CalibrationError(f"{trial.name}: before and after calibration meshes must have matching bounds and row order.")


def _validate_trial_mesh(trial_name: str, label: str, mesh: MeshGrid) -> None:
    if mesh.row_count < 2 or mesh.column_count < 2:
        raise CalibrationError(f"{trial_name}: {label} calibration mesh must be at least 2x2.")
    bounds = (mesh.x_min_mm, mesh.x_max_mm, mesh.y_min_mm, mesh.y_max_mm)
    if any(not math.isfinite(float(value)) for value in bounds):
        raise CalibrationError(f"{trial_name}: {label} calibration mesh bounds must be finite.")
    if mesh.x_min_mm >= mesh.x_max_mm or mesh.y_min_mm >= mesh.y_max_mm:
        raise CalibrationError(f"{trial_name}: {label} calibration mesh bounds must satisfy x_min < x_max and y_min < y_max.")
    if any(len(row) != mesh.column_count for row in mesh.z_values):
        raise CalibrationError(f"{trial_name}: {label} calibration mesh rows must all have the same number of columns.")
    if any(not math.isfinite(float(cell)) for row in mesh.z_values for cell in row):
        raise CalibrationError(f"{trial_name}: {label} calibration mesh values must be finite.")


def _close_float(left: float, right: float, tolerance: float = 1e-9) -> bool:
    return abs(float(left) - float(right)) <= tolerance


def _decay_candidates(spans: Sequence[float]) -> np.ndarray:
    spans = [span for span in spans if math.isfinite(span) and span > 0.0]
    median_span = float(np.median(spans)) if spans else 200.0
    low = max(20.0, median_span * 0.15)
    high = max(low + 1.0, median_span * 2.0)
    return np.linspace(low, high, 241, dtype=float)


def _median_bed_span(trial: CalibrationTrial) -> float:
    return float(np.median([trial.bed.width_mm, trial.bed.height_mm]))


def _sample_mesh_at_screws(mesh, screw_positions: Sequence[tuple[str, float, float]]) -> np.ndarray:
    x_coords = mesh.x_coordinates()
    y_coords = mesh.y_coordinates()
    return np.asarray(
        [
            bilinear_interpolate(x_coords, y_coords, mesh.z_values, x_mm, y_mm)
            for _, x_mm, y_mm in screw_positions
        ],
        dtype=float,
    )


def _finite_float(label: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise CalibrationError(f"{label} must be finite.")
    return number
