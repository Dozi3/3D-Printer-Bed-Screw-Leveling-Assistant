from __future__ import annotations

from dataclasses import replace
import math
from math import exp
from typing import Sequence

import numpy as np

from materials import (
    DEFAULT_SUPPORT_MATERIAL_BY_MOUNT,
    DEFAULT_SUPPORT_STACK_HEIGHT_MM,
    MaterialResponseProfile,
    choice_uses_custom_response,
    lookup_material_entry,
    material_label,
    material_profile,
    normalize_mount_type,
)
from models import (
    BedConfig,
    EffectiveMechanicalModel,
    EnvironmentMetadata,
    MechanicalConfidence,
    MechanicalModelConfig,
    ScrewInstruction,
    TurnPlan,
    TurnStep,
)
from solver import HOLD_THRESHOLD_MM

DEFAULT_REGULARIZATION_LAMBDA = 1e-5
AGGRESSIVE_COUPLING_RATIO = 0.8
AMBIENT_REFERENCE_C = 20.0
MIN_STEP_TURNS = 1.0 / 64.0
MAX_NEIGHBOR_TO_SELF_RATIO = 0.85

PRESET_DEFAULTS: dict[str, MechanicalModelConfig] = {
    "springs": MechanicalModelConfig(
        enabled=True,
        preset_name="springs",
        self_gain=0.80,
        neighbor_gain=0.25,
        decay_length_mm=180.0,
        max_step_turns=0.125,
        regularization_lambda=DEFAULT_REGULARIZATION_LAMBDA,
        use_advanced_override=False,
    ),
    "silicone": MechanicalModelConfig(
        enabled=True,
        preset_name="silicone",
        self_gain=0.85,
        neighbor_gain=0.15,
        decay_length_mm=140.0,
        max_step_turns=0.0625,
        regularization_lambda=DEFAULT_REGULARIZATION_LAMBDA,
        use_advanced_override=False,
    ),
    "rigid spacers": MechanicalModelConfig(
        enabled=True,
        preset_name="rigid spacers",
        self_gain=0.95,
        neighbor_gain=0.04,
        decay_length_mm=100.0,
        max_step_turns=0.03125,
        regularization_lambda=DEFAULT_REGULARIZATION_LAMBDA,
        use_advanced_override=False,
    ),
    "shims": MechanicalModelConfig(
        enabled=True,
        preset_name="shims",
        self_gain=1.00,
        neighbor_gain=0.02,
        decay_length_mm=80.0,
        max_step_turns=0.03125,
        regularization_lambda=DEFAULT_REGULARIZATION_LAMBDA,
        use_advanced_override=False,
    ),
    "other": MechanicalModelConfig(
        enabled=True,
        preset_name="other",
        self_gain=0.85,
        neighbor_gain=0.12,
        decay_length_mm=140.0,
        max_step_turns=0.0625,
        regularization_lambda=DEFAULT_REGULARIZATION_LAMBDA,
        use_advanced_override=False,
    ),
}


class MechanicalModelError(ValueError):
    pass


def infer_preset_name(mount_type: str) -> str:
    normalized = normalize_mount_type(mount_type)
    return normalized if normalized in PRESET_DEFAULTS else "other"


def default_mechanical_config(
    metadata: EnvironmentMetadata,
    *,
    enabled: bool,
) -> MechanicalModelConfig:
    preset_name = infer_preset_name(metadata.mount_type)
    return replace(PRESET_DEFAULTS[preset_name], enabled=enabled)


def effective_mechanical_config(
    config: MechanicalModelConfig,
    metadata: EnvironmentMetadata,
    screw_positions: Sequence[tuple[str, float, float]] | None = None,
) -> MechanicalModelConfig:
    resolved, _, _, _ = resolve_effective_mechanical_model(config, metadata, screw_positions)
    return resolved


