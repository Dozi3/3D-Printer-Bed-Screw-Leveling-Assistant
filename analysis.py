from __future__ import annotations

from dataclasses import replace

from mechanics import (
    MechanicalModelError,
    build_turn_plan,
    resolve_effective_mechanical_model,
    solve_physical_response,
)
from models import (
    AnalysisResult,
    GeometryReport,
    GeometryScrewStatus,
    MechanicalConfidence,
    ProbeAreaSummary,
    ProjectData,
    ScrewInstruction,
)
from solver import (
    compute_residual_stats,
    compute_screw_instructions,
    evaluate_plane_surface,
    fit_plane_to_mesh,
    measurement_to_internal,
    validate_turn_config,
)
from warp import classify_warp, note_high_local_residuals


class AnalysisError(ValueError):
    pass


def inspect_project_geometry(project: ProjectData) -> GeometryReport:
    screw_statuses: list[GeometryScrewStatus] = []
    blocking_errors: list[str] = []
    warnings: list[str] = []

    if not _is_finite(project.bed.width_mm) or not _is_finite(project.bed.height_mm):
        blocking_errors.append("Bed width and height must be finite numbers.")
    elif project.bed.width_mm <= 0.0 or project.bed.height_mm <= 0.0:
        blocking_errors.append("Bed width and height must be greater than zero.")
    try:
        validate_turn_config(project.turn_config)
    except ValueError as exc:
        blocking_errors.append(str(exc))
    if len(project.screws) < 3:
        blocking_errors.append("At least 3 screws are required.")

    names = [screw.name.strip() for screw in project.screws]
    if any(not name for name in names):
        blocking_errors.append("All screws must have a name.")
    if len(set(names)) != len(names):
        blocking_errors.append("Screw names must be unique.")
    if project.reference_screw_name not in names:
        blocking_errors.append("Reference screw must exist in the screw list.")

    centre_x = project.bed.width_mm / 2.0 if project.bed.width_mm > 0.0 else 0.0
    centre_y = project.bed.height_mm / 2.0 if project.bed.height_mm > 0.0 else 0.0
    for screw in project.screws:
        if not _is_finite(screw.left_mm) or not _is_finite(screw.y_measure_mm):
            blocking_errors.append(f"Screw '{screw.name}' has a non-finite coordinate.")
            continue
        x_mm, y_mm = measurement_to_internal(
            screw.left_mm,
            screw.y_measure_mm,
            project.bed.height_mm,
            project.coordinate_convention.screw_y_reference_edge,
        )
        inside_bed = (0.0 <= screw.left_mm <= project.bed.width_mm) and (
            0.0 <= screw.y_measure_mm <= project.bed.height_mm
        )
        quadrant = _quadrant(x_mm, y_mm, centre_x, centre_y) if inside_bed else None
        screw_statuses.append(
            GeometryScrewStatus(
                name=screw.name,
                left_mm=screw.left_mm,
                y_measure_mm=screw.y_measure_mm,
                x_mm=x_mm,
                y_mm=y_mm,
                inside_bed=inside_bed,
                quadrant=quadrant,
            )
        )
        if not (0.0 <= screw.left_mm <= project.bed.width_mm):
            blocking_errors.append(f"Screw '{screw.name}' lies outside the bed width.")
        if not (0.0 <= screw.y_measure_mm <= project.bed.height_mm):
            blocking_errors.append(f"Screw '{screw.name}' lies outside the bed height.")

    mesh = project.mesh
    mesh_is_valid = mesh is not None
    if mesh is not None:
        mesh_bounds = (mesh.x_min_mm, mesh.x_max_mm, mesh.y_min_mm, mesh.y_max_mm)
        if not all(_is_finite(value) for value in mesh_bounds):
            blocking_errors.append("Mesh bounds must be finite numbers.")
            mesh_is_valid = False
        elif mesh.x_min_mm >= mesh.x_max_mm or mesh.y_min_mm >= mesh.y_max_mm:
            blocking_errors.append("Mesh bounds must satisfy x_min < x_max and y_min < y_max.")
            mesh_is_valid = False
        if mesh.row_count < 2 or mesh.column_count < 2:
            blocking_errors.append("Mesh must be at least 2x2 to analyse.")
            mesh_is_valid = False
        if any(len(row) != mesh.column_count for row in mesh.z_values):
            blocking_errors.append("Mesh rows must all have the same number of columns.")
            mesh_is_valid = False
        if any(not _is_finite(cell) for row in mesh.z_values for cell in row):
            blocking_errors.append("Mesh values must be finite numbers.")
            mesh_is_valid = False

    duplicate_positions: dict[tuple[float, float], list[str]] = {}
    for status in screw_statuses:
        duplicate_positions.setdefault((round(status.x_mm, 6), round(status.y_mm, 6)), []).append(status.name)
        if mesh is not None and mesh_is_valid:
            status.inside_mesh = mesh.contains_point(status.x_mm, status.y_mm)
        else:
            status.inside_mesh = None

    for (x_mm, y_mm), duplicate_names in duplicate_positions.items():
        if len(duplicate_names) <= 1:
            continue
        for status in screw_statuses:
            if status.name in duplicate_names:
                status.duplicate_with = [name for name in duplicate_names if name != status.name]
        joined_names = ", ".join(f"'{name}'" for name in duplicate_names)
        blocking_errors.append(
            f"Screws {joined_names} share the same internal position ({x_mm:.3f}, {y_mm:.3f})."
        )

    if mesh is not None and mesh_is_valid:
        outside_probe = [status for status in screw_statuses if status.inside_mesh is False]
        if (
            mesh.x_min_mm < 0.0
            or mesh.y_min_mm < 0.0
            or mesh.x_max_mm > project.bed.width_mm
            or mesh.y_max_mm > project.bed.height_mm
        ):
            warnings.append(
                "Mesh bounds exceed the physical bed bounds; probe coverage is computed from the overlap only."
            )
        if outside_probe:
            warnings.append(
                f"{len(outside_probe)} of {len(screw_statuses)} screw positions are outside the probed mesh bounds "
                f"(X {mesh.x_min_mm:.1f}..{mesh.x_max_mm:.1f} mm, Y {mesh.y_min_mm:.1f}..{mesh.y_max_mm:.1f} mm) "
                f"on a {project.bed.width_mm:.1f} x {project.bed.height_mm:.1f} mm bed."
            )
            warnings.append(
                "Plane correction is extrapolated for screw positions outside the probed area."
            )
            warnings.append("Plane correction still computed; local residual note skipped outside mesh bounds.")
        if mesh.row_count < 3 or mesh.column_count < 3:
            warnings.append("Warp classification disabled: mesh needs at least 3x3 samples.")

    mount_type = project.metadata.mount_type.strip().lower()
    if mount_type == "springs":
        warnings.append("Spring mounts are compliant; keep first passes small and re-mesh after each pass.")
    elif mount_type == "silicone":
        warnings.append("Silicone mounts can creep; allow the bed to settle before re-meshing.")
    elif mount_type in {"rigid spacers", "shims"}:
        warnings.append("Rigid mount stacks respond more directly and can overreact to large turns.")

    if project.upgraded_from_schema in {1, 2}:
        warnings.append(
            "This project was upgraded from an older schema. Review the bed assembly because older files could not distinguish the plate from the top surface."
        )

    if project.metadata.bed_temperature_c is None:
        warnings.append("No bed temperature recorded. Final tram should be verified at print temperature.")
    elif project.metadata.bed_temperature_c >= 90.0:
        warnings.append("High-temperature mesh: use this result for that hot-state workflow only.")
    if project.metadata.chamber_temperature_c is not None and project.metadata.chamber_temperature_c >= 45.0:
        warnings.append("Hot chamber recorded. Frame and bed geometry may differ from cold-state calibration.")

    return GeometryReport(
        screw_statuses=screw_statuses,
        blocking_errors=_dedupe_messages(blocking_errors),
        warnings=_dedupe_messages(warnings),
    )


