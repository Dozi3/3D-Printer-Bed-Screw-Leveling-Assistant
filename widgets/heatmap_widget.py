from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from models import EdgeReference, GeometryScrewStatus, MeshGrid


DEFAULT_DRAWING_PALETTE: dict[str, str] = {
    "mesh_background": "#fbfdff",
    "mesh_empty": "#eef3f8",
    "mesh_low": "#2c7fb8",
    "mesh_mid": "#f8fafc",
    "mesh_high": "#d7301f",
    "text": "#17202a",
    "muted": "#526173",
    "border_strong": "#66788d",
    "probe": "#c77500",
    "screw": "#17202a",
    "screw_warning": "#d18700",
    "screw_error": "#c43b36",
}


class HeatmapWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bed_width_mm: float | None = None
        self._bed_height_mm: float | None = None
        self._mesh: MeshGrid | None = None
        self._values: list[list[float]] | None = None
        self._probe_bounds: tuple[float, float, float, float] | None = None
        self._screws: list[tuple[str, float, float]] = []
        self._screw_statuses: dict[str, GeometryScrewStatus] = {}
        self._display_front_edge: EdgeReference = "top"
        self._palette = dict(DEFAULT_DRAWING_PALETTE)
        self.setMinimumSize(280, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_theme_palette(self, palette: dict[str, str]) -> None:
        self._palette = {**DEFAULT_DRAWING_PALETTE, **palette}
        self.update()

    def clear(self) -> None:
        self._bed_width_mm = None
        self._bed_height_mm = None
        self._mesh = None
        self._values = None
        self._probe_bounds = None
        self._screws = []
        self._screw_statuses = {}
        self.update()

    def set_layout(
        self,
        bed_width_mm: float,
        bed_height_mm: float,
        screws: Sequence[tuple[str, float, float]] = (),
        statuses: Sequence[GeometryScrewStatus] = (),
        *,
        probe_bounds: tuple[float, float, float, float] | None = None,
        display_front_edge: EdgeReference = "top",
    ) -> None:
        self._bed_width_mm = float(bed_width_mm)
        self._bed_height_mm = float(bed_height_mm)
        self._mesh = None
        self._values = None
        self._probe_bounds = probe_bounds
        self._display_front_edge = display_front_edge
        self._screws = [(name, float(x_mm), float(y_mm)) for name, x_mm, y_mm in screws]
        self._screw_statuses = {status.name: status for status in statuses}
        self.update()

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
        self._bed_width_mm = float(bed_width_mm)
        self._bed_height_mm = float(bed_height_mm)
        self._mesh = mesh
        self._values = [[float(cell) for cell in row] for row in values]
        self._probe_bounds = (mesh.x_min_mm, mesh.x_max_mm, mesh.y_min_mm, mesh.y_max_mm)
        self._display_front_edge = display_front_edge
        self._screws = [(name, float(x_mm), float(y_mm)) for name, x_mm, y_mm in screws]
        self._screw_statuses = {status.name: status for status in statuses}
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(self._palette["mesh_background"]))

        if self._bed_width_mm is None or self._bed_height_mm is None:
            painter.setPen(QColor(self._palette["muted"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No layout loaded")
            return

        plot_rect = QRectF(24.0, 24.0, max(40.0, self.width() - 110.0), max(40.0, self.height() - 60.0))
        legend_rect = QRectF(plot_rect.right() + 12.0, plot_rect.top(), 18.0, plot_rect.height())

        if self._mesh is not None and self._values is not None:
            surface_rows, x_coords, y_coords = self._ordered_surface()
            x_edges = _cell_edges(x_coords)
            y_edges = _cell_edges(y_coords)
            flat_values = [cell for row in surface_rows for cell in row]
            value_min = min(flat_values)
            value_max = max(flat_values)
            for row_index, row in enumerate(surface_rows):
                for column_index, value in enumerate(row):
                    x0 = self._map_x(x_edges[column_index], plot_rect)
                    x1 = self._map_x(x_edges[column_index + 1], plot_rect)
                    y0 = self._map_y(y_edges[row_index], plot_rect)
                    y1 = self._map_y(y_edges[row_index + 1], plot_rect)
                    painter.fillRect(
                        QRectF(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)),
                        _interpolate_color(value, value_min, value_max, self._palette),
                    )
        else:
            value_min = 0.0
            value_max = 0.0
            painter.fillRect(plot_rect, QColor(self._palette["mesh_empty"]))

        painter.setPen(QPen(QColor(self._palette["border_strong"]), 1.25))
        painter.drawRect(plot_rect)
        self._draw_probe_overlay(painter, plot_rect)
        self._draw_front_edge_labels(painter, plot_rect)
        self._draw_screws(painter, plot_rect)
        if self._mesh is not None and self._values is not None:
            self._draw_legend(painter, legend_rect, value_min, value_max)

    def _ordered_surface(self) -> tuple[list[list[float]], list[float], list[float]]:
        assert self._mesh is not None
        assert self._values is not None
        x_coords = list(self._mesh.x_coordinates())
        y_coords = list(self._mesh.y_coordinates())
        values = [row[:] for row in self._values]

        if len(x_coords) >= 2 and x_coords[0] > x_coords[-1]:
            x_coords.reverse()
            values = [list(reversed(row)) for row in values]
        if len(y_coords) >= 2 and y_coords[0] > y_coords[-1]:
            y_coords.reverse()
            values.reverse()
        return values, x_coords, y_coords

    def _draw_probe_overlay(self, painter: QPainter, plot_rect: QRectF) -> None:
        if self._probe_bounds is None:
            return
        x_min, x_max, y_min, y_max = self._probe_bounds
        if (
            x_min <= 0.0
            and y_min <= 0.0
            and x_max >= (self._bed_width_mm or 0.0)
            and y_max >= (self._bed_height_mm or 0.0)
        ):
            return
        overlay = QRectF(
            min(self._map_x(x_min, plot_rect), self._map_x(x_max, plot_rect)),
            min(self._map_y(y_min, plot_rect), self._map_y(y_max, plot_rect)),
            abs(self._map_x(x_max, plot_rect) - self._map_x(x_min, plot_rect)),
            abs(self._map_y(y_max, plot_rect) - self._map_y(y_min, plot_rect)),
        )
        painter.setPen(QPen(QColor(self._palette["probe"]), 1.2, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(overlay)
        painter.setPen(QColor(self._palette["probe"]))
        painter.drawText(QPointF(overlay.left() + 4.0, overlay.top() - 6.0), "Probe area")

    def _draw_front_edge_labels(self, painter: QPainter, plot_rect: QRectF) -> None:
        front_top = self._display_front_edge == "top"
        painter.setPen(QColor(self._palette["muted"]))
        painter.drawText(
            QRectF(plot_rect.left(), plot_rect.top() - 18.0, plot_rect.width(), 16.0),
            Qt.AlignmentFlag.AlignCenter,
            "Front" if front_top else "Rear",
        )
        painter.drawText(
            QRectF(plot_rect.left(), plot_rect.bottom() + 4.0, plot_rect.width(), 16.0),
            Qt.AlignmentFlag.AlignCenter,
            "Rear" if front_top else "Front",
        )

    def _draw_screws(self, painter: QPainter, plot_rect: QRectF) -> None:
        for name, x_mm, y_mm in self._screws:
            pen, brush = self._screw_style(name)
            painter.setPen(pen)
            painter.setBrush(brush)
            x_pos = self._clamp_to_plot(self._map_x(x_mm, plot_rect), plot_rect.left(), plot_rect.right())
            y_pos = self._clamp_to_plot(self._map_y(y_mm, plot_rect), plot_rect.top(), plot_rect.bottom())
            painter.drawEllipse(QPointF(x_pos, y_pos), 4.0, 4.0)
            painter.drawText(QPointF(x_pos + 6.0, y_pos - 6.0), name)

    def _draw_legend(self, painter: QPainter, rect: QRectF, value_min: float, value_max: float) -> None:
        steps = 60
        for index in range(steps):
            top = rect.top() + (rect.height() * index / steps)
            bottom = rect.top() + (rect.height() * (index + 1) / steps)
            value = value_max - ((value_max - value_min) * index / max(1, steps - 1))
            painter.fillRect(
                QRectF(rect.left(), top, rect.width(), bottom - top),
                _interpolate_color(value, value_min, value_max, self._palette),
            )
        painter.setPen(QPen(QColor(self._palette["border_strong"]), 1.0))
        painter.drawRect(rect)
        painter.drawText(QPointF(rect.left() - 6.0, rect.top() - 4.0), f"{value_max:.3f}")
        painter.drawText(QPointF(rect.left() - 6.0, rect.bottom() + 14.0), f"{value_min:.3f}")

    def _map_x(self, x_mm: float, rect: QRectF) -> float:
        assert self._bed_width_mm is not None
        ratio = 0.0 if self._bed_width_mm == 0.0 else x_mm / self._bed_width_mm
        return rect.left() + (ratio * rect.width())

    def _map_y(self, y_mm: float, rect: QRectF) -> float:
        assert self._bed_height_mm is not None
        ratio = 0.0 if self._bed_height_mm == 0.0 else y_mm / self._bed_height_mm
        return rect.bottom() - (ratio * rect.height())

    def _screw_style(self, name: str) -> tuple[QPen, QColor]:
        status = self._screw_statuses.get(name)
        if status is None:
            return QPen(QColor(self._palette["screw"]), 1.2), QColor(self._palette["screw"])
        if not status.inside_bed or status.duplicate_with:
            return QPen(QColor(self._palette["screw_error"]), 1.4), QColor(self._palette["screw_error"])
        if status.inside_mesh is False:
            return QPen(QColor(self._palette["screw_warning"]), 1.4), QColor(self._palette["screw_warning"])
        return QPen(QColor(self._palette["screw"]), 1.2), QColor(self._palette["screw"])

    def _clamp_to_plot(self, value: float, minimum: float, maximum: float) -> float:
        return max(minimum + 4.0, min(maximum - 4.0, value))


def _cell_edges(coords: Sequence[float]) -> list[float]:
    if len(coords) == 1:
        return [coords[0] - 0.5, coords[0] + 0.5]
    edges = [coords[0] - ((coords[1] - coords[0]) / 2.0)]
    for left, right in zip(coords, coords[1:]):
        edges.append((left + right) / 2.0)
    edges.append(coords[-1] + ((coords[-1] - coords[-2]) / 2.0))
    return edges


def _interpolate_color(value: float, minimum: float, maximum: float, palette: dict[str, str]) -> QColor:
    if maximum <= minimum:
        return QColor(palette["mesh_empty"])
    ratio = (value - minimum) / (maximum - minimum)
    ratio = max(0.0, min(1.0, ratio))
    if ratio <= 0.5:
        return _blend(QColor(palette["mesh_low"]), QColor(palette["mesh_mid"]), ratio / 0.5)
    return _blend(QColor(palette["mesh_mid"]), QColor(palette["mesh_high"]), (ratio - 0.5) / 0.5)


def _blend(start: QColor, end: QColor, ratio: float) -> QColor:
    inverse = 1.0 - ratio
    return QColor(
        int((start.red() * inverse) + (end.red() * ratio)),
        int((start.green() * inverse) + (end.green() * ratio)),
        int((start.blue() * inverse) + (end.blue() * ratio)),
    )
