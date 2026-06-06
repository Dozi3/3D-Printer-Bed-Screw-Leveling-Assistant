from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from models import MeshGrid, QuadraticFit, WarpReport
from solver import LOCAL_RESIDUAL_PROXIMITY_RADIUS_MM, bilinear_interpolate

NEARLY_FLAT_MAX_ABS_MM = 0.03
NEARLY_FLAT_PEAK_TO_VALLEY_MM = 0.06
CURVATURE_EPSILON = 1e-9
BOWL_SYMMETRY_RATIO = 2.0
BOWL_CROSS_TERM_RATIO = 0.35
AXIS_DOMINANCE_RATIO = 1.8
SADDLE_CROSS_TERM_RATIO = 0.6
LOCAL_DEFECT_R2_MAX = 0.45
LOCAL_DEFECT_MIN_ABS_MM = 0.08
LOCAL_DEFECT_RMS_FACTOR = 2.0
LOCAL_DEFECT_MAX_FRACTION = 0.2
HIGH_CONFIDENCE_R2 = 0.75
MEDIUM_CONFIDENCE_R2 = 0.5
LOCAL_RESIDUAL_NOTE_THRESHOLD_MM = 0.05
OUTSIDE_MESH_NOTE = "outside mesh bounds; plane only; no local residual note"


def fit_quadratic_residual(mesh: MeshGrid, residual_surface: Sequence[Sequence[float]]) -> QuadraticFit:
    x_grid, y_grid = np.meshgrid(mesh.x_coordinates(), mesh.y_coordinates())
    residuals = np.asarray(residual_surface, dtype=float).ravel()
    u = _normalize_axis(x_grid.ravel(), mesh.x_min_mm, mesh.x_max_mm)
    v = _normalize_axis(y_grid.ravel(), mesh.y_min_mm, mesh.y_max_mm)

    design = np.column_stack((u**2, v**2, u * v, u, v, np.ones_like(u)))
    coefficients, _, _, _ = np.linalg.lstsq(design, residuals, rcond=None)
    predicted = design @ coefficients
    ss_res = float(np.sum(np.square(residuals - predicted)))
    ss_tot = float(np.sum(np.square(residuals - np.mean(residuals))))
    r_squared = 1.0 if ss_tot <= CURVATURE_EPSILON else 1.0 - (ss_res / ss_tot)

    return QuadraticFit(
        a_x2=float(coefficients[0]),
        b_y2=float(coefficients[1]),
        c_xy=float(coefficients[2]),
        d_x=float(coefficients[3]),
        e_y=float(coefficients[4]),
        f_constant=float(coefficients[5]),
        r_squared=float(r_squared),
    )


def classify_warp(mesh: MeshGrid, residual_surface: Sequence[Sequence[float]]) -> WarpReport:
    residuals = np.asarray(residual_surface, dtype=float)
    if mesh.row_count < 3 or mesh.column_count < 3:
        return WarpReport(
            enabled=False,
            classification="disabled",
            confidence="low",
            summary="Warp classification requires at least a 3x3 mesh.",
        )

    fit = fit_quadratic_residual(mesh, residuals)
    max_abs = float(np.max(np.abs(residuals)))
    rms = float(np.sqrt(np.mean(np.square(residuals))))
    peak_to_valley = float(np.max(residuals) - np.min(residuals))

    local_outlier_threshold = max(LOCAL_DEFECT_MIN_ABS_MM, LOCAL_DEFECT_RMS_FACTOR * rms)
    outlier_fraction = float(np.count_nonzero(np.abs(residuals) >= local_outlier_threshold) / residuals.size)

    a_term = abs(fit.a_x2)
    b_term = abs(fit.b_y2)
    c_term = abs(fit.c_xy)
    dominant_term = max(a_term, b_term, CURVATURE_EPSILON)

    classification = "mixed / unclassified"
    if max_abs <= NEARLY_FLAT_MAX_ABS_MM and peak_to_valley <= NEARLY_FLAT_PEAK_TO_VALLEY_MM:
        classification = "nearly flat / mostly tilt only"
    elif fit.r_squared < LOCAL_DEFECT_R2_MAX and 0.0 < outlier_fraction <= LOCAL_DEFECT_MAX_FRACTION:
        classification = "local defect / isolated bump or dip"
    elif (
        math.copysign(1.0, fit.a_x2) == math.copysign(1.0, fit.b_y2)
        and a_term > CURVATURE_EPSILON
        and b_term > CURVATURE_EPSILON
        and max(a_term, b_term) / min(a_term, b_term) <= BOWL_SYMMETRY_RATIO
        and c_term <= BOWL_CROSS_TERM_RATIO * max(a_term, b_term)
    ):
        classification = "bowl/dish" if fit.a_x2 > 0.0 else "dome"
    elif a_term >= AXIS_DOMINANCE_RATIO * max(b_term, c_term, CURVATURE_EPSILON):
        classification = "taco/barrel warp mainly along X"
    elif b_term >= AXIS_DOMINANCE_RATIO * max(a_term, c_term, CURVATURE_EPSILON):
        classification = "taco/barrel warp mainly along Y"
    elif (
        fit.a_x2 * fit.b_y2 < 0.0 and min(a_term, b_term) > CURVATURE_EPSILON
    ) or c_term >= SADDLE_CROSS_TERM_RATIO * dominant_term:
        classification = "saddle/twist-like"

    return WarpReport(
        enabled=True,
        classification=classification,
        confidence=_confidence_label(classification, fit.r_squared, outlier_fraction, max_abs),
        summary=_summary_for_classification(classification),
        fit=fit,
    )


