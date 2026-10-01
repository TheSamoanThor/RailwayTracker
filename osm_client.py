"""
Клиент OpenStreetMap: Nominatim + Overpass + локальный справочник.
Реализует каскадный поиск станций согласно методологии
Geischberger et al. (2026) — работа с OSM-инфраструктурой.
"""

import json
import urllib.request
import urllib.parse
from typing import Optional, Tuple

from config import (
    RAIL_HUBS, OSM_USER_AGENT, NOMINATIM_URL, OVERPASS_URL,
    NOMINATIM_TIMEOUT, OVERPASS_TIMEOUT, RU_BBOX,
)


# Низкоуровневый HTTP-хелпер
def _http_get_json(url: str, timeout: int) -> Optional[dict]:
    """GET-запрос с корректным User-Agent (требование OSM)."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": OSM_USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


# Шаг 1: локальный справочник
def lookup_local(station_name: str) -> Optional[Tuple[float, float, str, str]]:
    """Поиск в локальном справочнике RAIL_HUBS (офлайн, мгновенно)."""
    key = station_name.strip().lower()
    if key in RAIL_HUBS:
        lat, lon = RAIL_HUBS[key]
        return lat, lon, "локальный справочник", station_name
    return None


# Шаг 2: Nominatim (OSM)
def lookup_nominatim(station_name: str) -> Optional[Tuple[float, float, str, str]]:
    """
    Поиск ж/д станции через официальный API Nominatim.
    Приоритет отдаётся объектам с class=railway.
    """
    query = f"{station_name}, Россия"
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "limit": 5,
        "countrycodes": "ru",
        "addressdetails": 1,
        "featuretype": "railway",
    })

    data = _http_get_json(url, NOMINATIM_TIMEOUT)
    if not data:
        return None

    # Приоритет — железнодорожные объекты
    for item in data:
        cls = (item.get("class") or "").lower()
        typ = (item.get("type") or "").lower()
        if cls == "railway" or typ in ("station", "halt", "stop", "junction"):
            return (float(item["lat"]), float(item["lon"]),
                    "Nominatim (OSM)", item.get("display_name", station_name))

    item = data[0]
    return (float(item["lat"]), float(item["lon"]),
            "Nominatim (OSM)", item.get("display_name", station_name))


# Шаг 3: Overpass API (fallback)
def lookup_overpass(station_name: str) -> Optional[Tuple[float, float, str, str]]:
    """
    Fallback через Overpass API: ищем railway=station|halt по имени.
    Работает по методике из статьи (OSM → Overpass-turbo API).
    """
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


# Публичная функция: каскадный поиск
def find_station(station_name: str) -> Optional[Tuple[float, float, str, str]]:
    """
    Каскадный поиск станции по возрастанию стоимости:
        1) локальный справочник (мгновенно, офлайн)
        2) Nominatim (OSM)
        3) Overpass API
    
    Возвращает: (lat, lon, source, display_name) или None.
    """
    for lookup in (lookup_local, lookup_nominatim, lookup_overpass):
        result = lookup(station_name)
        if result:
            return result
    return None