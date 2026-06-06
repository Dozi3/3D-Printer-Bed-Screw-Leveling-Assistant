from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Sequence

from materials import (
    default_support_assembly,
    infer_legacy_plate_choice,
    infer_legacy_surface_choice,
    make_library_choice,
    normalize_mount_type,
)
from mechanics import PRESET_DEFAULTS, infer_preset_name
from models import (
    BedAssemblyConfig,
    EnvironmentMetadata,
    MechanicalModelConfig,
    ProjectData,
    SupportAssemblyConfig,
)


SUPPORTED_SCHEMA_VERSION = 1
UNKNOWN_VALUE = "-"
NOT_APPLICABLE_VALUE = "n/a"
REQUIRED_TOP_LEVEL_KEYS = (
    "schema_version",
    "printer_component_profiles",
    "app_calibration_profiles",
    "material_properties",
    "source_evidence",
    "research_gaps",
)
ARRAY_KEYS = (
    "printer_component_profiles",
    "app_calibration_profiles",
    "material_properties",
    "source_evidence",
    "research_gaps",
)
SUPPORTED_APPLY_FIELDS = {
    "bed_plate_material",
    "surface_material",
    "mount_preset",
    "max_step_turns",
}
SQLITE_ALLOWED_RELATIONS = {
    "v_gui_printer_component_profiles",
    "v_gui_app_calibration_profiles",
    "gui_printer_component_profiles",
    "gui_app_calibration_profiles",
    "source_evidence",
    "research_gaps",
    "material_properties",
}


class ComponentLibraryError(ValueError):
    pass


@dataclass(frozen=True)
class ComponentProfileLibrary:
    data: dict
    source_label: str
    source_path: Path | None = None
    imported: bool = False

    @property
    def schema_version(self) -> int:
        return int(self.data["schema_version"])

    @property
    def library_name(self) -> str:
        return str(self.data.get("library_name") or "Component Library")

    @property
    def generated_at_utc(self) -> str:
        return str(self.data.get("generated_at_utc") or UNKNOWN_VALUE)

    @property
    def printer_profiles(self) -> list[dict]:
        return list(self.data.get("printer_component_profiles", []))

    @property
    def app_calibration_profiles(self) -> list[dict]:
        return list(self.data.get("app_calibration_profiles", []))

    @property
    def source_evidence(self) -> list[dict]:
        return list(self.data.get("source_evidence", []))

    @property
    def research_gaps(self) -> list[dict]:
        return list(self.data.get("research_gaps", []))


@dataclass(frozen=True)
class ProfileSuggestion:
    field_key: str
    label: str
    current_value: str
    suggested_value: str
    confidence: str
    applicable: bool
    advisory: bool
    reason: str = ""
    value_key: str | None = None
    numeric_value: float | None = None


@dataclass(frozen=True)
class ProfileApplicationResult:
    project: ProjectData
    applied: list[ProfileSuggestion]
    skipped: list[ProfileSuggestion]


_active_library: ComponentProfileLibrary | None = None


def bundled_library_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "app_component_profile_library.json"


def bundled_sqlite_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "component_materials_database.sqlite"


def load_component_profile_library(path: str | Path) -> ComponentProfileLibrary:
    library_path = Path(path)
    try:
        raw_text = library_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ComponentLibraryError(f"Invalid component library JSON: {exc.msg}") from exc
    except OSError as exc:
        raise ComponentLibraryError(f"Could not read component library: {exc}") from exc
    validate_component_profile_library(data)
    return ComponentProfileLibrary(
        data=data,
        source_label=library_path.name,
        source_path=library_path,
        imported=library_path.resolve() != bundled_library_path().resolve(),
    )


def load_bundled_component_profile_library() -> ComponentProfileLibrary:
    library = load_component_profile_library(bundled_library_path())
    return ComponentProfileLibrary(
        data=library.data,
        source_label="Built-in",
        source_path=library.source_path,
        imported=False,
    )


