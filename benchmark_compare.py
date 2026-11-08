import time, random
from geo_logic import filter_outliers
from java_geo_bridge import filter_outliers_java, init_jvm

def gen(n): # генерация рандомных точек по двум координатам с учетом рф границ по долготе и широте (числа в скобках)
    return [(i, random.uniform(40, 80), random.uniform(19, 180)) for i in range(n)]

for n in (100, 500, 1000, 2000, 5000):
    pts = gen(n)
    # Python
    t0 = time.perf_counter()
    # считаем среднее время на 3 прогонах
    for _ in range(3):
        filter_outliers(pts, 1.0)
    t_py = (time.perf_counter() - t0) / 3
    # Java (warm-up + замер)
    init_jvm()
    filter_outliers_java(pts, 1.0)  # warm-up
    t0 = time.perf_counter()
    # считаем среднее время на 3 прогонах
    for _ in range(3):
        filter_outliers_java(pts, 1.0)
    t_java = (time.perf_counter() - t0) / 3
    print(f"N={n:5d}  Python={t_py*1000:8.3f} ms   Java={t_java*1000:8.3f} ms   "
          f"ускорение×{t_py/t_java:.2f}")
