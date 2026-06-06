from __future__ import annotations

import json
import math
from pathlib import Path

from materials import (
    DEFAULT_SUPPORT_STACK_HEIGHT_MM,
    default_bed_assembly,
    default_fastener_config,
    default_support_assembly,
    infer_legacy_plate_choice,
    infer_legacy_screw_choice,
    infer_legacy_support_choice,
    normalize_mount_type,
)
from mechanics import MechanicalModelError, default_mechanical_config, infer_preset_name, validate_mechanical_config
from mesh_io import build_mesh_grid
from models import (
    BedAssemblyConfig,
    BedConfig,
    CalibrationTrial,
    CoordinateConvention,
    EnvironmentMetadata,
    FastenerConfig,
    MaterialChoice,
    MaterialResponseOverride,
    MechanicalModelConfig,
    MeshGrid,
    ProjectData,
    ScrewMeasurement,
    ScrewTurnConfig,
    SupportAssemblyConfig,
)
from solver import validate_turn_config

SCHEMA_VERSION = 4


class ProjectDataError(ValueError):
    pass


def save_project(path: str | Path, project: ProjectData) -> None:
    output_path = Path(path)
    normalized = ProjectData(
        bed=project.bed,
        screws=project.screws,
        turn_config=project.turn_config,
        reference_screw_name=project.reference_screw_name,
        coordinate_convention=project.coordinate_convention,
        mechanical_model=project.mechanical_model,
        metadata=project.metadata,
        mesh=project.mesh,
        calibration_trials=project.calibration_trials,
        schema_version=SCHEMA_VERSION,
    )
    try:
        payload = json.dumps(_project_to_dict(normalized), indent=2, allow_nan=False)
    except ValueError as exc:
        raise ProjectDataError(str(exc)) from exc
    output_path.write_text(payload, encoding="utf-8")


def load_project(path: str | Path) -> ProjectData:
    data = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    if not isinstance(data, dict):
        raise ProjectDataError("Project file must contain a JSON object.")
    try:
        schema_version = _coerce_int(data.get("schema_version", 1), "schema_version")
        if schema_version == 1:
            return _upgrade_schema_v1(data)
        if schema_version == 2:
            return _upgrade_schema_v2(data)
        if schema_version == 3:
            return _upgrade_schema_v3(data)
        if schema_version != SCHEMA_VERSION:
            raise ProjectDataError(f"Unsupported project schema version: {schema_version}")
        return _load_schema_v4(data)
    except KeyError as exc:
        raise ProjectDataError(f"{exc.args[0]} is required.") from exc


def _project_to_dict(project: ProjectData) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "bed": {
            "width_mm": project.bed.width_mm,
            "height_mm": project.bed.height_mm,
        },
        "screws": [
            {
                "name": screw.name,
                "left_mm": screw.left_mm,
                "y_measure_mm": screw.y_measure_mm,
            }
            for screw in project.screws
        ],
        "turn_config": {
            "pitch_mm_per_turn": project.turn_config.pitch_mm_per_turn,
            "clockwise_effect": project.turn_config.clockwise_effect,
            "viewpoint": project.turn_config.viewpoint,
            "fraction_denominator": project.turn_config.fraction_denominator,
            "hold_threshold_mm": project.turn_config.hold_threshold_mm,
        },
        "reference_screw_name": project.reference_screw_name,
        "coordinate_convention": {
            "screw_y_reference_edge": project.coordinate_convention.screw_y_reference_edge,
            "display_front_edge": project.coordinate_convention.display_front_edge,
        },
        "mechanical_model": {
            "enabled": project.mechanical_model.enabled,
            "preset_name": project.mechanical_model.preset_name,
            "self_gain": project.mechanical_model.self_gain,
            "neighbor_gain": project.mechanical_model.neighbor_gain,
            "decay_length_mm": project.mechanical_model.decay_length_mm,
            "max_step_turns": project.mechanical_model.max_step_turns,
            "regularization_lambda": project.mechanical_model.regularization_lambda,
            "use_advanced_override": project.mechanical_model.use_advanced_override,
        },
        "metadata": _metadata_to_dict(project.metadata),
        "mesh": None if project.mesh is None else _mesh_to_dict(project.mesh),
        "calibration_trials": [
            _calibration_trial_to_dict(trial) for trial in project.calibration_trials
        ],
    }


