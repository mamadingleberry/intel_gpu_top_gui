import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from intel_gpu_top_gui.grid import (  # noqa: E402
    ASPECT, ROW_SPACING, Item, choose_columns, column_min, extra_heights, layout_quality)


def items(n, min_h=100, floor=50, weight=1.0):
    return [Item(min_h, floor, weight) for _ in range(n)]


class ColumnMathTest(unittest.TestCase):
    def test_column_min_includes_spacing(self):
        self.assertEqual(column_min(items(3)), 300 + 2 * ROW_SPACING)

    def test_extra_is_shared_by_weight(self):
        col = [Item(100, 50, 2.0), Item(100, 50, 1.0)]
        extra = extra_heights(col, 200 + ROW_SPACING + 300)
        self.assertEqual(extra, [200, 100])

    def test_no_extra_when_short(self):
        self.assertEqual(extra_heights(items(2), 50), [0, 0])


class QualityTest(unittest.TestCase):
    def test_overflow_is_negative(self):
        q = layout_quality([items(6)], 900, 400)
        self.assertEqual(q, -(column_min(items(6)) - 400))

    def test_height_beyond_aspect_does_not_count(self):
        q = layout_quality([items(1)], 300, 10_000)
        self.assertEqual(q, 300 / ASPECT)

    def test_two_columns_fit_a_quarter_tile(self):
        # Six sections that overflow a short window in one column fit in two.
        one = layout_quality([items(6)], 900, 500)
        two = layout_quality([items(3), items(3)], 441, 500)
        self.assertLess(one, 0)
        self.assertGreater(two, 0)
        self.assertEqual(choose_columns({1: one, 2: two}), 2)


class ChooseColumnsTest(unittest.TestCase):
    def test_prefers_fewer_columns_when_close(self):
        self.assertEqual(choose_columns({1: 100, 2: 105}), 1)

    def test_takes_more_columns_when_clearly_better(self):
        self.assertEqual(choose_columns({1: 60, 2: 200, 3: 210}), 2)

    def test_least_overflow_when_nothing_fits(self):
        self.assertEqual(choose_columns({1: -300, 2: -40}), 2)


if __name__ == "__main__":
    unittest.main()
