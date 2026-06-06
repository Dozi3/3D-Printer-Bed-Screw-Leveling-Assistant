from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

ClockwiseEffect = Literal["raise", "lower"]
Viewpoint = Literal["above", "below"]
EdgeReference = Literal["top", "bottom"]
ModelSource = Literal["baseline", "physical"]
MaterialChoiceKind = Literal["library", "custom"]
ConfidenceLevel = Literal["high", "medium", "low"]


@dataclass(slots=True)
class BedConfig:
    width_mm: float
    height_mm: float


@dataclass(slots=True)
class ScrewMeasurement:
    name: str
    left_mm: float
    y_measure_mm: float

    @property
    def top_mm(self) -> float:
        return self.y_measure_mm


@dataclass(slots=True)
class ScrewTurnConfig:
    pitch_mm_per_turn: float
    clockwise_effect: ClockwiseEffect = "raise"
    viewpoint: Viewpoint = "above"
    fraction_denominator: int = 16
    hold_threshold_mm: float = 0.01


@dataclass(slots=True)
class CoordinateConvention:
    screw_y_reference_edge: EdgeReference = "top"
    display_front_edge: EdgeReference = "top"


@dataclass(slots=True)
class MaterialResponseOverride:
    self_multiplier: float = 1.0
    neighbor_multiplier: float = 1.0
    decay_multiplier: float = 1.0
    step_multiplier: float = 1.0
    self_temp_coeff: float = 0.0
    neighbor_temp_coeff: float = 0.0
    step_temp_coeff: float = 0.0
    absolute_cap_turns: float | None = None


@dataclass(slots=True)
class MaterialChoice:
    kind: MaterialChoiceKind = "library"
    library_key: str = "other"
    label: str = ""
    custom_response: MaterialResponseOverride | None = None


@dataclass(slots=True)
class BedAssemblyConfig:
    plate_material: MaterialChoice = field(default_factory=MaterialChoice)
    surface_material: MaterialChoice = field(default_factory=lambda: MaterialChoice(library_key="none", label="None"))


@dataclass(slots=True)
class SupportAssemblyConfig:
    mount_type: str = ""
    support_material: MaterialChoice = field(default_factory=MaterialChoice)
    support_stack_height_mm: float = 12.0


@dataclass(slots=True)
class FastenerConfig:
    screw_material: MaterialChoice = field(default_factory=MaterialChoice)


@dataclass(slots=True)
class RawMechanicalModelConfig:
    enabled: bool = True
    preset_name: str = "other"
    self_gain: float = 0.85
    neighbor_gain: float = 0.12
    decay_length_mm: float = 140.0
    max_step_turns: float = 0.0625
    regularization_lambda: float = 1e-5
    use_advanced_override: bool = False


MechanicalModelConfig = RawMechanicalModelConfig


@dataclass(slots=True)
class EnvironmentMetadata:
    bed_assembly: BedAssemblyConfig = field(default_factory=BedAssemblyConfig)
    support_assembly: SupportAssemblyConfig = field(default_factory=SupportAssemblyConfig)
    fastener: FastenerConfig = field(default_factory=FastenerConfig)
    bed_temperature_c: float | None = None
    chamber_temperature_c: float | None = None

    @property
    def bed_material(self) -> str:
        return self.bed_assembly.plate_material.label or self.bed_assembly.plate_material.library_key

    @property
    def mount_type(self) -> str:
        return self.support_assembly.mount_type

    @property
    def standoff_material(self) -> str:
        return self.support_assembly.support_material.label or self.support_assembly.support_material.library_key

    @property
    def screw_material(self) -> str:
        return self.fastener.screw_material.label or self.fastener.screw_material.library_key


@dataclass(slots=True)
class MeshGrid:
    z_values: list[list[float]]
    x_min_mm: float
    x_max_mm: float
    y_min_mm: float
    y_max_mm: float
    top_row_is_y_max: bool = True

    @property
    def row_count(self) -> int:
        return len(self.z_values)

    @property
    def column_count(self) -> int:
        return len(self.z_values[0]) if self.z_values else 0

    def x_coordinates(self) -> np.ndarray:
        return np.linspace(self.x_min_mm, self.x_max_mm, self.column_count, dtype=float)

    def y_coordinates(self) -> np.ndarray:
        ascending = np.linspace(self.y_min_mm, self.y_max_mm, self.row_count, dtype=float)
        return ascending[::-1] if self.top_row_is_y_max else ascending

    def z_array(self) -> np.ndarray:
        return np.asarray(self.z_values, dtype=float)

    def contains_point(self, x_mm: float, y_mm: float) -> bool:
        return self.x_min_mm <= x_mm <= self.x_max_mm and self.y_min_mm <= y_mm <= self.y_max_mm