def inspect_geometry(project: ProjectData) -> GeometryReport:
    return inspect_project_geometry(project)


def analyse_project(project: ProjectData) -> AnalysisResult:
    mesh = project.mesh
    if mesh is None:
        raise AnalysisError("A mesh is required before analysis can run.")

    geometry = inspect_project_geometry(project)
    if geometry.blocking_errors:
        raise AnalysisError("\n".join(geometry.blocking_errors))

    screw_positions = [(status.name, status.x_mm, status.y_mm) for status in geometry.screw_statuses]
    plane_fit = fit_plane_to_mesh(mesh)
    plane_surface = evaluate_plane_surface(mesh, plane_fit)
    residual_surface = mesh.z_array() - plane_surface
    residual_stats = compute_residual_stats(residual_surface, plane_fit)
    warp_report = classify_warp(mesh, residual_surface)
    probe_summary = build_probe_area_summary(project)

    baseline_instructions = compute_screw_instructions(
        plane_fit,
        screw_positions,
        project.reference_screw_name,
        project.turn_config,
        source_model="baseline",
    )
    local_residual_notes = note_high_local_residuals(mesh, residual_surface, screw_positions)
    baseline_instructions = _attach_local_notes(baseline_instructions, local_residual_notes)

    try:
        effective_mechanics, effective_model, mechanical_confidence, mechanical_warnings = (
            resolve_effective_mechanical_model(
                project.mechanical_model,
                project.metadata,
                screw_positions,
            )
        )
    except MechanicalModelError as exc:
        raise AnalysisError(str(exc)) from exc

    baseline_turn_plan = build_turn_plan(
        "baseline",
        baseline_instructions,
        project.reference_screw_name,
        effective_mechanics.max_step_turns,
        project.bed,
    )

    physical_instructions: list[ScrewInstruction] = []
    physical_turn_plan = None
    divergence_warnings: list[str] = []
    if project.mechanical_model.enabled:
        baseline_deltas = {instruction.name: instruction.delta_height_mm for instruction in baseline_instructions}
        command_mm, achieved_delta_mm, physical_warnings, suppressed = solve_physical_response(
            screw_positions,
            baseline_deltas,
            project.reference_screw_name,
            effective_mechanics,
            project.turn_config.hold_threshold_mm,
        )
        note_map = _build_physical_note_map(local_residual_notes, achieved_delta_mm, suppressed)
        physical_instructions = compute_screw_instructions(
            plane_fit,
            screw_positions,
            project.reference_screw_name,
            project.turn_config,
            source_model="physical",
            delta_override_mm=command_mm,
            achieved_override_mm=achieved_delta_mm,
            note_map=note_map,
        )
        physical_turn_plan = build_turn_plan(
            "physical",
            physical_instructions,
            project.reference_screw_name,
            effective_mechanics.max_step_turns,
            project.bed,
            warnings=physical_warnings,
        )
        divergence_warnings = _build_divergence_warnings(baseline_instructions, physical_instructions)

    warnings = _build_warnings(
        project,
        geometry,
        warp_report.classification,
        probe_summary,
        mechanical_warnings,
        mechanical_confidence if project.mechanical_model.enabled else None,
    )

    return AnalysisResult(
        plane_fit=plane_fit,
        residual_stats=residual_stats,
        warp_report=warp_report,
        baseline_instructions=baseline_instructions,
        physical_instructions=physical_instructions,
        baseline_turn_plan=baseline_turn_plan,
        physical_turn_plan=physical_turn_plan,
        geometry_report=geometry,
        probe_area_summary=probe_summary,
        effective_mechanical_model=effective_model if project.mechanical_model.enabled else None,
        mechanical_confidence=mechanical_confidence if project.mechanical_model.enabled else None,
        warnings=warnings,
        divergence_warnings=divergence_warnings,
        plane_surface=plane_surface.tolist(),
        residual_surface=residual_surface.tolist(),
    )


