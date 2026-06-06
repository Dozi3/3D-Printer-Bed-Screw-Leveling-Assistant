from __future__ import annotations

from dataclasses import dataclass

from models import (
    BedAssemblyConfig,
    FastenerConfig,
    MaterialChoice,
    MaterialResponseOverride,
    SupportAssemblyConfig,
)


@dataclass(frozen=True)
class MaterialResponseProfile:
    self_mult: float = 1.0
    neighbor_mult: float = 1.0
    decay_mult: float = 1.0
    step_mult: float = 1.0
    self_temp_coeff: float = 0.0
    neighbor_temp_coeff: float = 0.0
    step_temp_coeff: float = 0.0
    absolute_cap_turns: float | None = None


@dataclass(frozen=True)
class MaterialWarningRule:
    message: str
    bed_threshold_c: float | None = None
    chamber_threshold_c: float | None = None


@dataclass(frozen=True)
class MaterialLibraryEntry:
    key: str
    label: str
    response: MaterialResponseProfile = MaterialResponseProfile()
    warning_rules: tuple[MaterialWarningRule, ...] = ()
    notes: tuple[str, ...] = ()


MOUNT_TYPE_LABELS: dict[str, str] = {
    "springs": "Springs",
    "silicone": "Silicone",
    "rigid spacers": "Rigid spacers",
    "shims": "Shims",
    "other": "Other",
}

DEFAULT_SUPPORT_STACK_HEIGHT_MM: dict[str, float] = {
    "springs": 15.0,
    "silicone": 10.0,
    "rigid spacers": 8.0,
    "shims": 1.0,
    "other": 12.0,
}

BED_PLATE_LIBRARY: dict[str, MaterialLibraryEntry] = {
    "cast_aluminum": MaterialLibraryEntry("cast_aluminum", "Cast aluminum"),
    "rolled_aluminum": MaterialLibraryEntry("rolled_aluminum", "Rolled aluminum"),
    "steel": MaterialLibraryEntry(
        "steel",
        "Steel",
        response=MaterialResponseProfile(neighbor_mult=1.08, decay_mult=1.10),
    ),
    "stainless": MaterialLibraryEntry(
        "stainless",
        "Stainless steel",
        response=MaterialResponseProfile(neighbor_mult=1.08, decay_mult=1.10),
    ),
    "borosilicate_glass": MaterialLibraryEntry(
        "borosilicate_glass",
        "Borosilicate glass",
        response=MaterialResponseProfile(neighbor_mult=0.98, decay_mult=0.98, absolute_cap_turns=1.0 / 32.0),
        notes=("Brittle bed plate; keep first-pass moves conservative.",),
    ),
    "graphite": MaterialLibraryEntry(
        "graphite",
        "Graphite",
        response=MaterialResponseProfile(step_mult=0.90, absolute_cap_turns=1.0 / 32.0),
        notes=("Graphite plate is brittle; keep first-pass moves conservative.",),
    ),
    "other": MaterialLibraryEntry("other", "Other"),
}

BED_SURFACE_LIBRARY: dict[str, MaterialLibraryEntry] = {
    "none": MaterialLibraryEntry("none", "None"),
    "pei_on_spring_steel": MaterialLibraryEntry(
        "pei_on_spring_steel",
        "PEI on spring steel",
        notes=("Removable spring-steel surfaces can shift thermal lag relative to the plate.",),
    ),
    "glass_sheet": MaterialLibraryEntry(
        "glass_sheet",
        "Glass sheet",
        notes=("Glass sheets can trap thermal lag; verify the hot-state mesh after surface changes.",),
    ),
    "garolite": MaterialLibraryEntry(
        "garolite",
        "Garolite",
        notes=("Garolite surfaces can change thermal lag and clamping behavior.",),
    ),
    "polymer_sheet": MaterialLibraryEntry(
        "polymer_sheet",
        "Polymer sheet",
        notes=("Polymer build sheets can change thermal lag relative to the bed plate.",),
    ),
    "other": MaterialLibraryEntry("other", "Other"),
}