def resolve_effective_mechanical_model(
    config: MechanicalModelConfig,
    metadata: EnvironmentMetadata,
    screw_positions: Sequence[tuple[str, float, float]] | None = None,
) -> tuple[MechanicalModelConfig, EffectiveMechanicalModel, MechanicalConfidence, list[str]]:
    base = _base_mechanical_config(config, metadata)
    validate_mechanical_config(base)

    support_mount = infer_preset_name(metadata.mount_type)
    support_height = metadata.support_assembly.support_stack_height_mm
    if support_height <= 0.0:
        raise MechanicalModelError("Support stack height must be greater than zero.")
    if not math.isfinite(float(support_height)):
        raise MechanicalModelError("Support stack height must be finite.")

    plate_choice = metadata.bed_assembly.plate_material
    surface_choice = metadata.bed_assembly.surface_material
    support_choice = metadata.support_assembly.support_material
    screw_choice = metadata.fastener.screw_material

    plate_profile = material_profile(plate_choice, "plate")
    surface_profile = (
        material_profile(surface_choice, "surface")
        if choice_uses_custom_response(surface_choice)
        else MaterialResponseProfile()
    )
    support_profile = material_profile(support_choice, "support")
    screw_profile = material_profile(screw_choice, "screw")

    bed_temperature = metadata.bed_temperature_c
    chamber_temperature = metadata.chamber_temperature_c
    bed_hot = max(0.0, ((bed_temperature or AMBIENT_REFERENCE_C) - AMBIENT_REFERENCE_C) / 80.0)
    chamber_hot = max(0.0, ((chamber_temperature or AMBIENT_REFERENCE_C) - AMBIENT_REFERENCE_C) / 40.0)
    stack_factor = _clamp(support_height / 15.0, 0.5, 1.75)
    thermal_index = _clamp(stack_factor * ((0.65 * bed_hot) + (0.35 * chamber_hot)), 0.0, 2.0)

    self_gain = (
        base.self_gain
        * support_profile.self_mult
        * screw_profile.self_mult
        * (1.0 - (support_profile.self_temp_coeff * thermal_index))
    )
    neighbor_gain = (
        base.neighbor_gain
        * plate_profile.neighbor_mult
        * surface_profile.neighbor_mult
        * support_profile.neighbor_mult
        * (1.0 + (support_profile.neighbor_temp_coeff * thermal_index))
    )
    decay_length_mm = base.decay_length_mm * plate_profile.decay_mult * surface_profile.decay_mult
    step_temp_coeff = max(support_profile.step_temp_coeff, screw_profile.step_temp_coeff)
    max_step_turns = (
        base.max_step_turns
        * plate_profile.step_mult
        * surface_profile.step_mult
        * support_profile.step_mult
        * screw_profile.step_mult
        * (1.0 - (step_temp_coeff * thermal_index))
    )
    max_step_turns = _clamp(max_step_turns, MIN_STEP_TURNS, base.max_step_turns)
    for absolute_cap in (
        plate_profile.absolute_cap_turns,
        surface_profile.absolute_cap_turns,
        support_profile.absolute_cap_turns,
        screw_profile.absolute_cap_turns,
    ):
        if absolute_cap is not None:
            max_step_turns = min(max_step_turns, absolute_cap)

    reasons = [
        (
            f"Thermal index {thermal_index:.2f} from bed {bed_temperature if bed_temperature is not None else 'n/a'} C, "
            f"chamber {chamber_temperature if chamber_temperature is not None else 'n/a'} C, "
            f"stack {support_height:.1f} mm."
        )
    ]
    if choice_uses_custom_response(plate_choice):
        reasons.append("Custom bed-plate override is active.")
    if choice_uses_custom_response(surface_choice):
        reasons.append("Custom bed-surface override is active.")
    if choice_uses_custom_response(support_choice):
        reasons.append("Custom support-material override is active.")
    if choice_uses_custom_response(screw_choice):
        reasons.append("Custom screw-material override is active.")

    self_gain = max(0.001, float(self_gain))
    neighbor_gain = max(0.0, float(neighbor_gain))
    decay_length_mm = max(1.0, float(decay_length_mm))
    if neighbor_gain >= (MAX_NEIGHBOR_TO_SELF_RATIO * self_gain):
        neighbor_gain = max(0.0, (MAX_NEIGHBOR_TO_SELF_RATIO * self_gain) - 1e-6)
        reasons.append("Neighbour gain was capped below self gain for stability.")

    resolved = replace(
        base,
        self_gain=self_gain,
        neighbor_gain=neighbor_gain,
        decay_length_mm=decay_length_mm,
        max_step_turns=max_step_turns,
    )
    validate_mechanical_config(resolved)

    warnings = _build_material_warnings(metadata, resolved, thermal_index)
    aggressive = coupling_warnings(resolved, screw_positions or [])
    warnings.extend(aggressive)
    confidence = _build_confidence(metadata, thermal_index, aggressive)
    effective = EffectiveMechanicalModel(
        enabled=resolved.enabled,
        preset_name=resolved.preset_name,
        self_gain=resolved.self_gain,
        neighbor_gain=resolved.neighbor_gain,
        decay_length_mm=resolved.decay_length_mm,
        max_step_turns=resolved.max_step_turns,
        regularization_lambda=resolved.regularization_lambda,
        thermal_index=float(thermal_index),
        reasons=_dedupe_messages(reasons),
    )
    return resolved, effective, confidence, _dedupe_messages(warnings)


