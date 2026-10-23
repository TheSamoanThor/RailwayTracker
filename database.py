"""
Слой БД (SQLite, in-memory).
Отвечает только за хранение и CRUD-операции.
Бизнес-логика сюда НЕ проникает.

Схема расширена под:
  • роли (admin / client)
  • трекер-номера заказов
  • симуляцию движения (route_from/route_to, speed, departed_at)
  • состав вагонов (таблица wagons)
  • кэш найденных станций (station_cache) — для офлайн-повторов
  • загрузку локального справочника станций из GeoJSON
"""

import sqlite3
import secrets
import json
from datetime import datetime, timezone
from typing import Optional


def generate_tracker() -> str:
    """Генерирует уникальный трекер-номер вида RZ-2026-A1B2C3."""
    year = datetime.now(timezone.utc).year
    token = secrets.token_hex(3).upper()  # 6 hex-символов
    return f"RZ-{year}-{token}"


# Инициализация схемы
def init_db() -> sqlite3.Connection:
    """
    Создаёт схему БД согласно бизнес-процессу:
    container_trains — контейнерные поезда (активы)
    cargo_requests   — клиентские заявки на перевозку
    wagons           — вагоны в составе поезда
    station_cache    — кэш найденных станций (офлайн-повторы)
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE container_trains (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            train_number    TEXT UNIQUE NOT NULL,
            lat             REAL NOT NULL,
            lon             REAL NOT NULL,
            route           TEXT NOT NULL,
            cargo_type      TEXT NOT NULL,
            teu_capacity    INTEGER NOT NULL,
            teu_used        INTEGER NOT NULL DEFAULT 0,
            station_src     TEXT,
            -- Симуляция движения:
            route_from_lat  REAL,
            route_from_lon  REAL,
            route_to_lat    REAL,
            route_to_lon    REAL,
            avg_speed_kmh   REAL DEFAULT 60.0,
            departed_at     TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE cargo_requests (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            tracker       TEXT UNIQUE NOT NULL,
            client        TEXT NOT NULL,
            route         TEXT NOT NULL,
            cargo_type    TEXT NOT NULL,
            teu_requested INTEGER NOT NULL,
            train_id      INTEGER,
            status        TEXT NOT NULL DEFAULT 'ожидает агрегации',
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (train_id) REFERENCES container_trains(id)
        )
    """)

    cur.execute("""
        CREATE TABLE wagons (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            train_id    INTEGER NOT NULL,
            wagon_no    TEXT NOT NULL,
            position    INTEGER NOT NULL,
            cargo_type  TEXT NOT NULL,
            weight_t    REAL NOT NULL,
            teu         INTEGER NOT NULL DEFAULT 0,
            consignee   TEXT,
            FOREIGN KEY (train_id) REFERENCES container_trains(id)
        )
    """)

    # Кэш станций: ключ — нормализованное имя, значение — координаты
    cur.execute("""
        CREATE TABLE station_cache (
            name       TEXT PRIMARY KEY,
            lat        REAL NOT NULL,
            lon        REAL NOT NULL,
            source     TEXT,
            display    TEXT,
            cached_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # ─── Стартовый парк поездов на реальных ж/д узлах РФ ───
    seed_trains = [
        # (num, lat, lon, route, cargo, cap, used,
        #  from_lat, from_lon, to_lat, to_lon, speed, departed_iso)
        ("102M", 55.0350, 82.8970, "Владивосток - Москва",
         "Бытовая техника и электроника", 120, 95,
         43.1155, 131.8855, 55.7558, 37.6173, 65.0,
         "2026-10-20T08:00:00+00:00"),

        ("204Б", 56.8770, 60.5050, "Находка - Екатеринбург",
         "Автокомпоненты", 96, 60,
         42.8244, 132.8870, 56.8389, 60.6057, 55.0,
         "2026-10-21T12:30:00+00:00"),

        ("088А", 56.0340, 93.1250, "Китай - Брест (Транзит)",
         "Одежда и текстиль", 144, 144,
         43.1155, 131.8855, 52.0976, 23.7341, 70.0,
         "2026-10-18T06:00:00+00:00"),

        ("512В", 53.2120, 50.1830, "Хабаровск - Санкт-Петербург",
         "Промышленные станки", 80, 40,
         48.4827, 135.0838, 59.9311, 30.3609, 60.0,
         "2026-10-22T04:15:00+00:00"),

        ("301Х", 54.9810, 73.3180, "Владивосток - Новосибирск",
         "Химикаты (танк-контейнеры)", 110, 75,
         43.1155, 131.8855, 55.0084, 82.9357, 58.0,
         "2026-10-19T18:00:00+00:00"),

        # Выбросы (специально для демонстрации фильтрации)
        ("999А_АНГАР", 64.0000, 80.0000, "Секретный маршрут",
         "Опасный спецгруз", 40, 40,
         None, None, None, None, 60.0, None),

        ("777Х_УГОН", 62.0300, 129.7400, "Иркутск - Якутск (Сбой)",
         "Продукты питания", 64, 64,
         52.2870, 104.3050, 62.0281, 129.7326, 50.0,
         "2026-10-23T00:00:00+00:00"),
    ]
    cur.executemany("""
        INSERT INTO container_trains
            (train_number, lat, lon, route, cargo_type, teu_capacity, teu_used,
             station_src, route_from_lat, route_from_lon,
             route_to_lat, route_to_lon, avg_speed_kmh, departed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'seed',
                ?, ?, ?, ?, ?, ?)
    """, seed_trains)

    # ─── Демо-вагоны для первых поездов ───
    demo_wagons = [
        (1, "WG-102M-01", 1, "Бытовая техника и электроника", 22.5, 40, "ООО «ТехноМир»"),
        (1, "WG-102M-02", 2, "Бытовая техника и электроника", 21.0, 35, "ООО «ЭлектроСбыт»"),
        (1, "WG-102M-03", 3, "Комплектующие", 18.0, 20, "АО «Завод №5»"),
        (2, "WG-204B-01", 1, "Автокомпоненты", 24.0, 30, "ООО «АвтоДеталь»"),
        (2, "WG-204B-02", 2, "Автокомпоненты", 23.5, 30, "ООО «АвтоДеталь»"),
    ]
    cur.executemany("""
        INSERT INTO wagons (train_id, wagon_no, position, cargo_type, weight_t, teu, consignee)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, demo_wagons)

    conn.commit()
    return conn


