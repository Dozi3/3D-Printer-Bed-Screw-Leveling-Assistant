from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, radians, sin
from typing import Sequence

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPolygonF
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QSizePolicy, QWidget

from models import EdgeReference, GeometryScrewStatus, MeshGrid
from widgets.heatmap_widget import DEFAULT_DRAWING_PALETTE


@dataclass(frozen=True)
class MeshVertex:
    row: int
    column: int
    x_mm: float
    y_mm: float
    z_mm: float


@dataclass(frozen=True)
class ProjectedVertex:
    vertex: MeshVertex
    screen_x: float
    screen_y: float
    depth: float


def build_mesh_vertices(mesh: MeshGrid, values: Sequence[Sequence[float]]) -> list[list[MeshVertex]]:
    x_coords = list(mesh.x_coordinates())
    y_coords = list(mesh.y_coordinates())
    rows = [[float(cell) for cell in row] for row in values]

    if len(x_coords) >= 2 and x_coords[0] > x_coords[-1]:
        x_coords.reverse()
        rows = [list(reversed(row)) for row in rows]
    if len(y_coords) >= 2 and y_coords[0] > y_coords[-1]:
        y_coords.reverse()
        rows.reverse()

    vertices: list[list[MeshVertex]] = []
    for row_index, row in enumerate(rows):
        vertices.append(
            [
                MeshVertex(
                    row=row_index,
                    column=column_index,
                    x_mm=float(x_coords[column_index]),
                    y_mm=float(y_coords[row_index]),
                    z_mm=float(value),
                )
                for column_index, value in enumerate(row)
            ]
        )
    return vertices


def mesh_value_range(vertices: Sequence[Sequence[MeshVertex]]) -> tuple[float, float]:
    values = [vertex.z_mm for row in vertices for vertex in row]
    if not values:
        return 0.0, 0.0
    return min(values), max(values)


def project_mesh_vertices(
    vertices: Sequence[Sequence[MeshVertex]],
    *,
    bed_width_mm: float,
    bed_height_mm: float,
    viewport_width_px: int,
    viewport_height_px: int,
    yaw_degrees: float,
    pitch_degrees: float,
    zoom: float,
    pan_x_px: float,
    pan_y_px: float,
    height_scale: float,
) -> list[list[ProjectedVertex]]:
    value_min, value_max = mesh_value_range(vertices)
    value_span = max(1e-9, value_max - value_min)
    value_mid = (value_min + value_max) / 2.0
    bed_span = max(1.0, bed_width_mm, bed_height_mm)
    scale = min(viewport_width_px, viewport_height_px) * 0.68 * max(0.2, zoom)
    centre_x = viewport_width_px / 2.0 + pan_x_px
    centre_y = viewport_height_px / 2.0 + pan_y_px
    yaw = radians(yaw_degrees)
    pitch = radians(pitch_degrees)
    yaw_cos = cos(yaw)
    yaw_sin = sin(yaw)
    pitch_cos = cos(pitch)
    pitch_sin = sin(pitch)

    projected_rows: list[list[ProjectedVertex]] = []
    for row in vertices:
        projected_row: list[ProjectedVertex] = []
        for vertex in row:
            x_norm = (vertex.x_mm - (bed_width_mm / 2.0)) / bed_span
            y_norm = (vertex.y_mm - (bed_height_mm / 2.0)) / bed_span
            z_norm = ((vertex.z_mm - value_mid) / value_span) * 0.32 * max(0.0, height_scale)

            yaw_x = (x_norm * yaw_cos) - (y_norm * yaw_sin)
            yaw_y = (x_norm * yaw_sin) + (y_norm * yaw_cos)
            pitch_y = (yaw_y * pitch_cos) - (z_norm * pitch_sin)
            depth = (yaw_y * pitch_sin) + (z_norm * pitch_cos)

            projected_row.append(
                ProjectedVertex(
                    vertex=vertex,
                    screen_x=centre_x + (yaw_x * scale),
                    screen_y=centre_y - (pitch_y * scale),
                    depth=depth,
                )
            )
        projected_rows.append(projected_row)
    return projected_rows


