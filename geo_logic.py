"""
Бизнес-логика выявления пространственных аномалий.
"""

import math
from typing import List, Tuple


def compute_center_of_mass(points: List[Tuple]) -> Tuple[float, float]:
    """Центр масс = среднее арифметическое координат всех точек."""
    if not points:
        return (0.0, 0.0)
    n = len(points)
    lat = sum(p[1] for p in points) / n
    lon = sum(p[2] for p in points) / n
    return (lat, lon)


def average_pairwise_distance(points: List[Tuple]) -> float:
    """Среднее евклидово расстояние между всеми парами точек."""
    n = len(points)
    if n < 2:
        return 0.0

    total = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            total += math.hypot(points[i][1] - points[j][1],
                                points[i][2] - points[j][2])
    return total / (n * (n - 1) / 2)


def filter_outliers(points: List[Tuple], multiplier: float):
    """
    Основная функция фильтрации.
    
    points: список кортежей (id, lat, lon)
    multiplier: множитель для порога
    
    Возвращает:
        (valid_ids, center_mass, threshold, avg_distance)
    """
    if not points:
        return [], (0.0, 0.0), 0.0, 0.0

    center = compute_center_of_mass(points)
    avg_dist = average_pairwise_distance(points)
    threshold = multiplier * avg_dist

    valid_ids = [
        p[0] for p in points
        if math.hypot(p[1] - center[0], p[2] - center[1]) <= threshold
    ]
    return valid_ids, center, threshold, avg_dist
