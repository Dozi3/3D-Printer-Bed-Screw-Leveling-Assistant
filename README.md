# Bed Screw Solver V4

[![CI](https://github.com/Dozi3/3D-Printer-Bed-Screw-Leveling-Assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/Dozi3/3D-Printer-Bed-Screw-Leveling-Assistant/actions/workflows/ci.yml)

Bed Screw Solver V4 is a local desktop utility for analysing a regular bed mesh, separating global tilt from local warp, and turning the fitted plane into per-screw adjustment guidance.

V4 keeps the V2 plane-fit baseline solver as the primary recommendation path, keeps the physical-response model clearly labelled as heuristic / advisory, adds saved per-project calibration trials, and keeps the component-library layer as seed suggestion data.

## What V4 Does
- Fits a best plane to a pasted or imported regular mesh.
- Computes baseline screw adjustments from the plane only.
- Shows a heuristic physical-response second opinion beside the baseline result.
- Generates first-pass turn plans for both models.
- Shows raw mesh, plane-only tilt, residual warp, and probe coverage separately.
- Provides 2D and interactive 3D mesh views for mesh input and analysis.
- Saves and loads local JSON project files with schema version `4`.
- Loads a bundled component profile library and optionally imports validated local JSON libraries.
- Shows component-library suggestions as suggestions only; they never silently overwrite active project values.
- Saves calibration trials with before/after meshes and applied signed turns, then fits optional per-project physical-response parameters.

## Recommendation Model
- Baseline:
  - authoritative recommendation path
  - fits `z = a*x + b*y + c`
  - evaluates that plane at each screw
  - computes deltas relative to the selected reference screw
  - converts those deltas to turns using pitch only
- Physical-response model:
  - optional heuristic / advisory comparison
  - starts from the mount preset or advanced override, then applies bounded material and temperature modifiers
  - uses bed plate, support stack, screw material, and hot-state inputs to estimate multi-screw interaction
  - never silently replaces the baseline recommendation

Residual warp classification is diagnostic only. It does not directly drive either baseline or physical target turns.

## Material And Thermal Model
- Bed assembly is split into:
  - structural plate material
  - removable surface material
- Support stack is split into:
  - mount type
  - support material
  - support stack height
- Fastener material is tracked separately from the support stack.
- Library-backed material selectors cover common 3D-printer hardware:
  - bed plates: cast / rolled aluminum, steel, stainless, borosilicate glass, graphite
  - surfaces: none, PEI on spring steel, glass sheet, garolite, polymer sheet
  - support stacks: springs, silicone, rigid spacers, shims, and custom overrides
  - screws: steel, stainless, alloy steel, brass, aluminum, titanium, PEEK, nylon
- Materials and temperatures only affect the heuristic / advisory physical model:
  - support material and stack height dominate the response modifiers
  - bed plate material modestly changes neighbour coupling and brittle-step limits
  - screw material mainly affects safe first-pass size and confidence
  - removable surface material changes warnings by default and only changes gains when a custom override is enabled
- The app computes a thermal index from:
  - `bed_temperature_c`
  - `chamber_temperature_c`
  - `support_stack_height_mm`
- The app shows an effective mechanical model summary and a runtime confidence level, but these do not change the baseline plane-fit math.

## Coordinate Conventions
- Screw measurements are stored as:
  - `left_mm`
  - `y_measure_mm`
- Screw coordinate conversion depends only on `screw_y_reference_edge`:
  - `"top"` -> `x = left_mm`, `y = bed_height_mm - y_measure_mm`
  - `"bottom"` -> `x = left_mm`, `y = y_measure_mm`
- `display_front_edge` affects labels and on-screen orientation only. It does not affect solver math.
- Mesh row order stays independent through `top_row_is_y_max`.

## Project Format
- V4 writes schema version `4` only.
- V4 still reads schema versions `1`, `2`, and `3` and upgrades them in memory.
- Schema-v1 upgrades default to:
  - `screw_y_reference_edge = "top"`
  - `display_front_edge = "top"`
  - `mechanical_model.enabled = false`
  - preset inferred from the support mount type
  - `use_advanced_override = false`
- Schema-v2 upgrades map legacy free-text material fields into the schema-v4 material library and preserve unknown labels as `other`.
- Schema-v4 stores raw UI mechanical settings and saved calibration trials. Effective mechanical parameters are resolved at analysis time.
- Upgraded legacy projects warn that older files could not distinguish the bed plate from the top surface.

## Mesh Input
Supported mesh input:
- pasted CSV
- pasted TSV
- pasted whitespace-delimited numeric text
- imported CSV file with the same rectangular grid

The mesh must be rectangular and at least `2x2`.

The app also requires:
- `x_min_mm`
- `x_max_mm`
- `y_min_mm`
- `y_max_mm`
- row order:
  - `Top row = y_max`
  - `Top row = y_min`

Mesh preview panels can switch between 2D and 3D. The 3D view supports drag-to-orbit, wheel zoom, right/middle drag pan, reset view, height scaling, screw/probe overlays, and click-to-inspect X/Y/Z values.

## Usage
1. Enter the bed width, bed height, screw pitch, and reference screw.
2. Add screw positions using `left_mm` and `y_measure_mm`.
3. Choose the screw Y reference edge and display front edge.
4. Optionally use `Tools > Component Library` to browse or import printer/component profiles.
5. Apply only explicitly selected profile fields after reviewing current value, suggested value, and confidence.
6. Enter or review the bed plate, surface, support, screw, and temperature metadata.
7. Set support stack height if the mount stack is taller or shorter than the default.
8. Enable custom material overrides only if the library entry is not close enough for your hardware.
9. Paste or import the mesh and set mesh bounds plus row order.
10. Use `Preview Mesh` to inspect the active and alternate row-order views in 2D or 3D.
11. Run `Analyse`.
12. Follow the baseline recommendation first.
13. Use the physical-response result only as a heuristic / advisory comparison.
14. Optionally save calibration trials from before/after meshes and the turns you actually applied.
15. Re-mesh after each first pass and iterate.

## Calibration
- Calibration is per-project only and does not write a global printer database.
- Each trial stores the before mesh, after mesh, applied signed turns, screw/bed/reference snapshots, coordinate convention, turn config, and metadata snapshot.
- Positive signed turns mean raise; negative signed turns mean lower.
- Fitted calibration values are written into the raw mechanical config as an advanced override. Baseline plane-fit recommendations do not change.

## Component Library
- Built-in seed data is stored in `assets/app_component_profile_library.json`.
- Optional imports must use the same app-focused JSON contract and pass validation.
- The read-only SQLite browser uses `assets/component_materials_database.sqlite` and starts from the GUI views.
- `-` means unknown and `n/a` means not applicable; neither becomes a solver default.
- Profile application never changes mesh data, screw positions, row order, reference screw, or coordinate conventions.

## Build
Use a workspace-local virtual environment for development and validation:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run the full validation gate:

```powershell
.\validate_all.ps1
```

The validation gate checks dependency imports, compiles source/tests, runs the test suite, and performs a onefile build check.

Install dependencies without creating a virtual environment:

```powershell
python -m pip install -r requirements.txt
```

Windows standalone build:

```powershell
.\build_standalone.ps1
```

Isolated validation build:

```powershell
.\build_standalone.ps1 -OutputDir dist-validation\standalone
```

Windows onefile build:

```powershell
.\build_onefile.ps1
```

Build dependency check without producing an executable:

```powershell
.\build_onefile.ps1 -CheckOnly -NoPause
```

Linux standalone build with PowerShell:

```powershell
pwsh ./build_linux_standalone.ps1
```

Linux prerequisites:
- `pwsh`
- Python 3
- a compiler toolchain supported by Nuitka on the target distro
- PySide6 and Nuitka runtime requirements for standalone builds

V4 does not add Linux onefile packaging.

## Known Limits
- The physical-response model is heuristic and should be validated with short passes and re-mesh cycles.
- Probe coverage can be partial; residual interpretation is weaker outside the probed area.
- Shim workflows are approximate in a turn-based UI and should be interpreted as mm-equivalent support change.
- Missing, custom, or unusual hardware and temperature metadata reduce confidence in the heuristic model, but do not change the plane-fit target math.
