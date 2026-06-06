# Component Materials Database - App Integration Notes

## What was extracted

All usable tables from `3D Printer Component Materials and Bed Flatness Database.docx` were extracted and normalised.

The DOCX contained 17 native Word tables plus one malformed Markdown-style table for `Table 10: Probing and Calibration Hardware`. That malformed table was recovered and converted into a standard table.

Missing or blank cells were normalised to `-`.

## Output files

- `component_materials_database.xlsx`
  Human-readable workbook with each table as a separate sheet and two merged GUI lookup sheets.

- `component_materials_database.sqlite`
  SQLite database with one table per extracted table plus GUI-friendly merged tables and views.

- `component_materials_database.json`
  Full normalised JSON export containing all extracted tables.

- `app_component_profile_library.json`
  Smaller app-oriented JSON containing the merged printer/component profiles, app calibration profiles, material properties, source evidence and research gaps.

- `csv/*.csv`
  One CSV per table.

## Best first implementation inside the app

Use `app_component_profile_library.json` first.

Recommended loading flow:

1. Load built-in defaults from code.
2. If an imported JSON library exists, load and validate it.
3. If valid, expose it in the GUI lookup/preset selector.
4. Do not automatically overwrite user-entered project values.
5. Let the user manually apply a selected profile.
6. Keep user-entered mesh, screw positions and row-order authoritative.

## Useful GUI tables

### `gui_printer_component_profiles`

One row per printer model. This is the broad lookup table for users browsing specs.

Good for:

- search/filter by manufacturer/model
- bed material lookup
- build plate lookup
- probe type lookup
- chamber state lookup
- research-gap display
- source tracking

### `gui_app_calibration_profiles`

One row per application calibration mapping. This is the best table to feed preset behaviour.

Good for:

- recommended mount preset
- recommended max step turns
- hot mesh warnings
- bed material warnings
- probe material-interaction warnings
- suggested solver mode

## Suggested app data hierarchy

The app should treat data sources in this order:

1. User-entered project values
2. Measured mesh data
3. Imported profile library
4. Built-in defaults
5. General material heuristics

Remote or imported data should pre-fill values, not silently override active project data.

## Things to be wary of

### 1. Do not use unknown values as defaults

A `-` means unknown or unavailable, not zero, false or no.

### 2. Do not collapse bed layers

Keep these separate:

- bed core material
- build surface
- removable plate material
- magnetic layer
- mounting/spacer material
- screw hardware
- probe type

### 3. Do not treat heuristic recommendations as measured physics

`recommended_mount_preset`, `recommended_max_step_turns` and solver mode are application recommendations. They are not measured mechanical constants.

### 4. Keep source/confidence visible

Many fields have medium or low confidence because manufacturers often do not publish hidden mount-stack data. Show confidence in the UI.

### 5. Support versioning

The JSON includes `schema_version`. Future versions should preserve backward compatibility.

## Minimal app-side validation

When importing a JSON library:

- check `schema_version`
- ensure required top-level keys exist
- reject non-object/non-array data where arrays are expected
- reject negative screw pitch / max step values
- treat missing fields as `-`
- warn, do not crash, if a table is missing

## SQLite usage

The SQLite database has these useful views:

- `v_gui_printer_component_profiles`
- `v_gui_app_calibration_profiles`

For most GUI lookups, query those views first rather than joining raw tables in application code.
