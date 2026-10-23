"""
Переиспользуемые UI-компоненты Streamlit.
Убирает дублирование кода из app.py.

Добавлены:
  • build_single_train_map — карта для клиента (один поезд)
  • render_client_tracking — экран слежения по трекеру
  • render_wagon_manifest — состав вагонов (админ)
"""

import folium
import streamlit as st
from streamlit_folium import st_folium

from simulation import position_at


# ═══════════════════════════════════════════════
# Карта для админа: вся сеть + аномалии
# ═══════════════════════════════════════════════

def build_rail_map(center: tuple, trains: list, valid_ids: list,
                   avg_distance: float, threshold: float, multiplier: float):
    """
    Строит карту Folium с:
      • слоем железных дорог OpenRailMap
      • маркером центра масс
      • маркерами поездов (зелёные — норма, красные — выбросы)
    """
    m = folium.Map(
        location=[center[0], center[1]],
        zoom_start=4,
        attribution_control=False,
    )

    folium.TileLayer(
        tiles="https://{s}.tiles.openrailmap.org/standard/{z}/{x}/{y}.png",
        attr='Map data: &copy; <a href="https://openstreetmap.org">OpenStreetMap</a> '
             '| Style: &copy; <a href="https://openrailmap.org">OpenRailMap</a>',
        name="Железные дороги",
        overlay=False,
        control=True,
    ).add_to(m)

    folium.Marker(
        location=[center[0], center[1]],
        popup=(f"<b>Центр масс грузопотока</b><br>"
               f"Среднее расстояние: {avg_distance:.3f}°<br>"
               f"Порог (×{multiplier}): {threshold:.3f}°"),
        icon=folium.Icon(color="blue", icon="info-sign"),
    ).add_to(m)

    # train tuple: (id, num, lat, lon, route, cargo, cap, used, src,
    #               f_lat, f_lon, t_lat, t_lon, speed, departed)
    for t in trains:
        t_id, t_num, lat, lon, route, cargo, teu_cap, teu_used, _src = t[:9]
        f_lat, f_lon, t_lat, t_lon, speed, departed = t[9:15]

        # Если есть данные маршрута — считаем позицию на момент «сейчас»
        if all(v is not None for v in (f_lat, f_lon, t_lat, t_lon, departed)):
            lat, lon, _prog, _eta, _tot, _trv = position_at(
                (f_lat, f_lon), (t_lat, t_lon), speed or 60, departed)

        is_valid = t_id in valid_ids
        color = "green" if is_valid else "red"
        status = "В пределах нормы" if is_valid else "Аномальное удаление"

        popup_html = (
            f"<b>Поезд №:</b> {t_num}<br>"
            f"<b>Статус:</b> {status}<br>"
            f"<b>Маршрут:</b> {route}<br>"
            f"<b>Груз:</b> {cargo}<br>"
            f"<b>Загрузка:</b> {teu_used}/{teu_cap} TEU"
        )
        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=320),
            icon=folium.Icon(color=color, icon="play" if is_valid else "stop"),
        ).add_to(m)

    return m


def render_map(map_obj, width: int = 850, height: int = 530):
    """Рендерит карту Folium в Streamlit."""
    st_folium(map_obj, width=width, height=height, returned_objects=[])


# ═══════════════════════════════════════════════
# Карта для клиента: один поезд
# ═══════════════════════════════════════════════

def build_single_train_map(train_row, popup_title: str = "Поезд"):
    """
    Карта с одной позицией (для клиента) — без остальных составов.
    train_row: кортеж из find_request_by_tracker / get_train_by_id
    Возвращает (map, progress, eta_min, total_km, traveled_km).
    """
    # Разбираем кортеж: первые 9 полей — общие, дальше — маршрут
    (t_id, t_num, lat, lon, route, cargo,
     teu_cap, teu_used, src,
     f_lat, f_lon, t_lat, t_lon, speed, departed) = train_row

    if all(v is not None for v in (f_lat, f_lon, t_lat, t_lon, departed)):
        lat, lon, prog, eta, tot, trv = position_at(
            (f_lat, f_lon), (t_lat, t_lon), speed or 60, departed)
    else:
        prog, eta, tot, trv = 1.0, 0.0, 0.0, 0.0

    m = folium.Map(location=[lat, lon], zoom_start=5,
                   attribution_control=False)

    folium.TileLayer(
        tiles="https://{s}.tiles.openrailmap.org/standard/{z}/{x}/{y}.png",
        attr="© OpenStreetMap | OpenRailMap",
        name="ЖД", overlay=False,
    ).add_to(m)

    folium.Marker(
        [lat, lon],
        popup=(f"<b>{popup_title} №{t_num}</b><br>"
               f"{route}<br>"
               f"Прогресс: {prog * 100:.1f}%<br>"
               f"Пройдено: {trv:.0f} / {tot:.0f} км"),
        icon=folium.Icon(color="blue", icon="train"),
    ).add_to(m)

    return m, prog, eta, tot, trv


