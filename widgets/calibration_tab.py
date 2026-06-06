from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTextEdit,
)


def build_calibration_tab(window) -> None:
    layout = window._create_scrolled_tab_layout(window.calibration_tab)

    entry_group = QGroupBox("Calibration Trial")
    entry_layout = QGridLayout(entry_group)
    window.calibration_name_edit = QLineEdit()
    window.calibration_name_edit.setText("Trial 1")
    window.calibration_bounds_label = QLabel()
    window.calibration_bounds_label.setObjectName("MeshBoundsStatus")
    window.calibration_before_edit = QTextEdit()
    window.calibration_before_edit.setPlaceholderText("Before mesh")
    window.calibration_after_edit = QTextEdit()
    window.calibration_after_edit.setPlaceholderText("After mesh")
    window.calibration_turns_table = QTableWidget(0, 2)
    window.calibration_turns_table.setHorizontalHeaderLabels(["Screw", "Signed turns"])
    window._configure_data_table(window.calibration_turns_table, stretch_column=0)
    window.calibration_turns_table.setSelectionBehavior(QAbstractItemView.SelectRows)
    window.refresh_calibration_button = QPushButton("Refresh Screws")
    window.add_calibration_button = QPushButton("Save Trial")
    window.fit_calibration_button = QPushButton("Fit && Apply")

    entry_layout.addWidget(QLabel("Name"), 0, 0)
    entry_layout.addWidget(window.calibration_name_edit, 0, 1, 1, 3)
    entry_layout.addWidget(QLabel("Mesh context"), 1, 0)
    entry_layout.addWidget(window.calibration_bounds_label, 1, 1, 1, 3)
    entry_layout.addWidget(QLabel("Before"), 2, 0)
    entry_layout.addWidget(window.calibration_before_edit, 2, 1)
    entry_layout.addWidget(QLabel("After"), 2, 2)
    entry_layout.addWidget(window.calibration_after_edit, 2, 3)
    entry_layout.addWidget(QLabel("Applied signed turns"), 3, 0)
    entry_layout.addWidget(window.calibration_turns_table, 3, 1, 1, 3)
    button_row = QHBoxLayout()
    button_row.addWidget(window.refresh_calibration_button)
    button_row.addStretch(1)
    button_row.addWidget(window.add_calibration_button)
    button_row.addWidget(window.fit_calibration_button)
    entry_layout.addLayout(button_row, 4, 0, 1, 4)

    window.calibration_summary_text = QTextEdit()
    window._configure_readonly_text(window.calibration_summary_text, minimum_height=160)
    layout.addWidget(entry_group)
    layout.addWidget(window.calibration_summary_text)
    layout.addStretch(1)

    window.refresh_calibration_button.clicked.connect(window._refresh_calibration_turn_table)
    window.add_calibration_button.clicked.connect(window._add_calibration_trial)
    window.fit_calibration_button.clicked.connect(window._fit_and_apply_calibration)
    window._update_calibration_mesh_context()