# ═══════════════════════════════════════════════
# CRUD: поезда
# ═══════════════════════════════════════════════

def get_all_trains(conn) -> list:
    """Возвращает все поезда в виде списка кортежей (с полями симуляции)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, train_number, lat, lon, route, cargo_type,
               teu_capacity, teu_used, station_src,
               route_from_lat, route_from_lon, route_to_lat, route_to_lon,
               avg_speed_kmh, departed_at
        FROM container_trains
    """)
    return cur.fetchall()


def get_train_by_id(conn, train_id: int):
    cur = conn.cursor()
    cur.execute("""
        SELECT id, train_number, lat, lon, route, cargo_type,
               teu_capacity, teu_used, station_src,
               route_from_lat, route_from_lon, route_to_lat, route_to_lon,
               avg_speed_kmh, departed_at
        FROM container_trains WHERE id = ?
    """, (train_id,))
    return cur.fetchone()


def add_train(conn, num: str, lat: float, lon: float, route: str,
              cargo: str, teu_capacity: int, station_src: str,
              from_lat: Optional[float] = None,
              from_lon: Optional[float] = None,
              to_lat: Optional[float] = None,
              to_lon: Optional[float] = None,
              speed_kmh: float = 60.0,
              departed_at: Optional[str] = None) -> tuple[bool, str]:
    """
    Добавляет новый поезд.
    Возвращает (успех, сообщение).
    """
    try:
        cur = conn.cursor()
        if departed_at is None:
            departed_at = datetime.now(timezone.utc).isoformat()
        cur.execute("""
            INSERT INTO container_trains
                (train_number, lat, lon, route, cargo_type,
                 teu_capacity, teu_used, station_src,
                 route_from_lat, route_from_lon, route_to_lat, route_to_lon,
                 avg_speed_kmh, departed_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
        """, (num, lat, lon, route, cargo, teu_capacity, station_src,
              from_lat, from_lon, to_lat, to_lon, speed_kmh, departed_at))
        conn.commit()
        return True, "OK"
    except sqlite3.IntegrityError:
        return False, "Поезд с таким номером уже зарегистрирован."


# ═══════════════════════════════════════════════
# CRUD: заявки
# ═══════════════════════════════════════════════

def find_matching_train(conn, route: str, teu_requested: int) -> Optional[tuple]:
    """
    Ищет поезд с тем же маршрутом и достаточной свободной ёмкостью.
    Сортировка: сначала самый «заполненный» (плотная упаковка).
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT id, teu_capacity, teu_used
        FROM container_trains
        WHERE route = ? AND (teu_capacity - teu_used) >= ?
        ORDER BY (teu_capacity - teu_used) ASC
        LIMIT 1
    """, (route, teu_requested))
    return cur.fetchone()


def add_request_aggregated(conn, client: str, route: str, cargo: str,
                           teu: int, train_id: int) -> str:
    """Создаёт заявку, привязанную к составу, и увеличивает загрузку.
    Возвращает сгенерированный tracker."""
    tracker = generate_tracker()
    cur = conn.cursor()
    cur.execute("UPDATE container_trains SET teu_used = teu_used + ? WHERE id = ?",
                (teu, train_id))
    cur.execute("""
        INSERT INTO cargo_requests
            (tracker, client, route, cargo_type, teu_requested, train_id, status)
        VALUES (?, ?, ?, ?, ?, ?, 'прикреплена к составу')
    """, (tracker, client, route, cargo, teu, train_id))
    conn.commit()
    return tracker


