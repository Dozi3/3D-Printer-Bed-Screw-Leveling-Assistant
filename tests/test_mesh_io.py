from __future__ import annotations

import unittest

from mesh_io import MeshInputError, build_mesh_grid, parse_text_grid


class MeshIoTests(unittest.TestCase):
    def test_parse_csv_grid(self) -> None:
        values = parse_text_grid("1, 2, 3\n4, 5, 6")
        self.assertEqual(values, [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])

    def test_parse_whitespace_grid(self) -> None:
        values = parse_text_grid("1 2 3\n4 5 6")
        self.assertEqual(values, [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])

    def test_reject_non_rectangular_grid(self) -> None:
        with self.assertRaises(MeshInputError):
            parse_text_grid("1,2\n3,4,5")

    def test_reject_empty_csv_cell(self) -> None:
        with self.assertRaises(MeshInputError):
            parse_text_grid("1,,2\n3,4,5")

    def test_row_order_handling(self) -> None:
        grid = build_mesh_grid([[1.0, 2.0], [3.0, 4.0]], 0.0, 10.0, 0.0, 20.0, top_row_is_y_max=True)
        self.assertEqual(grid.y_coordinates().tolist(), [20.0, 0.0])

        flipped = build_mesh_grid([[1.0, 2.0], [3.0, 4.0]], 0.0, 10.0, 0.0, 20.0, top_row_is_y_max=False)
        self.assertEqual(flipped.y_coordinates().tolist(), [0.0, 20.0])

    def test_bounds_validation(self) -> None:
        with self.assertRaises(MeshInputError):
            build_mesh_grid([[1.0, 2.0], [3.0, 4.0]], 10.0, 0.0, 0.0, 20.0)


if __name__ == "__main__":
    unittest.main()