def validate_mechanical_config(config: MechanicalModelConfig) -> None:
    for label, value in (
        ("self gain", config.self_gain),
        ("neighbour gain", config.neighbor_gain),
        ("decay length", config.decay_length_mm),
        ("max step turns", config.max_step_turns),
        ("regularization", config.regularization_lambda),
    ):
        if not math.isfinite(float(value)):
            raise MechanicalModelError(f"Mechanical model {label} must be finite.")
    if config.self_gain <= 0.0:
        raise MechanicalModelError("Mechanical model self gain must be greater than zero.")
    if config.neighbor_gain < 0.0:
        raise MechanicalModelError("Mechanical model neighbour gain must be non-negative.")
    if config.neighbor_gain >= config.self_gain:
        raise MechanicalModelError("Mechanical model neighbour gain must stay below self gain.")
    if config.decay_length_mm <= 0.0:
        raise MechanicalModelError("Mechanical model decay length must be greater than zero.")
    if config.max_step_turns <= 0.0:
        raise MechanicalModelError("Mechanical model max step turns must be greater than zero.")
    if config.regularization_lambda <= 0.0:
        raise MechanicalModelError("Mechanical model regularization must be greater than zero.")


def coupling_warnings(
    config: MechanicalModelConfig,
    screw_positions: Sequence[tuple[str, float, float]],
) -> list[str]:
    warnings: list[str] = []
    if len(screw_positions) < 2:
        if config.preset_name == "shims":
            warnings.append(
                "Shim workflows are approximate here; treat turns as mm-equivalent support change and re-mesh after each change."
            )
        return warnings
    matrix = build_coupling_matrix(screw_positions, config)
    off_diagonal = np.abs(matrix - np.diag(np.diag(matrix)))
    row_sums = off_diagonal.sum(axis=1)
    if np.any(row_sums > (AGGRESSIVE_COUPLING_RATIO * config.self_gain)):
        warnings.append("Physical model coupling looks aggressive for this screw layout.")
    if config.preset_name == "shims":
        warnings.append(
            "Shim workflows are approximate here; treat turns as mm-equivalent support change and re-mesh after each change."
        )
    return warnings