def render_client_tracking(req_row):
    """
    Экран клиента: информация о заказе + карта + метрики.
    req_row — результат find_request_by_tracker.
    """
    (rid, tracker, client, route, cargo, teu, status,
     train_id, num, lat, lon,
     f_lat, f_lon, t_lat, t_lon, speed, departed) = req_row

    st.subheader(f"Заказ {tracker}")
    st.write(f"**Клиент:** {client}")
    st.write(f"**Маршрут:** {route}")
    st.write(f"**Груз:** {cargo}, **{teu} TEU**")
    st.write(f"**Статус:** {status}")

    if train_id is None:
        st.warning("Состав ещё не назначен — заявка ожидает агрегации. "
                   "Позиция появится после формирования поезда.")
        return

    # Собираем train_row в том же формате, что ждёт build_single_train_map
    train_row = (train_id, num, lat, lon, route, cargo,
                 0, 0, "db",
                 f_lat, f_lon, t_lat, t_lon, speed, departed)

    m, prog, eta, tot, trv = build_single_train_map(
        train_row, f"Заказ {tracker}")
    st_folium(m, width=850, height=460, returned_objects=[])

    c1, c2, c3 = st.columns(3)
    c1.metric("Пройдено", f"{trv:.0f} км")
    c2.metric("Осталось", f"{max(tot - trv, 0):.0f} км")
    c3.metric("ETA", f"{eta:.0f} мин")
    st.progress(prog)


# ═══════════════════════════════════════════════
# Манифест поезда (админ)
# ═══════════════════════════════════════════════

def render_train_manifest(train: tuple, is_valid: bool):
    """
    Карточка манифеста поезда (этап 2 бизнес-процесса: поиск по ID).
    train: (id, num, lat, lon, route, cargo, teu_cap, teu_used, src,
            f_lat, f_lon, t_lat, t_lon, speed, departed)
    """
    (t_id, t_num, lat, lon, route, cargo,
     teu_cap, teu_used, src) = train[:9]

    st.info(f"**Манифест состава {t_num}**")
    st.write(f"**Координаты:** {lat:.4f}, {lon:.4f}")
    st.write(f"**Источник координат:** {src}")
    st.write(f"**Маршрут:** {route}")
    st.write(f"**Груз:** {cargo}")
    st.write(f"**Загрузка:** {teu_used} / {teu_cap} TEU")
    st.progress(min(teu_used / max(teu_cap, 1), 1.0))

    if not is_valid:
        st.error("Состав вне основного транспортного коридора. "
                 "Возможен ложный сход с маршрута, задержка или угон.")


def render_wagon_manifest(wagons: list, train_num: str):
    """Таблица состава вагонов (админ)."""
    st.subheader(f"Состав вагонов поезда {train_num}")
    if not wagons:
        st.info("Вагоны ещё не добавлены.")
        return
    st.dataframe(
        [{"Позиция": w[1], "Вагон": w[0], "Груз": w[2],
          "Вес, т": w[3], "TEU": w[4], "Грузополучатель": w[5] or "—"}
         for w in wagons],
        use_container_width=True,
    )


# ═══════════════════════════════════════════════
# Аналитика (админ)
# ═══════════════════════════════════════════════

def render_analytics_panel(raw_trains: list, valid_ids: list,
                           threshold: float, avg_distance: float):
    """Правая панель с метриками и сводкой."""
    st.subheader("Аналитика и Манифест")
    st.metric("Порог отклонения (threshold)", f"{threshold:.3f}°")
    st.metric("Среднее расстояние в паре", f"{avg_distance:.3f}°")
    st.write(f"Всего составов в сети: **{len(raw_trains)}**")
    st.write(
        f"Штатно следуют: <span style='color:green'>**{len(valid_ids)}**</span>",
        unsafe_allow_html=True,
    )
    st.write(
        f"Аномалий: <span style='color:red'>"
        f"**{len(raw_trains) - len(valid_ids)}**</span>",
        unsafe_allow_html=True,
    )
    st.markdown("---")