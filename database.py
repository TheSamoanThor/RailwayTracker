"""
Слой БД (SQLite, in-memory).
Отвечает только за хранение и CRUD-операции.
Бизнес-логика сюда НЕ проникает.
"""

import sqlite3
from typing import Optional


# Инициализация схемы
def init_db() -> sqlite3.Connection:
    """
    Создаёт схему БД согласно бизнес-процессу:
      • container_trains — контейнерные поезда (активы)
      • cargo_requests   — клиентские заявки на перевозку
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE container_trains (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            train_number TEXT UNIQUE NOT NULL,
            lat          REAL NOT NULL,
            lon          REAL NOT NULL,
            route        TEXT NOT NULL,
            cargo_type   TEXT NOT NULL,
            teu_capacity INTEGER NOT NULL,
            teu_used     INTEGER NOT NULL DEFAULT 0,
            station_src  TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE cargo_requests (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            client        TEXT NOT NULL,
            route         TEXT NOT NULL,
            cargo_type    TEXT NOT NULL,
            teu_requested INTEGER NOT NULL,
            train_id      INTEGER,
            status        TEXT NOT NULL DEFAULT 'ожидает агрегации',
            FOREIGN KEY (train_id) REFERENCES container_trains(id)
        )
    """)

    # ─── Стартовый парк поездов на реальных ж/д узлах РФ ───
    seed_trains = [
        ("102M",       55.0350,  82.8970, "Владивосток - Москва",        "Бытовая техника и электроника", 120, 95),
        ("204Б",       56.8770,  60.5050, "Находка - Екатеринбург",      "Автокомпоненты",                 96, 60),
        ("088А",       56.0340,  93.1250, "Китай - Брест (Транзит)",     "Одежда и текстиль",             144, 144),
        ("512В",       53.2120,  50.1830, "Хабаровск - Санкт-Петербург", "Промышленные станки",            80, 40),
        ("301Х",       54.9810,  73.3180, "Владивосток - Новосибирск",   "Химикаты (танк-контейнеры)",    110, 75),
        ("999А_АНГАР", 64.0000,  80.0000, "Секретный маршрут",           "Опасный спецгруз",               40, 40),
        ("777Х_УГОН",  62.0300, 129.7400, "Иркутск - Якутск (Сбой)",     "Продукты питания",               64, 64),
    ]
    cur.executemany("""
        INSERT INTO container_trains
            (train_number, lat, lon, route, cargo_type, teu_capacity, teu_used, station_src)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'seed')
    """, seed_trains)

    conn.commit()
    return conn


# CRUD: поезда
def get_all_trains(conn) -> list:
    """Возвращает все поезда в виде списка кортежей."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, train_number, lat, lon, route, cargo_type,
               teu_capacity, teu_used, station_src
        FROM container_trains
    """)
    return cur.fetchall()


def add_train(conn, num: str, lat: float, lon: float, route: str,
              cargo: str, teu_capacity: int, station_src: str) -> tuple[bool, str]:
    """
    Добавляет новый поезд.
    Возвращает (успех, сообщение).
    """
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO container_trains
                (train_number, lat, lon, route, cargo_type,
                 teu_capacity, teu_used, station_src)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        """, (num, lat, lon, route, cargo, teu_capacity, station_src))
        conn.commit()
        return True, "OK"
    except sqlite3.IntegrityError:
        return False, "Поезд с таким номером уже зарегистрирован."


# CRUD: заявки
def find_matching_train(conn, route: str, teu_requested: int) -> Optional[tuple]:
    """
    Ищет поезд с тем же маршрутом и достаточной свободной ёмкостью.
    Сортировка: сначала самый «заполненный» (чтобы плотнее упаковывать).
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
                           teu: int, train_id: int) -> None:
    """Создаёт заявку, привязанную к существующему составу, и увеличивает загрузку."""
    cur = conn.cursor()
    cur.execute("UPDATE container_trains SET teu_used = teu_used + ? WHERE id = ?",
                (teu, train_id))
    cur.execute("""
        INSERT INTO cargo_requests
            (client, route, cargo_type, teu_requested, train_id, status)
        VALUES (?, ?, ?, ?, ?, 'прикреплена к составу')
    """, (client, route, cargo, teu, train_id))
    conn.commit()


def add_request_pending(conn, client: str, route: str, cargo: str, teu: int) -> None:
    """Создаёт заявку, ожидающую агрегации (нет подходящего состава)."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cargo_requests
            (client, route, cargo_type, teu_requested, train_id, status)
        VALUES (?, ?, ?, ?, NULL, 'ожидает агрегации')
    """, (client, route, cargo, teu))
    conn.commit()


def get_all_requests(conn) -> list:
    """Возвращает все заявки с присоединённым номером поезда (если есть)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT r.id, r.client, r.route, r.cargo_type, r.teu_requested,
               COALESCE(t.train_number, '—'), r.status
        FROM cargo_requests r
        LEFT JOIN container_trains t ON t.id = r.train_id
        ORDER BY r.id DESC
    """)
    return cur.fetchall()