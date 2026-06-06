from __future__ import annotations

import csv
import math
from pathlib import Path

from models import MeshGrid


class MeshInputError(ValueError):
    pass


def parse_text_grid(text: str) -> list[list[float]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise MeshInputError("Mesh input is empty.")

    if any("," in line for line in lines):
        raw_rows = list(csv.reader(lines))
    elif any("\t" in line for line in lines):
        raw_rows = list(csv.reader(lines, delimiter="\t"))
    else:
        raw_rows = [line.split() for line in lines]

    rows: list[list[float]] = []
    expected_length: int | None = None

    for row_index, raw_row in enumerate(raw_rows, start=1):
        cells = [cell.strip() for cell in raw_row]
        if not cells:
            continue
        if any(cell == "" for cell in cells):
            raise MeshInputError(f"Mesh contains an empty cell on row {row_index}.")
        if expected_length is None:
            expected_length = len(cells)
        elif len(cells) != expected_length:
            raise MeshInputError("Mesh rows must all have the same number of columns.")

        try:
            row = [float(cell) for cell in cells]
        except ValueError as exc:
            raise MeshInputError(f"Mesh contains a non-numeric value on row {row_index}.") from exc
        if any(not math.isfinite(cell) for cell in row):
            raise MeshInputError(f"Mesh contains a non-finite value on row {row_index}.")
        rows.append(row)

    _validate_grid_shape(rows)
    return rows


def load_csv_grid(path: str | Path) -> list[list[float]]:
    text = Path(path).read_text(encoding="utf-8")
    return parse_text_grid(text)


def build_mesh_grid(
    values: list[list[float]],
    x_min_mm: float,
    x_max_mm: float,
    y_min_mm: float,
    y_max_mm: float,
    top_row_is_y_max: bool = True,
) -> MeshGrid:
    _validate_grid_shape(values)
    for row in values:
        if any(not math.isfinite(float(cell)) for cell in row):
            raise MeshInputError("Mesh values must be finite numbers.")
    for label, value in (
        ("x_min_mm", x_min_mm),
        ("x_max_mm", x_max_mm),
        ("y_min_mm", y_min_mm),
        ("y_max_mm", y_max_mm),
    ):
        if not math.isfinite(float(value)):
            raise MeshInputError(f"{label} must be a finite number.")
    if x_min_mm >= x_max_mm or y_min_mm >= y_max_mm:
        raise MeshInputError("Mesh bounds must satisfy x_min < x_max and y_min < y_max.")

    return MeshGrid(
        z_values=[[float(cell) for cell in row] for row in values],
        x_min_mm=float(x_min_mm),
        x_max_mm=float(x_max_mm),
        y_min_mm=float(y_min_mm),
        y_max_mm=float(y_max_mm),
        top_row_is_y_max=top_row_is_y_max,
    )


def _validate_grid_shape(values: list[list[float]]) -> None:
    if not values:
        raise MeshInputError("Mesh input is empty.")
    if len(values) < 2:
        raise MeshInputError("Mesh must contain at least 2 rows.")
    column_count = len(values[0])
    if column_count < 2:
        raise MeshInputError("Mesh must contain at least 2 columns.")
    for row in values:
        if len(row) != column_count:
            raise MeshInputError("Mesh rows must all have the same number of columns.")