def nearest_projected_vertex(
    projected_rows: Sequence[Sequence[ProjectedVertex]],
    screen_x: float,
    screen_y: float,
    *,
    max_distance_px: float = 18.0,
) -> ProjectedVertex | None:
    nearest: ProjectedVertex | None = None
    nearest_distance = max_distance_px
    for row in projected_rows:
        for vertex in row:
            distance = hypot(vertex.screen_x - screen_x, vertex.screen_y - screen_y)
            if distance <= nearest_distance:
                nearest = vertex
                nearest_distance = distance
    return nearest


class Mesh3DWidget(QOpenGLWidget):
    inspectChanged = Signal(str)

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
        self._show_screws = True
        self._show_probe_bounds = True
        self._height_scale = 1.0
        self._yaw_degrees = -42.0
        self._pitch_degrees = 58.0
        self._zoom = 1.0
        self._pan_x_px = 0.0
        self._pan_y_px = 0.0
        self._last_mouse_pos: QPoint | None = None
        self._press_mouse_pos: QPoint | None = None
        self._last_projected: list[list[ProjectedVertex]] = []
        self._selected: ProjectedVertex | None = None
        self._inspect_text = "Click the 3D mesh to inspect X / Y / Z."
        self._palette = dict(DEFAULT_DRAWING_PALETTE)
        self.setMinimumSize(280, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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
        self._selected = None
        self._set_inspect_text("Click the 3D mesh to inspect X / Y / Z.")
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
        self._selected = None
        self._set_inspect_text("Click the 3D mesh to inspect X / Y / Z.")
        self.update()

    def set_height_scale(self, value: float) -> None:
        self._height_scale = max(0.0, float(value))
        self.update()

    def set_show_screws(self, enabled: bool) -> None:
        self._show_screws = bool(enabled)
        self.update()

    def set_show_probe_bounds(self, enabled: bool) -> None:
        self._show_probe_bounds = bool(enabled)
        self.update()

    def reset_view(self) -> None:
        self._yaw_degrees = -42.0
        self._pitch_degrees = 58.0
        self._zoom = 1.0
        self._pan_x_px = 0.0
        self._pan_y_px = 0.0
        self.update()

    def inspect_text(self) -> str:
        return self._inspect_text

    def paintGL(self) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(self._palette["mesh_background"]))

        if self._mesh is None or self._values is None or self._bed_width_mm is None or self._bed_height_mm is None:
            painter.setPen(QColor(self._palette["muted"]))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No 3D mesh loaded")
            painter.end()
            return

        vertices = build_mesh_vertices(self._mesh, self._values)
        projected = project_mesh_vertices(
            vertices,
            bed_width_mm=self._bed_width_mm,
            bed_height_mm=self._bed_height_mm,
            viewport_width_px=max(1, self.width() - 76),
            viewport_height_px=max(1, self.height() - 16),
            yaw_degrees=self._yaw_degrees,
            pitch_degrees=self._pitch_degrees,
            zoom=self._zoom,
            pan_x_px=self._pan_x_px - 34.0,
            pan_y_px=self._pan_y_px,
            height_scale=self._height_scale,
        )
        self._last_projected = projected
        value_min, value_max = mesh_value_range(vertices)

        self._draw_surface(painter, projected, value_min, value_max)
        if self._show_probe_bounds:
            self._draw_probe_bounds(painter, value_min, value_max)
        if self._show_screws:
            self._draw_screws(painter, value_min, value_max)
        self._draw_selected_point(painter)
        self._draw_front_rear_labels(painter)
        self._draw_legend(painter, value_min, value_max)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._last_mouse_pos = event.pos()
        self._press_mouse_pos = event.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._last_mouse_pos is None:
            self._last_mouse_pos = event.pos()
            return
        delta = event.pos() - self._last_mouse_pos
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._yaw_degrees += delta.x() * 0.45
            self._pitch_degrees = max(12.0, min(82.0, self._pitch_degrees + (delta.y() * 0.35)))
            self.update()
        elif event.buttons() & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton):
            self._pan_x_px += delta.x()
            self._pan_y_px += delta.y()
            self.update()
        self._last_mouse_pos = event.pos()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._press_mouse_pos is not None
            and (event.pos() - self._press_mouse_pos).manhattanLength() <= 5
        ):
            self._inspect_at(event.position().x(), event.position().y())
        self._last_mouse_pos = None
        self._press_mouse_pos = None

    def wheelEvent(self, event) -> None:  # noqa: N802
        direction = 1.0 if event.angleDelta().y() > 0 else -1.0
        self._zoom = max(0.35, min(3.5, self._zoom * (1.0 + (0.12 * direction))))
        self.update()

    def _draw_surface(
        self,
        painter: QPainter,
        projected: list[list[ProjectedVertex]],
        value_min: float,
        value_max: float,
    ) -> None:
        cells: list[tuple[float, QPolygonF, QColor]] = []
        for row_index in range(max(0, len(projected) - 1)):
            for column_index in range(max(0, len(projected[row_index]) - 1)):
                corners = [
                    projected[row_index][column_index],
                    projected[row_index][column_index + 1],
                    projected[row_index + 1][column_index + 1],
                    projected[row_index + 1][column_index],
                ]
                polygon = QPolygonF([QPointF(corner.screen_x, corner.screen_y) for corner in corners])
                average_value = sum(corner.vertex.z_mm for corner in corners) / 4.0
                average_depth = sum(corner.depth for corner in corners) / 4.0
                cells.append((average_depth, polygon, _interpolate_color(average_value, value_min, value_max, self._palette)))
        for _, polygon, color in sorted(cells, key=lambda item: item[0]):
            painter.setPen(QPen(QColor(self._palette["border_strong"]), 0.6))
            painter.setBrush(color)
            painter.drawPolygon(polygon)

    def _draw_probe_bounds(self, painter: QPainter, value_min: float, value_max: float) -> None:
        if self._probe_bounds is None or self._bed_width_mm is None or self._bed_height_mm is None:
            return
        x_min, x_max, y_min, y_max = self._probe_bounds
        if x_min <= 0.0 and y_min <= 0.0 and x_max >= self._bed_width_mm and y_max >= self._bed_height_mm:
            return
        z = value_min
        vertices = [
            MeshVertex(0, 0, x_min, y_min, z),
            MeshVertex(0, 1, x_max, y_min, z),
            MeshVertex(1, 1, x_max, y_max, z),
            MeshVertex(1, 0, x_min, y_max, z),
        ]
        projected = self._project_arbitrary_vertices(vertices, value_min, value_max)
        polygon = QPolygonF([QPointF(vertex.screen_x, vertex.screen_y) for vertex in projected])
        painter.setPen(QPen(QColor(self._palette["probe"]), 1.4, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(polygon)

    def _draw_screws(self, painter: QPainter, value_min: float, value_max: float) -> None:
        z = value_min
        vertices = [MeshVertex(0, index, x_mm, y_mm, z) for index, (_, x_mm, y_mm) in enumerate(self._screws)]
        projected = self._project_arbitrary_vertices(vertices, value_min, value_max)
        for projected_vertex, (name, _, _) in zip(projected, self._screws, strict=True):
            pen, brush = self._screw_style(name)
            painter.setPen(pen)
            painter.setBrush(brush)
            point = QPointF(projected_vertex.screen_x, projected_vertex.screen_y)
            painter.drawEllipse(point, 4.5, 4.5)
            painter.drawText(QPointF(point.x() + 7.0, point.y() - 6.0), name)

    def _draw_selected_point(self, painter: QPainter) -> None:
        if self._selected is None:
            return
        point = QPointF(self._selected.screen_x, self._selected.screen_y)
        painter.setPen(QPen(QColor(self._palette["border_strong"]), 1.5))
        painter.setBrush(QColor(self._palette["selected"]))
        painter.drawEllipse(point, 7.0, 7.0)

    def _draw_front_rear_labels(self, painter: QPainter) -> None:
        front_top = self._display_front_edge == "top"
        painter.setPen(QColor(self._palette["muted"]))
        painter.drawText(QRectF(14.0, 8.0, 120.0, 18.0), "Front" if front_top else "Rear")
        painter.drawText(QRectF(14.0, self.height() - 26.0, 120.0, 18.0), "Rear" if front_top else "Front")

    def _draw_legend(self, painter: QPainter, value_min: float, value_max: float) -> None:
        rect = QRectF(self.width() - 48.0, 20.0, 16.0, max(48.0, self.height() - 66.0))
        steps = 60
        for index in range(steps):
            top = rect.top() + (rect.height() * index / steps)
            bottom = rect.top() + (rect.height() * (index + 1) / steps)
            value = value_max - ((value_max - value_min) * index / max(1, steps - 1))
            painter.fillRect(QRectF(rect.left(), top, rect.width(), bottom - top), _interpolate_color(value, value_min, value_max, self._palette))
        painter.setPen(QPen(QColor(self._palette["border_strong"]), 1.0))
        painter.drawRect(rect)
        painter.drawText(QPointF(rect.left() - 8.0, rect.top() - 4.0), f"{value_max:.3f}")
        painter.drawText(QPointF(rect.left() - 8.0, rect.bottom() + 14.0), f"{value_min:.3f}")
        painter.drawText(QPointF(rect.left() - 22.0, rect.bottom() + 30.0), f"{self._height_scale:.1f}x")

    def _project_arbitrary_vertices(
        self,
        vertices: Sequence[MeshVertex],
        value_min: float,
        value_max: float,
    ) -> list[ProjectedVertex]:
        if self._bed_width_mm is None or self._bed_height_mm is None:
            return []
        rows = [list(vertices)]
        projected = project_mesh_vertices(
            rows,
            bed_width_mm=self._bed_width_mm,
            bed_height_mm=self._bed_height_mm,
            viewport_width_px=max(1, self.width() - 76),
            viewport_height_px=max(1, self.height() - 16),
            yaw_degrees=self._yaw_degrees,
            pitch_degrees=self._pitch_degrees,
            zoom=self._zoom,
            pan_x_px=self._pan_x_px - 34.0,
            pan_y_px=self._pan_y_px,
            height_scale=self._height_scale if value_max > value_min else 0.0,
        )
        return projected[0] if projected else []

    def _inspect_at(self, screen_x: float, screen_y: float) -> None:
        nearest = nearest_projected_vertex(self._last_projected, screen_x, screen_y)
        if nearest is None:
            return
        self._selected = nearest
        vertex = nearest.vertex
        self._set_inspect_text(f"X {vertex.x_mm:.2f} mm | Y {vertex.y_mm:.2f} mm | Z {vertex.z_mm:.4f} mm")
        self.update()

    def _set_inspect_text(self, text: str) -> None:
        self._inspect_text = text
        self.inspectChanged.emit(text)

    def _screw_style(self, name: str) -> tuple[QPen, QColor]:
        status = self._screw_statuses.get(name)
        if status is None:
            return QPen(QColor(self._palette["screw"]), 1.2), QColor(self._palette["screw"])
        if not status.inside_bed or status.duplicate_with:
            return QPen(QColor(self._palette["screw_error"]), 1.4), QColor(self._palette["screw_error"])
        if status.inside_mesh is False:
            return QPen(QColor(self._palette["screw_warning"]), 1.4), QColor(self._palette["screw_warning"])
        return QPen(QColor(self._palette["screw"]), 1.2), QColor(self._palette["screw"])


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