def validate_component_profile_library(data: object) -> None:
    if not isinstance(data, dict):
        raise ComponentLibraryError("Component library must be a JSON object.")

    missing = [key for key in REQUIRED_TOP_LEVEL_KEYS if key not in data]
    if missing:
        raise ComponentLibraryError(f"Component library is missing required keys: {', '.join(missing)}.")

    try:
        schema_version = int(data["schema_version"])
    except (TypeError, ValueError) as exc:
        raise ComponentLibraryError("Component library schema_version must be an integer.") from exc
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise ComponentLibraryError(
            f"Unsupported component library schema version: {schema_version}."
        )

    for key in ARRAY_KEYS:
        if not isinstance(data[key], list):
            raise ComponentLibraryError(f"Component library key '{key}' must be a list.")
        for index, row in enumerate(data[key], start=1):
            if not isinstance(row, dict):
                raise ComponentLibraryError(f"Row {index} in '{key}' must be an object.")

    _validate_non_negative_field(
        data["printer_component_profiles"],
        "bed_fasteners.screw_pitch_mm",
        "printer_component_profiles",
    )
    _validate_non_negative_field(
        data["printer_component_profiles"],
        "app_calibration_mapping.recommended_max_step_turns",
        "printer_component_profiles",
    )
    _validate_non_negative_field(
        data["app_calibration_profiles"],
        "bed_fasteners.screw_pitch_mm",
        "app_calibration_profiles",
    )
    _validate_non_negative_field(
        data["app_calibration_profiles"],
        "recommended_max_step_turns",
        "app_calibration_profiles",
    )


def get_active_component_library() -> ComponentProfileLibrary:
    global _active_library
    if _active_library is None:
        _active_library = load_bundled_component_profile_library()
    return _active_library


def set_active_component_library(library: ComponentProfileLibrary) -> None:
    global _active_library
    _active_library = library


def reload_bundled_component_profile_library() -> ComponentProfileLibrary:
    library = load_bundled_component_profile_library()
    set_active_component_library(library)
    return library


def get_printer_profiles(library: ComponentProfileLibrary | None = None) -> list[dict]:
    return (library or get_active_component_library()).printer_profiles


def get_app_calibration_profiles(library: ComponentProfileLibrary | None = None) -> list[dict]:
    return (library or get_active_component_library()).app_calibration_profiles


def get_profile_counts(library: ComponentProfileLibrary | None = None) -> dict[str, int]:
    active = library or get_active_component_library()
    return {
        "printer_component_profiles": len(active.printer_profiles),
        "app_calibration_profiles": len(active.app_calibration_profiles),
        "source_evidence": len(active.source_evidence),
        "research_gaps": len(active.research_gaps),
    }


def find_printer_profile(
    profile_id: str,
    library: ComponentProfileLibrary | None = None,
) -> dict:
    for profile in get_printer_profiles(library):
        if str(profile.get("printer_id")) == profile_id:
            return profile
    raise ComponentLibraryError(f"Printer profile not found: {profile_id}")


def find_app_calibration_profile(
    printer_id: str,
    library: ComponentProfileLibrary | None = None,
) -> dict | None:
    for profile in get_app_calibration_profiles(library):
        if str(profile.get("printer_id")) == printer_id:
            return profile
    return None


def build_profile_suggestions(
    project: ProjectData,
    profile_id: str,
    library: ComponentProfileLibrary | None = None,
) -> list[ProfileSuggestion]:
    active = library or get_active_component_library()
    profile = find_printer_profile(profile_id, active)
    calibration = find_app_calibration_profile(profile_id, active) or {}

    suggestions: list[ProfileSuggestion] = []
    plate_suggestion = _build_plate_suggestion(project, profile)
    if plate_suggestion is not None:
        suggestions.append(plate_suggestion)

    surface_suggestion = _build_surface_suggestion(project, profile)
    if surface_suggestion is not None:
        suggestions.append(surface_suggestion)

    mount_suggestion = _build_mount_suggestion(project, profile, calibration)
    if mount_suggestion is not None:
        suggestions.append(mount_suggestion)

    max_step_suggestion = _build_max_step_suggestion(project, profile, calibration)
    if max_step_suggestion is not None:
        suggestions.append(max_step_suggestion)

    return suggestions