def _metadata_to_dict(metadata: EnvironmentMetadata) -> dict:
    return {
        "bed_assembly": {
            "plate_material": _material_choice_to_dict(metadata.bed_assembly.plate_material),
            "surface_material": _material_choice_to_dict(metadata.bed_assembly.surface_material),
        },
        "support_assembly": {
            "mount_type": metadata.support_assembly.mount_type,
            "support_material": _material_choice_to_dict(metadata.support_assembly.support_material),
            "support_stack_height_mm": metadata.support_assembly.support_stack_height_mm,
        },
        "fastener": {
            "screw_material": _material_choice_to_dict(metadata.fastener.screw_material),
        },
        "bed_temperature_c": metadata.bed_temperature_c,
        "chamber_temperature_c": metadata.chamber_temperature_c,
    }


def _material_choice_to_dict(choice: MaterialChoice) -> dict:
    payload = {
        "kind": choice.kind,
        "library_key": choice.library_key,
        "label": choice.label,
    }
    if choice.custom_response is not None:
        payload["custom_response"] = {
            "self_multiplier": choice.custom_response.self_multiplier,
            "neighbor_multiplier": choice.custom_response.neighbor_multiplier,
            "decay_multiplier": choice.custom_response.decay_multiplier,
            "step_multiplier": choice.custom_response.step_multiplier,
            "self_temp_coeff": choice.custom_response.self_temp_coeff,
            "neighbor_temp_coeff": choice.custom_response.neighbor_temp_coeff,
            "step_temp_coeff": choice.custom_response.step_temp_coeff,
            "absolute_cap_turns": choice.custom_response.absolute_cap_turns,
        }
    return payload


def _mesh_to_dict(mesh: MeshGrid) -> dict:
    return {
        "z_values": mesh.z_values,
        "x_min_mm": mesh.x_min_mm,
        "x_max_mm": mesh.x_max_mm,
        "y_min_mm": mesh.y_min_mm,
        "y_max_mm": mesh.y_max_mm,
        "top_row_is_y_max": mesh.top_row_is_y_max,
    }


def _calibration_trial_to_dict(trial: CalibrationTrial) -> dict:
    return {
        "name": trial.name,
        "before_mesh": _mesh_to_dict(trial.before_mesh),
        "after_mesh": _mesh_to_dict(trial.after_mesh),
        "applied_turns": trial.applied_turns,
        "bed": {
            "width_mm": trial.bed.width_mm,
            "height_mm": trial.bed.height_mm,
        },
        "screws": [
            {
                "name": screw.name,
                "left_mm": screw.left_mm,
                "y_measure_mm": screw.y_measure_mm,
            }
            for screw in trial.screws
        ],
        "turn_config": {
            "pitch_mm_per_turn": trial.turn_config.pitch_mm_per_turn,
            "clockwise_effect": trial.turn_config.clockwise_effect,
            "viewpoint": trial.turn_config.viewpoint,
            "fraction_denominator": trial.turn_config.fraction_denominator,
            "hold_threshold_mm": trial.turn_config.hold_threshold_mm,
        },
        "reference_screw_name": trial.reference_screw_name,
        "coordinate_convention": {
            "screw_y_reference_edge": trial.coordinate_convention.screw_y_reference_edge,
            "display_front_edge": trial.coordinate_convention.display_front_edge,
        },
        "metadata": _metadata_to_dict(trial.metadata),
    }


def _load_schema_v4(data: dict) -> ProjectData:
    mesh_data = _required(data, "mesh", "mesh")
    mesh = _load_mesh(mesh_data) if mesh_data is not None else None
    coordinate_convention = _load_coordinate_convention(_required(data, "coordinate_convention", "coordinate_convention"))
    mechanical_model = _load_mechanical_model(_required(data, "mechanical_model", "mechanical_model"))
    calibration_trials_data = _expect_list(
        _required(data, "calibration_trials", "calibration_trials"),
        "calibration_trials",
    )
    return ProjectData(
        bed=_load_bed(_required(data, "bed", "bed")),
        screws=[
            _load_screw(entry, index)
            for index, entry in enumerate(_expect_list(_required(data, "screws", "screws"), "screws"), start=1)
        ],
        turn_config=_load_turn_config(_required(data, "turn_config", "turn_config")),
        reference_screw_name=str(_required(data, "reference_screw_name", "reference_screw_name")),
        coordinate_convention=coordinate_convention,
        mechanical_model=mechanical_model,
        metadata=_load_metadata_v3(_required(data, "metadata", "metadata")),
        mesh=mesh,
        calibration_trials=[
            _load_calibration_trial(entry, index)
            for index, entry in enumerate(calibration_trials_data, start=1)
        ],
        schema_version=SCHEMA_VERSION,
    )


