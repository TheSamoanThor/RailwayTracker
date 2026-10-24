"""
Симуляция движения поезда между двумя узловыми станциями.
Модель: равномерное прямолинейное движение по отрезку
(линейная интерполяция координат).
"""

import math
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

EARTH_R_KM = 6371.0


def haversine_km(lat1: float, lon1: float,
                 lat2: float, lon2: float) -> float:
    """Расстояние между двумя точками на сфере (км)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def interpolate(lat0: float, lon0: float,
                lat1: float, lon1: float,
                frac: float) -> Tuple[float, float]:
    """Линейная интерполяция координат (frac from [0, 1])."""
    frac = max(0.0, min(1.0, frac))
    return (lat0 + (lat1 - lat0) * frac, lon0 + (lon1 - lon0) * frac)


def position_at(route_from: Tuple[float, float],
                route_to: Tuple[float, float],
                avg_speed_kmh: float,
                departed_at_iso: str,
                now: Optional[datetime] = None):
    """
    Вычисляет текущую позицию поезда.

    Возвращает:
        (lat, lon, progress [0..1], eta_minutes, total_km, traveled_km)
    Если маршрут вырожден или время отправления некорректно —
    возвращает конечную точку с progress=1.0.
    """
    now = now or datetime.now(timezone.utc)

    try:
        departed = datetime.fromisoformat(departed_at_iso)
    except (TypeError, ValueError):
        return (route_to[0], route_to[1], 1.0, 0.0, 0.0, 0.0)

    if departed.tzinfo is None:
        departed = departed.replace(tzinfo=timezone.utc)

    total_km = haversine_km(route_from[0], route_from[1],
                            route_to[0], route_to[1])
    if total_km < 1e-6:
        return (route_to[0], route_to[1], 1.0, 0.0, 0.0, 0.0)

    elapsed_h = max(0.0, (now - departed).total_seconds() / 3600.0)
    traveled_km = min(total_km, avg_speed_kmh * elapsed_h)
    progress = traveled_km / total_km
    eta_min = max(0.0, (total_km - traveled_km) / max(avg_speed_kmh, 0.1) * 60.0)

    lat, lon = interpolate(route_from[0], route_from[1],
                           route_to[0], route_to[1], progress)
    return lat, lon, progress, eta_min, total_km, traveled_km


def simulation_now(offset_minutes: float = 0.0) -> datetime:
    """
    Текущее «время симуляции»:
    реальное UTC-время + сдвиг в минутах.
    """
    return datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)


def train_position(train_row, simulation_enabled: bool = True,
                   now: Optional[datetime] = None):
    """
    Универсальная функция позиции для кортежа поезда из get_all_trains():

    train_row = (
        id, train_number, lat, lon, route, cargo_type,
        teu_capacity, teu_used, station_src,
        route_from_lat, route_from_lon,
        route_to_lat, route_to_lon,
        avg_speed_kmh, departed_at
    )

    Если симуляция выключена или маршрут не задан — возвращает
    сохранённые lat/lon и нулевой прогресс.
    """
    (t_id, t_num, lat, lon, route, cargo,
     teu_cap, teu_used, src,
     f_lat, f_lon, t_lat, t_lon, speed, departed) = train_row

    if not simulation_enabled:
        return lat, lon, 0.0, 0.0, 0.0, 0.0

    if all(v is not None for v in (f_lat, f_lon, t_lat, t_lon, departed)):
        return position_at(
            (f_lat, f_lon),
            (t_lat, t_lon),
            speed or 60.0,
            departed,
            now=now,
        )

    return lat, lon, 0.0, 0.0, 0.0, 0.0