def apply_profile_to_project(
    profile_id: str,
    selected_fields: Iterable[str],
    project: ProjectData,
    library: ComponentProfileLibrary | None = None,
) -> ProfileApplicationResult:
    selected = set(selected_fields)
    unknown_fields = selected - SUPPORTED_APPLY_FIELDS
    if unknown_fields:
        raise ComponentLibraryError(f"Unsupported profile fields: {', '.join(sorted(unknown_fields))}.")

    suggestions = build_profile_suggestions(project, profile_id, library)
    suggestion_map = {suggestion.field_key: suggestion for suggestion in suggestions}
    new_project = project
    applied: list[ProfileSuggestion] = []
    skipped: list[ProfileSuggestion] = []

    for field_key in (
        "bed_plate_material",
        "surface_material",
        "mount_preset",
        "max_step_turns",
    ):
        if field_key not in selected:
            continue
        suggestion = suggestion_map.get(field_key)
        if suggestion is None or not suggestion.applicable:
            if suggestion is not None:
                skipped.append(suggestion)
            continue

        if field_key == "bed_plate_material" and suggestion.value_key is not None:
            metadata = replace(
                new_project.metadata,
                bed_assembly=BedAssemblyConfig(
                    plate_material=make_library_choice("plate", suggestion.value_key),
                    surface_material=new_project.metadata.bed_assembly.surface_material,
                ),
            )
            new_project = replace(new_project, metadata=metadata)
            applied.append(suggestion)
        elif field_key == "surface_material" and suggestion.value_key is not None:
            metadata = replace(
                new_project.metadata,
                bed_assembly=BedAssemblyConfig(
                    plate_material=new_project.metadata.bed_assembly.plate_material,
                    surface_material=make_library_choice("surface", suggestion.value_key),
                ),
            )
            new_project = replace(new_project, metadata=metadata)
            applied.append(suggestion)
        elif field_key == "mount_preset" and suggestion.value_key is not None:
            metadata = _replace_mount_metadata(new_project.metadata, suggestion.value_key)
            preset_name = infer_preset_name(suggestion.value_key)
            preset = PRESET_DEFAULTS[preset_name]
            mechanical_model = replace(
                preset,
                enabled=new_project.mechanical_model.enabled,
                preset_name=preset_name,
                use_advanced_override=False,
            )
            new_project = replace(
                new_project,
                metadata=metadata,
                mechanical_model=mechanical_model,
            )
            applied.append(suggestion)
        elif field_key == "max_step_turns" and suggestion.numeric_value is not None:
            mechanical_model = replace(
                new_project.mechanical_model,
                max_step_turns=suggestion.numeric_value,
                use_advanced_override=True,
            )
            new_project = replace(new_project, mechanical_model=mechanical_model)
            applied.append(suggestion)

    return ProfileApplicationResult(project=new_project, applied=applied, skipped=skipped)


def critical_unknown_fields(profile: dict) -> list[str]:
    labels = {
        "bed_core.bed_core_material": "Bed core material",
        "bed_core.bed_core_thickness_mm": "Bed core thickness",
        "bed_mounting.mount_count": "Mount count",
        "bed_mounting.spacer_material": "Spacer material",
        "bed_fasteners.screw_pitch_mm": "Screw pitch",
        "bed_fasteners.screw_material": "Screw material",
        "chamber_thermal.chamber_max_temp_c": "Chamber max temperature",
    }
    return [label for key, label in labels.items() if is_unknown_value(profile.get(key))]


def warning_lines_for_profile(profile: dict, calibration: dict | None = None) -> list[str]:
    calibration = calibration or {}
    warnings: list[str] = []
    for key in (
        "app_calibration_mapping.bed_material_warning",
        "app_calibration_mapping.mount_material_warning",
        "app_calibration_mapping.probe_material_interaction_warning",
        "bed_core.known_thermal_warp_issue",
        "build_surface.known_flatness_effect",
    ):
        value = _clean_text(profile.get(key))
        if value:
            warnings.append(value)
    for key in (
        "bed_material_warning",
        "mount_material_warning",
        "probe_material_interaction_warning",
        "recommended_cold_mesh_warning",
        "notes",
    ):
        value = _clean_text(calibration.get(key))
        if value:
            if key == "recommended_cold_mesh_warning" and value in {"yes", "no"}:
                if value == "yes":
                    warnings.append("Cold mesh warning: use a hot-state mesh for this profile.")
                continue
            warnings.append(value)
    return _dedupe(warnings)