def build_coupling_matrix(
    screw_positions: Sequence[tuple[str, float, float]],
    config: MechanicalModelConfig,
) -> np.ndarray:
    validate_mechanical_config(config)
    coordinates = np.asarray([(x_mm, y_mm) for _, x_mm, y_mm in screw_positions], dtype=float)
    if not np.all(np.isfinite(coordinates)):
        raise MechanicalModelError("Screw positions must be finite.")
    count = coordinates.shape[0]
    matrix = np.zeros((count, count), dtype=float)
    for row in range(count):
        for column in range(count):
            if row == column:
                matrix[row, column] = config.self_gain
                continue
            distance = float(np.hypot(*(coordinates[row] - coordinates[column])))
            matrix[row, column] = config.neighbor_gain * exp(-distance / config.decay_length_mm)
    return matrix


def solve_physical_response(
    screw_positions: Sequence[tuple[str, float, float]],
    baseline_delta_mm: dict[str, float],
    reference_screw_name: str,
    config: MechanicalModelConfig,
    hold_threshold_mm: float = HOLD_THRESHOLD_MM,
) -> tuple[dict[str, float], dict[str, float], list[str], list[str]]:
    validate_mechanical_config(config)
    if not math.isfinite(float(hold_threshold_mm)) or hold_threshold_mm < 0.0:
        raise MechanicalModelError("Hold threshold must be a finite non-negative value.")

    names = [name for name, _, _ in screw_positions]
    reference_index = names.index(reference_screw_name)
    non_reference_names = [name for name in names if name != reference_screw_name]
    baseline_vector = np.asarray([baseline_delta_mm[name] for name in non_reference_names], dtype=float)
    if not np.all(np.isfinite(baseline_vector)):
        raise MechanicalModelError("Baseline deltas must be finite.")
    active_names = [
        name for name in non_reference_names if abs(baseline_delta_mm[name]) >= hold_threshold_mm
    ]

    commanded_mm = {name: 0.0 for name in names}
    if not active_names:
        return commanded_mm, {name: 0.0 for name in names}, [], []

    matrix = build_coupling_matrix(screw_positions, config)
    global_index = {name: index for index, name in enumerate(names)}
    active_indices = [global_index[name] for name in active_names]
    sign_vector = np.asarray(
        [1.0 if baseline_delta_mm[name] > 0.0 else -1.0 for name in active_names],
        dtype=float,
    )

    response_matrix = np.zeros((len(non_reference_names), len(active_names)), dtype=float)
    for row, name in enumerate(non_reference_names):
        screw_index = global_index[name]
        for column, active_index in enumerate(active_indices):
            response_matrix[row, column] = (
                matrix[screw_index, active_index] - matrix[reference_index, active_index]
            ) * sign_vector[column]

    magnitudes = _solve_non_negative_ridge(
        response_matrix,
        baseline_vector,
        config.regularization_lambda,
    )

    for name, sign, magnitude in zip(active_names, sign_vector, magnitudes, strict=True):
        commanded_mm[name] = float(sign * magnitude)

    achieved_delta = _compute_achieved_delta(matrix, commanded_mm, names, reference_index)

    warnings: list[str] = []
    suppressed: list[str] = []
    for name in active_names:
        target = baseline_delta_mm[name]
        achieved = achieved_delta[name]
        if abs(achieved) >= hold_threshold_mm and (achieved > 0.0) != (target > 0.0):
            warnings.append(
                f"Physical model direction conflict at {name}; suppressing the physical recommendation for this screw."
            )
            suppressed.append(name)
            commanded_mm[name] = 0.0

    if suppressed:
        achieved_delta = _compute_achieved_delta(matrix, commanded_mm, names, reference_index)

    return commanded_mm, achieved_delta, warnings, suppressed


