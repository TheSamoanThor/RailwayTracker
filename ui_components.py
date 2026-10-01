"""
Переиспользуемые UI-компоненты Streamlit.
Убирает дублирование кода из app.py.
"""

import folium
import streamlit as st
from streamlit_folium import st_folium


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

    # Слой железных дорог (методология статьи)
    folium.TileLayer(
        tiles="https://{s}.tiles.openrailmap.org/standard/{z}/{x}/{y}.png",
        attr='Map data: &copy; <a href="https://openstreetmap.org">OpenStreetMap</a> '
             '| Style: &copy; <a href="https://openrailmap.org">OpenRailMap</a>',
        name="Железные дороги",
        overlay=False,
        control=True,
    ).add_to(m)

    # Центр масс
    folium.Marker(
        location=[center[0], center[1]],
        popup=(f"<b>Центр масс грузопотока</b><br>"
               f"Среднее расстояние: {avg_distance:.3f}°<br>"
               f"Порог (×{multiplier}): {threshold:.3f}°"),
        icon=folium.Icon(color="blue", icon="info-sign"),
    ).add_to(m)

    # Поезда
    for t in trains:
        t_id, t_num, lat, lon, route, cargo, teu_cap, teu_used, _src = t
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


def render_train_manifest(train: tuple, is_valid: bool):
    """
    Карточка манифеста поезда (этап 2 бизнес-процесса: поиск по ID).
    train: кортеж из БД (id, num, lat, lon, route, cargo, teu_cap, teu_used, src)
    """
    (t_id, t_num, lat, lon, route, cargo, teu_cap, teu_used, src) = train
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