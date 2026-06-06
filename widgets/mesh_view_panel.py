from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from models import EdgeReference, GeometryScrewStatus, MeshGrid
from widgets.heatmap_widget import HeatmapWidget
from widgets.mesh3d_widget import Mesh3DWidget


class MeshViewPanel(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.heatmap = HeatmapWidget()
        self.mesh3d = Mesh3DWidget()

        self.setObjectName("MeshViewPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PanelTitle")
        header.addWidget(self.title_label)
        header.addStretch(1)

        self.mode_group = QButtonGroup(self)
        self.mode_2d_button = _mode_button("2D")
        self.mode_3d_button = _mode_button("3D")
        self.mode_group.addButton(self.mode_2d_button, 0)
        self.mode_group.addButton(self.mode_3d_button, 1)
        self.mode_2d_button.setChecked(True)
        header.addWidget(self.mode_2d_button)
        header.addWidget(self.mode_3d_button)

        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Reset 3D view")
        header.addWidget(self.reset_button)

        header.addWidget(QLabel("Height"))
        self.height_slider = QSlider(Qt.Orientation.Horizontal)
        self.height_slider.setRange(25, 400)
        self.height_slider.setValue(100)
        self.height_slider.setFixedWidth(120)
        self.height_slider.setToolTip("3D height scale")
        header.addWidget(self.height_slider)

        self.screws_check = QCheckBox("Screws")
        self.screws_check.setChecked(True)
        self.probe_check = QCheckBox("Probe")
        self.probe_check.setChecked(True)
        header.addWidget(self.screws_check)
        header.addWidget(self.probe_check)
        layout.addLayout(header)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.heatmap)
        self.stack.addWidget(self.mesh3d)
        layout.addWidget(self.stack, 1)

        self.inspect_label = QLabel(self.mesh3d.inspect_text())
        self.inspect_label.setObjectName("InspectReadout")
        self.inspect_label.setWordWrap(True)
        layout.addWidget(self.inspect_label)

        self.mode_group.idClicked.connect(self.stack.setCurrentIndex)
        self.reset_button.clicked.connect(self.mesh3d.reset_view)
        self.height_slider.valueChanged.connect(lambda value: self.mesh3d.set_height_scale(value / 100.0))
        self.screws_check.toggled.connect(self.mesh3d.set_show_screws)
        self.probe_check.toggled.connect(self.mesh3d.set_show_probe_bounds)
        self.mesh3d.inspectChanged.connect(self.inspect_label.setText)

    def set_theme_palette(self, palette: dict[str, str]) -> None:
        self.heatmap.set_theme_palette(palette)
        self.mesh3d.set_theme_palette(palette)

    def clear(self) -> None:
        self.heatmap.clear()
        self.mesh3d.clear()

    def set_surface(
        self,
        bed_width_mm: float,
        bed_height_mm: float,
        mesh: MeshGrid,
        values: Sequence[Sequence[float]],
        screws: Sequence[tuple[str, float, float]] = (),
        statuses: Sequence[GeometryScrewStatus] = (),
        *,
        display_front_edge: EdgeReference = "top",
    ) -> None:
        self.heatmap.set_surface(
            bed_width_mm,
            bed_height_mm,
            mesh,
            values,
            screws,
            statuses,
            display_front_edge=display_front_edge,
        )
        self.mesh3d.set_surface(
            bed_width_mm,
            bed_height_mm,
            mesh,
            values,
            screws,
            statuses,
            display_front_edge=display_front_edge,
        )


def _mode_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setCheckable(True)
    button.setMinimumWidth(38)
    button.setMaximumWidth(44)
    button.setProperty("modeToggle", True)
    return button