def build_turn_plan(
    source_model: str,
    instructions: Sequence[ScrewInstruction],
    reference_screw_name: str,
    max_step_turns: float,
    bed: BedConfig,
    *,
    warnings: Sequence[str] = (),
) -> TurnPlan:
    total_target_turns = {instruction.name: instruction.signed_turns for instruction in instructions}
    active = [
        instruction
        for instruction in instructions
        if instruction.name != reference_screw_name and abs(instruction.signed_turns) >= 1e-12
    ]

    if not active:
        return TurnPlan(
            source_model=source_model,  # type: ignore[arg-type]
            total_target_turns=total_target_turns,
            first_pass_steps=[],
            requires_remesh_after_pass=True,
            warnings=[*warnings, "Re-mesh after this pass."],
        )

    largest = max(abs(instruction.signed_turns) for instruction in active)
    scale = 1.0 if largest <= max_step_turns else max_step_turns / largest
    plan_warnings = list(warnings)
    if scale < 1.0:
        plan_warnings.append(
            f"First-pass turns scaled to keep the largest move within {max_step_turns:.4f} turns."
        )

    ordered = _order_instructions_for_first_pass(active, instructions, bed)
    steps: list[TurnStep] = []
    for instruction in ordered:
        first_pass_turns = abs(instruction.signed_turns * scale)
        remaining_turns = max(0.0, abs(instruction.signed_turns) - first_pass_turns)
        steps.append(
            TurnStep(
                pass_index=1,
                screw_name=instruction.name,
                action=instruction.action,
                rotation=instruction.direction,
                turns_this_pass=float(first_pass_turns),
                remaining_after_pass=float(remaining_turns),
                note="Re-mesh before the next pass." if remaining_turns > 0.0 else None,
            )
        )

    plan_warnings.append("Re-mesh after this pass.")
    return TurnPlan(
        source_model=source_model,  # type: ignore[arg-type]
        total_target_turns=total_target_turns,
        first_pass_steps=steps,
        requires_remesh_after_pass=True,
        warnings=plan_warnings,
    )


def _base_mechanical_config(
    config: MechanicalModelConfig,
    metadata: EnvironmentMetadata,
) -> MechanicalModelConfig:
    preset_name = config.preset_name if config.preset_name in PRESET_DEFAULTS else infer_preset_name(metadata.mount_type)
    preset = PRESET_DEFAULTS[preset_name]
    if config.use_advanced_override:
        return replace(config, preset_name=preset_name)
    return replace(
        preset,
        enabled=config.enabled,
        preset_name=preset_name,
        use_advanced_override=False,
    )


def _compute_achieved_delta(
    matrix: np.ndarray,
    commanded_mm: dict[str, float],
    names: Sequence[str],
    reference_index: int,
) -> dict[str, float]:
    q_vector = np.asarray([commanded_mm[name] for name in names], dtype=float)
    achieved_absolute = matrix @ q_vector
    reference_achieved = float(achieved_absolute[reference_index])
    return {
        name: float(achieved_absolute[index] - reference_achieved)
        for index, name in enumerate(names)
    }