def build_probe_area_summary(project: ProjectData) -> ProbeAreaSummary:
    mesh = project.mesh
    if mesh is None or project.bed.width_mm <= 0.0 or project.bed.height_mm <= 0.0:
        return ProbeAreaSummary(
            probe_width_mm=0.0,
            probe_height_mm=0.0,
            coverage_ratio=0.0,
            warning_level="strong",
        )

    overlap_x_min = max(0.0, mesh.x_min_mm)
    overlap_x_max = min(project.bed.width_mm, mesh.x_max_mm)
    overlap_y_min = max(0.0, mesh.y_min_mm)
    overlap_y_max = min(project.bed.height_mm, mesh.y_max_mm)
    probe_width = max(0.0, overlap_x_max - overlap_x_min)
    probe_height = max(0.0, overlap_y_max - overlap_y_min)
    coverage_ratio = (probe_width * probe_height) / (project.bed.width_mm * project.bed.height_mm)
    coverage_ratio = min(1.0, max(0.0, coverage_ratio))
    if coverage_ratio < 0.50:
        warning_level = "strong"
    elif coverage_ratio < 0.75:
        warning_level = "partial"
    else:
        warning_level = "none"
    return ProbeAreaSummary(
        probe_width_mm=float(probe_width),
        probe_height_mm=float(probe_height),
        coverage_ratio=float(coverage_ratio),
        warning_level=warning_level,
    )