SUPPORT_LIBRARY: dict[str, MaterialLibraryEntry] = {
    "spring_steel": MaterialLibraryEntry(
        "spring_steel",
        "Spring steel",
        response=MaterialResponseProfile(self_temp_coeff=0.05, neighbor_temp_coeff=0.02, step_temp_coeff=0.05),
    ),
    "music_wire": MaterialLibraryEntry(
        "music_wire",
        "Music wire",
        response=MaterialResponseProfile(self_temp_coeff=0.05, neighbor_temp_coeff=0.02, step_temp_coeff=0.05),
        warning_rules=(
            MaterialWarningRule(
                "Music-wire springs are less comfortable in sustained hot-state workflows; verify the first pass carefully.",
                bed_threshold_c=90.0,
                chamber_threshold_c=60.0,
            ),
        ),
    ),
    "stainless_spring": MaterialLibraryEntry(
        "stainless_spring",
        "Stainless spring",
        response=MaterialResponseProfile(self_temp_coeff=0.04, neighbor_temp_coeff=0.02, step_temp_coeff=0.04),
        warning_rules=(
            MaterialWarningRule(
                "Stainless springs are usually stable here, but sustained hot-state operation can still relax the stack.",
                bed_threshold_c=110.0,
                chamber_threshold_c=80.0,
            ),
        ),
    ),
    "chrome_silicon": MaterialLibraryEntry(
        "chrome_silicon",
        "Chrome silicon spring",
        response=MaterialResponseProfile(self_temp_coeff=0.03, neighbor_temp_coeff=0.01, step_temp_coeff=0.03),
        warning_rules=(
            MaterialWarningRule(
                "Chrome-silicon springs tolerate heat well, but hot-state passes should still be validated with a re-mesh.",
                bed_threshold_c=110.0,
                chamber_threshold_c=80.0,
            ),
        ),
    ),
    "silicone_elastomer": MaterialLibraryEntry(
        "silicone_elastomer",
        "Silicone elastomer",
        response=MaterialResponseProfile(
            self_mult=0.90,
            neighbor_mult=1.10,
            step_mult=0.80,
            self_temp_coeff=0.22,
            neighbor_temp_coeff=0.12,
            step_temp_coeff=0.30,
        ),
        warning_rules=(
            MaterialWarningRule(
                "Silicone support stacks are creep- and compression-set-sensitive; let the bed settle before re-meshing.",
                bed_threshold_c=100.0,
                chamber_threshold_c=70.0,
            ),
        ),
        notes=("Silicone stacks are viscoelastic; short passes and settle time matter.",),
    ),
    "steel": MaterialLibraryEntry(
        "steel",
        "Steel spacer",
        response=MaterialResponseProfile(self_mult=1.05, neighbor_mult=0.95, self_temp_coeff=0.02, step_temp_coeff=0.03),
    ),
    "stainless": MaterialLibraryEntry(
        "stainless",
        "Stainless spacer",
        response=MaterialResponseProfile(self_mult=1.05, neighbor_mult=0.95, self_temp_coeff=0.02, step_temp_coeff=0.03),
    ),
    "aluminum": MaterialLibraryEntry(
        "aluminum",
        "Aluminum spacer",
        response=MaterialResponseProfile(self_mult=1.05, neighbor_mult=0.95, self_temp_coeff=0.02, step_temp_coeff=0.03),
    ),
    "brass": MaterialLibraryEntry(
        "brass",
        "Brass spacer",
        response=MaterialResponseProfile(self_mult=1.05, neighbor_mult=0.95, self_temp_coeff=0.02, step_temp_coeff=0.03),
    ),
    "peek": MaterialLibraryEntry(
        "peek",
        "PEEK spacer",
        response=MaterialResponseProfile(
            self_mult=0.97,
            step_mult=0.90,
            self_temp_coeff=0.08,
            neighbor_temp_coeff=0.03,
            step_temp_coeff=0.10,
        ),
        warning_rules=(
            MaterialWarningRule(
                "PEEK is usually stable in common printer hot-state workflows; re-mesh if you are near its upper operating range.",
                bed_threshold_c=140.0,
                chamber_threshold_c=100.0,
            ),
        ),
    ),
    "pom_delrin": MaterialLibraryEntry(
        "pom_delrin",
        "POM / Delrin spacer",
        response=MaterialResponseProfile(
            self_mult=0.92,
            neighbor_mult=1.05,
            step_mult=0.75,
            self_temp_coeff=0.16,
            neighbor_temp_coeff=0.08,
            step_temp_coeff=0.25,
        ),
        warning_rules=(
            MaterialWarningRule(
                "POM / Delrin support stacks soften sooner in hot-state workflows; keep passes short and verify with a re-mesh.",
                bed_threshold_c=70.0,
                chamber_threshold_c=50.0,
            ),
        ),
    ),
    "nylon_pa": MaterialLibraryEntry(
        "nylon_pa",
        "Nylon / PA spacer",
        response=MaterialResponseProfile(
            self_mult=0.92,
            neighbor_mult=1.05,
            step_mult=0.75,
            self_temp_coeff=0.16,
            neighbor_temp_coeff=0.08,
            step_temp_coeff=0.25,
        ),
        warning_rules=(
            MaterialWarningRule(
                "Nylon support stacks are temperature- and moisture-sensitive; expect lower repeatability than metal hardware.",
                bed_threshold_c=80.0,
                chamber_threshold_c=60.0,
            ),
        ),
        notes=("Nylon changes with moisture as well as heat; repeatability is lower than metal stacks.",),
    ),
    "printed_polymer": MaterialLibraryEntry(
        "printed_polymer",
        "Printed polymer spacer",
        response=MaterialResponseProfile(
            self_mult=0.92,
            neighbor_mult=1.05,
            step_mult=0.75,
            self_temp_coeff=0.16,
            neighbor_temp_coeff=0.08,
            step_temp_coeff=0.25,
        ),
        notes=("Printed polymer spacers are low-confidence because creep depends strongly on print quality and polymer choice.",),
    ),
    "polyimide": MaterialLibraryEntry(
        "polyimide",
        "Polyimide shim",
        response=MaterialResponseProfile(
            self_mult=0.95,
            neighbor_mult=1.05,
            step_mult=0.60,
            self_temp_coeff=0.12,
            neighbor_temp_coeff=0.06,
            step_temp_coeff=0.20,
        ),
    ),
    "other": MaterialLibraryEntry("other", "Other"),
}