def research_gaps_for_profile(
    profile: dict,
    library: ComponentProfileLibrary | None = None,
) -> list[dict]:
    active = library or get_active_component_library()
    printer_id = str(profile.get("printer_id") or "")
    return [gap for gap in active.research_gaps if str(gap.get("printer_id") or "") == printer_id]


def source_evidence_for_profile(
    profile: dict,
    library: ComponentProfileLibrary | None = None,
) -> list[dict]:
    active = library or get_active_component_library()
    ids = _split_source_ids(str(profile.get("combined_source_ids") or ""))
    if not ids:
        for value in profile.values():
            if isinstance(value, str) and value.startswith("S"):
                ids.extend(_split_source_ids(value))
    wanted = set(ids)
    return [source for source in active.source_evidence if str(source.get("source_id") or "") in wanted]


def list_sqlite_relations(database_path: str | Path | None = None) -> list[str]:
    path = Path(database_path) if database_path is not None else bundled_sqlite_path()
    if not path.exists():
        return []
    with _connect_readonly_sqlite(path) as connection:
        rows = connection.execute(
            "select name from sqlite_master where type in ('table', 'view') order by name"
        ).fetchall()
    return [row[0] for row in rows if row[0] in SQLITE_ALLOWED_RELATIONS]


def query_sqlite_relation(
    relation: str,
    *,
    search_text: str = "",
    limit: int = 500,
    database_path: str | Path | None = None,
) -> list[dict[str, object]]:
    if relation not in SQLITE_ALLOWED_RELATIONS:
        raise ComponentLibraryError(f"Unsupported SQLite relation: {relation}")
    path = Path(database_path) if database_path is not None else bundled_sqlite_path()
    if not path.exists():
        raise ComponentLibraryError(f"SQLite database not found: {path}")

    with _connect_readonly_sqlite(path) as connection:
        connection.row_factory = sqlite3.Row
        columns = [row[1] for row in connection.execute(f"pragma table_info('{relation}')")]
        query = f"select * from '{relation}'"
        params: list[object] = []
        if search_text.strip():
            clauses = [f"cast({_quote_identifier(column)} as text) like ?" for column in columns]
            query += " where " + " or ".join(clauses)
            params.extend([f"%{search_text.strip()}%"] * len(columns))
        query += " limit ?"
        params.append(max(1, min(int(limit), 2000)))
        return [dict(row) for row in connection.execute(query, params).fetchall()]


def is_unknown_value(value: object) -> bool:
    return str(value).strip().lower() == UNKNOWN_VALUE


def is_not_applicable_value(value: object) -> bool:
    return str(value).strip().lower() == NOT_APPLICABLE_VALUE


def is_missing_component_value(value: object) -> bool:
    return is_unknown_value(value) or is_not_applicable_value(value) or str(value).strip() == ""


def _build_plate_suggestion(project: ProjectData, profile: dict) -> ProfileSuggestion | None:
    raw_value = _clean_text(profile.get("bed_core.bed_core_material"))
    confidence = _clean_text(profile.get("bed_core.confidence")) or "unknown"
    current = _material_label(project.metadata.bed_assembly.plate_material.label)
    if not raw_value:
        return ProfileSuggestion(
            field_key="bed_plate_material",
            label="Bed plate material",
            current_value=current,
            suggested_value="Unknown",
            confidence=confidence,
            applicable=False,
            advisory=True,
            reason="Bed core material is unknown in the component library.",
        )

    key = _map_plate_material(raw_value)
    if key is None or confidence.lower() == "low":
        return ProfileSuggestion(
            field_key="bed_plate_material",
            label="Bed plate material",
            current_value=current,
            suggested_value=raw_value,
            confidence=confidence,
            applicable=False,
            advisory=True,
            reason="Bed core material is not confidently mapped to the app material library.",
        )
    label = make_library_choice("plate", key).label
    return ProfileSuggestion(
        field_key="bed_plate_material",
        label="Bed plate material",
        current_value=current,
        suggested_value=label,
        confidence=confidence,
        applicable=True,
        advisory=False,
        reason="Suggested from component library bed core material.",
        value_key=key,
    )