def _upgrade_schema_v3(data: dict) -> ProjectData:
    v4_data = {**data}
    v4_data.setdefault("coordinate_convention", {})
    v4_data.setdefault("mechanical_model", {})
    v4_data.setdefault("metadata", {})
    v4_data.setdefault("mesh", None)
    v4_data.setdefault("calibration_trials", [])
    project = _load_schema_v4(v4_data)
    return ProjectData(
        bed=project.bed,
        screws=project.screws,
        turn_config=project.turn_config,
        reference_screw_name=project.reference_screw_name,
        coordinate_convention=project.coordinate_convention,
        mechanical_model=project.mechanical_model,
        metadata=project.metadata,
        mesh=project.mesh,
        calibration_trials=project.calibration_trials,
        schema_version=SCHEMA_VERSION,
        upgraded_from_schema=3,
    )


def _load_metadata_v3(data: dict) -> EnvironmentMetadata:
    if not isinstance(data, dict):
        raise ProjectDataError("metadata must be an object.")
    bed_assembly_data = data.get("bed_assembly", {})
    support_assembly_data = data.get("support_assembly", {})
    fastener_data = data.get("fastener", {})
    mount_type = normalize_mount_type(str(support_assembly_data.get("mount_type", "")))
    default_support = default_support_assembly(mount_type)
    return EnvironmentMetadata(
        bed_assembly=BedAssemblyConfig(
            plate_material=_load_material_choice(
                bed_assembly_data.get("plate_material"),
                default_bed_assembly().plate_material,
            ),
            surface_material=_load_material_choice(
                bed_assembly_data.get("surface_material"),
                default_bed_assembly().surface_material,
            ),
        ),
        support_assembly=SupportAssemblyConfig(
            mount_type=mount_type,
            support_material=_load_material_choice(
                support_assembly_data.get("support_material"),
                default_support.support_material,
            ),
            support_stack_height_mm=_coerce_finite_float(
                support_assembly_data.get(
                    "support_stack_height_mm",
                    default_support.support_stack_height_mm,
                ),
                "support_stack_height_mm",
            ),
        ),
        fastener=FastenerConfig(
            screw_material=_load_material_choice(
                fastener_data.get("screw_material"),
                default_fastener_config().screw_material,
            )
        ),
        bed_temperature_c=_coerce_optional_float(data.get("bed_temperature_c")),
        chamber_temperature_c=_coerce_optional_float(data.get("chamber_temperature_c")),
    )


def _load_material_choice(data: dict | None, default: MaterialChoice) -> MaterialChoice:
    if data is None:
        return default
    if not isinstance(data, dict):
        raise ProjectDataError("Material choice must be an object.")
    custom_data = data.get("custom_response")
    custom_response = _load_material_response_override(custom_data) if custom_data is not None else None
    kind = str(data.get("kind", default.kind))
    if kind not in {"library", "custom"}:
        raise ProjectDataError("Material choice kind must be 'library' or 'custom'.")
    return MaterialChoice(
        kind=kind,
        library_key=str(data.get("library_key", default.library_key)),
        label=str(data.get("label", default.label)),
        custom_response=custom_response,
    )


def _upgrade_schema_v2(data: dict) -> ProjectData:
    metadata = _upgrade_legacy_metadata(data.get("metadata", {}))
    mesh_data = data.get("mesh")
    mesh = _load_mesh(mesh_data) if mesh_data is not None else None
    coordinate_convention = _load_coordinate_convention(data.get("coordinate_convention", {}))
    mechanical_model = _load_mechanical_model(data.get("mechanical_model", {}))
    return ProjectData(
        bed=_load_bed(data["bed"]),
        screws=[
            ScrewMeasurement(
                name=str(entry["name"]),
                left_mm=_coerce_finite_float(entry["left_mm"], "left_mm"),
                y_measure_mm=_coerce_finite_float(entry.get("y_measure_mm", entry.get("top_mm")), "y_measure_mm"),
            )
            for entry in _expect_list(data.get("screws", []), "screws")
        ],
        turn_config=_load_turn_config(data["turn_config"]),
        reference_screw_name=str(data["reference_screw_name"]),
        coordinate_convention=coordinate_convention,
        mechanical_model=mechanical_model,
        metadata=metadata,
        mesh=mesh,
        schema_version=SCHEMA_VERSION,
        upgraded_from_schema=2,
    )