SCREW_LIBRARY: dict[str, MaterialLibraryEntry] = {
    "steel": MaterialLibraryEntry("steel", "Steel"),
    "stainless": MaterialLibraryEntry("stainless", "Stainless steel"),
    "alloy_steel": MaterialLibraryEntry("alloy_steel", "Alloy steel"),
    "brass": MaterialLibraryEntry(
        "brass",
        "Brass",
        response=MaterialResponseProfile(step_mult=0.90),
        notes=("Brass screws are softer; watch for thread wear and galling.",),
    ),
    "aluminum": MaterialLibraryEntry(
        "aluminum",
        "Aluminum",
        response=MaterialResponseProfile(step_mult=0.90),
        notes=("Aluminum screws are soft; watch for thread wear and galling.",),
    ),
    "titanium": MaterialLibraryEntry(
        "titanium",
        "Titanium",
        response=MaterialResponseProfile(step_mult=0.95),
    ),
    "peek": MaterialLibraryEntry(
        "peek",
        "PEEK",
        response=MaterialResponseProfile(self_mult=0.95, step_mult=0.75),
        warning_rules=(
            MaterialWarningRule(
                "Polymer screws reduce mechanical confidence; use shorter first-pass moves and re-mesh immediately.",
            ),
        ),
    ),
    "nylon": MaterialLibraryEntry(
        "nylon",
        "Nylon",
        response=MaterialResponseProfile(self_mult=0.95, step_mult=0.75),
        warning_rules=(
            MaterialWarningRule(
                "Polymer screws reduce mechanical confidence; use shorter first-pass moves and re-mesh immediately.",
            ),
        ),
    ),
    "other": MaterialLibraryEntry("other", "Other"),
}

SUPPORT_OPTIONS_BY_MOUNT: dict[str, list[str]] = {
    "springs": ["spring_steel", "music_wire", "stainless_spring", "chrome_silicon", "other"],
    "silicone": ["silicone_elastomer", "other"],
    "rigid spacers": ["steel", "stainless", "aluminum", "brass", "peek", "pom_delrin", "nylon_pa", "printed_polymer", "other"],
    "shims": ["steel", "stainless", "aluminum", "brass", "peek", "polyimide", "printed_polymer", "other"],
    "other": ["other"],
}

DEFAULT_SUPPORT_MATERIAL_BY_MOUNT: dict[str, str] = {
    "springs": "spring_steel",
    "silicone": "silicone_elastomer",
    "rigid spacers": "steel",
    "shims": "steel",
    "other": "other",
}

