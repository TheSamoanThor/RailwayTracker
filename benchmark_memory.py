"""
Сравнение потребления памяти между Python- и Java-реализацией.

Три независимые метрики:
  1. peak_tracemalloc — пик Python-аллокаций во время вызова функции
     (только Python-объекты; JNI-массивы не видны, это ожидаемо);
  2. rss_fixed_jvm — фиксированная стоимость запуска JVM (RSS до/после startJVM);
  3. rss_delta_call — дельта RSS на один вызов после прогрева.

Запуск:
    python benchmark_memory.py
    python benchmark_memory.py --sizes 100 1000 5000 --reps 5
"""

import argparse
import gc
import os
import random
import sys
import tracemalloc

try:
    import psutil
except ImportError:
    sys.exit(
        "psutil не установлен. Выполните: pip install psutil"
    )

from geo_logic import filter_outliers
from java_geo_bridge import filter_outliers_java, init_jvm, is_java_available


PROC = psutil.Process(os.getpid())


def rss_mb() -> float:
    """Текущий RSS процесса в МБ. gc.collect() перед вызовом — стабильнее."""
    gc.collect()
    return PROC.memory_info().rss / 1024 / 1024


def gen_points(n: int, seed: int = 42):
    rng = random.Random(seed)
    return [(i, rng.uniform(40, 80), rng.uniform(19, 180)) for i in range(n)]


def peak_tracemalloc(fn, pts, reps: int) -> float:
    """
    Пик Python-аллокаций за reps вызовов, в МБ.
    tracemalloc видит только Python-объекты: списки, float, int.
    Java-сторона через JNI — не видна (это ограничение метода, не бага).
    """
    gc.collect()
    tracemalloc.start()
    try:
        for _ in range(reps):
            fn(pts, 1.0)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak / 1024 / 1024


def rss_delta_call(fn, pts, reps: int) -> float:
    """
    Средняя дельта RSS на один вызов после прогрева, в МБ.
    gc.collect() до/после — снижает шум от сборщика мусора.
    """
    for _ in range(3):
        fn(pts, 1.0)  # прогрев JIT / кэшей CPU
    gc.collect()
    before = rss_mb()
    for _ in range(reps):
        fn(pts, 1.0)
    gc.collect()
    after = rss_mb()
    return (after - before) / reps


def measure_jvm_fixed_cost() -> float:
    """
    Фиксированная цена запуска JVM, в МБ.
    Замеряется однократно, до любых вызовов filter_outliers_java.
    Вызывать эту функцию ДО первого init_jvm().
    """
    before = rss_mb()
    if not init_jvm():
        raise RuntimeError("Не удалось запустить JVM")
    after = rss_mb()
    return after - before


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reps", type=int, default=5,
        help="Повторов на размер (по умолчанию 5 — как в benchmark_time.py)",
    )
    parser.add_argument(
        "--sizes", type=int, nargs="+",
        default=[100, 1000, 5000],
        help="Размеры выборок",
    )
    args = parser.parse_args()

    print(f"Python: {sys.executable}")
    print(f"Повторов на размер: {args.reps}")
    print()

    if not is_java_available():
        sys.exit(
            "Java-модуль недоступен. Проверьте JDK 17+ в PATH и JPype1."
        )

    # 1. Фиксированная цена запуска JVM — замеряем ОДИН раз, до первого вызова.
    #    Это отдельная, не зависимая от N метрика.
    jvm_cost = measure_jvm_fixed_cost()
    print(f"Фиксированная стоимость запуска JVM: {jvm_cost:+.1f} MB RSS\n")

    # 2. Прогрев JVM — чтобы дальнейшие rss_delta_call не включали
    #    однократную загрузку классов.
    warm = gen_points(100)
    for _ in range(10):
        filter_outliers_java(warm, 1.0)

    header = (
        f"{'N':>6}  "
        f"{'Python peak':>12}  {'Java peak':>10}  "
        f"{'ΔRSS Python':>12}  {'ΔRSS Java':>10}"
    )
    print(header)
    print("-" * len(header))

    for n in args.sizes:
        pts = gen_points(n)

        py_peak = peak_tracemalloc(filter_outliers, pts, args.reps)
        j_peak = peak_tracemalloc(filter_outliers_java, pts, args.reps)

        py_drss = rss_delta_call(filter_outliers, pts, args.reps)
        j_drss = rss_delta_call(filter_outliers_java, pts, args.reps)

        print(
            f"{n:>6}  "
            f"{py_peak:>10.3f} MB  {j_peak:>8.3f} MB  "
            f"{py_drss:>+10.3f} MB  {j_drss:>+8.3f} MB"
        )


if __name__ == "__main__":
    main()