def _upgrade_schema_v1(data: dict) -> ProjectData:
    metadata = _upgrade_legacy_metadata(data.get("metadata", {}))
    screws = [
        ScrewMeasurement(
            name=str(entry["name"]),
            left_mm=_coerce_finite_float(entry["left_mm"], "left_mm"),
            y_measure_mm=_coerce_finite_float(entry.get("top_mm", entry.get("y_measure_mm")), "y_measure_mm"),
        )
        for entry in _expect_list(data.get("screws", []), "screws")
    ]
    mesh_data = data.get("mesh")
    mesh = _load_mesh(mesh_data) if mesh_data is not None else None
    mechanical_defaults = default_mechanical_config(metadata, enabled=False)
    return ProjectData(
        bed=_load_bed(data["bed"]),
        screws=screws,
        turn_config=_load_turn_config(data["turn_config"]),
        reference_screw_name=data["reference_screw_name"],
        coordinate_convention=CoordinateConvention(
            screw_y_reference_edge="top",
            display_front_edge="top",
        ),
        mechanical_model=MechanicalModelConfig(
            enabled=False,
            preset_name=infer_preset_name(metadata.mount_type),
            self_gain=mechanical_defaults.self_gain,
            neighbor_gain=mechanical_defaults.neighbor_gain,
            decay_length_mm=mechanical_defaults.decay_length_mm,
            max_step_turns=mechanical_defaults.max_step_turns,
            regularization_lambda=mechanical_defaults.regularization_lambda,
            use_advanced_override=False,
        ),
        metadata=metadata,
        mesh=mesh,
        schema_version=SCHEMA_VERSION,
        upgraded_from_schema=1,
    )


def _upgrade_legacy_metadata(data: dict) -> EnvironmentMetadata:
    mount_type = normalize_mount_type(str(data.get("mount_type", "")))
    support_assembly = default_support_assembly(mount_type)
    return EnvironmentMetadata(
        bed_assembly=BedAssemblyConfig(
            plate_material=infer_legacy_plate_choice(str(data.get("bed_material", ""))),
            surface_material=default_bed_assembly().surface_material,
        ),
        support_assembly=SupportAssemblyConfig(
            mount_type=mount_type,
            support_material=infer_legacy_support_choice(mount_type, str(data.get("standoff_material", ""))),
            support_stack_height_mm=DEFAULT_SUPPORT_STACK_HEIGHT_MM[mount_type],
        ),
        fastener=FastenerConfig(
            screw_material=infer_legacy_screw_choice(str(data.get("screw_material", ""))),
        ),
        bed_temperature_c=_coerce_optional_float(data.get("bed_temperature_c")),
        chamber_temperature_c=_coerce_optional_float(data.get("chamber_temperature_c")),
    )


def _load_turn_config(data: dict) -> ScrewTurnConfig:
    if not isinstance(data, dict):
        raise ProjectDataError("turn_config must be an object.")
    if "clockwise_effect" in data:
        clockwise_effect = str(data["clockwise_effect"])
    else:
        clockwise_effect = "raise" if _coerce_bool(data.get("clockwise_raises", True), "clockwise_raises") else "lower"
    viewpoint = str(data.get("viewpoint", "above"))
    config = ScrewTurnConfig(
        pitch_mm_per_turn=_coerce_finite_float(
            _required(data, "pitch_mm_per_turn", "turn_config.pitch_mm_per_turn"),
            "pitch_mm_per_turn",
        ),
        clockwise_effect=clockwise_effect,
        viewpoint=viewpoint,
        fraction_denominator=_coerce_int(data.get("fraction_denominator", 16), "fraction_denominator"),
        hold_threshold_mm=_coerce_finite_float(data.get("hold_threshold_mm", 0.01), "hold_threshold_mm"),
    )
    try:
        validate_turn_config(config)
    except ValueError as exc:
        raise ProjectDataError(str(exc)) from exc
    return config