CUSTOM_NEUTRAL_RESPONSE = MaterialResponseOverride()


def normalize_mount_type(value: str) -> str:
    normalized = " ".join(value.strip().lower().replace("-", " ").split())
    aliases = {
        "rigid spacer": "rigid spacers",
        "rigid spacers": "rigid spacers",
        "rigid spacer stack": "rigid spacers",
        "ridgid spacer": "rigid spacers",
        "ridgid spacers": "rigid spacers",
        "spring": "springs",
        "springs": "springs",
        "silicone": "silicone",
        "shim": "shims",
        "shims": "shims",
        "other": "other",
    }
    return aliases.get(normalized, normalized if normalized in MOUNT_TYPE_LABELS else "other")


def make_library_choice(category: str, key: str) -> MaterialChoice:
    entry = lookup_material_entry(category, key)
    return MaterialChoice(kind="library", library_key=entry.key, label=entry.label)


def default_bed_assembly() -> BedAssemblyConfig:
    return BedAssemblyConfig(
        plate_material=make_library_choice("plate", "cast_aluminum"),
        surface_material=make_library_choice("surface", "none"),
    )


def default_support_assembly(mount_type: str = "other") -> SupportAssemblyConfig:
    normalized_mount = normalize_mount_type(mount_type)
    return SupportAssemblyConfig(
        mount_type=normalized_mount,
        support_material=make_library_choice("support", DEFAULT_SUPPORT_MATERIAL_BY_MOUNT[normalized_mount]),
        support_stack_height_mm=DEFAULT_SUPPORT_STACK_HEIGHT_MM[normalized_mount],
    )


def default_fastener_config() -> FastenerConfig:
    return FastenerConfig(screw_material=make_library_choice("screw", "steel"))


def support_options_for_mount(mount_type: str) -> list[tuple[str, str]]:
    normalized_mount = normalize_mount_type(mount_type)
    return [
        (SUPPORT_LIBRARY[key].label, key)
        for key in SUPPORT_OPTIONS_BY_MOUNT.get(normalized_mount, SUPPORT_OPTIONS_BY_MOUNT["other"])
    ]


def lookup_material_entry(category: str, key: str) -> MaterialLibraryEntry:
    library = _library_for_category(category)
    return library.get(key, library["other"])


def material_label(choice: MaterialChoice, category: str) -> str:
    if choice.label:
        return choice.label
    return lookup_material_entry(category, choice.library_key).label


def material_profile(choice: MaterialChoice, category: str) -> MaterialResponseProfile:
    base = lookup_material_entry(category, choice.library_key).response
    if choice.kind != "custom" or choice.custom_response is None:
        return base
    custom = choice.custom_response
    cap = _min_cap(base.absolute_cap_turns, custom.absolute_cap_turns)
    return MaterialResponseProfile(
        self_mult=base.self_mult * custom.self_multiplier,
        neighbor_mult=base.neighbor_mult * custom.neighbor_multiplier,
        decay_mult=base.decay_mult * custom.decay_multiplier,
        step_mult=base.step_mult * custom.step_multiplier,
        self_temp_coeff=base.self_temp_coeff + custom.self_temp_coeff,
        neighbor_temp_coeff=base.neighbor_temp_coeff + custom.neighbor_temp_coeff,
        step_temp_coeff=base.step_temp_coeff + custom.step_temp_coeff,
        absolute_cap_turns=cap,
    )


def choice_uses_custom_response(choice: MaterialChoice) -> bool:
    return choice.kind == "custom" and choice.custom_response is not None


def infer_legacy_plate_choice(raw_value: str) -> MaterialChoice:
    normalized = _normalize_material_value(raw_value)
    if not normalized:
        return make_library_choice("plate", "cast_aluminum")
    mapping = {
        "aluminum": "cast_aluminum",
        "aluminium": "cast_aluminum",
        "cast aluminum": "cast_aluminum",
        "cast aluminium": "cast_aluminum",
        "milled aluminum": "cast_aluminum",
        "milled aluminium": "cast_aluminum",
        "tooling plate": "cast_aluminum",
        "rolled aluminum": "rolled_aluminum",
        "rolled aluminium": "rolled_aluminum",
        "steel": "steel",
        "spring steel": "steel",
        "stainless": "stainless",
        "stainless steel": "stainless",
        "glass": "borosilicate_glass",
        "borosilicate": "borosilicate_glass",
        "borosilicate glass": "borosilicate_glass",
        "graphite": "graphite",
    }
    key = mapping.get(normalized, "other")
    if key == "other":
        return MaterialChoice(kind="library", library_key="other", label=raw_value.strip())
    return make_library_choice("plate", key)