def note_high_local_residuals(
    mesh: MeshGrid,
    residual_surface: Sequence[Sequence[float]],
    screw_positions: Sequence[tuple[str, float, float]],
) -> dict[str, tuple[float | None, list[str]]]:
    x_grid, y_grid = np.meshgrid(mesh.x_coordinates(), mesh.y_coordinates())
    residuals = np.asarray(residual_surface, dtype=float)
    notes: dict[str, tuple[float | None, list[str]]] = {}

    for name, x_mm, y_mm in screw_positions:
        if not mesh.contains_point(x_mm, y_mm):
            notes[name] = (None, [OUTSIDE_MESH_NOTE])
            continue

        local_value = bilinear_interpolate(
            mesh.x_coordinates(),
            mesh.y_coordinates(),
            residuals,
            x_mm,
            y_mm,
        )
        distances = np.hypot(x_grid - x_mm, y_grid - y_mm)
        nearby = np.abs(residuals[distances <= LOCAL_RESIDUAL_PROXIMITY_RADIUS_MM])
        nearby_peak = float(np.max(nearby)) if nearby.size else abs(local_value)

        screw_notes: list[str] = []
        if nearby_peak >= LOCAL_RESIDUAL_NOTE_THRESHOLD_MM:
            screw_notes.append("high local residual nearby")

        notes[name] = (float(local_value), screw_notes)

    return notes


def _normalize_axis(values: np.ndarray, minimum: float, maximum: float) -> np.ndarray:
    midpoint = (minimum + maximum) / 2.0
    half_span = (maximum - minimum) / 2.0
    return (values - midpoint) / half_span


def _confidence_label(
    classification: str,
    r_squared: float,
    outlier_fraction: float,
    max_abs: float,
) -> str:
    if classification == "nearly flat / mostly tilt only":
        return "high" if max_abs <= (NEARLY_FLAT_MAX_ABS_MM / 2.0) else "medium"
    if classification == "local defect / isolated bump or dip":
        if r_squared < 0.25 and outlier_fraction <= 0.1:
            return "high"
        return "medium"
    if r_squared >= HIGH_CONFIDENCE_R2:
        return "high"
    if r_squared >= MEDIUM_CONFIDENCE_R2:
        return "medium"
    return "low"


def _summary_for_classification(classification: str) -> str:
    summaries = {
        "nearly flat / mostly tilt only": "Residuals are small compared with the fitted plane.",
        "bowl/dish": "Residuals suggest the centre sits low relative to the edges.",
        "dome": "Residuals suggest the centre sits high relative to the edges.",
        "taco/barrel warp mainly along X": "Residual curvature is stronger along the X direction.",
        "taco/barrel warp mainly along Y": "Residual curvature is stronger along the Y direction.",
        "saddle/twist-like": "Residuals show opposing curvature or a strong cross-term.",
        "local defect / isolated bump or dip": "Residuals are dominated by one or a few local outliers.",
        "mixed / unclassified": "Residuals do not cleanly match one heuristic pattern.",
    }
    return summaries.get(classification, classification)