def add_request_pending(conn, client: str, route: str, cargo: str, teu: int) -> str:
    """Создаёт заявку, ожидающую агрегации. Возвращает tracker."""
    tracker = generate_tracker()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cargo_requests
            (tracker, client, route, cargo_type, teu_requested, train_id, status)
        VALUES (?, ?, ?, ?, ?, NULL, 'ожидает агрегации')
    """, (tracker, client, route, cargo, teu))
    conn.commit()
    return tracker


def get_all_requests(conn) -> list:
    """Возвращает все заявки с присоединённым номером поезда (если есть)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT r.id, r.tracker, r.client, r.route, r.cargo_type, r.teu_requested,
               COALESCE(t.train_number, '—'), r.status, r.created_at
        FROM cargo_requests r
        LEFT JOIN container_trains t ON t.id = r.train_id
        ORDER BY r.id DESC
    """)
    return cur.fetchall()


def find_request_by_tracker(conn, tracker: str):
    """
    Поиск заявки по трекер-номеру для клиентского экрана.
    Возвращает расширенный кортеж с полями поезда для симуляции:
      (req_id, tracker, client, route, cargo, teu, status,
       train_id, train_number, lat, lon,
       from_lat, from_lon, to_lat, to_lon, speed, departed_at)
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT r.id, r.tracker, r.client, r.route, r.cargo_type,
               r.teu_requested, r.status,
               t.id, t.train_number, t.lat, t.lon,
               t.route_from_lat, t.route_from_lon,
               t.route_to_lat, t.route_to_lon,
               t.avg_speed_kmh, t.departed_at
        FROM cargo_requests r
        LEFT JOIN container_trains t ON t.id = r.train_id
        WHERE UPPER(r.tracker) = UPPER(?)
    """, (tracker.strip(),))
    return cur.fetchone()


def get_client_requests(conn, client: str) -> list:
    """Все заявки конкретного клиента (для клиентского экрана)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT r.id, r.tracker, r.route, r.cargo_type, r.teu_requested,
               COALESCE(t.train_number, '—'), r.status, r.created_at
        FROM cargo_requests r
        LEFT JOIN container_trains t ON t.id = r.train_id
        WHERE LOWER(r.client) = LOWER(?)
        ORDER BY r.id DESC
    """, (client,))
    return cur.fetchall()


# ═══════════════════════════════════════════════
# CRUD: вагоны
# ═══════════════════════════════════════════════

def get_wagons(conn, train_id: int) -> list:
    """Список вагонов поезда, упорядоченный по позиции."""
    cur = conn.cursor()
    cur.execute("""
        SELECT wagon_no, position, cargo_type, weight_t, teu, consignee
        FROM wagons WHERE train_id = ? ORDER BY position
    """, (train_id,))
    return cur.fetchall()


def add_wagon(conn, train_id: int, wagon_no: str, position: int,
              cargo: str, weight_t: float, teu: int,
              consignee: str = "") -> None:
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO wagons
            (train_id, wagon_no, position, cargo_type, weight_t, teu, consignee)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (train_id, wagon_no, position, cargo, weight_t, teu, consignee))
    conn.commit()


def delete_wagon(conn, wagon_id: int) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM wagons WHERE id = ?", (wagon_id,))
    conn.commit()


# ═══════════════════════════════════════════════
# Кэш станций (для офлайн-повторов)
# ═══════════════════════════════════════════════

def get_cached_station(conn, name: str):
    """Возвращает (lat, lon, source, display) или None."""
    cur = conn.cursor()
    cur.execute("""
        SELECT lat, lon, source, display FROM station_cache
        WHERE LOWER(name) = LOWER(?)
    """, (name.strip(),))
    row = cur.fetchone()
    return row if row else None


def cache_station(conn, name: str, lat: float, lon: float,
                  source: str, display: str = "") -> None:
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO station_cache (name, lat, lon, source, display)
        VALUES (?, ?, ?, ?, ?)
    """, (name.strip().lower(), lat, lon, source, display))
    conn.commit()


# ═══════════════════════════════════════════════
# Импорт локального справочника станций (GeoJSON)
# ═══════════════════════════════════════════════

def load_stations_from_geojson(conn, geojson_path: str) -> int:
    """
    Загружает станции из GeoJSON в station_cache.
    Ожидает FeatureCollection с geometry.type == "Point"
    и properties.name (название станции).
    Возвращает количество загруженных записей.

    Формат координат GeoJSON: [lon, lat].
    """
    try:
        with open(geojson_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return 0

    features = data.get("features", [])
    if not features:
        return 0

    cur = conn.cursor()
    loaded = 0

    for feat in features:
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}

        if geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue

        name = (props.get("name") or props.get("name:ru") or "").strip()
        if not name:
            continue

        lon, lat = float(coords[0]), float(coords[1])
        cur.execute("""
            INSERT OR IGNORE INTO station_cache (name, lat, lon, source, display)
            VALUES (?, ?, ?, 'local_geojson', ?)
        """, (name.lower(), lat, lon, name))

        if cur.rowcount:
            loaded += 1

    conn.commit()
    return loaded


def count_cached_stations(conn) -> int:
    """Сколько станций доступно в локальном справочнике."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM station_cache")
    return cur.fetchone()[0]