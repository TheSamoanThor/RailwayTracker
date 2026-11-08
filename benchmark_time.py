"""
Сравнение времени выполнения фильтрации выбросов:
    Python-реализация (geo_logic.filter_outliers)
    vs
    Java-реализация (GeoAnalyzer через JPype).

Запуск:
    python benchmark_time.py
    python benchmark_time.py --reps 10
    python benchmark_time.py --sizes 100 500 1000 2000 5000
"""

import argparse
import random
import sys
import time

from geo_logic import filter_outliers
from java_geo_bridge import filter_outliers_java, init_jvm, is_java_available


def gen_points(n: int, seed: int = 42):
    """
    Детерминированный набор точек для воспроизводимости.
    Значения в скобках генерации точек - граничные значения широты/долготы для РФ
    """
    rng = random.Random(seed)
    return [(i, rng.uniform(40, 80), rng.uniform(19, 180)) for i in range(n)]


def time_call(fn, pts, reps: int) -> float:
    """
    Среднее время одного вызова fn(pts, 1.0) за reps прогонов, мс.
    Для более точных замеров делаем reps прогонов и берем среднее
    """
    t0 = time.perf_counter()
    for _ in range(reps):
        fn(pts, 1.0)
    return (time.perf_counter() - t0) / reps * 1000.0


def warm_up(fn, pts, calls: int = 3):
    """
    Прогрев перед замером.
    - JIT-компиляция Java: первые вызовы интерпретируются, потом компилируются.
    - Кэш CPU: горячий кэш даёт стабильные цифры.
    """
    for _ in range(calls):
        fn(pts, 1.0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reps", type=int, default=5,
        help="Количество повторов на каждый размер (по умолчанию 5)",
    )
    parser.add_argument(
        "--sizes", type=int, nargs="+",
        default=[100, 500, 1000, 2000, 5000],
        help="Размеры выборок",
    )
    args = parser.parse_args()

    print(f"Python: {sys.executable}")
    print(f"Повторов на размер: {args.reps}")
    print()

    if not is_java_available():
        sys.exit(
            "Java-модуль недоступен. Проверьте JDK 17+ в PATH и JPype1 "
            "(pip install -r requirements.txt)."
        )

    # Один глобальный прогрев JVM — до цикла по размерам.
    # Это убирает «холодный старт» из первого замера.
    init_jvm()
    warm_up(filter_outliers_java, gen_points(100), calls=10)

    print(f"{'N':>6}  {'Python, мс':>12}  {'Java, мс':>10}  {'ускорение':>10}")
    print("-" * 46)

    for n in args.sizes:
        pts = gen_points(n)

        # Отдельный прогрев под конкретный размер — стабильнее цифры.
        warm_up(filter_outliers, pts, calls=1)
        warm_up(filter_outliers_java, pts, calls=3)

        t_py = time_call(filter_outliers, pts, args.reps)
        t_java = time_call(filter_outliers_java, pts, args.reps)

        speedup = t_py / t_java if t_java > 0 else float("inf")
        print(f"{n:>6}  {t_py:>12.3f}  {t_java:>10.3f}  {speedup:>9.2f}×")


if __name__ == "__main__":
    main()
