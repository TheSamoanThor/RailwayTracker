"""
Клиент OpenStreetMap: Nominatim + Overpass + локальный справочник.
Каскадный поиск станций с кэшированием в SQLite.
"""

import json
import urllib.request
import urllib.parse
from typing import Optional, Tuple

from config import (
    RAIL_HUBS, OSM_USER_AGENT, NOMINATIM_URL, OVERPASS_URL,
    NOMINATIM_TIMEOUT, OVERPASS_TIMEOUT, RU_BBOX,
)


def _http_get_json(url: str, timeout: int) -> Optional[dict]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": OSM_USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def lookup_local(station_name: str) -> Optional[Tuple[float, float, str, str]]:
    key = station_name.strip().lower()
    if key in RAIL_HUBS:
        lat, lon = RAIL_HUBS[key]
        return lat, lon, "локальный справочник", station_name
    return None


def lookup_nominatim(station_name: str) -> Optional[Tuple[float, float, str, str]]:
    query = f"{station_name}, Россия"
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode({
        "q": query, "format": "json", "limit": 5,
        "countrycodes": "ru", "addressdetails": 1,
        "featuretype": "railway",
    })
    data = _http_get_json(url, NOMINATIM_TIMEOUT)
    if not data:
        return None
    for item in data:
        cls = (item.get("class") or "").lower()
        typ = (item.get("type") or "").lower()
        if cls == "railway" or typ in ("station", "halt", "stop", "junction"):
            return (float(item["lat"]), float(item["lon"]),
                    "Nominatim (OSM)", item.get("display_name", station_name))
    item = data[0]
    return (float(item["lat"]), float(item["lon"]),
            "Nominatim (OSM)", item.get("display_name", station_name))


def lookup_overpass(station_name: str) -> Optional[Tuple[float, float, str, str]]:
    south, west, north, east = RU_BBOX
    query = f"""
    [out:json][timeout:{OVERPASS_TIMEOUT}];
    node["railway"~"station|halt"]["name"~"{station_name}",i]
        ({south},{west},{north},{east});
    out center 5;
    """
    url = OVERPASS_URL + "?" + urllib.parse.urlencode({"data": query})
    data = _http_get_json(url, OVERPASS_TIMEOUT)
    if not data:
        return None
    elements = data.get("elements", [])
    if not elements:
        return None
    el = elements[0]
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    if lat is None or lon is None:
        return None
    return (float(lat), float(lon),
            "Overpass (OSM)", el.get("tags", {}).get("name", station_name))


def find_station(station_name: str, conn=None) -> Optional[Tuple[float, float, str, str]]:
    """
    Каскадный поиск станции по возрастанию стоимости:
        0) кэш в SQLite (если передан conn)
        1) локальный справочник
        2) Nominatim (OSM)
        3) Overpass API

    Возвращает: (lat, lon, source, display_name) или None.
    """
    # Шаг 0: кэш
    if conn is not None:
        try:
            from database import get_cached_station, cache_station
            cached = get_cached_station(conn, station_name)
            if cached:
                lat, lon, src, disp = cached
                return (lat, lon, src + " (кэш)", disp)
        except Exception:
            pass

    # Шаги 1–3
    result = None
    for lookup in (lookup_local, lookup_nominatim, lookup_overpass):
        result = lookup(station_name)
        if result:
            break

    # Сохраняем в кэш
    if result and conn is not None:
        try:
            from database import cache_station
            lat, lon, src, disp = result
            cache_station(conn, station_name, lat, lon, src, disp)
        except Exception:
            pass

    return result
