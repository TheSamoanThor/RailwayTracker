# java_geo_bridge.py
"""
Мост между Python и JVM (JPype).
- Автоматически компилирует GeoAnalyzer.java через javac, если нужно.
- Возвращает все метрики (center, avg_dist, threshold) из Java,
  без повторного пересчёта в Python (иначе теряется выигрыш производительности).
- Безопасен при перезапусках Streamlit: проверяет jpype.isJVMStarted().
"""

import jpype
import jpype.imports
from jpype.types import JArray, JDouble
import os
import subprocess
import shutil
import logging

log = logging.getLogger(__name__)

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
JAVA_SRC = os.path.join(_MODULE_DIR, "GeoAnalyzer.java")
JAVA_CLASS_DIR = _MODULE_DIR
JAVA_CLASS_FILE = os.path.join(JAVA_CLASS_DIR, "GeoAnalyzer.class")

_JVM_STARTED = False
_JAVA_AVAILABLE = False


def _find_javac() -> str | None:
    """Ищет javac в PATH или в JAVA_HOME."""
    javac = shutil.which("javac")
    if javac:
        return javac
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = os.path.join(java_home, "bin", "javac")
        if os.path.isfile(candidate):
            return candidate
    return None


def ensure_java_compiled() -> bool:
    """
    Гарантирует наличие и актуальность GeoAnalyzer.class.
    Перекомпилирует, если .java новее .class или .class отсутствует.
    """
    global _JAVA_AVAILABLE

    if os.path.isfile(JAVA_CLASS_FILE) and os.path.isfile(JAVA_SRC):
        try:
            if os.path.getmtime(JAVA_CLASS_FILE) >= os.path.getmtime(JAVA_SRC):
                _JAVA_AVAILABLE = True
                return True
            log.info("GeoAnalyzer.java новее .class — перекомпиляция")
        except OSError:
            pass  # mtime не удалось — компилируем заново

    if not os.path.isfile(JAVA_SRC):
        log.error("GeoAnalyzer.java не найден: %s", JAVA_SRC)
        return False

    javac = _find_javac()
    if not javac:
        log.error("javac не найден. Установите JDK 17+ и добавьте в PATH.")
        return False

    log.info("Компиляция %s...", JAVA_SRC)
    try:
        result = subprocess.run(
            [javac, "-encoding", "UTF-8", JAVA_SRC],
            cwd=JAVA_CLASS_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.error("Ошибка запуска javac: %s", exc)
        return False

    if result.returncode != 0:
        log.error("javac завершился с ошибкой:\n%s", result.stderr)
        return False

    if not os.path.isfile(JAVA_CLASS_FILE):
        log.error("После компиляции .class не появился")
        return False

    _JAVA_AVAILABLE = True
    log.info("GeoAnalyzer.class успешно создан")
    return True


def init_jvm(class_path: str | None = None) -> bool:
    """
    Запускает JVM (один раз за процесс).
    Безопасен при перезапусках Streamlit: если JVM уже запущена —
    просто возвращает True, не пытаясь запустить повторно.
    """
    global _JVM_STARTED

    if not ensure_java_compiled():
        return False

    # ВАЖНО: проверяем глобальное состояние JPype, а не только свой флаг.
    # Streamlit перезапускает скрипт сверху вниз при каждом взаимодействии —
    # локальный _JVM_STARTED может сброситься, а JVM в процессе остаётся.
    if jpype.isJVMStarted():
        _JVM_STARTED = True
        return True

    class_path = class_path or JAVA_CLASS_DIR
    try:
        jpype.startJVM(classpath=[class_path], convertStrings=False)
        _JVM_STARTED = True
        return True
    except Exception as exc:
        log.exception("Не удалось запустить JVM: %s", exc)
        return False


def is_java_available() -> bool:
    """Мягкая проверка доступности Java-модуля (для UI-toggle)."""
    return _JAVA_AVAILABLE or ensure_java_compiled()


def filter_outliers_java(points, multiplier):
    """
    Аналог geo_logic.filter_outliers, но через Java.

    points: список кортежей (id, lat, lon)
    multiplier: float

    Возвращает: (valid_ids, center_mass, threshold, avg_distance)
    """
    if not init_jvm():
        raise RuntimeError("Java-модуль недоступен")

    if not points:
        return [], (0.0, 0.0), 0.0, 0.0

    n = len(points)
    lats = [p[1] for p in points]
    lons = [p[2] for p in points]

    j_lats = JArray(JDouble)(lats)
    j_lons = JArray(JDouble)(lons)
    j_mult = JDouble(multiplier)

    GeoAnalyzer = jpype.JClass("GeoAnalyzer")
    result = GeoAnalyzer.filterOutliers(j_lats, j_lons, j_mult)

    # Все метрики получены из Java — Python-циклов больше не нужно.
    valid_indices = result.validIndices
    valid_ids = [points[int(i)][0] for i in valid_indices]

    center = (float(result.centerLat), float(result.centerLon))
    threshold = float(result.threshold)
    avg_dist = float(result.avgDist)

    return valid_ids, center, threshold, avg_dist