@dataclass(slots=True)
class CalibrationTrial:
    name: str
    before_mesh: MeshGrid
    after_mesh: MeshGrid
    applied_turns: dict[str, float]
    bed: BedConfig
    screws: list[ScrewMeasurement]
    turn_config: ScrewTurnConfig
    reference_screw_name: str
    coordinate_convention: CoordinateConvention = field(default_factory=CoordinateConvention)
    metadata: EnvironmentMetadata = field(default_factory=EnvironmentMetadata)


@dataclass(slots=True)
class ProjectData:
    bed: BedConfig
    screws: list[ScrewMeasurement]
    turn_config: ScrewTurnConfig
    reference_screw_name: str
    coordinate_convention: CoordinateConvention = field(default_factory=CoordinateConvention)
    mechanical_model: RawMechanicalModelConfig = field(default_factory=RawMechanicalModelConfig)
    metadata: EnvironmentMetadata = field(default_factory=EnvironmentMetadata)
    mesh: MeshGrid | None = None
    calibration_trials: list[CalibrationTrial] = field(default_factory=list)
    schema_version: int = 4
    upgraded_from_schema: int | None = field(default=None, repr=False, compare=False)


@dataclass(slots=True)
class GeometryScrewStatus:
    name: str
    left_mm: float
    y_measure_mm: float
    x_mm: float
    y_mm: float
    inside_bed: bool
    inside_mesh: bool | None = None
    duplicate_with: list[str] = field(default_factory=list)
    quadrant: str | None = None


@dataclass(slots=True)
class GeometryReport:
    screw_statuses: list[GeometryScrewStatus]
    blocking_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProbeAreaSummary:
    probe_width_mm: float
    probe_height_mm: float
    coverage_ratio: float
    warning_level: Literal["none", "partial", "strong"]


@dataclass(slots=True)
class PlaneFit:
    a: float
    b: float
    c: float


@dataclass(slots=True)
class ResidualStats:
    max_abs_mm: float
    rms_mm: float
    peak_to_valley_mm: float
    plane_slope_magnitude: float


@dataclass(slots=True)
class QuadraticFit:
    a_x2: float
    b_y2: float
    c_xy: float
    d_x: float
    e_y: float
    f_constant: float
    r_squared: float


@dataclass(slots=True)
class WarpReport:
    enabled: bool
    classification: str
    confidence: str
    summary: str
    fit: QuadraticFit | None = None


@dataclass(slots=True)
class ScrewInstruction:
    name: str
    x_mm: float
    y_mm: float
    plane_height_mm: float
    delta_height_mm: float
    action: str
    direction: str
    signed_turns: float
    decimal_turns: float
    rounded_turns: str
    source_model: ModelSource = "baseline"
    expected_achieved_delta_mm: float | None = None
    local_residual_mm: float | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TurnStep:
    pass_index: int
    screw_name: str
    action: str
    rotation: str
    turns_this_pass: float
    remaining_after_pass: float
    note: str | None = None


@dataclass(slots=True)
class TurnPlan:
    source_model: ModelSource
    total_target_turns: dict[str, float]
    first_pass_steps: list[TurnStep]
    requires_remesh_after_pass: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MechanicalConfidence:
    score: float
    level: ConfidenceLevel
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EffectiveMechanicalModel:
    enabled: bool = True
    preset_name: str = "other"
    self_gain: float = 0.85
    neighbor_gain: float = 0.12
    decay_length_mm: float = 140.0
    max_step_turns: float = 0.0625
    regularization_lambda: float = 1e-5
    thermal_index: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AnalysisResult:
    plane_fit: PlaneFit
    residual_stats: ResidualStats
    warp_report: WarpReport
    baseline_instructions: list[ScrewInstruction]
    physical_instructions: list[ScrewInstruction]
    baseline_turn_plan: TurnPlan
    physical_turn_plan: TurnPlan | None
    geometry_report: GeometryReport
    probe_area_summary: ProbeAreaSummary
    effective_mechanical_model: EffectiveMechanicalModel | None
    mechanical_confidence: MechanicalConfidence | None
    warnings: list[str]
    divergence_warnings: list[str]
    plane_surface: list[list[float]]
    residual_surface: list[list[float]]

    @property
    def instructions(self) -> list[ScrewInstruction]:
        return self.baseline_instructions
