from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QSettings, QSignalBlocker, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from analysis import AnalysisError, analyse_project, build_probe_area_summary, inspect_project_geometry
from materials import (
    BED_PLATE_LIBRARY,
    BED_SURFACE_LIBRARY,
    SCREW_LIBRARY,
    SUPPORT_LIBRARY,
    default_bed_assembly,
    default_fastener_config,
    default_support_assembly,
    normalize_mount_type,
    support_options_for_mount,
)
from mechanics import PRESET_DEFAULTS, infer_preset_name, resolve_effective_mechanical_model, validate_mechanical_config
from mesh_io import MeshInputError, build_mesh_grid, load_csv_grid, parse_text_grid
from models import (
    AnalysisResult,
    BedConfig,
    BedAssemblyConfig,
    CoordinateConvention,
    EnvironmentMetadata,
    FastenerConfig,
    GeometryReport,
    MaterialChoice,
    MaterialResponseOverride,
    MechanicalModelConfig,
    MeshGrid,
    ProjectData,
    ScrewInstruction,
    ScrewMeasurement,
    ScrewTurnConfig,
    SupportAssemblyConfig,
    TurnPlan,
)
from project_io import ProjectDataError, load_project, save_project
from solver import measurement_to_internal
from widgets.calibration_tab import build_calibration_tab
from widgets import calibration_actions
from widgets.component_library_dialog import ComponentLibraryDialog
from widgets.heatmap_widget import HeatmapWidget
from widgets.material_editor import MaterialEditorControls
from widgets.mesh_view_panel import MeshViewPanel
from widgets.project_binding import apply_mechanical_model_to_controls


@dataclass
class GuiSettings:
    theme: str = "light"
    font_size_pt: int = 10