def _build_surface_suggestion(project: ProjectData, profile: dict) -> ProfileSuggestion | None:
    raw_parts = [
        _clean_text(profile.get("build_surface.build_plate_material")),
        _clean_text(profile.get("build_surface.coating_material")),
        _clean_text(profile.get("build_surface.stock_build_surface")),
    ]
    raw_value = " ".join(part for part in raw_parts if part)
    confidence = _clean_text(profile.get("build_surface.confidence")) or "unknown"
    current = _material_label(project.metadata.bed_assembly.surface_material.label)
    if not raw_value:
        return ProfileSuggestion(
            field_key="surface_material",
            label="Build surface material",
            current_value=current,
            suggested_value="Unknown",
            confidence=confidence,
            applicable=False,
            advisory=True,
            reason="Build surface material is unknown in the component library.",
        )

    key = _map_surface_material(raw_value)
    if key is None:
        return ProfileSuggestion(
            field_key="surface_material",
            label="Build surface material",
            current_value=current,
            suggested_value=raw_value,
            confidence=confidence,
            applicable=False,
            advisory=True,
            reason="Build surface is advisory only because it does not map cleanly to an app surface preset.",
        )
    label = make_library_choice("surface", key).label
    return ProfileSuggestion(
        field_key="surface_material",
        label="Build surface material",
        current_value=current,
        suggested_value=label,
        confidence=confidence,
        applicable=True,
        advisory=False,
        reason="Suggested from component library build-surface data.",
        value_key=key,
    )


def _build_mount_suggestion(
    project: ProjectData,
    profile: dict,
    calibration: dict,
) -> ProfileSuggestion | None:
    raw_value = _clean_text(
        calibration.get("recommended_mount_preset")
        or profile.get("app_calibration_mapping.recommended_mount_preset")
        or profile.get("bed_mounting.bed_mount_type")
    )
    confidence = (
        _clean_text(calibration.get("confidence"))
        or _clean_text(profile.get("app_calibration_mapping.confidence"))
        or _clean_text(profile.get("bed_mounting.confidence"))
        or "unknown"
    )
    current = project.metadata.support_assembly.mount_type or "other"
    if not raw_value:
        return ProfileSuggestion(
            field_key="mount_preset",
            label="Mount preset",
            current_value=current,
            suggested_value="Unknown",
            confidence=confidence,
            applicable=False,
            advisory=True,
            reason="Mount preset is unknown in the component library.",
        )
    mapped = _map_mount_preset(raw_value, profile)
    if mapped is None:
        return ProfileSuggestion(
            field_key="mount_preset",
            label="Mount preset",
            current_value=current,
            suggested_value=raw_value,
            confidence=confidence,
            applicable=False,
            advisory=True,
            reason="Advisory only; fixed-bed, unknown, and unavailable mount data do not change solver settings.",
        )
    return ProfileSuggestion(
        field_key="mount_preset",
        label="Mount preset",
        current_value=current,
        suggested_value=mapped,
        confidence=confidence,
        applicable=True,
        advisory=False,
        reason="Suggested from component library mount mapping.",
        value_key=mapped,
    )


def _build_max_step_suggestion(
    project: ProjectData,
    profile: dict,
    calibration: dict,
) -> ProfileSuggestion | None:
    raw_value = _clean_text(
        calibration.get("recommended_max_step_turns")
        or profile.get("app_calibration_mapping.recommended_max_step_turns")
    )
    confidence = (
        _clean_text(calibration.get("confidence"))
        or _clean_text(profile.get("app_calibration_mapping.confidence"))
        or "unknown"
    )
    current = f"{project.mechanical_model.max_step_turns:g}"
    if not raw_value:
        return ProfileSuggestion(
            field_key="max_step_turns",
            label="Max step turns",
            current_value=current,
            suggested_value="Unknown",
            confidence=confidence,
            applicable=False,
            advisory=True,
            reason="Recommended max step is unknown or not applicable.",
        )
    number = _parse_simple_number(raw_value)
    if number is None or number <= 0.0:
        return ProfileSuggestion(
            field_key="max_step_turns",
            label="Max step turns",
            current_value=current,
            suggested_value=raw_value,
            confidence=confidence,
            applicable=False,
            advisory=True,
            reason="Zero, fixed-bed, not-applicable, and unknown max-step values do not change solver settings.",
        )
    return ProfileSuggestion(
        field_key="max_step_turns",
        label="Max step turns",
        current_value=current,
        suggested_value=f"{number:g}",
        confidence=confidence,
        applicable=True,
        advisory=False,
        reason="Suggested from component library; applying this enables advanced override.",
        numeric_value=number,
    )