def _attach_local_notes(
    instructions: list[ScrewInstruction],
    local_residual_notes: dict[str, tuple[float | None, list[str]]],
) -> list[ScrewInstruction]:
    enriched: list[ScrewInstruction] = []
    for instruction in instructions:
        local_residual_mm, notes = local_residual_notes[instruction.name]
        enriched.append(
            replace(
                instruction,
                local_residual_mm=local_residual_mm,
                notes=list(notes),
                expected_achieved_delta_mm=instruction.delta_height_mm,
            )
        )
    return enriched


def _build_physical_note_map(
    local_residual_notes: dict[str, tuple[float | None, list[str]]],
    achieved_delta_mm: dict[str, float],
    suppressed: list[str],
) -> dict[str, list[str]]:
    note_map: dict[str, list[str]] = {}
    for name, (_, notes) in local_residual_notes.items():
        note_map[name] = list(notes)
        if abs(achieved_delta_mm.get(name, 0.0)) >= 1e-9:
            note_map[name].append(f"predicted achieved delta {achieved_delta_mm[name]:.4f} mm")
    for name in suppressed:
        note_map.setdefault(name, []).append("physical model conflict; suppressed for this screw")
    return note_map


def _build_divergence_warnings(
    baseline_instructions: list[ScrewInstruction],
    physical_instructions: list[ScrewInstruction],
) -> list[str]:
    warnings: list[str] = []
    physical_by_name = {instruction.name: instruction for instruction in physical_instructions}
    for baseline in baseline_instructions:
        physical = physical_by_name.get(baseline.name)
        if physical is None:
            continue
        difference = abs(physical.signed_turns - baseline.signed_turns)
        threshold = max(1.0 / 32.0, 0.35 * abs(baseline.signed_turns))
        if difference >= threshold:
            warnings.append(
                f"Physical model materially changes {baseline.name}: baseline {abs(baseline.signed_turns):.4f} turns vs physical {abs(physical.signed_turns):.4f} turns."
            )
        if baseline.action != "hold" and physical.action == "hold":
            warnings.append(
                f"Physical model reduces {baseline.name} to hold; treat that recommendation as heuristic and re-mesh after the first pass."
            )
    return _dedupe_messages(warnings)


def _build_warnings(
    project: ProjectData,
    geometry: GeometryReport,
    warp_classification: str,
    probe_summary: ProbeAreaSummary,
    mechanical_warnings: list[str],
    mechanical_confidence: MechanicalConfidence | None,
) -> list[str]:
    warnings = [
        "Screw adjustments correct global tilt, not local warp.",
        "This result is iterative. Re-mesh after adjustment.",
    ]
    warnings.extend(geometry.warnings)
    if warp_classification == "saddle/twist-like":
        warnings.append("Residual pattern suggests saddle/twist-like behaviour.")
    if warp_classification == "local defect / isolated bump or dip":
        warnings.append("Residual pattern suggests local defect or sheet issue.")
    if probe_summary.warning_level == "partial":
        warnings.append("Probe area covers only part of the bed; residual insight is limited outside that area.")
    if probe_summary.warning_level == "strong":
        warnings.append("Probe coverage is limited; treat residual interpretation outside the probed area cautiously.")
    if project.mechanical_model.enabled:
        warnings.append(
            "Baseline plane-fit recommendations remain the primary path; use the physical-response model as a heuristic / advisory comparison."
        )
        if mechanical_confidence is not None:
            warnings.append(
                f"Physical-response confidence: {mechanical_confidence.level} ({mechanical_confidence.score:.2f})."
            )
    warnings.extend(mechanical_warnings)
    return _dedupe_messages(warnings)


def _quadrant(x_mm: float, y_mm: float, centre_x: float, centre_y: float) -> str:
    horizontal = "left" if x_mm <= centre_x else "right"
    vertical = "rear" if y_mm >= centre_y else "front"
    return f"{vertical}-{horizontal}"


def _dedupe_messages(messages: list[str]) -> list[str]:
    deduped: list[str] = []
    for message in messages:
        if message not in deduped:
            deduped.append(message)
    return deduped


def _is_finite(value: float) -> bool:
    try:
        return float("-inf") < float(value) < float("inf")
    except (TypeError, ValueError):
        return False