def _build_material_warnings(
    metadata: EnvironmentMetadata,
    resolved: MechanicalModelConfig,
    thermal_index: float,
) -> list[str]:
    warnings: list[str] = []
    if resolved.enabled and metadata.bed_temperature_c is None:
        warnings.append("No bed temperature recorded. Thermal modifiers assume ambient for the physical model.")
    if resolved.enabled and metadata.chamber_temperature_c is None:
        warnings.append("No chamber temperature recorded. Thermal modifiers assume ambient for the physical model.")

    plate_entry = lookup_material_entry("plate", metadata.bed_assembly.plate_material.library_key)
    surface_entry = lookup_material_entry("surface", metadata.bed_assembly.surface_material.library_key)
    support_entry = lookup_material_entry("support", metadata.support_assembly.support_material.library_key)
    screw_entry = lookup_material_entry("screw", metadata.fastener.screw_material.library_key)

    warnings.extend(plate_entry.notes)
    warnings.extend(surface_entry.notes)
    warnings.extend(support_entry.notes)
    warnings.extend(screw_entry.notes)

    if metadata.bed_assembly.plate_material.library_key in {"borosilicate_glass", "graphite"}:
        warnings.append("Brittle bed material detected; first-pass moves are capped at 1/32 turn.")

    for entry in (support_entry, screw_entry):
        for rule in entry.warning_rules:
            if _warning_rule_matches(rule, metadata.bed_temperature_c, metadata.chamber_temperature_c):
                warnings.append(rule.message)

    if choice_uses_custom_response(metadata.bed_assembly.plate_material):
        warnings.append("Custom bed-plate override active. Re-check the first pass before trusting larger moves.")
    if choice_uses_custom_response(metadata.bed_assembly.surface_material):
        warnings.append("Custom bed-surface override active. Surface effects are heuristic and should be verified by re-meshing.")
    if choice_uses_custom_response(metadata.support_assembly.support_material):
        warnings.append("Custom support-material override active. Physical-response confidence depends on the entered heuristics.")
    if choice_uses_custom_response(metadata.fastener.screw_material):
        warnings.append("Custom screw-material override active. Keep first-pass moves short until the stack is validated.")

    if thermal_index >= 0.75 and metadata.support_assembly.support_material.library_key == "silicone_elastomer":
        warnings.append("Hot silicone stack detected; expect more settling and re-mesh after short passes.")
    if thermal_index >= 0.75 and metadata.support_assembly.support_material.library_key in {
        "pom_delrin",
        "nylon_pa",
        "printed_polymer",
    }:
        warnings.append("Hot polymer support stack detected; response repeatability is lower than metal hardware.")

    return _dedupe_messages(warnings)


def _build_confidence(
    metadata: EnvironmentMetadata,
    thermal_index: float,
    aggressive_warnings: Sequence[str],
) -> MechanicalConfidence:
    score = 1.0
    reasons: list[str] = []

    choices = (
        metadata.bed_assembly.plate_material,
        metadata.bed_assembly.surface_material,
        metadata.support_assembly.support_material,
        metadata.fastener.screw_material,
    )
    custom_or_other = sum(1 for choice in choices if choice.kind == "custom" or choice.library_key == "other")
    if custom_or_other:
        penalty = min(0.15 * custom_or_other, 0.30)
        score -= penalty
        reasons.append("Custom or unclassified materials reduce confidence.")

    if metadata.bed_assembly.plate_material.library_key in {"borosilicate_glass", "graphite"}:
        score -= 0.10
        reasons.append("Brittle bed plates reduce confidence in larger first-pass moves.")

    support_key = metadata.support_assembly.support_material.library_key
    if thermal_index >= 0.75 and support_key == "silicone_elastomer":
        score -= 0.15
        reasons.append("Hot silicone support stacks are creep-sensitive.")
    if thermal_index >= 0.75 and support_key in {"pom_delrin", "nylon_pa", "printed_polymer"}:
        score -= 0.20
        reasons.append("Hot polymer support stacks are low-repeatability.")
    if metadata.support_assembly.support_stack_height_mm > 18.0:
        score -= 0.10
        reasons.append("Tall support stacks amplify thermal and compliance uncertainty.")

    screw_key = metadata.fastener.screw_material.library_key
    if screw_key in {"brass", "aluminum"}:
        score -= 0.10
        reasons.append("Soft-metal screws reduce confidence in repeated adjustments.")
    if screw_key in {"peek", "nylon"}:
        score -= 0.25
        reasons.append("Polymer screws materially reduce physical-model confidence.")

    if metadata.bed_temperature_c is None:
        score -= 0.10
        reasons.append("Missing bed temperature forces ambient thermal assumptions.")
    if metadata.chamber_temperature_c is None:
        score -= 0.10
        reasons.append("Missing chamber temperature forces ambient thermal assumptions.")

    if any("aggressive" in warning.lower() for warning in aggressive_warnings):
        score -= 0.10
        reasons.append("Coupling looks aggressive for this screw layout.")

    score = _clamp(score, 0.0, 1.0)
    if score >= 0.75:
        level = "high"
    elif score >= 0.50:
        level = "medium"
    else:
        level = "low"
    return MechanicalConfidence(score=float(score), level=level, reasons=_dedupe_messages(reasons))


