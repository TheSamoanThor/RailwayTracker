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

from simulation import position_at, train_position


# ═══════════════════════════════════════════════
# Карта для админа: вся сеть + аномалии
# ═══════════════════════════════════════════════

def build_rail_map(center: tuple, trains: list, valid_ids: list,
                   avg_distance: float, threshold: float, multiplier: float,
                   now=None, simulation_enabled: bool = True):
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

    for t in trains:
        t_id, t_num = t[0], t[1]
        route, cargo = t[4], t[5]
        teu_cap, teu_used = t[6], t[7]

        lat, lon, _prog, _eta, _tot, _trv = train_position(
            t, simulation_enabled=simulation_enabled, now=now
        )

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


def render_map(map_obj, height: int = 530):
    """Рендерит карту Folium в Streamlit."""
    st_folium(map_obj, width=None, height=height, returned_objects=[])


# ═══════════════════════════════════════════════
# Карта для клиента: один поезд
# ═══════════════════════════════════════════════

def build_single_train_map(train_row, popup_title: str = "Поезд",
                           now=None, simulation_enabled: bool = True):
    """
    Карта с одной позицией (для клиента) — без остальных составов.
    train_row: кортеж из find_request_by_tracker / get_train_by_id
    Возвращает (map, progress, eta_min, total_km, traveled_km).
    """
    # Разбираем кортеж: первые 9 полей — общие, дальше — маршрут
    (t_id, t_num, lat, lon, route, cargo,
     teu_cap, teu_used, src,
     f_lat, f_lon, t_lat, t_lon, speed, departed) = train_row

    # Используем новую универсальную функцию из simulation.py
    lat, lon, prog, eta, tot, trv = train_position(
        train_row, simulation_enabled=simulation_enabled, now=now
    )

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


def render_client_tracking(req_row, incident=None, now=None,
                           simulation_enabled: bool = True):
    """
    Экран клиента: информация о заказе + карта + метрики + инцидент.
    req_row — результат find_request_by_tracker.
    incident — результат get_active_incident() или None.
    """
    (rid, tracker, client, route, cargo, teu, status,
     train_id, num, lat, lon,
     f_lat, f_lon, t_lat, t_lon, speed, departed) = req_row

    st.subheader(f"Заказ {tracker}")
    st.write(f"**Клиент:** {client}")
    st.write(f"**Маршрут:** {route}")
    st.write(f"**Груз:** {cargo}, **{teu} TEU**")
    st.write(f"**Статус:** {status}")

    if incident:
        st.error(
            f"**Инцидент:** {incident[2]} ({incident[4]})\n\n"
            f"{incident[3] or '—'}\n\n"
            f"_Зафиксировано: {incident[5]}_"
        )
    else:
        st.success("Активных инцидентов по составу нет.")

    if train_id is None:
        st.warning("Состав ещё не назначен — заявка ожидает агрегации. "
                   "Позиция появится после формирования поезда.")
        return

    train_row = (train_id, num, lat, lon, route, cargo,
                 0, 0, "db",
                 f_lat, f_lon, t_lat, t_lon, speed, departed)

    m, prog, eta, tot, trv = build_single_train_map(
        train_row, f"Заказ {tracker}",
        now=now, simulation_enabled=simulation_enabled
    )
    st_folium(m, width=850, height=460, returned_objects=[])

    if not simulation_enabled:
        st.caption("Симуляция движения выключена: показана последняя сохранённая координата.")

    c1, c2, c3 = st.columns(3)
    c1.metric("Пройдено", f"{trv:.0f} км")
    c2.metric("Осталось", f"{max(tot - trv, 0):.0f} км")
    c3.metric("ETA", f"{eta:.0f} мин")
    st.progress(min(max(prog, 0.0), 1.0))


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
        width="stretch",
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


# ═══════════════════════════════════════════════
# Происшествия (админ)
# ═══════════════════════════════════════════════

def render_incident_manager(conn, trains: list, valid_ids: list):
    """
    Модуль обработки аномалий у диспетчера:
    выбор состава, фиксация того, что случилось, запись в БД.
    Клиент увидит инцидент при вводе трекера.
    """
    from config import INCIDENT_TYPES
    from database import get_active_incident, get_incidents, report_train_incident

    st.subheader("Обработка аномалий и инцидентов")

    if not trains:
        st.info("Парк пуст — сначала добавьте состав.")
        return

    anomaly_ids = {t[0] for t in trains} - set(valid_ids)

    # По умолчанию показываем аномальные составы, если они есть
    default_trains = [t for t in trains if t[0] in anomaly_ids] or trains

    labels = {}
    for t in default_trains:
        mark = "Аномалия" if t[0] in anomaly_ids else "Норма"
        labels[f"{t[1]} — {t[4]} [{mark}]"] = t[0]

    picked_label = st.selectbox(
        "Выберите состав для обработки",
        list(labels.keys()),
        key="incident_train_select",
    )
    tid = labels[picked_label]

    active = get_active_incident(conn, tid)
    if active:
        st.warning(
            f"Активный инцидент: **{active[2]}** ({active[4]})\n\n"
            f"{active[3] or '—'}\n\n"
            f"Создан: {active[5]}"
        )
    else:
        st.success("Активных инцидентов нет.")

    with st.form("incident_form", clear_on_submit=True):
        itype = st.selectbox("Что произошло с составом", INCIDENT_TYPES)
        severity = st.selectbox(
            "Важность", ["info", "warning", "critical"], index=1
        )
        desc = st.text_area(
            "Комментарий диспетчера",
            placeholder="Например: состав задержан на перегоне...",
        )
        submitted = st.form_submit_button("Зафиксировать в БД")

        if submitted:
            report_train_incident(conn, tid, itype, desc.strip(), severity)
            st.success("Инцидент обновлён. Клиент увидит его при вводе трекера.")
            st.rerun()

    st.markdown("### Последние инциденты")
    rows = get_incidents(conn, limit=50)
    if rows:
        st.dataframe(
            [{
                "ID": r[0],
                "Поезд": r[1],
                "Тип": r[2],
                "Описание": r[3],
                "Важность": r[4],
                "Создан": r[5],
                "Закрыт": r[6] or "—",
                "Активен": "да" if r[7] else "нет",
            } for r in rows],
            width="stretch",
        )
    else:
        st.write("Инцидентов пока нет.")
