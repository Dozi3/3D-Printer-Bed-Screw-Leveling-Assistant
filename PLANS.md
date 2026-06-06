# Bed Screw Solver V1

## Derived Requirements
- Build a local-only Windows-first desktop app with a native `PySide6` GUI.
- Keep the solver deterministic and printer-agnostic.
- Base screw instructions on a fitted plane only.
- Report residual warp separately for diagnostics.
- Support local JSON save/load, clipboard export, and CSV export.

## Assumptions
- Mesh bounds use the same physical bed-edge coordinate frame as screw measurements.
- V1 assumes one global screw pitch, thread behaviour, and viewing convention for all screws.
- Screw pitch is treated as a linear first-order mapping from turns to local bed-height change.
- Compliance, thermal effects, and multi-screw coupling are handled by iterative re-meshing, not by the solver.
- Warp classification is heuristic and threshold-based.
- Analysis is manual, single-threaded, and on-demand.

## Exact File Tree
```text
repo-root/
  PLANS.md
  README.md
  requirements.txt
  build_onefile.ps1
  build_standalone.ps1
  main.py
  models.py
  mesh_io.py
  project_io.py
  solver.py
  warp.py
  analysis.py
  widgets/
    __init__.py
    heatmap_widget.py
    main_window.py
  tests/
    __init__.py
    test_mesh_io.py
    test_project_io.py
    test_solver.py
    test_warp.py
```

## Implementation Phases
1. Define typed project, mesh, and analysis models.
2. Implement mesh parsing, validation, and JSON persistence.
3. Implement plane fitting, screw instruction logic, interpolation, and residual stats.
4. Implement heuristic residual warp fitting and classification.
5. Implement a thin `analysis.py` orchestration layer.
6. Build the Qt UI with setup, mesh, analysis, and results tabs.
7. Add core math and persistence tests.
8. Add Nuitka build scripts and concise usage documentation.

## Math Summary
- User measurements use left/top distances from the physical bed edges.
- Internal solver coordinates use a Cartesian bottom-left origin:
  - `x = left_mm`
  - `y = bed_height_mm - top_mm`
- Fit `z = a*x + b*y + c` with `numpy.linalg.lstsq`.
- Evaluate the plane at each screw and compute `delta_j = p_ref - p_j`.
- Convert `delta_j` to turns with `delta_j / pitch_mm_per_turn`.
- Report physical action and apparent `CW` / `CCW` separately.
- Compute residuals as `z_i - p(x_i, y_i)` and classify them heuristically after plane removal.
- Use bilinear interpolation only for display and local residual notes, never for screw-turn math.

## Non-goals
- No printer communication, printer control, or G-code generation.
- No OCR, screenshot import, or automatic screw detection.
- No cloud save, telemetry, accounts, theming systems, plugins, or databases.
- No advanced compliance, stiffness, or thermal mechanics model.
- No independent-Z motor levelling support.