def _warning_rule_matches(
    rule,
    bed_temperature_c: float | None,
    chamber_temperature_c: float | None,
) -> bool:
    bed_match = rule.bed_threshold_c is not None and bed_temperature_c is not None and bed_temperature_c >= rule.bed_threshold_c
    chamber_match = (
        rule.chamber_threshold_c is not None
        and chamber_temperature_c is not None
        and chamber_temperature_c >= rule.chamber_threshold_c
    )
    return bed_match or chamber_match


def _solve_non_negative_ridge(
    matrix: np.ndarray,
    targets: np.ndarray,
    regularization_lambda: float,
) -> np.ndarray:
    if matrix.size == 0:
        return np.zeros(matrix.shape[1], dtype=float)

    active = list(range(matrix.shape[1]))
    solution = np.zeros(matrix.shape[1], dtype=float)

    while active:
        active_matrix = matrix[:, active]
        regularized_design = np.vstack(
            (
                active_matrix,
                np.sqrt(regularization_lambda) * np.eye(len(active), dtype=float),
            )
        )
        regularized_targets = np.concatenate((targets, np.zeros(len(active), dtype=float)))
        partial, _, _, _ = np.linalg.lstsq(regularized_design, regularized_targets, rcond=None)
        negative_indexes = [index for index, value in enumerate(partial) if value < 0.0]
        if not negative_indexes:
            for active_index, value in zip(active, partial, strict=True):
                solution[active_index] = max(0.0, float(value))
            break
        for index in sorted(negative_indexes, reverse=True):
            del active[index]

    return solution


def _order_instructions_for_first_pass(
    instructions: Sequence[ScrewInstruction],
    layout_instructions: Sequence[ScrewInstruction],
    bed: BedConfig,
) -> list[ScrewInstruction]:
    if len(layout_instructions) != 4:
        return sorted(instructions, key=lambda item: (-abs(item.signed_turns), item.name))

    quadrants: dict[str, ScrewInstruction] = {}
    centre_x = bed.width_mm / 2.0
    centre_y = bed.height_mm / 2.0
    for instruction in layout_instructions:
        quadrant = _quadrant(instruction.x_mm, instruction.y_mm, centre_x, centre_y)
        if quadrant in quadrants:
            return sorted(instructions, key=lambda item: (-abs(item.signed_turns), item.name))
        quadrants[quadrant] = instruction

    ordered = sorted(instructions, key=lambda item: (-abs(item.signed_turns), item.name))
    if not ordered:
        return []
    first = ordered[0]
    first_quadrant = _quadrant(first.x_mm, first.y_mm, centre_x, centre_y)
    opposite = quadrants.get(_opposite_quadrant(first_quadrant))
    final_order = [first]
    if opposite is not None and opposite is not first and opposite in instructions:
        final_order.append(opposite)
    for instruction in ordered[1:]:
        if instruction not in final_order:
            final_order.append(instruction)
    return final_order


def _quadrant(x_mm: float, y_mm: float, centre_x: float, centre_y: float) -> str:
    horizontal = "left" if x_mm <= centre_x else "right"
    vertical = "rear" if y_mm >= centre_y else "front"
    return f"{vertical}-{horizontal}"


def _opposite_quadrant(quadrant: str) -> str:
    mapping = {
        "front-left": "rear-right",
        "front-right": "rear-left",
        "rear-left": "front-right",
        "rear-right": "front-left",
    }
    return mapping[quadrant]


def _dedupe_messages(messages: Sequence[str]) -> list[str]:
    deduped: list[str] = []
    for message in messages:
        if message and message not in deduped:
            deduped.append(message)
    return deduped


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))
