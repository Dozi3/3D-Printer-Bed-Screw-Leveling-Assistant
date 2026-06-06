from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QWidget


@dataclass
class MaterialEditorControls:
    combo: QComboBox
    custom_check: QCheckBox
    custom_label_edit: QLineEdit
    custom_widget: QWidget
    fields: dict[str, QDoubleSpinBox]