def _coerce_optional_float(value) -> float | None:
    if value is None or value == "":
        return None
    return _coerce_finite_float(value, "optional float")


def _load_bed(data: dict) -> BedConfig:
    if not isinstance(data, dict):
        raise ProjectDataError("bed must be an object.")
    return BedConfig(
        width_mm=_coerce_finite_float(_required(data, "width_mm", "bed.width_mm"), "bed.width_mm"),
        height_mm=_coerce_finite_float(_required(data, "height_mm", "bed.height_mm"), "bed.height_mm"),
    )


def _load_screw(data: dict, index: int) -> ScrewMeasurement:
    if not isinstance(data, dict):
        raise ProjectDataError(f"screws[{index}] must be an object.")
    return ScrewMeasurement(
        name=str(_required(data, "name", f"screws[{index}].name")),
        left_mm=_coerce_finite_float(_required(data, "left_mm", f"screws[{index}].left_mm"), f"screws[{index}].left_mm"),
        y_measure_mm=_coerce_finite_float(
            _required(data, "y_measure_mm", f"screws[{index}].y_measure_mm"),
            f"screws[{index}].y_measure_mm",
        ),
    )


def _load_coordinate_convention(data: dict) -> CoordinateConvention:
    if not isinstance(data, dict):
        raise ProjectDataError("coordinate_convention must be an object.")
    screw_y_reference_edge = str(data.get("screw_y_reference_edge", "top"))
    display_front_edge = str(data.get("display_front_edge", "top"))
    _validate_literal(screw_y_reference_edge, {"top", "bottom"}, "screw_y_reference_edge")
    _validate_literal(display_front_edge, {"top", "bottom"}, "display_front_edge")
    return CoordinateConvention(
        screw_y_reference_edge=screw_y_reference_edge,  # type: ignore[arg-type]
        display_front_edge=display_front_edge,  # type: ignore[arg-type]
    )


def _load_mechanical_model(data: dict) -> MechanicalModelConfig:
    if not isinstance(data, dict):
        raise ProjectDataError("mechanical_model must be an object.")
    preset_name = infer_preset_name(str(data.get("preset_name", "other")))
    config = MechanicalModelConfig(
        enabled=_coerce_bool(data.get("enabled", True), "mechanical_model.enabled"),
        preset_name=preset_name,
        self_gain=_coerce_finite_float(data.get("self_gain", 0.85), "mechanical_model.self_gain"),
        neighbor_gain=_coerce_finite_float(data.get("neighbor_gain", 0.12), "mechanical_model.neighbor_gain"),
        decay_length_mm=_coerce_finite_float(data.get("decay_length_mm", 140.0), "mechanical_model.decay_length_mm"),
        max_step_turns=_coerce_finite_float(data.get("max_step_turns", 0.0625), "mechanical_model.max_step_turns"),
        regularization_lambda=_coerce_finite_float(
            data.get("regularization_lambda", 1e-5),
            "mechanical_model.regularization_lambda",
        ),
        use_advanced_override=_coerce_bool(
            data.get("use_advanced_override", False),
            "mechanical_model.use_advanced_override",
        ),
    )
    try:
        validate_mechanical_config(config)
    except MechanicalModelError as exc:
        raise ProjectDataError(str(exc)) from exc
    return config


def _load_mesh(data: dict) -> MeshGrid:
    if not isinstance(data, dict):
        raise ProjectDataError("mesh must be an object.")
    try:
        return build_mesh_grid(
            [
                [_coerce_finite_float(cell, "mesh.z_values") for cell in _expect_list(row, "mesh.z_values row")]
                for row in _expect_list(_required(data, "z_values", "mesh.z_values"), "mesh.z_values")
            ],
            _coerce_finite_float(_required(data, "x_min_mm", "mesh.x_min_mm"), "mesh.x_min_mm"),
            _coerce_finite_float(_required(data, "x_max_mm", "mesh.x_max_mm"), "mesh.x_max_mm"),
            _coerce_finite_float(_required(data, "y_min_mm", "mesh.y_min_mm"), "mesh.y_min_mm"),
            _coerce_finite_float(_required(data, "y_max_mm", "mesh.y_max_mm"), "mesh.y_max_mm"),
            _coerce_bool(data.get("top_row_is_y_max", True), "mesh.top_row_is_y_max"),
        )
    except ValueError as exc:
        raise ProjectDataError(str(exc)) from exc