def infer_legacy_surface_choice(raw_value: str) -> MaterialChoice:
    normalized = _normalize_material_value(raw_value)
    mapping = {
        "none": "none",
        "pei": "pei_on_spring_steel",
        "pei on spring steel": "pei_on_spring_steel",
        "spring steel pei": "pei_on_spring_steel",
        "glass": "glass_sheet",
        "glass sheet": "glass_sheet",
        "garolite": "garolite",
        "polymer": "polymer_sheet",
        "polymer sheet": "polymer_sheet",
    }
    key = mapping.get(normalized, "other")
    if not normalized:
        key = "none"
    if key == "other":
        return MaterialChoice(kind="library", library_key="other", label=raw_value.strip())
    return make_library_choice("surface", key)


def infer_legacy_support_choice(mount_type: str, raw_value: str) -> MaterialChoice:
    normalized_mount = normalize_mount_type(mount_type)
    normalized = _normalize_material_value(raw_value)
    if not normalized:
        return make_library_choice("support", DEFAULT_SUPPORT_MATERIAL_BY_MOUNT[normalized_mount])

    if normalized_mount == "springs":
        if "music" in normalized:
            key = "music_wire"
        elif "chrome" in normalized or "silicon" in normalized:
            key = "chrome_silicon"
        elif "stainless" in normalized:
            key = "stainless_spring"
        elif "spring" in normalized or "steel" in normalized:
            key = "spring_steel"
        else:
            key = "other"
    elif normalized_mount == "silicone":
        key = "silicone_elastomer" if "silicone" in normalized else "other"
    else:
        if any(token in normalized for token in ("stainless",)):
            key = "stainless"
        elif any(token in normalized for token in ("steel",)):
            key = "steel"
        elif "brass" in normalized:
            key = "brass"
        elif any(token in normalized for token in ("aluminium", "aluminum")):
            key = "aluminum"
        elif "peek" in normalized:
            key = "peek"
        elif any(token in normalized for token in ("delrin", "pom", "acetal")):
            key = "pom_delrin"
        elif any(token in normalized for token in ("nylon", "pa6", "pa12", "polyamide")):
            key = "nylon_pa"
        elif any(token in normalized for token in ("printed", "petg", "pla", "abs", "asa")):
            key = "printed_polymer"
        elif "polyimide" in normalized or "kapton" in normalized:
            key = "polyimide"
        else:
            key = "other"

    if key == "other":
        return MaterialChoice(kind="library", library_key="other", label=raw_value.strip())
    return make_library_choice("support", key)


def infer_legacy_screw_choice(raw_value: str) -> MaterialChoice:
    normalized = _normalize_material_value(raw_value)
    if not normalized:
        return make_library_choice("screw", "steel")
    if "alloy" in normalized and "steel" in normalized:
        key = "alloy_steel"
    elif "stainless" in normalized:
        key = "stainless"
    elif "steel" in normalized:
        key = "steel"
    elif "brass" in normalized:
        key = "brass"
    elif any(token in normalized for token in ("aluminium", "aluminum")):
        key = "aluminum"
    elif "titanium" in normalized:
        key = "titanium"
    elif "peek" in normalized:
        key = "peek"
    elif "nylon" in normalized:
        key = "nylon"
    else:
        key = "other"
    if key == "other":
        return MaterialChoice(kind="library", library_key="other", label=raw_value.strip())
    return make_library_choice("screw", key)


def _library_for_category(category: str) -> dict[str, MaterialLibraryEntry]:
    if category == "plate":
        return BED_PLATE_LIBRARY
    if category == "surface":
        return BED_SURFACE_LIBRARY
    if category == "support":
        return SUPPORT_LIBRARY
    if category == "screw":
        return SCREW_LIBRARY
    raise KeyError(f"Unknown material library category: {category}")


def _normalize_material_value(value: str) -> str:
    return " ".join(value.strip().lower().replace("-", " ").replace("_", " ").split())


def _min_cap(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)
