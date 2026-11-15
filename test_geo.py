# to run: python -m unittest test_geo.py from venv

import unittest
from geo_logic import (
    compute_center_of_mass,
    average_pairwise_distance,
    filter_outliers,
)
from java_geo_bridge import filter_outliers_java


class TestGeoOutliers(unittest.TestCase):

    def test_empty_and_single_point(self):
        # Проверка пустого списка и списка из одной точки
        self.assertEqual(filter_outliers([], 1.5), ([], (0.0, 0.0), 0.0, 0.0))
        single = [(1, 55.75, 37.61)]
        valid, center, thresh, avg = filter_outliers(single, 1.5)
        self.assertEqual(valid, [1])
        self.assertEqual(center, (55.75, 37.61))
        self.assertEqual(thresh, 0.0)
        self.assertEqual(avg, 0.0)

    def test_known_coordinates_math(self):
        # Проверка точных математических значений на 3 точках
        points = [
            (10, 0.0, 0.0),
            (20, 0.0, 3.0),
            (30, 4.0, 0.0),
        ]
        # Попарные расстояния: 3.0, 4.0 и 5.0 -> среднее = 4.0
        self.assertAlmostEqual(average_pairwise_distance(points), 4.0, places=6)
        lat, lon = compute_center_of_mass(points)
        self.assertAlmostEqual(lat, 4.0 / 3.0, places=6)
        self.assertAlmostEqual(lon, 1.0, places=6)

    def test_outlier_detection(self):
        # 4 поезда в Московском узле и 1 явный выброс во Владивостоке
        trains = [
            (1, 55.75, 37.61),
            (2, 55.80, 37.55),
            (3, 55.70, 37.70),
            (4, 55.78, 37.65),
            (5, 43.11, 131.88),  # Выброс
        ]
        valid_ids, _, _, _ = filter_outliers(trains, multiplier=1.0)
        self.assertEqual(valid_ids, [1, 2, 3, 4])
        self.assertNotIn(5, valid_ids)

    def test_python_java_consistency(self):
        # Сверка идентичности результатов Python и Java через JPype
        trains = [
            (101, 55.75, 37.61),
            (102, 59.93, 30.33),
            (103, 56.83, 60.60),
            (104, 43.11, 131.88),
        ]
        py_ids, py_c, py_t, py_a = filter_outliers(trains, 1.2)
        jv_ids, jv_c, jv_t, jv_a = filter_outliers_java(trains, 1.2)
        self.assertEqual(py_ids, jv_ids)
        self.assertAlmostEqual(py_c[0], jv_c[0], places=6)
        self.assertAlmostEqual(py_c[1], jv_c[1], places=6)
        self.assertAlmostEqual(py_t, jv_t, places=6)
        self.assertAlmostEqual(py_a, jv_a, places=6)


if __name__ == "__main__":
    unittest.main()