def _load_calibration_trial(data: dict, index: int) -> CalibrationTrial:
    if not isinstance(data, dict):
        raise ProjectDataError(f"calibration_trials[{index}] must be an object.")
    applied_turns_data = _required(data, "applied_turns", f"calibration_trials[{index}].applied_turns")
    if not isinstance(applied_turns_data, dict):
        raise ProjectDataError(f"calibration_trials[{index}].applied_turns must be an object.")
    return CalibrationTrial(
        name=str(data.get("name", f"Trial {index}")),
        before_mesh=_load_mesh(_required(data, "before_mesh", f"calibration_trials[{index}].before_mesh")),
        after_mesh=_load_mesh(_required(data, "after_mesh", f"calibration_trials[{index}].after_mesh")),
        applied_turns={
            str(name): _coerce_finite_float(value, f"calibration_trials[{index}].applied_turns.{name}")
            for name, value in applied_turns_data.items()
        },
        bed=_load_bed(_required(data, "bed", f"calibration_trials[{index}].bed")),
        screws=[
            _load_screw(entry, row)
            for row, entry in enumerate(
                _expect_list(_required(data, "screws", f"calibration_trials[{index}].screws"), f"calibration_trials[{index}].screws"),
                start=1,
            )
        ],
        turn_config=_load_turn_config(_required(data, "turn_config", f"calibration_trials[{index}].turn_config")),
        reference_screw_name=str(_required(data, "reference_screw_name", f"calibration_trials[{index}].reference_screw_name")),
        coordinate_convention=_load_coordinate_convention(
            _required(data, "coordinate_convention", f"calibration_trials[{index}].coordinate_convention")
        ),
        metadata=_load_metadata_v3(_required(data, "metadata", f"calibration_trials[{index}].metadata")),
    )


def _load_material_response_override(data: dict) -> MaterialResponseOverride:
    if not isinstance(data, dict):
        raise ProjectDataError("custom_response must be an object.")
    absolute_cap = data.get("absolute_cap_turns")
    return MaterialResponseOverride(
        self_multiplier=_coerce_finite_float(data.get("self_multiplier", 1.0), "self_multiplier"),
        neighbor_multiplier=_coerce_finite_float(data.get("neighbor_multiplier", 1.0), "neighbor_multiplier"),
        decay_multiplier=_coerce_finite_float(data.get("decay_multiplier", 1.0), "decay_multiplier"),
        step_multiplier=_coerce_finite_float(data.get("step_multiplier", 1.0), "step_multiplier"),
        self_temp_coeff=_coerce_finite_float(data.get("self_temp_coeff", 0.0), "self_temp_coeff"),
        neighbor_temp_coeff=_coerce_finite_float(data.get("neighbor_temp_coeff", 0.0), "neighbor_temp_coeff"),
        step_temp_coeff=_coerce_finite_float(data.get("step_temp_coeff", 0.0), "step_temp_coeff"),
        absolute_cap_turns=None
        if absolute_cap is None
        else _coerce_finite_float(absolute_cap, "absolute_cap_turns"),
    )


def _coerce_finite_float(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProjectDataError(f"{label} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ProjectDataError(f"{label} must be a number.") from exc
    if not math.isfinite(number):
        raise ProjectDataError(f"{label} must be finite.")
    return number


def _coerce_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProjectDataError(f"{label} must be an integer.")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ProjectDataError(f"{label} must be an integer.")
    return int(value)


def _coerce_bool(value, label: str) -> bool:
    if not isinstance(value, bool):
        raise ProjectDataError(f"{label} must be a boolean.")
    return value


def _expect_list(value, label: str) -> list:
    if not isinstance(value, list):
        raise ProjectDataError(f"{label} must be a list.")
    return value


def _required(data: dict, key: str, label: str):
    if key not in data:
        raise ProjectDataError(f"{label} is required.")
    return data[key]


def _validate_literal(value: str, allowed: set[str], label: str) -> None:
    if value not in allowed:
        raise ProjectDataError(f"{label} must be one of: {', '.join(sorted(allowed))}.")


def _reject_json_constant(value: str):
    raise ProjectDataError(f"Invalid JSON numeric constant: {value}")