APP_NAME = "Bed Screw Solver V4"
APP_VERSION = "4.0.0"
APP_RELEASE_DATE = "2026-04-20"
APP_RELEASE_NOTES = [
    "Light, dark, and high-contrast GUI themes with explicit readable field, table, button, and diagnostic colors.",
    "Mesh bounds can follow bed size until manually edited, with a Use Bed Bounds reset for full-bed probe workflows.",
    "Interactive 3D mesh views with orbit, zoom, pan, inspect, screw overlay, and probe overlay controls.",
    "2D / 3D mesh toggles in Mesh Input and Analysis.",
    "Technical-clean visual refresh for top actions, mesh panels, tabs, tables, and setup diagnostics.",
    "Component Library lookup with bundled JSON seed data and optional validated JSON import.",
    "Manual profile application workflow that never silently overwrites project values.",
    "Read-only SQLite browser for advanced component/source inspection.",
    "Saved per-project calibration trials for fitting advisory physical-response parameters.",
    "V2 plane-fit solver remains the baseline path; V4 writes schema-4 project files.",
]
USER_GUIDE_PAGES = [
    (
        "Welcome",
        """# Welcome

Bed Screw Solver V4 helps you turn a probed bed mesh into practical screw adjustments.

## Core workflow
- Set bed size, screw positions, and turn direction on **Printer / Bed Setup**.
- Optionally browse **Tools > Component Library** for printer-specific suggestions.
- Paste or import the probed mesh on **Mesh Input**.
- Switch mesh panels between 2D and 3D views as needed.
- Run **Analyse** to compare the baseline plane-fit recommendation with the heuristic physical-response model.
- Apply only the first pass, then re-mesh before making more changes.

## Important principle
- **Baseline** recommendations remain the authoritative path.
- **Physical-response** recommendations are a second opinion and stay labeled *heuristic / advisory*.
- Component-library data is labeled *Suggested from component library* and is not authoritative hardware specification data.
""",
    ),
    (
        "Component Library",
        """# Component Library

Use **Tools > Component Library** to browse the bundled seed database or import a validated local JSON profile library.

## Rules
- Imported data suggests values; it does not silently overwrite the active project.
- `-` means unknown, not false, zero, or not applicable.
- `n/a` means not applicable and does not become a solver default.
- Bed core, build surface, removable plate, mounting stack, fasteners, probe hardware, Z support, frame, and chamber data stay separate.

## Applying a profile
- Select a printer profile and use **Apply Selected Profile**.
- Review current value -> suggested value with confidence.
- Tick only the fields you want to apply.
- Mesh data, screw positions, row order, reference screw, and coordinate conventions are not changed by the component-library workflow.
""",
    ),
    (
        "Printer / Bed Setup",
        """# Printer / Bed Setup

Use this tab to define the machine geometry and support stack.

## What to enter
- **Bed width / height** in millimetres.
- **Pitch** in mm per full turn.
- **Clockwise effect** and **viewpoint** exactly as you will turn the screws.
- Screw names and their measured positions.

## Coordinate conventions
- **Screw Y reference** controls how measured screw coordinates are converted internally.
- **Display front edge** changes the on-screen orientation only. It does not affect solver math.

## Metadata
- Select the bed plate, surface, support, and screw materials.
- Use **Custom override** only when you need to model a known non-standard stack.
- Bed and chamber temperatures only affect the advisory physical model and warnings.
""",
    ),
    (
        "Mesh Input",
        """# Mesh Input

Paste mesh data directly or import it from CSV.

## Input rules
- The mesh must be a rectangular numeric grid.
- Mesh bounds follow bed size until you manually edit them.
- Use **Use Bed Bounds** to reset the probed area to the full bed.
- Set manual **x/y bounds** only when the probed area is smaller than the bed.
- Use the **Row order** selector to match how your probe output is arranged.

## Previewing
- The left preview shows the active row-order interpretation.
- The right preview shows the alternate interpretation for comparison.
- Each preview can switch between 2D and 3D.
- In 3D, drag to rotate, use the wheel to zoom, right-drag to pan, and click the mesh to inspect X / Y / Z.
- If the probe area does not cover the full bed, that is acceptable, but the app will warn you.
""",
    ),
    (
        "Analysis",
        """# Analysis

The Analysis tab separates global tilt from local warp.

## Views
- **Raw mesh** shows the imported surface.
- **Plane-only tilt** shows the fitted plane used for baseline screw moves.
- **Residual warp** shows the remaining surface after plane subtraction.
- Each mesh view supports 2D and interactive 3D display.

## Text panels
- **Analysis summary** reports plane coefficients, residual statistics, warp classification, probe coverage, and effective mechanical parameters.
- **Baseline recommendation** shows the primary exact turn values and first-pass logic.
- **Physical-response model** shows the advisory second opinion.
- **Warnings** calls out probe coverage limits, geometry issues, model divergence, and thermal/material cautions.
""",
    ),
    (
        "Results / Export",
        """# Results / Export

The Results tab is organized to keep each recommendation readable.

## Baseline and physical tabs
- Each tab contains a detailed instruction table plus a first-pass turn plan.
- Tables can scroll horizontally rather than crushing columns together.
- The **Notes** column stretches so longer guidance stays readable.

## Export tools
- Use **Export Results CSV** for a machine-readable record.
- Use **Copy Summary** for a text summary you can paste into notes or a support thread.
""",
    ),
    (
        "Practical Use",
        """# Practical Use

## Recommended workflow
1. Heat the printer to the state you actually use.
2. Probe the bed and import the mesh.
3. Review geometry and probe coverage warnings first.
4. Follow the **baseline** first-pass plan.
5. Re-mesh after the pass.
6. Use the physical-response model only as a comparison tool if it helps your hardware stack.

## When to distrust results
- Duplicate screw positions or invalid bed geometry.
- Very small probe coverage.
- Missing hot-state temperatures when you level hot.
- Polymer supports or fasteners at elevated temperatures.
""",
    ),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1500, 920)

        self.current_project: ProjectData | None = None
        self.current_analysis: AnalysisResult | None = None
        self.current_geometry_report: GeometryReport | None = None
        self.calibration_trials = []
        self._populating_project = False
        self._syncing_mesh_bounds = False
        self._mesh_bounds_auto_linked = True
        self.gui_settings = _load_gui_settings()

        self._build_actions()
        self._build_ui()
        self._apply_visual_style()
        self._add_default_screws()
        self._refresh_reference_combo()
        self._refresh_calibration_turn_table()
        self._sync_mechanical_controls()
        self._update_screw_table_headers()
        self.refresh_geometry_diagnostics()

    def _build_actions(self) -> None:
        self.load_action = QAction("&Load Project...", self)
        self.load_action.setShortcut("Ctrl+O")
        self.load_action.setStatusTip("Load a saved bed solver project")
        self.load_action.triggered.connect(self.load_project_dialog)

        self.save_action = QAction("&Save Project...", self)
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.setStatusTip("Save the current project")
        self.save_action.triggered.connect(self.save_project_dialog)

        self.gui_settings_action = QAction("&GUI Settings...", self)
        self.gui_settings_action.setStatusTip("Adjust GUI colors and text size")
        self.gui_settings_action.triggered.connect(self.show_gui_settings_dialog)

        self.close_action = QAction("E&xit", self)
        self.close_action.setShortcut("Ctrl+Q")
        self.close_action.triggered.connect(self.close)

        self.component_library_action = QAction("&Component Library...", self)
        self.component_library_action.setStatusTip("Browse and apply component-library profile suggestions")
        self.component_library_action.triggered.connect(self.show_component_library_dialog)

        self.user_guide_action = QAction("&User Guide", self)
        self.user_guide_action.setShortcut("F1")
        self.user_guide_action.triggered.connect(self.show_user_guide_dialog)

        self.about_action = QAction("&About", self)
        self.about_action.triggered.connect(self.show_about_dialog)

        menu_bar = self.menuBar()
        menu_bar.clear()

        self.file_menu = menu_bar.addMenu("&File")
        self.file_menu.addAction(self.load_action)
        self.file_menu.addAction(self.save_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.gui_settings_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.close_action)

        self.tools_menu = menu_bar.addMenu("&Tools")
        self.tools_menu.addAction(self.component_library_action)

        self.help_menu = menu_bar.addMenu("&Help")
        self.help_menu.addAction(self.user_guide_action)
        self.help_menu.addAction(self.about_action)

    def _build_ui(self) -> None:
        central = QWidget(self)
        outer_layout = QVBoxLayout(central)

        top_bar = QWidget()
        top_bar.setObjectName("TopActionBar")
        primary_actions_layout = QHBoxLayout(top_bar)
        primary_actions_layout.setContentsMargins(12, 8, 12, 8)
        title_label = QLabel("Bed Screw Solver V4")
        title_label.setObjectName("AppHeader")
        self.preview_button = QPushButton("Preview Mesh")
        self.analyse_button = QPushButton("Analyse")
        self.preview_button.setMinimumWidth(132)
        self.analyse_button.setMinimumWidth(132)
        self.analyse_button.setObjectName("PrimaryAction")
        primary_actions_layout.addWidget(title_label)
        primary_actions_layout.addStretch(1)
        primary_actions_layout.addWidget(self.preview_button)
        primary_actions_layout.addWidget(self.analyse_button)
        outer_layout.addWidget(top_bar)

        self.tabs = QTabWidget()
        outer_layout.addWidget(self.tabs, 1)

        self.setup_tab = QWidget()
        self.mesh_tab = QWidget()
        self.analysis_tab = QWidget()
        self.results_tab = QWidget()
        self.calibration_tab = QWidget()
        self.tabs.addTab(self.setup_tab, "Printer / Bed Setup")
        self.tabs.addTab(self.mesh_tab, "Mesh Input")
        self.tabs.addTab(self.analysis_tab, "Analysis")
        self.tabs.addTab(self.results_tab, "Results / Export")
        self.tabs.addTab(self.calibration_tab, "Calibration")

        self._build_setup_tab()
        self._build_mesh_tab()
        self._build_analysis_tab()
        self._build_results_tab()
        self._build_calibration_tab()

        self.setCentralWidget(central)

        self.preview_button.clicked.connect(self.preview_mesh)
        self.analyse_button.clicked.connect(self.run_analysis)

    def _apply_visual_style(self) -> None:
        colors = _gui_palette(self.gui_settings)
        self.setStyleSheet(_build_gui_stylesheet(self.gui_settings))
        self._apply_theme_to_custom_widgets(colors)

    def _apply_theme_to_custom_widgets(self, colors: dict[str, str]) -> None:
        for widget_name in (
            "layout_preview",
            "raw_heatmap",
            "alternate_heatmap",
            "analysis_raw_heatmap",
            "plane_heatmap",
            "residual_heatmap",
        ):
            widget = getattr(self, widget_name, None)
            if widget is not None and hasattr(widget, "set_theme_palette"):
                widget.set_theme_palette(colors)

    def _create_about_dialog(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"About {APP_NAME}")
        dialog.resize(680, 520)

        layout = QVBoxLayout(dialog)

        heading = QLabel(
            f"<h2>{APP_NAME}</h2>"
            f"<p><b>Version:</b> {APP_VERSION}<br>"
            f"<b>Release date:</b> {APP_RELEASE_DATE}</p>"
        )
        heading.setTextFormat(Qt.TextFormat.RichText)
        heading.setWordWrap(True)
        layout.addWidget(heading)

        release_notes = QTextBrowser()
        release_notes.setReadOnly(True)
        release_notes.setOpenExternalLinks(True)
        notes_markdown = "\n".join(f"- {entry}" for entry in APP_RELEASE_NOTES)
        release_notes.setMarkdown(
            f"""## Release Notes

{notes_markdown}

## Current focus
- Baseline plane-fit recommendations remain primary.
- Physical-response advice remains heuristic and advisory.
- The interface is optimized for readable, scrollable workflow panels.
"""
        )
        layout.addWidget(release_notes, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog

    def show_about_dialog(self) -> None:
        self._create_about_dialog().exec()

    def _create_gui_settings_dialog(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle("GUI Settings")
        dialog.resize(620, 430)

        layout = QVBoxLayout(dialog)
        intro = QLabel("Adjust visual accessibility settings for the application interface.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        theme_combo = QComboBox()
        theme_combo.addItem("Light", "light")
        theme_combo.addItem("Dark", "dark")
        theme_combo.addItem("High contrast", "high_contrast")
        self._set_combo_data(theme_combo, self.gui_settings.theme)

        font_combo = QComboBox()
        for label, value in (
            ("Standard text (10 pt)", 10),
            ("Large text (12 pt)", 12),
            ("Extra large text (14 pt)", 14),
        ):
            font_combo.addItem(label, value)
        self._set_combo_data(font_combo, self.gui_settings.font_size_pt)

        form.addRow("Theme", theme_combo)
        form.addRow("Text size", font_combo)
        layout.addLayout(form)

        preview_group = QGroupBox("Theme Preview")
        preview_layout = QVBoxLayout(preview_group)
        preview_edit = QLineEdit("Editable field preview")
        preview_layout.addWidget(preview_edit)
        preview_table = QTableWidget(2, 3)
        preview_table.setHorizontalHeaderLabels(["Control", "State", "Sample"])
        preview_table.verticalHeader().setVisible(False)
        preview_table.setAlternatingRowColors(True)
        preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for row, values in enumerate(
            (
                ("Input", "Normal", "Readable foreground"),
                ("Warning", "Selected", "Distinct selection"),
            )
        ):
            for column, value in enumerate(values):
                preview_table.setItem(row, column, QTableWidgetItem(value))
        preview_table.selectRow(1)
        preview_table.setMinimumHeight(106)
        preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        preview_layout.addWidget(preview_table)
        preview_text = QTextEdit()
        preview_text.setReadOnly(True)
        preview_text.setMinimumHeight(82)
        preview_text.setPlainText(
            "Read-only panel preview\n"
            "Fields, buttons, menus, tables, selections, and diagnostics use explicit accessible colors."
        )
        preview_layout.addWidget(preview_text)
        preview_button_row = QHBoxLayout()
        preview_button_row.addWidget(QPushButton("Secondary"))
        primary_preview_button = QPushButton("Primary")
        primary_preview_button.setObjectName("PrimaryAction")
        preview_button_row.addWidget(primary_preview_button)
        preview_button_row.addStretch(1)
        preview_layout.addLayout(preview_button_row)
        layout.addWidget(preview_group, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.RestoreDefaults
            | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(buttons)

        def chosen_settings() -> GuiSettings:
            return GuiSettings(
                theme=str(theme_combo.currentData() or "light"),
                font_size_pt=int(font_combo.currentData() or 10),
            )

        def apply_settings() -> None:
            self.gui_settings = chosen_settings()
            _save_gui_settings(self.gui_settings)
            self._apply_visual_style()
            self.refresh_geometry_diagnostics()

        def restore_defaults() -> None:
            self._set_combo_data(theme_combo, "light")
            self._set_combo_data(font_combo, 10)
            apply_settings()

        def handle_button(button) -> None:
            standard = buttons.standardButton(button)
            if standard == QDialogButtonBox.StandardButton.Apply:
                apply_settings()
            elif standard == QDialogButtonBox.StandardButton.RestoreDefaults:
                restore_defaults()
            elif standard == QDialogButtonBox.StandardButton.Ok:
                apply_settings()
                dialog.accept()
            elif standard == QDialogButtonBox.StandardButton.Cancel:
                dialog.reject()

        buttons.clicked.connect(handle_button)
        return dialog

    def show_gui_settings_dialog(self) -> None:
        self._create_gui_settings_dialog().exec()

    def show_component_library_dialog(self) -> None:
        ComponentLibraryDialog(self, self).exec()

    def _create_user_guide_dialog(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{APP_NAME} User Guide")
        dialog.resize(960, 680)

        layout = QVBoxLayout(dialog)
        intro = QLabel("Use the contents list or the Back / Next buttons to move through the guide.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        contents_list = QListWidget()
        contents_list.setMinimumWidth(220)
        for title, _ in USER_GUIDE_PAGES:
            contents_list.addItem(title)
        splitter.addWidget(contents_list)

        page_container = QWidget()
        page_layout = QVBoxLayout(page_container)
        page_layout.setContentsMargins(8, 0, 0, 0)
        page_title = QLabel()
        page_title.setWordWrap(True)
        page_stack = QStackedWidget()

        for _, body in USER_GUIDE_PAGES:
            browser = QTextBrowser()
            browser.setReadOnly(True)
            browser.setOpenExternalLinks(True)
            browser.setMarkdown(body)
            page_stack.addWidget(browser)

        page_layout.addWidget(page_title)
        page_layout.addWidget(page_stack, 1)
        splitter.addWidget(page_container)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([240, 700])
        layout.addWidget(splitter, 1)

        nav_layout = QHBoxLayout()
        guide_page_status = QLabel()
        nav_layout.addWidget(guide_page_status)
        nav_layout.addStretch(1)
        back_button = QPushButton("Back")
        next_button = QPushButton("Next")
        nav_layout.addWidget(back_button)
        nav_layout.addWidget(next_button)
        layout.addLayout(nav_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def set_page(index: int) -> None:
            if not 0 <= index < len(USER_GUIDE_PAGES):
                return
            contents_list.blockSignals(True)
            contents_list.setCurrentRow(index)
            contents_list.blockSignals(False)
            title, _ = USER_GUIDE_PAGES[index]
            page_title.setText(f"<h3>{title}</h3>")
            page_stack.setCurrentIndex(index)
            guide_page_status.setText(f"Page {index + 1} of {len(USER_GUIDE_PAGES)}")
            back_button.setEnabled(index > 0)
            next_button.setEnabled(index < len(USER_GUIDE_PAGES) - 1)

        contents_list.currentRowChanged.connect(set_page)
        back_button.clicked.connect(lambda: set_page(page_stack.currentIndex() - 1))
        next_button.clicked.connect(lambda: set_page(page_stack.currentIndex() + 1))
        set_page(0)
        return dialog

    def show_user_guide_dialog(self) -> None:
        self._create_user_guide_dialog().exec()

    def _build_setup_tab(self) -> None:
        layout = self._create_scrolled_tab_layout(self.setup_tab)

        controls_group = QGroupBox("Setup")
        controls_layout = QGridLayout(controls_group)
        controls_layout.setHorizontalSpacing(16)
        controls_layout.setVerticalSpacing(10)
        controls_layout.setColumnStretch(1, 1)
        controls_layout.setColumnStretch(3, 1)
        self.bed_width_spin = _make_spinbox(1.0, 9999.0, 0.1, 235.0)
        self.bed_height_spin = _make_spinbox(1.0, 9999.0, 0.1, 235.0)
        self.pitch_spin = _make_spinbox(0.001, 100.0, 0.001, 0.5, decimals=4)
        self.hold_threshold_spin = _make_spinbox(0.0, 10.0, 0.001, 0.01, decimals=4)

        self.clockwise_combo = QComboBox()
        self.clockwise_combo.addItem("Clockwise raises the bed", "raise")
        self.clockwise_combo.addItem("Clockwise lowers the bed", "lower")
        self.viewpoint_combo = QComboBox()
        self.viewpoint_combo.addItem("Viewed from above", "above")
        self.viewpoint_combo.addItem("Viewed from below", "below")
        self.reference_combo = QComboBox()
        self.screw_y_reference_combo = QComboBox()
        self.screw_y_reference_combo.addItem("Screw Y measured from top edge", "top")
        self.screw_y_reference_combo.addItem("Screw Y measured from bottom edge", "bottom")
        self.display_front_edge_combo = QComboBox()
        self.display_front_edge_combo.addItem("Display front edge at top", "top")
        self.display_front_edge_combo.addItem("Display front edge at bottom", "bottom")

        controls_layout.addWidget(QLabel("Bed width (mm)"), 0, 0)
        controls_layout.addWidget(self.bed_width_spin, 0, 1)
        controls_layout.addWidget(QLabel("Bed height (mm)"), 0, 2)
        controls_layout.addWidget(self.bed_height_spin, 0, 3)
        controls_layout.addWidget(QLabel("Pitch (mm/turn)"), 1, 0)
        controls_layout.addWidget(self.pitch_spin, 1, 1)
        controls_layout.addWidget(QLabel("Clockwise effect"), 1, 2)
        controls_layout.addWidget(self.clockwise_combo, 1, 3)
        controls_layout.addWidget(QLabel("Viewpoint"), 2, 0)
        controls_layout.addWidget(self.viewpoint_combo, 2, 1)
        controls_layout.addWidget(QLabel("Reference screw"), 2, 2)
        controls_layout.addWidget(self.reference_combo, 2, 3)
        controls_layout.addWidget(QLabel("Screw Y reference"), 3, 0)
        controls_layout.addWidget(self.screw_y_reference_combo, 3, 1)
        controls_layout.addWidget(QLabel("Display front edge"), 3, 2)
        controls_layout.addWidget(self.display_front_edge_combo, 3, 3)
        controls_layout.addWidget(QLabel("Hold threshold (mm)"), 4, 0)
        controls_layout.addWidget(self.hold_threshold_spin, 4, 1)
        layout.addWidget(controls_group)

        screw_group = QGroupBox("Screws")
        screw_group.setMinimumHeight(280)
        screw_layout = QVBoxLayout(screw_group)
        screw_layout.setSpacing(10)
        screw_buttons = QHBoxLayout()
        self.add_screw_button = QPushButton("Add Screw")
        self.remove_screw_button = QPushButton("Remove Selected")
        screw_buttons.addWidget(self.add_screw_button)
        screw_buttons.addWidget(self.remove_screw_button)
        screw_buttons.addStretch(1)
        screw_layout.addLayout(screw_buttons)
        self.screw_table = QTableWidget(0, 3)
        self.screw_table.setMinimumHeight(210)
        self.screw_table.setMinimumWidth(760)
        self._configure_screw_table()
        self.screw_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.screw_table.itemChanged.connect(self._refresh_reference_combo)
        screw_layout.addWidget(self.screw_table)
        layout.addWidget(screw_group, 1)

        metadata_and_mechanics = QSplitter(Qt.Orientation.Horizontal)

        metadata_group = QGroupBox("Metadata")
        metadata_group.setMinimumWidth(640)
        metadata_layout = QVBoxLayout(metadata_group)
        metadata_layout.setSpacing(12)

        assembly_group = QGroupBox("Bed Assembly")
        assembly_form = QFormLayout(assembly_group)
        self.plate_material_editor = self._create_material_editor(
            [(entry.label, key) for key, entry in BED_PLATE_LIBRARY.items()],
            [
                ("Custom label", "label", None),
                ("Neighbour multiplier", "neighbor_multiplier", _make_spinbox(0.10, 3.0, 0.01, 1.0, decimals=2)),
                ("Decay multiplier", "decay_multiplier", _make_spinbox(0.10, 3.0, 0.01, 1.0, decimals=2)),
                ("Step multiplier", "step_multiplier", _make_spinbox(0.10, 3.0, 0.01, 1.0, decimals=2)),
                ("Absolute cap", "absolute_cap_turns", _make_optional_spinbox(0.0, 2.0, 0.001, 0.0, decimals=4)),
            ],
        )
        self.surface_material_editor = self._create_material_editor(
            [(entry.label, key) for key, entry in BED_SURFACE_LIBRARY.items()],
            [
                ("Custom label", "label", None),
                ("Neighbour multiplier", "neighbor_multiplier", _make_spinbox(0.10, 3.0, 0.01, 1.0, decimals=2)),
                ("Decay multiplier", "decay_multiplier", _make_spinbox(0.10, 3.0, 0.01, 1.0, decimals=2)),
                ("Step multiplier", "step_multiplier", _make_spinbox(0.10, 3.0, 0.01, 1.0, decimals=2)),
                ("Absolute cap", "absolute_cap_turns", _make_optional_spinbox(0.0, 2.0, 0.001, 0.0, decimals=4)),
            ],
        )
        assembly_form.addRow("Plate material", self._editor_widget(self.plate_material_editor))
        assembly_form.addRow("Surface material", self._editor_widget(self.surface_material_editor))
        metadata_layout.addWidget(assembly_group)

        support_group = QGroupBox("Support Stack")
        support_form = QFormLayout(support_group)
        self.mount_type_combo = QComboBox()
        self.mount_type_combo.addItems(["springs", "silicone", "rigid spacers", "shims", "other"])
        self.support_material_editor = self._create_material_editor(
            [],
            [
                ("Custom label", "label", None),
                ("Self multiplier", "self_multiplier", _make_spinbox(0.10, 3.0, 0.01, 1.0, decimals=2)),
                ("Neighbour multiplier", "neighbor_multiplier", _make_spinbox(0.10, 3.0, 0.01, 1.0, decimals=2)),
                ("Step multiplier", "step_multiplier", _make_spinbox(0.10, 3.0, 0.01, 1.0, decimals=2)),
                ("Self temp coeff", "self_temp_coeff", _make_spinbox(0.0, 1.0, 0.01, 0.0, decimals=2)),
                ("Neighbour temp coeff", "neighbor_temp_coeff", _make_spinbox(0.0, 1.0, 0.01, 0.0, decimals=2)),
                ("Step temp coeff", "step_temp_coeff", _make_spinbox(0.0, 1.0, 0.01, 0.0, decimals=2)),
                ("Absolute cap", "absolute_cap_turns", _make_optional_spinbox(0.0, 2.0, 0.001, 0.0, decimals=4)),
            ],
        )
        self.support_stack_height_spin = _make_spinbox(0.1, 100.0, 0.1, 15.0, decimals=1)
        support_form.addRow("Mount type", self.mount_type_combo)
        support_form.addRow("Support material", self._editor_widget(self.support_material_editor))
        support_form.addRow("Support stack height (mm)", self.support_stack_height_spin)
        metadata_layout.addWidget(support_group)

        fastener_group = QGroupBox("Fastener")
        fastener_form = QFormLayout(fastener_group)
        self.screw_material_editor = self._create_material_editor(
            [(entry.label, key) for key, entry in SCREW_LIBRARY.items()],
            [
                ("Custom label", "label", None),
                ("Self multiplier", "self_multiplier", _make_spinbox(0.10, 3.0, 0.01, 1.0, decimals=2)),
                ("Step multiplier", "step_multiplier", _make_spinbox(0.10, 3.0, 0.01, 1.0, decimals=2)),
                ("Step temp coeff", "step_temp_coeff", _make_spinbox(0.0, 1.0, 0.01, 0.0, decimals=2)),
                ("Absolute cap", "absolute_cap_turns", _make_optional_spinbox(0.0, 2.0, 0.001, 0.0, decimals=4)),
            ],
        )
        fastener_form.addRow("Screw material", self._editor_widget(self.screw_material_editor))
        metadata_layout.addWidget(fastener_group)

        thermal_group = QGroupBox("Thermal")
        thermal_form = QFormLayout(thermal_group)
        self.bed_temp_edit = QLineEdit()
        self.chamber_temp_edit = QLineEdit()
        thermal_form.addRow("Bed temperature (C)", self.bed_temp_edit)
        thermal_form.addRow("Chamber temperature (C)", self.chamber_temp_edit)
        metadata_layout.addWidget(thermal_group)

        mechanics_group = QGroupBox("Physical-Response Model")
        mechanics_form = QFormLayout(mechanics_group)
        self.mechanical_enabled_check = QCheckBox("Enable heuristic physical-response model")
        self.mechanical_enabled_check.setChecked(True)
        self.mechanical_preset_combo = QComboBox()
        for preset_name in PRESET_DEFAULTS:
            self.mechanical_preset_combo.addItem(preset_name.title(), preset_name)
        self.mechanical_override_check = QCheckBox("Use advanced override")
        self.self_gain_spin = _make_spinbox(0.001, 5.0, 0.01, 0.85, decimals=3)
        self.neighbor_gain_spin = _make_spinbox(0.0, 5.0, 0.01, 0.12, decimals=3)
        self.decay_length_spin = _make_spinbox(1.0, 2000.0, 1.0, 140.0)
        self.max_step_spin = _make_spinbox(0.001, 2.0, 0.001, 0.0625, decimals=4)
        self.regularization_spin = _make_spinbox(0.000001, 1.0, 0.000001, 0.00001, decimals=6)
        mechanics_form.addRow(self.mechanical_enabled_check)
        mechanics_form.addRow("Preset", self.mechanical_preset_combo)
        mechanics_form.addRow(self.mechanical_override_check)
        mechanics_form.addRow("Self gain", self.self_gain_spin)
        mechanics_form.addRow("Neighbour gain", self.neighbor_gain_spin)
        mechanics_form.addRow("Decay length (mm)", self.decay_length_spin)
        mechanics_form.addRow("Max step (turns)", self.max_step_spin)
        mechanics_form.addRow("Regularization", self.regularization_spin)
        self.mechanical_effective_text = QTextEdit()
        self._configure_readonly_text(self.mechanical_effective_text, minimum_height=220)
        mechanics_form.addRow("Effective model", self.mechanical_effective_text)
        mechanics_group.setMinimumWidth(500)
        metadata_and_mechanics.addWidget(metadata_group)
        metadata_and_mechanics.addWidget(mechanics_group)
        metadata_and_mechanics.setStretchFactor(0, 3)
        metadata_and_mechanics.setStretchFactor(1, 2)
        self._configure_splitter(metadata_and_mechanics, [900, 560])

        layout.addWidget(metadata_and_mechanics)

        self.diagnostics_group = QGroupBox("Layout Diagnostics")
        diagnostics_layout = QVBoxLayout(self.diagnostics_group)
        diagnostics_layout.setSpacing(10)
        diagnostics_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.layout_preview = HeatmapWidget()
        self.layout_preview.setMinimumSize(420, 360)
        diagnostics_splitter.addWidget(self.layout_preview)

        diagnostics_right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.geometry_table = QTableWidget(0, 7)
        self.geometry_table.setHorizontalHeaderLabels(
            ["Screw", "X internal", "Y internal", "Quadrant", "Bed", "Probe", "Notes"]
        )
        self.geometry_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._configure_data_table(self.geometry_table, stretch_column=6)
        self.geometry_table.setMinimumHeight(240)
        self.geometry_status_text = QTextEdit()
        self._configure_readonly_text(self.geometry_status_text, minimum_height=170)
        diagnostics_right_splitter.addWidget(self.geometry_table)
        diagnostics_right_splitter.addWidget(self.geometry_status_text)
        self._configure_splitter(diagnostics_right_splitter, [300, 190])
        diagnostics_splitter.addWidget(diagnostics_right_splitter)
        self._configure_splitter(diagnostics_splitter, [760, 620])
        diagnostics_layout.addWidget(diagnostics_splitter, 1)
        layout.addWidget(self.diagnostics_group, 1)
        layout.addStretch(1)

        self.add_screw_button.clicked.connect(self.add_screw_row)
        self.remove_screw_button.clicked.connect(self.remove_selected_screws)
        self.screw_table.itemChanged.connect(self.refresh_geometry_diagnostics)
        self.bed_width_spin.valueChanged.connect(self._handle_bed_size_changed)
        self.bed_height_spin.valueChanged.connect(self._handle_bed_size_changed)
        self.screw_y_reference_combo.currentIndexChanged.connect(self._update_screw_table_headers)
        self.screw_y_reference_combo.currentIndexChanged.connect(self.refresh_geometry_diagnostics)
        self.display_front_edge_combo.currentIndexChanged.connect(self.refresh_geometry_diagnostics)
        self.mount_type_combo.currentTextChanged.connect(self._sync_preset_from_mount_type)
        self.mount_type_combo.currentTextChanged.connect(self.refresh_geometry_diagnostics)
        self.mount_type_combo.currentTextChanged.connect(self._sync_support_material_options)
        self.bed_temp_edit.textChanged.connect(self.refresh_geometry_diagnostics)
        self.chamber_temp_edit.textChanged.connect(self.refresh_geometry_diagnostics)
        self.mechanical_enabled_check.toggled.connect(self.refresh_geometry_diagnostics)
        self.mechanical_preset_combo.currentIndexChanged.connect(self._sync_mechanical_controls)
        self.mechanical_preset_combo.currentIndexChanged.connect(self.refresh_geometry_diagnostics)
        self.mechanical_override_check.toggled.connect(self._sync_mechanical_controls)
        self.mechanical_override_check.toggled.connect(self.refresh_geometry_diagnostics)
        for spinbox in (
            self.self_gain_spin,
            self.neighbor_gain_spin,
            self.decay_length_spin,
            self.max_step_spin,
            self.regularization_spin,
        ):
            spinbox.valueChanged.connect(self.refresh_geometry_diagnostics)
        self.support_stack_height_spin.valueChanged.connect(self.refresh_geometry_diagnostics)
        for editor in (
            self.plate_material_editor,
            self.surface_material_editor,
            self.support_material_editor,
            self.screw_material_editor,
        ):
            editor.combo.currentIndexChanged.connect(self.refresh_geometry_diagnostics)
            editor.custom_check.toggled.connect(self.refresh_geometry_diagnostics)
            editor.custom_label_edit.textChanged.connect(self.refresh_geometry_diagnostics)
            for field in editor.fields.values():
                field.valueChanged.connect(self.refresh_geometry_diagnostics)
        self._sync_support_material_options(self.mount_type_combo.currentText())

    def _build_mesh_tab(self) -> None:
        layout = QVBoxLayout(self.mesh_tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        bounds_group = QGroupBox("Mesh Bounds")
        bounds_layout = QGridLayout(bounds_group)
        bounds_layout.setHorizontalSpacing(14)
        bounds_layout.setVerticalSpacing(8)
        bounds_layout.setColumnStretch(1, 1)
        bounds_layout.setColumnStretch(3, 1)
        self.x_min_spin = _make_spinbox(-1000.0, 1000.0, 0.1, 0.0)
        self.x_max_spin = _make_spinbox(-1000.0, 1000.0, 0.1, 235.0)
        self.y_min_spin = _make_spinbox(-1000.0, 1000.0, 0.1, 0.0)
        self.y_max_spin = _make_spinbox(-1000.0, 1000.0, 0.1, 235.0)
        self.row_order_combo = QComboBox()
        self.row_order_combo.addItem("Top row = y_max", True)
        self.row_order_combo.addItem("Top row = y_min", False)
        self.import_csv_button = QPushButton("Import CSV")
        self.use_bed_bounds_button = QPushButton("Use Bed Bounds")
        self.use_bed_bounds_button.setToolTip("Set mesh bounds to x 0..bed width and y 0..bed height, then keep following bed size.")
        self.mesh_bounds_status_label = QLabel()
        self.mesh_bounds_status_label.setObjectName("MeshBoundsStatus")
        self.mesh_bounds_status_label.setWordWrap(True)

        bounds_layout.addWidget(QLabel("x_min (mm)"), 0, 0)
        bounds_layout.addWidget(self.x_min_spin, 0, 1)
        bounds_layout.addWidget(QLabel("x_max (mm)"), 0, 2)
        bounds_layout.addWidget(self.x_max_spin, 0, 3)
        bounds_layout.addWidget(QLabel("y_min (mm)"), 1, 0)
        bounds_layout.addWidget(self.y_min_spin, 1, 1)
        bounds_layout.addWidget(QLabel("y_max (mm)"), 1, 2)
        bounds_layout.addWidget(self.y_max_spin, 1, 3)
        bounds_layout.addWidget(QLabel("Row order"), 2, 0)
        bounds_layout.addWidget(self.row_order_combo, 2, 1)
        bounds_layout.addWidget(self.import_csv_button, 2, 2)
        bounds_layout.addWidget(self.use_bed_bounds_button, 2, 3)
        bounds_layout.addWidget(self.mesh_bounds_status_label, 3, 0, 1, 4)
        layout.addWidget(bounds_group)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.mesh_text_edit = QTextEdit()
        self.mesh_text_edit.setPlaceholderText("Paste CSV, TSV, or whitespace-delimited numeric mesh values here.")
        self.mesh_text_edit.setMinimumWidth(380)
        preview_container = QWidget()
        preview_container.setMinimumWidth(620)
        preview_layout = QHBoxLayout(preview_container)

        active_group = QGroupBox("Active row-order interpretation")
        active_layout = QVBoxLayout(active_group)
        self.raw_heatmap = MeshViewPanel("Active mesh")
        self.raw_heatmap.setMinimumSize(280, 280)
        active_layout.addWidget(self.raw_heatmap)

        alternate_group = QGroupBox("Alternate row-order preview")
        alternate_layout = QVBoxLayout(alternate_group)
        self.alternate_heatmap = MeshViewPanel("Alternate row order")
        self.alternate_heatmap.setMinimumSize(280, 280)
        alternate_layout.addWidget(self.alternate_heatmap)

        preview_layout.addWidget(active_group, 1)
        preview_layout.addWidget(alternate_group, 1)
        splitter.addWidget(self.mesh_text_edit)
        splitter.addWidget(preview_container)
        self._configure_splitter(splitter, [520, 840])
        layout.addWidget(splitter, 1)

        self.import_csv_button.clicked.connect(self.import_csv)
        self.use_bed_bounds_button.clicked.connect(self._use_bed_bounds)
        for spinbox in (self.x_min_spin, self.x_max_spin, self.y_min_spin, self.y_max_spin):
            spinbox.valueChanged.connect(self._mark_mesh_bounds_manual)
        self.x_min_spin.valueChanged.connect(self.refresh_geometry_diagnostics)
        self.x_max_spin.valueChanged.connect(self.refresh_geometry_diagnostics)
        self.y_min_spin.valueChanged.connect(self.refresh_geometry_diagnostics)
        self.y_max_spin.valueChanged.connect(self.refresh_geometry_diagnostics)
        self.row_order_combo.currentIndexChanged.connect(self.refresh_geometry_diagnostics)
        self.row_order_combo.currentIndexChanged.connect(self._update_calibration_mesh_context)
        self.mesh_text_edit.textChanged.connect(self.refresh_geometry_diagnostics)
        self._update_mesh_bounds_status()

    def _build_analysis_tab(self) -> None:
        layout = self._create_scrolled_tab_layout(self.analysis_tab)
        heatmap_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.analysis_raw_heatmap = MeshViewPanel("Raw mesh")
        self.plane_heatmap = MeshViewPanel("Plane-only tilt")
        self.residual_heatmap = MeshViewPanel("Residual warp")

        for widget in (
            self.analysis_raw_heatmap,
            self.plane_heatmap,
            self.residual_heatmap,
        ):
            panel = QWidget()
            panel_layout = QVBoxLayout(panel)
            widget.setMinimumSize(260, 260)
            panel_layout.addWidget(widget)
            heatmap_splitter.addWidget(panel)
        heatmap_splitter.setMinimumHeight(340)
        self._configure_splitter(heatmap_splitter, [420, 420, 420])
        layout.addWidget(heatmap_splitter, 2)

        summary_tabs = QTabWidget()
        self.stats_text = QTextEdit()
        self._configure_readonly_text(self.stats_text, minimum_height=280)
        self.baseline_model_text = QTextEdit()
        self._configure_readonly_text(self.baseline_model_text, minimum_height=280)
        self.physical_model_text = QTextEdit()
        self._configure_readonly_text(self.physical_model_text, minimum_height=280)
        self.warning_text = QTextEdit()
        self._configure_readonly_text(self.warning_text, minimum_height=240)
        for title, widget in (
            ("Analysis summary", self.stats_text),
            ("Baseline recommendation", self.baseline_model_text),
            ("Physical-response model (heuristic / advisory)", self.physical_model_text),
            ("Warnings", self.warning_text),
        ):
            panel = QWidget()
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(8, 8, 8, 8)
            panel_layout.addWidget(widget)
            summary_tabs.addTab(panel, title)
        layout.addWidget(summary_tabs, 1)

    def _build_results_tab(self) -> None:
        layout = QVBoxLayout(self.results_tab)
        button_layout = QHBoxLayout()
        self.export_csv_button = QPushButton("Export Results CSV")
        self.copy_summary_button = QPushButton("Copy Summary")
        button_layout.addStretch(1)
        button_layout.addWidget(self.export_csv_button)
        button_layout.addWidget(self.copy_summary_button)
        layout.addLayout(button_layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(12)

        results_tabs = QTabWidget()
        self.baseline_results_table = self._create_results_table()
        self.physical_results_table = self._create_results_table()
        for title, table, plan_target in (
            ("Baseline", self.baseline_results_table, "baseline"),
            ("Physical (heuristic / advisory)", self.physical_results_table, "physical"),
        ):
            panel = QWidget()
            panel_splitter = QSplitter(Qt.Orientation.Vertical)
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(0, 0, 0, 0)
            plan_text = QTextEdit()
            self._configure_readonly_text(plan_text, minimum_height=180)
            if plan_target == "baseline":
                self.baseline_turn_plan_text = plan_text
            else:
                self.physical_turn_plan_text = plan_text
            panel_splitter.addWidget(table)
            panel_splitter.addWidget(plan_text)
            self._configure_splitter(panel_splitter, [480, 220])
            panel_layout.addWidget(panel_splitter)
            results_tabs.addTab(panel, title)
        content_layout.addWidget(results_tabs, 2)

        summary_group = QGroupBox("Combined summary")
        summary_layout = QVBoxLayout(summary_group)
        self.summary_text = QTextEdit()
        self._configure_readonly_text(self.summary_text, minimum_height=220)
        summary_layout.addWidget(self.summary_text)
        content_layout.addWidget(summary_group, 1)

        scroll_area.setWidget(content)
        layout.addWidget(scroll_area, 1)

        self.export_csv_button.clicked.connect(self.export_results_csv)
        self.copy_summary_button.clicked.connect(self.copy_summary)

    def _build_calibration_tab(self) -> None:
        build_calibration_tab(self)

    def _create_results_table(self) -> QTableWidget:
        table = QTableWidget(0, 11)
        table.setHorizontalHeaderLabels(
            [
                "Screw",
                "X (mm)",
                "Y (mm)",
                "Plane Z (mm)",
                "Command delta (mm)",
                "Expected achieved (mm)",
                "Action",
                "Direction",
                "Exact turns",
                "Rounded turns",
                "Notes",
            ]
        )
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._configure_data_table(table, stretch_column=10)
        return table

    def _create_scrolled_tab_layout(self, tab: QWidget) -> QVBoxLayout:
        outer_layout = QVBoxLayout(tab)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        content = QWidget()
        content.setMinimumWidth(1160)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        scroll_area.setWidget(content)
        outer_layout.addWidget(scroll_area)
        return layout

    def _configure_splitter(self, splitter: QSplitter, sizes: list[int]) -> None:
        splitter.setChildrenCollapsible(False)
        splitter.setOpaqueResize(False)
        splitter.setHandleWidth(8)
        for index in range(splitter.count()):
            splitter.setCollapsible(index, False)
        splitter.setSizes(sizes)

    def _configure_readonly_text(self, widget: QTextEdit, minimum_height: int = 180) -> None:
        widget.setReadOnly(True)
        widget.setMinimumHeight(minimum_height)
        widget.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)

    def _configure_data_table(self, table: QTableWidget, stretch_column: int | None = None) -> None:
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        for column in range(table.columnCount()):
            mode = QHeaderView.ResizeMode.Stretch if column == stretch_column else QHeaderView.ResizeMode.ResizeToContents
            header.setSectionResizeMode(column, mode)

    def _configure_screw_table(self) -> None:
        self.screw_table.setAlternatingRowColors(True)
        self.screw_table.setWordWrap(False)
        self.screw_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.screw_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.screw_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.screw_table.verticalHeader().setVisible(False)
        header = self.screw_table.horizontalHeader()
        header.setMinimumSectionSize(130)
        for column in range(self.screw_table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        self.screw_table.setColumnWidth(0, 280)
        self.screw_table.setColumnWidth(1, 180)
        self.screw_table.setColumnWidth(2, 260)

    def _handle_bed_size_changed(self, *_args) -> None:
        if self._mesh_bounds_auto_linked and not self._populating_project:
            self._sync_mesh_bounds_to_bed()
        self.refresh_geometry_diagnostics()

    def _mark_mesh_bounds_manual(self, *_args) -> None:
        if self._syncing_mesh_bounds or self._populating_project:
            return
        self._mesh_bounds_auto_linked = False
        self._update_mesh_bounds_status()

    def _use_bed_bounds(self, *_args) -> None:
        self._mesh_bounds_auto_linked = True
        self._sync_mesh_bounds_to_bed()
        self.refresh_geometry_diagnostics()

    def _sync_mesh_bounds_to_bed(self) -> None:
        self._set_mesh_bounds(
            0.0,
            self.bed_width_spin.value(),
            0.0,
            self.bed_height_spin.value(),
        )
        self._update_mesh_bounds_status()

    def _set_mesh_bounds(self, x_min: float, x_max: float, y_min: float, y_max: float) -> None:
        self._syncing_mesh_bounds = True
        blockers = [
            QSignalBlocker(self.x_min_spin),
            QSignalBlocker(self.x_max_spin),
            QSignalBlocker(self.y_min_spin),
            QSignalBlocker(self.y_max_spin),
        ]
        try:
            self.x_min_spin.setValue(x_min)
            self.x_max_spin.setValue(x_max)
            self.y_min_spin.setValue(y_min)
            self.y_max_spin.setValue(y_max)
        finally:
            del blockers
            self._syncing_mesh_bounds = False

    def _mesh_bounds_match_bed(self) -> bool:
        return (
            abs(self.x_min_spin.value()) < 0.000001
            and abs(self.y_min_spin.value()) < 0.000001
            and abs(self.x_max_spin.value() - self.bed_width_spin.value()) < 0.000001
            and abs(self.y_max_spin.value() - self.bed_height_spin.value()) < 0.000001
        )

    def _update_mesh_bounds_status(self) -> None:
        if not hasattr(self, "mesh_bounds_status_label"):
            return
        if self._mesh_bounds_auto_linked:
            self.mesh_bounds_status_label.setText(
                "Mesh bounds follow bed size. Use manual edits only when the probed mesh covers less than the full bed."
            )
            self.mesh_bounds_status_label.setProperty("state", "linked")
        else:
            self.mesh_bounds_status_label.setText(
                "Mesh bounds manually set. Screws outside these probed bounds still use plane correction, but local residual notes are limited."
            )
            self.mesh_bounds_status_label.setProperty("state", "manual")
        self.mesh_bounds_status_label.style().unpolish(self.mesh_bounds_status_label)
        self.mesh_bounds_status_label.style().polish(self.mesh_bounds_status_label)
        self._update_calibration_mesh_context()

    def _add_default_screws(self) -> None:
        for name, left_mm, y_measure_mm in (
            ("Front Left", 30.0, 30.0),
            ("Front Right", 205.0, 30.0),
            ("Rear Left", 30.0, 205.0),
            ("Rear Right", 205.0, 205.0),
        ):
            self.add_screw_row(name, left_mm, y_measure_mm)

    def add_screw_row(self, name: str = "", left_mm: float = 0.0, y_measure_mm: float = 0.0) -> None:
        row = self.screw_table.rowCount()
        self.screw_table.insertRow(row)
        self.screw_table.setItem(row, 0, QTableWidgetItem(name))
        self.screw_table.setItem(row, 1, QTableWidgetItem(f"{left_mm:.3f}"))
        self.screw_table.setItem(row, 2, QTableWidgetItem(f"{y_measure_mm:.3f}"))
        self._refresh_reference_combo()
        self._refresh_calibration_turn_table()
        self.refresh_geometry_diagnostics()

    def remove_selected_screws(self) -> None:
        selected_rows = sorted({index.row() for index in self.screw_table.selectedIndexes()}, reverse=True)
        for row in selected_rows:
            self.screw_table.removeRow(row)
        self._refresh_reference_combo()
        self._refresh_calibration_turn_table()
        self.refresh_geometry_diagnostics()

    def _refresh_reference_combo(self, *_args) -> None:
        current_name = self.reference_combo.currentData()
        names = []
        for row in range(self.screw_table.rowCount()):
            item = self.screw_table.item(row, 0)
            name = item.text().strip() if item is not None else ""
            if name:
                names.append(name)

        self.reference_combo.blockSignals(True)
        self.reference_combo.clear()
        for name in names:
            self.reference_combo.addItem(name, name)
        if current_name in names:
            self.reference_combo.setCurrentIndex(names.index(current_name))
        elif names:
            self.reference_combo.setCurrentIndex(0)
        self.reference_combo.blockSignals(False)

    def _update_screw_table_headers(self, *_args) -> None:
        reference = str(self.screw_y_reference_combo.currentData())
        headers = [
            ("Name", "Screw name used in the result tables and reference selector."),
            ("Left X (mm)", "Measured distance from the left bed edge."),
            (f"Y from {reference} (mm)", f"Measured Y distance from the {reference} bed edge."),
        ]
        for column, (label, tooltip) in enumerate(headers):
            item = QTableWidgetItem(label)
            item.setToolTip(tooltip)
            self.screw_table.setHorizontalHeaderItem(column, item)

    def _sync_preset_from_mount_type(self, *_args) -> None:
        preset_name = infer_preset_name(self.mount_type_combo.currentText())
        self._set_combo_data(self.mechanical_preset_combo, preset_name)
        self._sync_mechanical_controls()

    def _sync_mechanical_controls(self) -> None:
        preset_name = str(self.mechanical_preset_combo.currentData() or "other")
        preset = PRESET_DEFAULTS.get(preset_name, PRESET_DEFAULTS["other"])
        enabled = self.mechanical_override_check.isChecked()
        for spinbox in (
            self.self_gain_spin,
            self.neighbor_gain_spin,
            self.decay_length_spin,
            self.max_step_spin,
            self.regularization_spin,
        ):
            spinbox.setEnabled(enabled)
        if not enabled:
            self.self_gain_spin.setValue(preset.self_gain)
            self.neighbor_gain_spin.setValue(preset.neighbor_gain)
            self.decay_length_spin.setValue(preset.decay_length_mm)
            self.max_step_spin.setValue(preset.max_step_turns)
            self.regularization_spin.setValue(preset.regularization_lambda)

    def _create_material_editor(
        self,
        options: list[tuple[str, str]],
        field_specs: list[tuple[str, str, QWidget | None]],
    ) -> MaterialEditorControls:
        combo = QComboBox()
        for label, key in options:
            combo.addItem(label, key)

        custom_check = QCheckBox("Custom override")
        custom_label_edit = QLineEdit()
        custom_widget = QWidget()
        custom_layout = QFormLayout(custom_widget)
        fields: dict[str, QDoubleSpinBox] = {}
        for row_label, field_name, widget in field_specs:
            if field_name == "label":
                custom_layout.addRow(row_label, custom_label_edit)
            elif isinstance(widget, QDoubleSpinBox):
                custom_layout.addRow(row_label, widget)
                fields[field_name] = widget
        custom_widget.setVisible(False)
        custom_check.toggled.connect(custom_widget.setVisible)
        return MaterialEditorControls(combo, custom_check, custom_label_edit, custom_widget, fields)

    def _editor_widget(self, editor: MaterialEditorControls) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(editor.combo, 1)
        header_layout.addWidget(editor.custom_check)
        layout.addLayout(header_layout)
        layout.addWidget(editor.custom_widget)
        return container

    def _sync_support_material_options(self, mount_type: str) -> None:
        current_key = str(self.support_material_editor.combo.currentData() or "")
        options = support_options_for_mount(mount_type)
        self.support_material_editor.combo.blockSignals(True)
        self.support_material_editor.combo.clear()
        for label, key in options:
            self.support_material_editor.combo.addItem(label, key)
        available_keys = [key for _, key in options]
        target_key = current_key if current_key in available_keys else default_support_assembly(mount_type).support_material.library_key
        self._set_combo_data(self.support_material_editor.combo, target_key)
        self.support_material_editor.combo.blockSignals(False)
        if not self._populating_project:
            self.support_stack_height_spin.setValue(default_support_assembly(mount_type).support_stack_height_mm)

    def _collect_material_choice(self, editor: MaterialEditorControls, category: str) -> MaterialChoice:
        library_key = str(editor.combo.currentData() or "other")
        label = editor.combo.currentText()
        if not editor.custom_check.isChecked():
            return MaterialChoice(kind="library", library_key=library_key, label=label)

        custom_label = editor.custom_label_edit.text().strip() or label
        custom_response = MaterialResponseOverride(
            self_multiplier=editor.fields["self_multiplier"].value() if "self_multiplier" in editor.fields else 1.0,
            neighbor_multiplier=editor.fields["neighbor_multiplier"].value() if "neighbor_multiplier" in editor.fields else 1.0,
            decay_multiplier=editor.fields["decay_multiplier"].value() if "decay_multiplier" in editor.fields else 1.0,
            step_multiplier=editor.fields["step_multiplier"].value() if "step_multiplier" in editor.fields else 1.0,
            self_temp_coeff=editor.fields["self_temp_coeff"].value() if "self_temp_coeff" in editor.fields else 0.0,
            neighbor_temp_coeff=editor.fields["neighbor_temp_coeff"].value() if "neighbor_temp_coeff" in editor.fields else 0.0,
            step_temp_coeff=editor.fields["step_temp_coeff"].value() if "step_temp_coeff" in editor.fields else 0.0,
            absolute_cap_turns=_optional_spinbox_value(editor.fields.get("absolute_cap_turns")),
        )
        return MaterialChoice(
            kind="custom",
            library_key=library_key,
            label=custom_label,
            custom_response=custom_response,
        )

    def _populate_material_choice(self, editor: MaterialEditorControls, choice: MaterialChoice) -> None:
        self._set_combo_data(editor.combo, choice.library_key)
        editor.custom_check.setChecked(choice.kind == "custom")
        editor.custom_widget.setVisible(choice.kind == "custom")
        editor.custom_label_edit.setText(choice.label)
        custom = choice.custom_response or MaterialResponseOverride()
        for field_name, value in (
            ("self_multiplier", custom.self_multiplier),
            ("neighbor_multiplier", custom.neighbor_multiplier),
            ("decay_multiplier", custom.decay_multiplier),
            ("step_multiplier", custom.step_multiplier),
            ("self_temp_coeff", custom.self_temp_coeff),
            ("neighbor_temp_coeff", custom.neighbor_temp_coeff),
            ("step_temp_coeff", custom.step_temp_coeff),
        ):
            if field_name in editor.fields:
                editor.fields[field_name].setValue(value)
        if "absolute_cap_turns" in editor.fields:
            _set_optional_spinbox(editor.fields["absolute_cap_turns"], custom.absolute_cap_turns)

    def _render_mechanical_context(self, project: ProjectData, geometry: GeometryReport | None) -> None:
        if geometry is None:
            self.mechanical_effective_text.clear()
            return
        screw_positions = [(status.name, status.x_mm, status.y_mm) for status in geometry.screw_statuses]
        try:
            _, effective_model, confidence, warnings = resolve_effective_mechanical_model(
                project.mechanical_model,
                project.metadata,
                screw_positions,
            )
        except ValueError as exc:
            self.mechanical_effective_text.setPlainText(str(exc))
            return

        lines = [
            f"Self gain: {effective_model.self_gain:.3f}",
            f"Neighbour gain: {effective_model.neighbor_gain:.3f}",
            f"Decay length: {effective_model.decay_length_mm:.1f} mm",
            f"Max step: {effective_model.max_step_turns:.4f} turns",
            f"Thermal index: {effective_model.thermal_index:.2f}",
            f"Confidence: {confidence.level} ({confidence.score:.2f})",
        ]
        if confidence.reasons:
            lines.append("")
            lines.append("Confidence drivers:")
            lines.extend(f"- {reason}" for reason in confidence.reasons)
        if warnings:
            lines.append("")
            lines.append("Material warnings:")
            lines.extend(f"- {warning}" for warning in warnings[:6])
        self.mechanical_effective_text.setPlainText("\n".join(lines))

    def import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import CSV Mesh", "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            values = load_csv_grid(path)
        except MeshInputError as exc:
            self._show_error("Mesh Import Error", str(exc))
            return
        self._set_mesh_text_from_values(values)
        self.preview_mesh()

    def refresh_geometry_diagnostics(self, *_args) -> None:
        try:
            project = self.collect_project_data(require_mesh=False)
        except (AnalysisError, MeshInputError) as exc:
            self.current_geometry_report = None
            self.geometry_table.setRowCount(0)
            self.geometry_status_text.setPlainText(str(exc))
            self.mechanical_effective_text.setPlainText(str(exc))
            self._render_best_effort_layout()
            self.raw_heatmap.clear()
            self.alternate_heatmap.clear()
            return

        geometry = inspect_project_geometry(project)
        self.current_geometry_report = geometry
        screws = [(status.name, status.x_mm, status.y_mm) for status in geometry.screw_statuses]
        probe_bounds = None
        if project.mesh is not None:
            probe_bounds = (
                project.mesh.x_min_mm,
                project.mesh.x_max_mm,
                project.mesh.y_min_mm,
                project.mesh.y_max_mm,
            )
        self.layout_preview.set_layout(
            project.bed.width_mm,
            project.bed.height_mm,
            screws,
            geometry.screw_statuses,
            probe_bounds=probe_bounds,
            display_front_edge=project.coordinate_convention.display_front_edge,
        )
        self._render_geometry_report(geometry)
        self._render_mechanical_context(project, geometry)
        self._render_mesh_previews(project, geometry)

    def preview_mesh(self) -> None:
        try:
            project = self.collect_project_data(require_mesh=True)
            geometry = inspect_project_geometry(project)
            if geometry.blocking_errors:
                raise AnalysisError("\n".join(geometry.blocking_errors))
        except (AnalysisError, MeshInputError) as exc:
            self._show_error("Preview Error", str(exc))
            return

        self.current_project = project
        self.current_geometry_report = geometry
        self._render_mesh_previews(project, geometry)
        self.statusBar().showMessage("Mesh preview updated.", 4000)

    def run_analysis(self) -> None:
        try:
            project = self.collect_project_data(require_mesh=True)
            geometry = inspect_project_geometry(project)
            if geometry.blocking_errors:
                raise AnalysisError("\n".join(geometry.blocking_errors))
            result = analyse_project(project)
        except (AnalysisError, MeshInputError) as exc:
            self._show_error("Analysis Error", str(exc))
            return

        self.current_project = project
        self.current_geometry_report = geometry
        self.current_analysis = result
        screws = [(status.name, status.x_mm, status.y_mm) for status in geometry.screw_statuses]
        display_front_edge = project.coordinate_convention.display_front_edge
        self.analysis_raw_heatmap.set_surface(
            project.bed.width_mm,
            project.bed.height_mm,
            project.mesh,
            project.mesh.z_values,
            screws,
            geometry.screw_statuses,
            display_front_edge=display_front_edge,
        )
        self.plane_heatmap.set_surface(
            project.bed.width_mm,
            project.bed.height_mm,
            project.mesh,
            result.plane_surface,
            screws,
            geometry.screw_statuses,
            display_front_edge=display_front_edge,
        )
        self.residual_heatmap.set_surface(
            project.bed.width_mm,
            project.bed.height_mm,
            project.mesh,
            result.residual_surface,
            screws,
            geometry.screw_statuses,
            display_front_edge=display_front_edge,
        )
        self._render_analysis(result)
        self._render_results(result)
        self.tabs.setCurrentWidget(self.analysis_tab)
        self.statusBar().showMessage("Analysis complete.", 4000)

    def collect_project_data(self, require_mesh: bool) -> ProjectData:
        screws = self._collect_screws()
        reference_name = self.reference_combo.currentData()
        if not reference_name and screws:
            reference_name = screws[0].name

        mount_type = normalize_mount_type(self.mount_type_combo.currentText().strip())
        metadata = EnvironmentMetadata(
            bed_assembly=BedAssemblyConfig(
                plate_material=self._collect_material_choice(self.plate_material_editor, "plate"),
                surface_material=self._collect_material_choice(self.surface_material_editor, "surface"),
            ),
            support_assembly=SupportAssemblyConfig(
                mount_type=mount_type,
                support_material=self._collect_material_choice(self.support_material_editor, "support"),
                support_stack_height_mm=self.support_stack_height_spin.value(),
            ),
            fastener=FastenerConfig(
                screw_material=self._collect_material_choice(self.screw_material_editor, "screw"),
            ),
            bed_temperature_c=_parse_optional_float(self.bed_temp_edit.text()),
            chamber_temperature_c=_parse_optional_float(self.chamber_temp_edit.text()),
        )
        mechanical_model = self._collect_mechanical_model(metadata)
        mesh = self._collect_mesh(required=require_mesh)

        return ProjectData(
            bed=BedConfig(
                width_mm=self.bed_width_spin.value(),
                height_mm=self.bed_height_spin.value(),
            ),
            screws=screws,
            turn_config=ScrewTurnConfig(
                pitch_mm_per_turn=self.pitch_spin.value(),
                clockwise_effect=str(self.clockwise_combo.currentData()),
                viewpoint=str(self.viewpoint_combo.currentData()),
                hold_threshold_mm=self.hold_threshold_spin.value(),
            ),
            reference_screw_name=str(reference_name),
            coordinate_convention=CoordinateConvention(
                screw_y_reference_edge=str(self.screw_y_reference_combo.currentData()),
                display_front_edge=str(self.display_front_edge_combo.currentData()),
            ),
            mechanical_model=mechanical_model,
            metadata=metadata,
            mesh=mesh,
            calibration_trials=list(self.calibration_trials),
        )

    def _collect_screws(self) -> list[ScrewMeasurement]:
        screws: list[ScrewMeasurement] = []
        for row in range(self.screw_table.rowCount()):
            name_item = self.screw_table.item(row, 0)
            left_item = self.screw_table.item(row, 1)
            y_item = self.screw_table.item(row, 2)
            values = [
                name_item.text().strip() if name_item is not None else "",
                left_item.text().strip() if left_item is not None else "",
                y_item.text().strip() if y_item is not None else "",
            ]
            if not any(values):
                continue
            if not all(values):
                raise AnalysisError("Each screw row must include a name, left value, and Y value.")
            try:
                screws.append(
                    ScrewMeasurement(
                        name=values[0],
                        left_mm=float(values[1]),
                        y_measure_mm=float(values[2]),
                    )
                )
            except ValueError as exc:
                raise AnalysisError(f"Invalid numeric value in screw row {row + 1}.") from exc
        return screws

    def _collect_mechanical_model(self, metadata: EnvironmentMetadata) -> MechanicalModelConfig:
        preset_name = str(self.mechanical_preset_combo.currentData() or "other")
        if self.mechanical_override_check.isChecked():
            config = MechanicalModelConfig(
                enabled=self.mechanical_enabled_check.isChecked(),
                preset_name=preset_name,
                self_gain=self.self_gain_spin.value(),
                neighbor_gain=self.neighbor_gain_spin.value(),
                decay_length_mm=self.decay_length_spin.value(),
                max_step_turns=self.max_step_spin.value(),
                regularization_lambda=self.regularization_spin.value(),
                use_advanced_override=True,
            )
        else:
            preset = PRESET_DEFAULTS.get(preset_name, PRESET_DEFAULTS["other"])
            config = replace(
                preset,
                enabled=self.mechanical_enabled_check.isChecked(),
                preset_name=preset_name,
                use_advanced_override=False,
            )
        try:
            validate_mechanical_config(config)
        except ValueError as exc:
            raise AnalysisError(str(exc)) from exc
        return config

    def _collect_mesh(self, required: bool) -> MeshGrid | None:
        text = self.mesh_text_edit.toPlainText().strip()
        if not text:
            if required:
                raise MeshInputError("Mesh input is required.")
            return None
        values = parse_text_grid(text)
        return build_mesh_grid(
            values,
            self.x_min_spin.value(),
            self.x_max_spin.value(),
            self.y_min_spin.value(),
            self.y_max_spin.value(),
            bool(self.row_order_combo.currentData()),
        )

    def _refresh_calibration_turn_table(self) -> None:
        calibration_actions.refresh_calibration_turn_table(self)

    def _add_calibration_trial(self) -> None:
        calibration_actions.add_calibration_trial(self)

    def _fit_and_apply_calibration(self) -> None:
        calibration_actions.fit_and_apply_calibration(self)

    def _build_calibration_mesh(self, text: str) -> MeshGrid:
        return calibration_actions.build_calibration_mesh(self, text)

    def _collect_calibration_turns(self) -> dict[str, float]:
        return calibration_actions.collect_calibration_turns(self)

    def _render_calibration_summary(self, result_text: str | None = None) -> None:
        calibration_actions.render_calibration_summary(self, result_text=result_text)

    def _update_calibration_mesh_context(self, *_args) -> None:
        calibration_actions.update_calibration_mesh_context(self)

    def _render_mesh_previews(self, project: ProjectData, geometry: GeometryReport) -> None:
        if project.mesh is None:
            self.raw_heatmap.clear()
            self.alternate_heatmap.clear()
            return
        screws = [(status.name, status.x_mm, status.y_mm) for status in geometry.screw_statuses]
        display_front_edge = project.coordinate_convention.display_front_edge
        self.raw_heatmap.set_surface(
            project.bed.width_mm,
            project.bed.height_mm,
            project.mesh,
            project.mesh.z_values,
            screws,
            geometry.screw_statuses,
            display_front_edge=display_front_edge,
        )
        alternate_mesh = build_mesh_grid(
            project.mesh.z_values,
            project.mesh.x_min_mm,
            project.mesh.x_max_mm,
            project.mesh.y_min_mm,
            project.mesh.y_max_mm,
            not project.mesh.top_row_is_y_max,
        )
        self.alternate_heatmap.set_surface(
            project.bed.width_mm,
            project.bed.height_mm,
            alternate_mesh,
            alternate_mesh.z_values,
            screws,
            geometry.screw_statuses,
            display_front_edge=display_front_edge,
        )

    def _render_geometry_report(self, geometry: GeometryReport) -> None:
        self.geometry_table.setRowCount(len(geometry.screw_statuses))
        for row, status in enumerate(geometry.screw_statuses):
            bed_status = "inside bed" if status.inside_bed else "outside bed"
            if status.inside_mesh is None:
                probe_status = "mesh not available"
            elif status.inside_mesh:
                probe_status = "inside probe"
            else:
                probe_status = "outside probe"

            notes: list[str] = []
            if status.duplicate_with:
                notes.append(f"duplicate with {', '.join(status.duplicate_with)}")
            if status.inside_mesh is False:
                notes.append("plane only; no local residual note")
            if not status.inside_bed:
                notes.append("invalid bed position")
            values = [
                status.name,
                f"{status.x_mm:.2f}",
                f"{status.y_mm:.2f}",
                status.quadrant or "-",
                bed_status,
                probe_status,
                "; ".join(notes),
            ]
            for column, value in enumerate(values):
                self.geometry_table.setItem(row, column, QTableWidgetItem(value))

        sections: list[str] = []
        if geometry.blocking_errors:
            sections.append("Blocking errors:\n" + "\n".join(f"- {message}" for message in geometry.blocking_errors))
            self.geometry_status_text.setStyleSheet(_status_text_style(self.gui_settings, "error"))
            self.diagnostics_group.setTitle("Layout Diagnostics - Action Required")
        if geometry.warnings:
            sections.append("Warnings:\n" + "\n".join(f"- {message}" for message in geometry.warnings))
            if not geometry.blocking_errors:
                self.geometry_status_text.setStyleSheet(_status_text_style(self.gui_settings, "warning"))
                self.diagnostics_group.setTitle("Layout Diagnostics - Review Warnings")
        if not sections:
            sections.append("Geometry looks valid.")
            self.geometry_status_text.setStyleSheet(_status_text_style(self.gui_settings, "ok"))
            self.diagnostics_group.setTitle("Layout Diagnostics")
        self.geometry_status_text.setPlainText("\n\n".join(sections))

    def _render_best_effort_layout(self) -> None:
        width_mm = self.bed_width_spin.value()
        height_mm = self.bed_height_spin.value()
        screws: list[tuple[str, float, float]] = []
        if width_mm > 0.0 and height_mm > 0.0:
            for row in range(self.screw_table.rowCount()):
                name_item = self.screw_table.item(row, 0)
                left_item = self.screw_table.item(row, 1)
                y_item = self.screw_table.item(row, 2)
                if name_item is None or left_item is None or y_item is None:
                    continue
                name = name_item.text().strip()
                if not name:
                    continue
                try:
                    left_mm = float(left_item.text())
                    y_measure_mm = float(y_item.text())
                except ValueError:
                    continue
                screws.append(
                    (
                        name,
                        *measurement_to_internal(
                            left_mm,
                            y_measure_mm,
                            height_mm,
                            str(self.screw_y_reference_combo.currentData()),
                        ),
                    )
                )
            probe_bounds = None
            try:
                mesh = self._collect_mesh(required=False)
            except MeshInputError:
                mesh = None
            if mesh is not None:
                probe_bounds = (mesh.x_min_mm, mesh.x_max_mm, mesh.y_min_mm, mesh.y_max_mm)
            self.layout_preview.set_layout(
                width_mm,
                height_mm,
                screws,
                probe_bounds=probe_bounds,
                display_front_edge=str(self.display_front_edge_combo.currentData()),
            )
        else:
            self.layout_preview.clear()

    def _render_analysis(self, result: AnalysisResult) -> None:
        probe = result.probe_area_summary
        lines = [
            f"Plane: z = {result.plane_fit.a:.6f}x + {result.plane_fit.b:.6f}y + {result.plane_fit.c:.6f}",
            f"Max abs residual: {result.residual_stats.max_abs_mm:.4f} mm",
            f"RMS residual: {result.residual_stats.rms_mm:.4f} mm",
            f"Peak-to-valley: {result.residual_stats.peak_to_valley_mm:.4f} mm",
            f"Plane slope magnitude: {result.residual_stats.plane_slope_magnitude:.6f}",
            f"Warp classification: {result.warp_report.classification}",
            f"Confidence: {result.warp_report.confidence}",
            result.warp_report.summary,
            "",
            f"Probe area: {probe.probe_width_mm:.1f} mm x {probe.probe_height_mm:.1f} mm",
            f"Probe coverage ratio: {probe.coverage_ratio:.2%}",
            f"Probe coverage level: {probe.warning_level}",
        ]
        if result.effective_mechanical_model is not None and result.mechanical_confidence is not None:
            lines.extend(
                [
                    "",
                    "Effective mechanical model:",
                    f"- self gain {result.effective_mechanical_model.self_gain:.3f}",
                    f"- neighbour gain {result.effective_mechanical_model.neighbor_gain:.3f}",
                    f"- decay length {result.effective_mechanical_model.decay_length_mm:.1f} mm",
                    f"- max step {result.effective_mechanical_model.max_step_turns:.4f} turns",
                    f"- thermal index {result.effective_mechanical_model.thermal_index:.2f}",
                    f"- confidence {result.mechanical_confidence.level} ({result.mechanical_confidence.score:.2f})",
                ]
            )
        self.stats_text.setPlainText(
            "\n".join(lines)
        )
        self.baseline_model_text.setPlainText(
            _build_model_summary("Baseline (primary)", result.baseline_instructions, result.baseline_turn_plan)
        )
        if result.physical_instructions:
            self.physical_model_text.setPlainText(
                _build_model_summary(
                    "Physical-response (heuristic / advisory)",
                    result.physical_instructions,
                    result.physical_turn_plan,
                )
            )
        else:
            self.physical_model_text.setPlainText(
                "Physical-response model disabled.\nEnable it in Setup to compare the heuristic / advisory second opinion."
            )

        warning_lines = list(result.warnings)
        if result.divergence_warnings:
            warning_lines.append("")
            warning_lines.append("Model divergence:")
            warning_lines.extend(f"- {warning}" for warning in result.divergence_warnings)
        self.warning_text.setPlainText("\n".join(warning_lines))

    def _render_results(self, result: AnalysisResult) -> None:
        self._populate_results_table(self.baseline_results_table, result.baseline_instructions)
        self._populate_results_table(self.physical_results_table, result.physical_instructions)
        self.baseline_turn_plan_text.setPlainText(_render_turn_plan(result.baseline_turn_plan))
        self.physical_turn_plan_text.setPlainText(
            _render_turn_plan(result.physical_turn_plan) if result.physical_turn_plan is not None else "Physical model disabled."
        )
        self.summary_text.setPlainText(_build_summary_text(result))

    def _populate_results_table(
        self,
        table: QTableWidget,
        instructions: list[ScrewInstruction],
    ) -> None:
        table.setRowCount(len(instructions))
        for row, instruction in enumerate(instructions):
            values = [
                instruction.name,
                f"{instruction.x_mm:.2f}",
                f"{instruction.y_mm:.2f}",
                f"{instruction.plane_height_mm:.4f}",
                f"{instruction.delta_height_mm:.4f}",
                "-"
                if instruction.expected_achieved_delta_mm is None
                else f"{instruction.expected_achieved_delta_mm:.4f}",
                instruction.action,
                instruction.direction,
                f"{instruction.decimal_turns:.4f}",
                instruction.rounded_turns,
                ", ".join(instruction.notes),
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))

    def save_project_dialog(self) -> None:
        try:
            project = self.collect_project_data(require_mesh=False)
        except (AnalysisError, MeshInputError) as exc:
            self._show_error("Save Error", str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project",
            "",
            "Bed Screw Solver Project (*.json)",
        )
        if not path:
            return
        try:
            save_project(path, project)
        except OSError as exc:
            self._show_error("Save Error", str(exc))
            return
        self.current_project = project
        self.statusBar().showMessage(f"Saved project to {Path(path).name}.", 4000)

    def load_project_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Project",
            "",
            "Bed Screw Solver Project (*.json)",
        )
        if not path:
            return
        try:
            project = load_project(path)
        except (OSError, ProjectDataError, KeyError, TypeError, ValueError) as exc:
            self._show_error("Load Error", str(exc))
            return
        self.populate_project(project)
        self.current_project = project
        self.statusBar().showMessage(f"Loaded project from {Path(path).name}.", 4000)

    def populate_project(self, project: ProjectData) -> None:
        self._populating_project = True
        self.calibration_trials = list(project.calibration_trials)
        self.bed_width_spin.setValue(project.bed.width_mm)
        self.bed_height_spin.setValue(project.bed.height_mm)
        self.pitch_spin.setValue(project.turn_config.pitch_mm_per_turn)
        self.hold_threshold_spin.setValue(project.turn_config.hold_threshold_mm)
        self._set_combo_data(self.clockwise_combo, project.turn_config.clockwise_effect)
        self._set_combo_data(self.viewpoint_combo, project.turn_config.viewpoint)
        self._set_combo_data(self.screw_y_reference_combo, project.coordinate_convention.screw_y_reference_edge)
        self._set_combo_data(self.display_front_edge_combo, project.coordinate_convention.display_front_edge)

        self.screw_table.setRowCount(0)
        for screw in project.screws:
            self.add_screw_row(screw.name, screw.left_mm, screw.y_measure_mm)
        self._set_combo_data(self.reference_combo, project.reference_screw_name)
        self._refresh_calibration_turn_table()

        self._set_combo_data(self.mount_type_combo, project.metadata.support_assembly.mount_type)
        self._sync_support_material_options(project.metadata.support_assembly.mount_type)
        self._populate_material_choice(self.plate_material_editor, project.metadata.bed_assembly.plate_material)
        self._populate_material_choice(self.surface_material_editor, project.metadata.bed_assembly.surface_material)
        self._populate_material_choice(self.support_material_editor, project.metadata.support_assembly.support_material)
        self._populate_material_choice(self.screw_material_editor, project.metadata.fastener.screw_material)
        self.support_stack_height_spin.setValue(project.metadata.support_assembly.support_stack_height_mm)
        self.bed_temp_edit.setText("" if project.metadata.bed_temperature_c is None else str(project.metadata.bed_temperature_c))
        self.chamber_temp_edit.setText(
            "" if project.metadata.chamber_temperature_c is None else str(project.metadata.chamber_temperature_c)
        )

        apply_mechanical_model_to_controls(self, project.mechanical_model)

        if project.mesh is not None:
            self._set_mesh_text_from_values(project.mesh.z_values)
            self._set_mesh_bounds(
                project.mesh.x_min_mm,
                project.mesh.x_max_mm,
                project.mesh.y_min_mm,
                project.mesh.y_max_mm,
            )
            self._set_combo_data(self.row_order_combo, project.mesh.top_row_is_y_max)
            self._mesh_bounds_auto_linked = self._mesh_bounds_match_bed()
        else:
            self.mesh_text_edit.clear()
            self.raw_heatmap.clear()
            self.alternate_heatmap.clear()
            self._mesh_bounds_auto_linked = True
            self._sync_mesh_bounds_to_bed()
        self._update_mesh_bounds_status()

        self.analysis_raw_heatmap.clear()
        self.plane_heatmap.clear()
        self.residual_heatmap.clear()
        self.baseline_results_table.setRowCount(0)
        self.physical_results_table.setRowCount(0)
        self.baseline_turn_plan_text.clear()
        self.physical_turn_plan_text.clear()
        self.summary_text.clear()
        self.stats_text.clear()
        self.warning_text.clear()
        self.baseline_model_text.clear()
        self.physical_model_text.clear()
        self.current_analysis = None
        self._render_calibration_summary()
        self._populating_project = False
        self.refresh_geometry_diagnostics()

    def export_results_csv(self) -> None:
        if self.current_analysis is None:
            self._show_error("Export Error", "Run analysis before exporting results.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Results CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        with Path(path).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "source_model",
                    "screw",
                    "x_mm",
                    "y_mm",
                    "plane_height_mm",
                    "delta_height_mm",
                    "expected_achieved_delta_mm",
                    "action",
                    "direction",
                    "decimal_turns",
                    "rounded_turns",
                    "notes",
                ]
            )
            for source_model, instructions in (
                ("baseline", self.current_analysis.baseline_instructions),
                ("physical", self.current_analysis.physical_instructions),
            ):
                for instruction in instructions:
                    writer.writerow(
                        [
                            source_model,
                            instruction.name,
                            f"{instruction.x_mm:.3f}",
                            f"{instruction.y_mm:.3f}",
                            f"{instruction.plane_height_mm:.6f}",
                            f"{instruction.delta_height_mm:.6f}",
                            ""
                            if instruction.expected_achieved_delta_mm is None
                            else f"{instruction.expected_achieved_delta_mm:.6f}",
                            instruction.action,
                            instruction.direction,
                            f"{instruction.decimal_turns:.6f}",
                            instruction.rounded_turns,
                            "; ".join(instruction.notes),
                        ]
                    )
        self.statusBar().showMessage(f"Exported results to {Path(path).name}.", 4000)

    def copy_summary(self) -> None:
        if self.current_analysis is None:
            self._show_error("Copy Error", "Run analysis before copying the summary.")
            return
        QApplication.clipboard().setText(self.summary_text.toPlainText())
        self.statusBar().showMessage("Summary copied to clipboard.", 3000)

    def _set_mesh_text_from_values(self, values: list[list[float]]) -> None:
        self.mesh_text_edit.setPlainText("\n".join(",".join(f"{cell:g}" for cell in row) for row in values))

    def _set_combo_data(self, combo: QComboBox, target) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == target:
                combo.setCurrentIndex(index)
                return
        if combo.isEditable():
            combo.setCurrentText(str(target))

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)


SUPPORTED_GUI_THEMES = {"light", "dark", "high_contrast"}


def _settings_store() -> QSettings:
    return QSettings("M3Engineering", "BedScrewSolverV4")


def _load_gui_settings() -> GuiSettings:
    settings = _settings_store()
    theme = str(settings.value("gui/theme", "light"))
    if theme not in SUPPORTED_GUI_THEMES:
        theme = "light"
    try:
        font_size = int(settings.value("gui/font_size_pt", 10))
    except (TypeError, ValueError):
        font_size = 10
    if font_size not in {10, 12, 14}:
        font_size = 10
    return GuiSettings(theme=theme, font_size_pt=font_size)


def _save_gui_settings(gui_settings: GuiSettings) -> None:
    settings = _settings_store()
    settings.setValue("gui/theme", gui_settings.theme)
    settings.setValue("gui/font_size_pt", gui_settings.font_size_pt)
    settings.sync()


def _gui_palette(gui_settings: GuiSettings) -> dict[str, str]:
    if gui_settings.theme == "dark":
        return {
            "window": "#151a20",
            "panel": "#1d232b",
            "panel_alt": "#252d36",
            "control": "#101419",
            "control_alt": "#192027",
            "text": "#edf2f7",
            "muted": "#b7c3d0",
            "disabled_text": "#778493",
            "disabled_bg": "#20262e",
            "border": "#465260",
            "border_strong": "#788696",
            "grid": "#3a4551",
            "focus": "#55a7ff",
            "primary": "#2d7ff0",
            "primary_hover": "#4d95f4",
            "primary_pressed": "#1d63bf",
            "primary_text": "#ffffff",
            "button": "#252d36",
            "button_hover": "#303a45",
            "button_pressed": "#1c242c",
            "mode": "#101419",
            "mode_checked": "#2d7ff0",
            "mode_checked_text": "#ffffff",
            "selection": "#2d7ff0",
            "selection_text": "#ffffff",
            "error_bg": "#381b1d",
            "error_border": "#e36b73",
            "warning_bg": "#352a14",
            "warning_border": "#f0bd55",
            "ok_bg": "#153020",
            "ok_border": "#66c98f",
            "mesh_background": "#12171d",
            "mesh_empty": "#1e2630",
            "mesh_low": "#4ea1ff",
            "mesh_mid": "#e5edf5",
            "mesh_high": "#ff6b63",
            "probe": "#f0bd55",
            "screw": "#f6f8fb",
            "screw_warning": "#f7b84b",
            "screw_error": "#ff6b6b",
            "selected": "#ffffff",
        }
    if gui_settings.theme == "high_contrast":
        return {
            "window": "#000000",
            "panel": "#111111",
            "panel_alt": "#1a1a1a",
            "control": "#000000",
            "control_alt": "#101010",
            "text": "#ffffff",
            "muted": "#ffffff",
            "disabled_text": "#cfcfcf",
            "disabled_bg": "#242424",
            "border": "#ffffff",
            "border_strong": "#ffd400",
            "grid": "#ffffff",
            "focus": "#00b7ff",
            "primary": "#ffd400",
            "primary_hover": "#ffe45c",
            "primary_pressed": "#e2bd00",
            "primary_text": "#000000",
            "button": "#000000",
            "button_hover": "#202020",
            "button_pressed": "#303030",
            "mode": "#000000",
            "mode_checked": "#ffd400",
            "mode_checked_text": "#000000",
            "selection": "#0b5fff",
            "selection_text": "#ffffff",
            "error_bg": "#4c0000",
            "error_border": "#ff9f9f",
            "warning_bg": "#4a3800",
            "warning_border": "#ffd166",
            "ok_bg": "#003d1f",
            "ok_border": "#86efac",
            "mesh_background": "#000000",
            "mesh_empty": "#101010",
            "mesh_low": "#00b7ff",
            "mesh_mid": "#ffffff",
            "mesh_high": "#ff3b30",
            "probe": "#ffd400",
            "screw": "#ffffff",
            "screw_warning": "#ffd400",
            "screw_error": "#ff3b30",
            "selected": "#ffffff",
        }
    return {
        "window": "#f4f7fb",
        "panel": "#ffffff",
        "panel_alt": "#e9f0f7",
        "control": "#ffffff",
        "control_alt": "#f7fafc",
        "text": "#17202a",
        "muted": "#526173",
        "disabled_text": "#7c8794",
        "disabled_bg": "#eef2f6",
        "border": "#aebdcc",
        "border_strong": "#66788d",
        "grid": "#d5dee8",
        "focus": "#0b6fdb",
        "primary": "#155cc8",
        "primary_hover": "#0f4da9",
        "primary_pressed": "#0b3f87",
        "primary_text": "#ffffff",
        "button": "#f8fbff",
        "button_hover": "#e9f1fb",
        "button_pressed": "#d8e5f3",
        "mode": "#f8fbff",
        "mode_checked": "#244e73",
        "mode_checked_text": "#ffffff",
        "selection": "#1d65ad",
        "selection_text": "#ffffff",
        "error_bg": "#fff5f5",
        "error_border": "#dc6a6a",
        "warning_bg": "#fffaf0",
        "warning_border": "#c58a18",
        "ok_bg": "#f3faf6",
        "ok_border": "#4ca66f",
        "mesh_background": "#fbfdff",
        "mesh_empty": "#eef3f8",
        "mesh_low": "#2c7fb8",
        "mesh_mid": "#f8fafc",
        "mesh_high": "#d7301f",
        "probe": "#c77500",
        "screw": "#17202a",
        "screw_warning": "#d18700",
        "screw_error": "#c43b36",
        "selected": "#ffffff",
    }


def _build_gui_stylesheet(gui_settings: GuiSettings) -> str:
    colors = _gui_palette(gui_settings)
    font_size = gui_settings.font_size_pt
    header_size = font_size + 3
    return f"""
        QWidget {{
            color: {colors["text"]};
            background-color: {colors["window"]};
            font-size: {font_size}pt;
        }}
        QMainWindow, QDialog, QStatusBar {{
            color: {colors["text"]};
            background-color: {colors["window"]};
        }}
        QWidget#TopActionBar {{
            background-color: {colors["panel"]};
            border: 1px solid {colors["border"]};
            border-radius: 6px;
        }}
        QLabel {{
            color: {colors["text"]};
            background-color: transparent;
        }}
        QLabel#AppHeader {{
            color: {colors["text"]};
            font-size: {header_size}pt;
            font-weight: 700;
        }}
        QLabel#PanelTitle {{
            color: {colors["text"]};
            font-weight: 700;
        }}
        QLabel#InspectReadout {{
            color: {colors["muted"]};
            min-height: 20px;
        }}
        QLabel#MeshBoundsStatus {{
            color: {colors["muted"]};
            background-color: {colors["panel_alt"]};
            border: 1px solid {colors["border"]};
            border-radius: 4px;
            padding: 5px 7px;
        }}
        QLabel#MeshBoundsStatus[state="manual"] {{
            color: {colors["text"]};
            background-color: {colors["warning_bg"]};
            border-color: {colors["warning_border"]};
        }}
        QPushButton {{
            color: {colors["text"]};
            background-color: {colors["button"]};
            border: 1px solid {colors["border"]};
            border-radius: 5px;
            padding: 6px 11px;
            min-height: 22px;
        }}
        QPushButton:hover {{
            background-color: {colors["button_hover"]};
            border-color: {colors["border_strong"]};
        }}
        QPushButton:pressed {{
            background-color: {colors["button_pressed"]};
        }}
        QPushButton:focus {{
            border: 2px solid {colors["focus"]};
            padding: 5px 10px;
        }}
        QPushButton:disabled {{
            color: {colors["disabled_text"]};
            background-color: {colors["disabled_bg"]};
            border-color: {colors["border"]};
        }}
        QPushButton#PrimaryAction {{
            background-color: {colors["primary"]};
            color: {colors["primary_text"]};
            border: 1px solid {colors["primary_hover"]};
            border-radius: 5px;
            font-weight: 700;
            padding: 6px 14px;
        }}
        QPushButton#PrimaryAction:hover {{
            background-color: {colors["primary_hover"]};
        }}
        QPushButton#PrimaryAction:pressed {{
            background-color: {colors["primary_pressed"]};
        }}
        QPushButton[modeToggle="true"] {{
            color: {colors["text"]};
            background-color: {colors["mode"]};
            padding: 3px 7px;
            border: 1px solid {colors["border"]};
        }}
        QPushButton[modeToggle="true"]:checked {{
            color: {colors["mode_checked_text"]};
            background-color: {colors["mode_checked"]};
            border-color: {colors["mode_checked"]};
        }}
        QGroupBox {{
            color: {colors["text"]};
            border: 1px solid {colors["border"]};
            border-radius: 6px;
            margin-top: 12px;
            padding: 12px 8px 8px 8px;
            font-weight: 700;
            background-color: {colors["panel"]};
        }}
        QGroupBox::title {{
            color: {colors["text"]};
            background-color: {colors["panel"]};
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
        }}
        QTabWidget::pane {{
            border: 1px solid {colors["border"]};
            border-radius: 4px;
            background-color: {colors["panel"]};
        }}
        QTabBar::tab {{
            color: {colors["text"]};
            background-color: {colors["panel_alt"]};
            border: 1px solid {colors["border"]};
            padding: 8px 14px;
        }}
        QTabBar::tab:selected {{
            background-color: {colors["control"]};
            border-bottom-color: {colors["control"]};
            font-weight: 700;
        }}
        QTabBar::tab:hover {{
            border-color: {colors["border_strong"]};
        }}
        QMenuBar, QMenu {{
            color: {colors["text"]};
            background-color: {colors["panel"]};
            border: 1px solid {colors["border"]};
        }}
        QMenuBar::item {{
            background-color: transparent;
            padding: 4px 8px;
        }}
        QMenu::item {{
            padding: 5px 24px 5px 18px;
        }}
        QMenuBar::item:selected, QMenu::item:selected {{
            color: {colors["selection_text"]};
            background-color: {colors["selection"]};
        }}
        QTextEdit, QTextBrowser, QLineEdit, QDoubleSpinBox, QComboBox, QListWidget, QTableWidget, QTableView {{
            color: {colors["text"]};
            background-color: {colors["control"]};
            selection-color: {colors["selection_text"]};
            selection-background-color: {colors["selection"]};
            border: 1px solid {colors["border"]};
            border-radius: 4px;
            padding: 3px;
        }}
        QTextEdit:focus, QTextBrowser:focus, QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus, QListWidget:focus, QTableWidget:focus, QTableView:focus {{
            border: 2px solid {colors["focus"]};
            padding: 2px;
        }}
        QTextEdit:read-only, QTextBrowser {{
            color: {colors["text"]};
            background-color: {colors["control_alt"]};
        }}
        QLineEdit:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QTextEdit:disabled {{
            color: {colors["disabled_text"]};
            background-color: {colors["disabled_bg"]};
            border-color: {colors["border"]};
        }}
        QComboBox::drop-down {{
            border-left: 1px solid {colors["border"]};
            width: 22px;
        }}
        QComboBox QAbstractItemView {{
            color: {colors["text"]};
            background-color: {colors["control"]};
            selection-color: {colors["selection_text"]};
            selection-background-color: {colors["selection"]};
            border: 1px solid {colors["border_strong"]};
        }}
        QTableWidget, QTableView {{
            color: {colors["text"]};
            background-color: {colors["control"]};
            alternate-background-color: {colors["control_alt"]};
            selection-color: {colors["selection_text"]};
            selection-background-color: {colors["selection"]};
            gridline-color: {colors["grid"]};
            border: 1px solid {colors["border"]};
        }}
        QTableWidget::item {{
            color: {colors["text"]};
            background-color: transparent;
            padding: 3px;
        }}
        QTableWidget::item:selected {{
            color: {colors["selection_text"]};
            background-color: {colors["selection"]};
        }}
        QHeaderView::section {{
            color: {colors["text"]};
            background-color: {colors["panel"]};
            border: 1px solid {colors["border"]};
            padding: 4px;
            font-weight: 700;
        }}
        QScrollArea, QAbstractScrollArea {{
            color: {colors["text"]};
            background-color: {colors["window"]};
            border: none;
        }}
        QCheckBox {{
            color: {colors["text"]};
            background-color: transparent;
            spacing: 7px;
        }}
        QCheckBox::indicator {{
            width: 15px;
            height: 15px;
            border: 1px solid {colors["border_strong"]};
            background-color: {colors["control"]};
            border-radius: 3px;
        }}
        QCheckBox::indicator:checked {{
            background-color: {colors["primary"]};
            border-color: {colors["primary_hover"]};
        }}
        QCheckBox::indicator:disabled {{
            background-color: {colors["disabled_bg"]};
            border-color: {colors["border"]};
        }}
        QSlider::groove:horizontal {{
            height: 6px;
            background-color: {colors["panel_alt"]};
            border: 1px solid {colors["border"]};
            border-radius: 3px;
        }}
        QSlider::handle:horizontal {{
            width: 16px;
            margin: -6px 0;
            background-color: {colors["primary"]};
            border: 1px solid {colors["primary_hover"]};
            border-radius: 8px;
        }}
        QSplitter::handle {{
            background-color: {colors["border"]};
        }}
        QSplitter::handle:hover {{
            background-color: {colors["border_strong"]};
        }}
        QScrollBar:vertical, QScrollBar:horizontal {{
            background-color: {colors["panel"]};
            border: 1px solid {colors["border"]};
            margin: 0;
        }}
        QScrollBar:vertical {{
            width: 14px;
        }}
        QScrollBar:horizontal {{
            height: 14px;
        }}
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
            background-color: {colors["border_strong"]};
            border-radius: 5px;
            min-height: 28px;
            min-width: 28px;
        }}
        QScrollBar::add-line, QScrollBar::sub-line {{
            width: 0;
            height: 0;
        }}
        QScrollBar::add-page, QScrollBar::sub-page {{
            background: transparent;
        }}
        QToolTip {{
            color: {colors["text"]};
            background-color: {colors["control"]};
            border: 1px solid {colors["border_strong"]};
            padding: 4px;
        }}
    """


def _status_text_style(gui_settings: GuiSettings, level: str) -> str:
    colors = _gui_palette(gui_settings)
    if level == "error":
        background = colors["error_bg"]
        border = colors["error_border"]
    elif level == "warning":
        background = colors["warning_bg"]
        border = colors["warning_border"]
    else:
        background = colors["ok_bg"]
        border = colors["ok_border"]
    return (
        f"color: {colors['text']}; "
        f"background-color: {background}; "
        f"selection-color: {colors['selection_text']}; "
        f"selection-background-color: {colors['selection']}; "
        f"border: 1px solid {border}; "
        "border-radius: 4px; padding: 4px;"
    )


def _make_spinbox(
    minimum: float,
    maximum: float,
    step: float,
    value: float,
    decimals: int = 2,
) -> QDoubleSpinBox:
    spinbox = QDoubleSpinBox()
    spinbox.setRange(minimum, maximum)
    spinbox.setDecimals(decimals)
    spinbox.setSingleStep(step)
    spinbox.setValue(value)
    return spinbox


def _make_optional_spinbox(
    minimum: float,
    maximum: float,
    step: float,
    value: float,
    decimals: int = 2,
) -> QDoubleSpinBox:
    spinbox = _make_spinbox(minimum, maximum, step, value, decimals=decimals)
    spinbox.setSpecialValueText("None")
    return spinbox


def _optional_spinbox_value(spinbox: QDoubleSpinBox | None) -> float | None:
    if spinbox is None:
        return None
    return None if spinbox.value() <= spinbox.minimum() else spinbox.value()


def _set_optional_spinbox(spinbox: QDoubleSpinBox, value: float | None) -> None:
    spinbox.setValue(spinbox.minimum() if value is None else value)


def _parse_optional_float(text: str) -> float | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError as exc:
        raise AnalysisError(f"Invalid numeric value: {text}") from exc


def _build_model_summary(title: str, instructions: list[ScrewInstruction], turn_plan: TurnPlan | None) -> str:
    lines = [f"{title} instructions:"]
    if not instructions:
        lines.append("No instructions available.")
        return "\n".join(lines)
    active = [instruction for instruction in instructions if instruction.action != "hold"]
    lines.append(f"Active screws: {len(active)}")
    for instruction in instructions:
        line = (
            f"{instruction.name}: {instruction.action} | {instruction.direction} | "
            f"{instruction.decimal_turns:.4f} turns | delta {instruction.delta_height_mm:.4f} mm"
        )
        if instruction.expected_achieved_delta_mm is not None:
            line += f" | predicted {instruction.expected_achieved_delta_mm:.4f} mm"
        if instruction.notes:
            line += f" | notes: {', '.join(instruction.notes)}"
        lines.append(line)
    if turn_plan is not None and turn_plan.warnings:
        lines.append("")
        lines.extend(turn_plan.warnings)
    return "\n".join(lines)


def _render_turn_plan(turn_plan: TurnPlan | None) -> str:
    if turn_plan is None:
        return "No turn plan available."
    if turn_plan.source_model == "physical":
        title = "Physical first pass (heuristic / advisory)"
    else:
        title = "Baseline first pass"
    lines = [f"{title}:"]
    if not turn_plan.first_pass_steps:
        lines.append("No active screws in this pass.")
    for step in turn_plan.first_pass_steps:
        line = (
            f"{step.screw_name}: {step.action} | {step.rotation} | "
            f"{step.turns_this_pass:.4f} turns this pass"
        )
        if step.remaining_after_pass > 0.0:
            line += f" | remaining {step.remaining_after_pass:.4f}"
        if step.note:
            line += f" | {step.note}"
        lines.append(line)
    if turn_plan.warnings:
        lines.append("")
        lines.extend(turn_plan.warnings)
    return "\n".join(lines)


def _build_summary_text(result: AnalysisResult) -> str:
    probe = result.probe_area_summary
    lines = [
        f"Warp classification: {result.warp_report.classification} ({result.warp_report.confidence})",
        f"Residual RMS: {result.residual_stats.rms_mm:.4f} mm",
        f"Probe coverage: {probe.coverage_ratio:.2%} ({probe.warning_level})",
    ]
    if result.mechanical_confidence is not None:
        lines.append(
            f"Physical confidence: {result.mechanical_confidence.level} ({result.mechanical_confidence.score:.2f})"
        )
    lines.extend(["", "Baseline:"])
    for instruction in result.baseline_instructions:
        lines.append(_summary_line_for_instruction(instruction))
    if result.physical_instructions:
        lines.append("")
        lines.append("Physical-response model (heuristic / advisory):")
        for instruction in result.physical_instructions:
            lines.append(_summary_line_for_instruction(instruction))
    if result.divergence_warnings:
        lines.append("")
        lines.append("Model divergence:")
        lines.extend(f"- {warning}" for warning in result.divergence_warnings)
    return "\n".join(lines)


def _summary_line_for_instruction(instruction: ScrewInstruction) -> str:
    line = (
        f"{instruction.name}: {instruction.action} | {instruction.direction} | "
        f"{instruction.decimal_turns:.4f} turns | rounded {instruction.rounded_turns} | "
        f"delta {instruction.delta_height_mm:.4f} mm"
    )
    if instruction.expected_achieved_delta_mm is not None and instruction.source_model == "physical":
        line += f" | predicted {instruction.expected_achieved_delta_mm:.4f} mm"
    if instruction.notes:
        line += f" | notes: {', '.join(instruction.notes)}"
    return line
