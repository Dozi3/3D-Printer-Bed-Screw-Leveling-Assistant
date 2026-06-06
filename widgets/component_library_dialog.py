from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from component_library import (
    ComponentLibraryError,
    ComponentProfileLibrary,
    ProfileSuggestion,
    apply_profile_to_project,
    build_profile_suggestions,
    critical_unknown_fields,
    find_app_calibration_profile,
    get_active_component_library,
    get_printer_profiles,
    get_profile_counts,
    list_sqlite_relations,
    load_component_profile_library,
    query_sqlite_relation,
    reload_bundled_component_profile_library,
    research_gaps_for_profile,
    set_active_component_library,
    source_evidence_for_profile,
    warning_lines_for_profile,
)


PROFILE_COLUMNS = [
    "Manufacturer",
    "Model",
    "Kinematics",
    "Bed motion",
    "Bed core material",
    "Build plate material",
    "Mount type",
    "Screw count",
    "Screw pitch",
    "Probe type",
    "Chamber heated",
    "Suggested solver mode",
    "Confidence",
]


class ComponentLibraryDialog(QDialog):
    def __init__(self, host_window, parent=None) -> None:
        super().__init__(parent)
        self.host_window = host_window
        self.library = get_active_component_library()
        self.filtered_profiles: list[dict] = []
        self.sqlite_rows: list[dict[str, object]] = []

        self.setWindowTitle("Component Library")
        self.resize(1280, 820)
        self._build_ui()
        self._refresh_library_summary("Built-in library loaded.")
        self._populate_profile_table()
        self._populate_sqlite_relation_combo()
        self._refresh_sqlite_table()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        actions_layout = QHBoxLayout()
        self.import_button = QPushButton("Import Library")
        self.reload_button = QPushButton("Reload Defaults")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search printer, manufacturer, probe, material, or solver mode")
        self.search_button = QPushButton("Search Printer")
        self.apply_button = QPushButton("Apply Selected Profile")
        actions_layout.addWidget(self.import_button)
        actions_layout.addWidget(self.reload_button)
        actions_layout.addWidget(self.search_edit, 1)
        actions_layout.addWidget(self.search_button)
        actions_layout.addWidget(self.apply_button)
        layout.addLayout(actions_layout)

        tabs = QTabWidget()
        tabs.addTab(self._build_profiles_tab(), "Profile Lookup")
        tabs.addTab(self._build_sqlite_tab(), "SQLite Browser")
        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.import_button.clicked.connect(self.import_library)
        self.reload_button.clicked.connect(self.reload_defaults)
        self.search_button.clicked.connect(self._populate_profile_table)
        self.search_edit.returnPressed.connect(self._populate_profile_table)
        self.profile_table.itemSelectionChanged.connect(self._render_selected_profile_preview)
        self.apply_button.clicked.connect(self.apply_selected_profile)
        self.sqlite_refresh_button.clicked.connect(self._refresh_sqlite_table)
        self.sqlite_search_edit.returnPressed.connect(self._refresh_sqlite_table)
        self.sqlite_relation_combo.currentIndexChanged.connect(self._refresh_sqlite_table)

    def _build_profiles_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.profile_table = QTableWidget(0, len(PROFILE_COLUMNS))
        self.profile_table.setHorizontalHeaderLabels(PROFILE_COLUMNS)
        self.profile_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.profile_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.profile_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._configure_table(self.profile_table)
        splitter.addWidget(self.profile_table)

        self.preview_browser = QTextBrowser()
        self.preview_browser.setReadOnly(True)
        self.preview_browser.setOpenExternalLinks(True)
        self.preview_browser.setMinimumWidth(420)
        splitter.addWidget(self.preview_browser)
        splitter.setSizes([820, 460])
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        return tab

    def _build_sqlite_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        controls_layout = QHBoxLayout()
        self.sqlite_relation_combo = QComboBox()
        self.sqlite_search_edit = QLineEdit()
        self.sqlite_search_edit.setPlaceholderText("Search current SQLite relation")
        self.sqlite_refresh_button = QPushButton("Refresh")
        controls_layout.addWidget(QLabel("Relation"))
        controls_layout.addWidget(self.sqlite_relation_combo)
        controls_layout.addWidget(self.sqlite_search_edit, 1)
        controls_layout.addWidget(self.sqlite_refresh_button)
        layout.addLayout(controls_layout)

        self.sqlite_table = QTableWidget(0, 0)
        self.sqlite_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sqlite_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._configure_table(self.sqlite_table)
        layout.addWidget(self.sqlite_table, 1)
        return tab

    def import_library(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Component Library",
            "",
            "Component Library JSON (*.json)",
        )
        if not path:
            return
        try:
            imported = load_component_profile_library(path)
        except ComponentLibraryError as exc:
            QMessageBox.warning(
                self,
                "Import Library",
                f"Could not import component library.\n\n{exc}\n\nThe current library remains loaded.",
            )
            self._refresh_library_summary("Import rejected; current library kept.")
            return
        set_active_component_library(imported)
        self.library = imported
        self._refresh_library_summary(f"Imported library from {Path(path).name}.")
        self._populate_profile_table()

    def reload_defaults(self) -> None:
        try:
            self.library = reload_bundled_component_profile_library()
        except ComponentLibraryError as exc:
            QMessageBox.warning(self, "Reload Defaults", str(exc))
            return
        self._refresh_library_summary("Built-in defaults reloaded.")
        self._populate_profile_table()

    def apply_selected_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            QMessageBox.information(self, "Apply Profile", "Select a profile first.")
            return

        try:
            project = self.host_window.collect_project_data(require_mesh=False)
            suggestions = build_profile_suggestions(project, str(profile.get("printer_id")), self.library)
        except (ComponentLibraryError, ValueError) as exc:
            QMessageBox.warning(self, "Apply Profile", str(exc))
            return

        selected_fields = self._show_apply_confirmation(profile, suggestions)
        if selected_fields is None:
            return
        if not selected_fields:
            QMessageBox.information(self, "Apply Profile", "No fields were selected.")
            return

        try:
            result = apply_profile_to_project(
                str(profile.get("printer_id")),
                selected_fields,
                project,
                self.library,
            )
        except ComponentLibraryError as exc:
            QMessageBox.warning(self, "Apply Profile", str(exc))
            return

        self.host_window.populate_project(result.project)
        count = len(result.applied)
        self.host_window.statusBar().showMessage(
            f"Applied {count} selected component-library field{'s' if count != 1 else ''}.",
            5000,
        )
        self._render_selected_profile_preview()

    def _refresh_library_summary(self, state: str) -> None:
        counts = get_profile_counts(self.library)
        source = self.library.source_label
        import_state = "Imported" if self.library.imported else "Built-in"
        self.summary_label.setText(
            f"<b>Component Library</b> | Source: {source} ({import_state}) | "
            f"Schema: {self.library.schema_version} | Generated: {self.library.generated_at_utc} | "
            f"Printer profiles: {counts['printer_component_profiles']} | "
            f"App mappings: {counts['app_calibration_profiles']} | {state}"
        )

    def _populate_profile_table(self) -> None:
        search_text = self.search_edit.text().strip().lower()
        profiles = get_printer_profiles(self.library)
        if search_text:
            profiles = [
                profile
                for profile in profiles
                if search_text in " ".join(str(value).lower() for value in profile.values()).lower()
            ]
        self.filtered_profiles = profiles
        self.profile_table.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            values = [
                profile.get("manufacturer_name", "-"),
                profile.get("model_name", "-"),
                profile.get("printer_kinematics", "-"),
                profile.get("bed_motion_type", "-"),
                profile.get("bed_core.bed_core_material", "-"),
                profile.get("build_surface.build_plate_material", "-"),
                profile.get("bed_mounting.bed_mount_type", "-"),
                profile.get("bed_fasteners.screw_count", "-"),
                profile.get("bed_fasteners.screw_pitch_mm", "-"),
                profile.get("probe_calibration.probe_type", "-"),
                profile.get("chamber_thermal.chamber_heated", "-"),
                profile.get("app_calibration_mapping.suggested_solver_mode", "-"),
                profile.get("app_calibration_mapping.confidence", "-"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, profile.get("printer_id"))
                self.profile_table.setItem(row, column, item)
        if profiles:
            self.profile_table.selectRow(0)
        else:
            self.preview_browser.setMarkdown("No matching profiles.")

    def _render_selected_profile_preview(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            self.preview_browser.clear()
            return
        calibration = find_app_calibration_profile(str(profile.get("printer_id")), self.library) or {}
        unknowns = critical_unknown_fields(profile)
        warnings = warning_lines_for_profile(profile, calibration)
        gaps = research_gaps_for_profile(profile, self.library)
        sources = source_evidence_for_profile(profile, self.library)

        lines = [
            f"## {profile.get('manufacturer_name', '-')} {profile.get('model_name', '-')}",
            "",
            "**Suggested from component library.** These values are seed-data suggestions, not authoritative hardware specifications.",
            "",
            f"- Kinematics: {profile.get('printer_kinematics', '-')}",
            f"- Bed motion: {profile.get('bed_motion_type', '-')}",
            f"- Bed core: {profile.get('bed_core.bed_core_material', '-')}",
            f"- Build plate: {profile.get('build_surface.build_plate_material', '-')}",
            f"- Mount: {profile.get('bed_mounting.bed_mount_type', '-')}",
            f"- Probe: {profile.get('probe_calibration.probe_type', '-')}",
            f"- Suggested solver mode: {calibration.get('suggested_solver_mode', profile.get('app_calibration_mapping.suggested_solver_mode', '-'))}",
            f"- Confidence: {calibration.get('confidence', profile.get('app_calibration_mapping.confidence', '-'))}",
        ]
        if unknowns:
            lines.extend(["", "### Unknown Fields"])
            lines.extend(f"- {field}" for field in unknowns)
        if warnings:
            lines.extend(["", "### Warnings"])
            lines.extend(f"- {warning}" for warning in warnings)
        if gaps:
            lines.extend(["", "### Research Gaps"])
            for gap in gaps[:5]:
                lines.append(
                    f"- {gap.get('component_area', '-')}: {gap.get('missing_fields', '-')} "
                    f"({gap.get('confidence', '-')})"
                )
        if sources:
            lines.extend(["", "### Source Evidence"])
            for source in sources[:8]:
                title = source.get("source_title", "-")
                url = source.get("source_url", "-")
                if url and url != "-":
                    lines.append(f"- [{title}]({url})")
                else:
                    lines.append(f"- {title}")
        self.preview_browser.setMarkdown("\n".join(lines))

    def _show_apply_confirmation(
        self,
        profile: dict,
        suggestions: list[ProfileSuggestion],
    ) -> list[str] | None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Apply Component Library Profile")
        dialog.resize(980, 420)
        layout = QVBoxLayout(dialog)
        heading = QLabel(
            "Suggested from component library. Select only the fields to apply; unchecked fields and advisory rows are not changed."
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)

        table = QTableWidget(len(suggestions), 6)
        table.setHorizontalHeaderLabels(["Apply", "Field", "Current", "Suggested", "Confidence", "Notes"])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._configure_table(table, stretch_column=5)
        checks: dict[str, QCheckBox] = {}
        for row, suggestion in enumerate(suggestions):
            check = QCheckBox()
            check.setEnabled(suggestion.applicable)
            check.setChecked(False)
            checks[suggestion.field_key] = check
            table.setCellWidget(row, 0, check)
            values = [
                suggestion.label,
                suggestion.current_value,
                suggestion.suggested_value,
                suggestion.confidence,
                suggestion.reason,
            ]
            for column, value in enumerate(values, start=1):
                table.setItem(row, column, QTableWidgetItem(value))
        layout.addWidget(table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(buttons)
        selected_fields: list[str] | None = None

        def accept_selected() -> None:
            nonlocal selected_fields
            selected_fields = [
                field_key
                for field_key, check in checks.items()
                if check.isEnabled() and check.isChecked()
            ]
            dialog.accept()

        def handle_button_click(button) -> None:
            if buttons.standardButton(button) == QDialogButtonBox.StandardButton.Apply:
                accept_selected()

        buttons.clicked.connect(handle_button_click)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return selected_fields

    def _populate_sqlite_relation_combo(self) -> None:
        self.sqlite_relation_combo.blockSignals(True)
        self.sqlite_relation_combo.clear()
        for relation in list_sqlite_relations():
            self.sqlite_relation_combo.addItem(relation, relation)
        self.sqlite_relation_combo.blockSignals(False)

    def _refresh_sqlite_table(self) -> None:
        relation = self.sqlite_relation_combo.currentData()
        if not relation:
            self.sqlite_table.setRowCount(0)
            self.sqlite_table.setColumnCount(0)
            return
        try:
            rows = query_sqlite_relation(
                str(relation),
                search_text=self.sqlite_search_edit.text(),
                limit=500,
            )
        except ComponentLibraryError as exc:
            QMessageBox.warning(self, "SQLite Browser", str(exc))
            return
        self.sqlite_rows = rows
        columns = list(rows[0].keys()) if rows else []
        self.sqlite_table.setColumnCount(len(columns))
        self.sqlite_table.setHorizontalHeaderLabels(columns)
        self.sqlite_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, column in enumerate(columns):
                self.sqlite_table.setItem(row_index, column_index, QTableWidgetItem(str(row[column])))

    def _selected_profile(self) -> dict | None:
        selected_rows = {index.row() for index in self.profile_table.selectedIndexes()}
        if not selected_rows:
            return None
        row = min(selected_rows)
        if not 0 <= row < len(self.filtered_profiles):
            return None
        return self.filtered_profiles[row]

    def _configure_table(self, table: QTableWidget, stretch_column: int | None = None) -> None:
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        for column in range(table.columnCount()):
            mode = QHeaderView.ResizeMode.Stretch if column == stretch_column else QHeaderView.ResizeMode.ResizeToContents
            header.setSectionResizeMode(column, mode)