def _replace_mount_metadata(metadata: EnvironmentMetadata, mount_type: str) -> EnvironmentMetadata:
    support_defaults = default_support_assembly(mount_type)
    return replace(
        metadata,
        support_assembly=SupportAssemblyConfig(
            mount_type=normalize_mount_type(mount_type),
            support_material=support_defaults.support_material,
            support_stack_height_mm=support_defaults.support_stack_height_mm,
        ),
    )


def _map_plate_material(value: str) -> str | None:
    normalized = _normalize(value)
    if any(token in normalized for token in ("mic 6", "mic6", "cast aluminium", "cast aluminum", "aluminium alloy", "aluminum alloy")):
        return "cast_aluminum"
    if "rolled" in normalized and ("aluminum" in normalized or "aluminium" in normalized):
        return "rolled_aluminum"
    if "borosilicate" in normalized or "glass" in normalized:
        return "borosilicate_glass"
    if "stainless" in normalized:
        return "stainless"
    if "steel" in normalized:
        return "steel"
    if "graphite" in normalized:
        return "graphite"
    choice = infer_legacy_plate_choice(value)
    return None if choice.library_key == "other" else choice.library_key


def _map_surface_material(value: str) -> str | None:
    normalized = _normalize(value)
    if "garolite" in normalized:
        return "garolite"
    if "glass" in normalized:
        return "glass_sheet"
    if "pei" in normalized or "spring steel" in normalized or "flexible steel" in normalized:
        return "pei_on_spring_steel"
    if "polymer" in normalized:
        return "polymer_sheet"
    if normalized in {"none", "no", "n a"}:
        return "none"
    choice = infer_legacy_surface_choice(value)
    return None if choice.library_key == "other" else choice.library_key


def _map_mount_preset(value: str, profile: dict) -> str | None:
    normalized = _normalize(value)
    if normalized in {"fixed bed", "fixed", "unknown", "n a"}:
        return None
    direct = normalize_mount_type(value)
    if direct in {"springs", "silicone", "rigid spacers", "shims", "other"} and direct != "other":
        return direct
    if _yes(profile.get("bed_mounting.spring_loaded")):
        return "springs"
    if _yes(profile.get("bed_mounting.silicone_spacers")):
        return "silicone"
    if _yes(profile.get("bed_mounting.rigid_standoffs")):
        return "rigid spacers"
    if "shim" in normalized:
        return "shims"
    return None


def _clean_text(value: object) -> str:
    if is_missing_component_value(value):
        return ""
    return str(value).strip()


def _material_label(value: str) -> str:
    return value or "Other"


def _validate_non_negative_field(rows: Sequence[dict], field: str, table: str) -> None:
    for index, row in enumerate(rows, start=1):
        value = row.get(field)
        number = _parse_simple_number(value)
        if number is not None and number < 0.0:
            raise ComponentLibraryError(
                f"Negative value for '{field}' in {table} row {index}: {value}"
            )


def _parse_simple_number(value: object) -> float | None:
    if is_missing_component_value(value):
        return None
    text = str(value).strip()
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        return None
    return float(text)


def _normalize(value: object) -> str:
    return " ".join(str(value).strip().lower().replace("-", " ").replace("_", " ").split())


def _yes(value: object) -> bool:
    return str(value).strip().lower() == "yes"


def _split_source_ids(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def _connect_readonly_sqlite(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _dedupe(messages: Sequence[str]) -> list[str]:
    deduped: list[str] = []
    for message in messages:
        if message and message not in deduped:
            deduped.append(message)
    return deduped
