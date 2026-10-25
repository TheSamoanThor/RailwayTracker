"""
Слой БД (SQLite, in-memory).
Отвечает только за хранение и CRUD-операции.
Бизнес-логика сюда НЕ проникает.

Схема расширена под:
роли (admin / client)
трекер-номера заказов
симуляцию движения (route_from/route_to, speed, departed_at)
состав вагонов (таблица wagons)
кэш найденных станций (station_cache) — для офлайн-повторов
загрузку локального справочника станций из GeoJSON
"""

import sqlite3
import secrets
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
import os
import atexit


def generate_tracker() -> str:
    """Генерирует уникальный трекер-номер вида RZ-2026-A1B2C3."""
    year = datetime.now(timezone.utc).year
    token = secrets.token_hex(3).upper()  # 6 hex-символов
    return f"RZ-{year}-{token}"


# ═══════════════════════════════════════════════
# НОВАЯ ФУНКЦИЯ: Безопасное закрытие БД
# ═══════════════════════════════════════════════
def close_db(conn: sqlite3.Connection) -> None:
    """Безопасно закрывает соединение с БД при завершении работы приложения."""
    try:
        conn.close()
    except Exception:
        pass


# Инициализация схемы
def init_db() -> sqlite3.Connection:
    """
    Создаёт схему БД согласно бизнес-процессу:
    container_trains — контейнерные поезда (активы)
    cargo_requests   — клиентские заявки на перевозку
    wagons           — вагоны в составе поезда
    station_cache    — кэш найденных станций (офлайн-повторы)
    train_incidents  — инциденты/аномалии по составам
    """
    # conn = sqlite3.connect(":memory:", check_same_thread=False)
    # cur = conn.cursor()

    # Указываем имя файла вместо ":memory:"
    db_filename = "data/transport.db" 
    
    # Проверяем, существовал ли файл до подключения
    is_new_db = not os.path.exists(db_filename)

    # check_same_thread=False обязателен для работы внутри Streamlit
    conn = sqlite3.connect(db_filename, check_same_thread=False)

    atexit.register(close_db, conn)

    # СТРОГО ВКЛЮЧАЕМ WAL-РЕЖИМ ДЛЯ ПАРАЛЛЕЛЬНОЙ РАБОТЫ ПОЛЬЗОВАТЕЛЕЙ
    conn.execute("PRAGMA journal_mode=WAL;")

    cur = conn.cursor()

    # Включаем поддержку внешних ключей (по умолчанию в SQLite она выключена)
    cur.execute("PRAGMA foreign_keys = ON")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS container_trains (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            train_number    TEXT UNIQUE NOT NULL,
            lat             REAL NOT NULL,
            lon             REAL NOT NULL,
            route           TEXT NOT NULL,
            cargo_type      TEXT NOT NULL,
            teu_capacity    INTEGER NOT NULL,
            teu_used        INTEGER NOT NULL DEFAULT 0,
            station_src     TEXT,
            route_from_lat  REAL,
            route_from_lon  REAL,
            route_to_lat    REAL,
            route_to_lon    REAL,
            avg_speed_kmh   REAL DEFAULT 60.0,
            departed_at     TEXT,
            route_path      TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cargo_requests (
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
        CREATE TABLE IF NOT EXISTS wagons (
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS station_cache (
            name       TEXT PRIMARY KEY,
            lat        REAL NOT NULL,
            lon        REAL NOT NULL,
            source     TEXT,
            display    TEXT,
            cached_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS train_incidents (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            train_id      INTEGER NOT NULL,
            incident_type TEXT NOT NULL,
            description   TEXT,
            severity      TEXT NOT NULL DEFAULT 'warning',
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            resolved_at   TEXT,
            is_active     INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (train_id) REFERENCES container_trains(id)
        )
    """)
    conn.commit()

    # Демо-заявки и трекеры для всех seed-составов.
    # Первая заявка — на клиента "client", чтобы работал раздел «Мои заявки».
    if is_new_db:
        # ИСПРАВЛЕНИЕ БАГА: Динамические даты отправления.
        # Поезда будут "в пути" прямо сейчас, а не прибудут мгновенно.
        now_utc = datetime.now(timezone.utc)
        
        d1 = (now_utc - timedelta(hours=12)).isoformat()
        d2 = (now_utc - timedelta(hours=6)).isoformat()
        d3 = (now_utc - timedelta(days=1)).isoformat()
        d4 = (now_utc - timedelta(hours=2)).isoformat()
        d5 = (now_utc - timedelta(hours=8)).isoformat()
        d7 = (now_utc - timedelta(hours=1)).isoformat()

        seed_trains = [
            ("102M", 55.0350, 82.8970, "Владивосток - Москва", "Бытовая техника и электроника", 120, 95, 43.1155, 131.8855, 55.7558, 37.6173, 65.0, d1),
            ("204Б", 56.8770, 60.5050, "Находка - Екатеринбург", "Автокомпоненты", 96, 60, 42.8244, 132.8870, 56.8389, 60.6057, 55.0, d2),
            ("088А", 56.0340, 93.1250, "Китай - Брест (Транзит)", "Одежда и текстиль", 144, 144, 43.1155, 131.8855, 52.0976, 23.7341, 70.0, d3),
            ("512В", 53.2120, 50.1830, "Хабаровск - Санкт-Петербург", "Промышленные станки", 80, 40, 48.4827, 135.0838, 59.9311, 30.3609, 60.0, d4),
            ("301Х", 54.9810, 73.3180, "Владивосток - Новосибирск", "Химикаты (танк-контейнеры)", 110, 75, 43.1155, 131.8855, 55.0084, 82.9357, 58.0, d5),
            ("999А_АНГАР", 64.0000, 80.0000, "Секретный маршрут", "Опасный спецгруз", 40, 40, None, None, None, None, 60.0, None),
            ("777Х_УГОН", 62.0300, 129.7400, "Иркутск - Якутск (Сбой)", "Продукты питания", 64, 64, 52.2870, 104.3050, 62.0281, 129.7326, 50.0, d7),
        ]
        cur.executemany("""
            INSERT INTO container_trains
                (train_number, lat, lon, route, cargo_type, teu_capacity, teu_used, station_src,
                 route_from_lat, route_from_lon, route_to_lat, route_to_lon, avg_speed_kmh, departed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'seed', ?, ?, ?, ?, ?, ?)
        """, seed_trains)

        demo_wagons = [
            (1, "WG-102M-01", 1, "Бытовая техника и электроника", 22.5, 40, "ООО «ТехноМир»"),
            (1, "WG-102M-02", 2, "Бытовая техника и электроника", 21.0, 35, "ООО «ЭлектроСбыт»"),
            (1, "WG-102M-03", 3, "Комплектующие", 18.0, 20, "АО «Завод №5»"),
            (2, "WG-204B-01", 1, "Автокомпоненты", 24.0, 30, "ООО «АвтоДеталь»"),
            (2, "WG-204B-02", 2, "Автокомпоненты", 23.5, 30, "ООО «АвтоДеталь»"),
            (3, "WG-088A-01", 1, "Одежда и текстиль", 22.0, 48, "ООО «МодаТранс»"),
            (4, "WG-512V-01", 1, "Промышленные станки", 25.0, 20, "АО «СтанкоИмпорт»"),
            (5, "WG-301X-01", 1, "Химикаты (танк-контейнеры)", 24.0, 25, "ООО «ХимТранс»"),
            (6, "WG-999A-01", 1, "Опасный спецгруз", 30.0, 20, "Спецполучатель"),
            (7, "WG-777X-01", 1, "Продукты питания", 20.0, 32, "ООО «ПродуктЛогистик»"),
        ]
        cur.executemany("""
            INSERT INTO wagons (train_id, wagon_no, position, cargo_type, weight_t, teu, consignee)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, demo_wagons)

        seed_requests = [
            ("RZ-2026-DEMO01", "client", "Владивосток - Москва", "Бытовая техника и электроника", 95, 1, "утверждена (в пути)"),
            ("RZ-2026-DEMO02", "ООО «АвтоДеталь»", "Находка - Екатеринбург", "Автокомпоненты", 60, 2, "прикреплена к составу"),
            ("RZ-2026-DEMO03", "ООО «ТекстильТранс»", "Китай - Брест (Транзит)", "Одежда и текстиль", 144, None, "на рассмотрении"),
            ("RZ-2026-DEMO04", "АО «СтанкоИмпорт»", "Хабаровск - Санкт-Петербург", "Промышленные станки", 40, 4, "прикреплена к составу"),
            ("RZ-2026-DEMO05", "ООО «ХимТранс»", "Владивосток - Новосибирск", "Химикаты (танк-контейнеры)", 75, None, "на рассмотрении"),
            ("RZ-2026-DEMO06", "Спецклиент", "Секретный маршрут", "Опасный спецгруз", 40, 6, "прикреплена к составу"),
            ("RZ-2026-DEMO07", "ООО «ПродуктЛогистик»", "Иркутск - Якутск (Сбой)", "Продукты питания", 64, 7, "прикреплена к составу"),
        ]
        cur.executemany("""
            INSERT INTO cargo_requests (tracker, client, route, cargo_type, teu_requested, train_id, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, seed_requests)

        seed_incidents = [
            (6, "Аварийная остановка", "Состав вне основного коридора, связь нестабильна.", "warning"),
            (7, "Угон / потеря контроля", "Состав отклонился от маршрута Иркутск — Якутск; требуется проверка диспетчера.", "critical"),
        ]
        cur.executemany("""
            INSERT INTO train_incidents (train_id, incident_type, description, severity, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, seed_incidents)

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
               avg_speed_kmh, departed_at, route_path
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
              departed_at: Optional[str] = None,
              route_path: Optional[list] = None) -> tuple[bool, str]:
    """
    Добавляет новый поезд.
    Возвращает (успех, сообщение).
    """
    try:
        cur = conn.cursor()
        if departed_at is None:
            departed_at = datetime.now(timezone.utc).isoformat()
            
        # Сериализуем список координат в JSON-строку
        import json
        path_json = json.dumps(route_path) if route_path else None

        cur.execute("""
            INSERT INTO container_trains
                (train_number, lat, lon, route, cargo_type,
                 teu_capacity, teu_used, station_src,
                 route_from_lat, route_from_lon, route_to_lat, route_to_lon,
                 avg_speed_kmh, departed_at, route_path)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (num, lat, lon, route, cargo, teu_capacity, station_src,
              from_lat, from_lon, to_lat, to_lon, speed_kmh, departed_at, path_json))
        conn.commit()
        return True, "OK"
    except sqlite3.IntegrityError:
        return False, "Поезд с таким номером уже зарегистрирован."


# ═══════════════════════════════════════════════
# CRUD: заявки
# ═══════════════════════════════════════════════

def _norm_route(route: str) -> str:
    """Нормализует маршрут для сравнения: регистр, пробелы, тире."""
    if not route:
        return ""
    route = route.replace("—", "-").replace("–", "-").replace("−", "-")
    return " ".join(route.lower().split())


def find_matching_train(conn, route: str, teu_requested: int):
    """
    Ищет поезд с тем же маршрутом (с нормализацией) и достаточной
    свободной ёмкостью. Сортировка: сначала самый «заполненный».
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT id, route, teu_capacity, teu_used
        FROM container_trains
        WHERE (teu_capacity - teu_used) >= ?
        ORDER BY (teu_capacity - teu_used) ASC
    """, (teu_requested,))

    target = _norm_route(route)
    for row in cur.fetchall():
        if _norm_route(row[1]) == target:
            return (row[0], row[2], row[3])
    return None


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
    """Создаёт новую клиентскую заявку со статусом 'на рассмотрении'."""
    tracker = generate_tracker()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cargo_requests (tracker, client, route, cargo_type, teu_requested, train_id, status)
        VALUES (?, ?, ?, ?, ?, NULL, 'на рассмотрении')
    """, (tracker, client, route, cargo, teu))
    conn.commit()
    return tracker


def get_pending_requests(conn) -> list:
    """Возвращает все заявки, ожидающие решения админа."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, tracker, client, route, cargo_type, teu_requested, created_at
        FROM cargo_requests WHERE status = 'на рассмотрении' ORDER BY id DESC
    """)
    return cur.fetchall()


def approve_request(conn, req_id: int, train_id: int, teu: int) -> None:
    """Утверждает заявку: привязывает к поезду, меняет статус и резервирует TEU."""
    cur = conn.cursor()
    # Увеличиваем загрузку поезда
    cur.execute("UPDATE container_trains SET teu_used = teu_used + ? WHERE id = ?", (teu, train_id))
    # Обновляем статус заявки
    cur.execute("""
        UPDATE cargo_requests 
        SET status = 'утверждена (распределена)', train_id = ? 
        WHERE id = ?
    """, (train_id, req_id))
    conn.commit()


def reject_request(conn, req_id: int) -> None:
    """Отклоняет заявку."""
    cur = conn.cursor()
    cur.execute("UPDATE cargo_requests SET status = 'отклонена' WHERE id = ?", (req_id,))
    conn.commit()


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
       from_lat, from_lon, to_lat, to_lon, speed, departed_at, route_path)
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT r.id, r.tracker, r.client, r.route, r.cargo_type,
               r.teu_requested, r.status,
               t.id, t.train_number, t.lat, t.lon,
               t.route_from_lat, t.route_from_lon,
               t.route_to_lat, t.route_to_lon,
               t.avg_speed_kmh, t.departed_at, t.route_path
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
# CRUD: проблемы
# ═══════════════════════════════════════════════


def report_train_incident(conn, train_id: int, incident_type: str,
                          description: str = "",
                          severity: str = "warning"):
    """
    Фиксирует инцидент по составу.
    Если incident_type == "В пределах нормы" — закрывает активные инциденты
    и не создаёт новый.
    Возвращает id нового инцидента или None.
    """
    cur = conn.cursor()

    # Закрываем предыдущие активные инциденты
    cur.execute("""
        UPDATE train_incidents
        SET is_active = 0, resolved_at = datetime('now')
        WHERE train_id = ? AND is_active = 1
    """, (train_id,))

    if incident_type.strip().lower() in ("в пределах нормы", "норма", "ok", "resolved"):
        conn.commit()
        return None

    cur.execute("""
        INSERT INTO train_incidents
            (train_id, incident_type, description, severity, is_active)
        VALUES (?, ?, ?, ?, 1)
    """, (train_id, incident_type, description, severity))
    conn.commit()
    return cur.lastrowid


def resolve_train_incidents(conn, train_id: int) -> None:
    """Закрывает все активные инциденты по составу."""
    cur = conn.cursor()
    cur.execute("""
        UPDATE train_incidents
        SET is_active = 0, resolved_at = datetime('now')
        WHERE train_id = ? AND is_active = 1
    """, (train_id,))
    conn.commit()


def get_active_incident(conn, train_id: int):
    """
    Возвращает активный инцидент по составу:
    (id, train_id, incident_type, description, severity, created_at)
    или None.
    """
    if train_id is None:
        return None
    cur = conn.cursor()
    cur.execute("""
        SELECT id, train_id, incident_type, description, severity, created_at
        FROM train_incidents
        WHERE train_id = ? AND is_active = 1
        ORDER BY id DESC
        LIMIT 1
    """, (train_id,))
    return cur.fetchone()


def get_incidents(conn, train_id: Optional[int] = None, limit: int = 50):
    """
    Журнал инцидентов.
    Если train_id=None — по всем составам.
    Возвращает:
    (id, train_number, incident_type, description, severity,
     created_at, resolved_at, is_active)
    """
    cur = conn.cursor()
    if train_id is None:
        cur.execute("""
            SELECT i.id, t.train_number, i.incident_type, i.description,
                   i.severity, i.created_at, i.resolved_at, i.is_active
            FROM train_incidents i
            JOIN container_trains t ON t.id = i.train_id
            ORDER BY i.id DESC
            LIMIT ?
        """, (limit,))
    else:
        cur.execute("""
            SELECT i.id, t.train_number, i.incident_type, i.description,
                   i.severity, i.created_at, i.resolved_at, i.is_active
            FROM train_incidents i
            JOIN container_trains t ON t.id = i.train_id
            WHERE i.train_id = ?
            ORDER BY i.id DESC
            LIMIT ?
        """, (train_id, limit))
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
