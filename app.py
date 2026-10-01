"""
Ситуационный центр: Контейнерные перевозки ЖД.
Точка входа: только Streamlit UI и оркестрация модулей.
Вся логика вынесена в отдельные модули.
"""

import time
import streamlit as st

# Импорт собственных модулей
from config import CARGO_TYPES
from database import (
    init_db, get_all_trains, add_train,
    find_matching_train, add_request_aggregated, add_request_pending,
    get_all_requests,
)
from geo_logic import filter_outliers
from osm_client import find_station
from ui_components import (
    build_rail_map, render_map, render_train_manifest, render_analytics_panel,
)

# Настройка страницы
st.set_page_config(
    layout="wide",
    page_title="Мониторинг контейнерных перевозок",
    page_icon="*",
)
st.title("Ситуационный центр: Контейнерные перевозки ЖД")

# Инициализация БД один раз за сессию
if "db_conn" not in st.session_state:
    st.session_state.db_conn = init_db()

conn = st.session_state.db_conn


# ВКЛАДКИ
tab_monitor, tab_request, tab_fleet = st.tabs([
    "Мониторинг сети и выявление аномалий",
    "Оформление заявок (этап 1)",
    "Парк составов и формирование поездов",
])

# Сайдбар: параметры фильтрации
st.sidebar.header("Параметры фильтрации")
multiplier = st.sidebar.slider(
    "Множитель расстояния (multiplier)",
    min_value=0.1, max_value=3.0, value=1.0, step=0.1,
)

# Общие данные для всех вкладок
raw_trains = get_all_trains(conn)
points_for_algo = [(t[0], t[2], t[3]) for t in raw_trains]
valid_ids, center, threshold, avg_dist = filter_outliers(points_for_algo, multiplier)


# ВКЛАДКА 1: МОНИТОРИНГ И ПОИСК
with tab_monitor:
    st.sidebar.header("Поиск состава")
    train_numbers = ["Все"] + [t[1] for t in raw_trains]
    selected = st.sidebar.selectbox(
        "Выберите номер поезда для вывода манифеста:", train_numbers,
    )

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Интерактивная карта движения")
        m = build_rail_map(center, raw_trains, valid_ids,
                           avg_dist, threshold, multiplier)
        render_map(m)

    with col2:
        render_analytics_panel(raw_trains, valid_ids, threshold, avg_dist)

        if selected != "Все":
            target = next(t for t in raw_trains if t[1] == selected)
            render_train_manifest(target, target[0] in valid_ids)
        else:
            st.write("*Выберите поезд слева для вывода манифеста.*")


# ВКЛАДКА 2: ОФОРМЛЕНИЕ ЗАЯВОК
with tab_request:
    st.subheader("Регистрация клиентской заявки на перевозку")
    st.caption("Согласно бизнес-процессу: заявка автоматически "
               "прикрепляется к подходящему по маршруту составу, "
               "если в нём есть свободная ёмкость (TEU).")

    with st.form("new_request", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            client = st.text_input("Клиент:", placeholder="ООО «Ромашка»")
            route = st.text_input("Маршрут:", placeholder="Владивосток - Москва")
        with c2:
            cargo = st.selectbox("Тип груза:", CARGO_TYPES)
            teu_req = st.number_input("Объём, TEU:", min_value=1,
                                      max_value=200, value=20)

        submit = st.form_submit_button("Зарегистрировать заявку")

        if submit:
            if not client.strip() or not route.strip():
                st.warning("Заполните клиента и маршрут.")
            else:
                match = find_matching_train(conn, route.strip(), teu_req)
                if match:
                    train_id = match[0]
                    add_request_aggregated(conn, client.strip(), route.strip(),
                                           cargo, teu_req, train_id)
                    st.success(f"Заявка прикреплена к составу (ID={train_id}).")
                else:
                    add_request_pending(conn, client.strip(), route.strip(),
                                        cargo, teu_req)
                    st.info("Заявка зарегистрирована как «ожидает агрегации». "
                            "Сформируйте новый состав во вкладке «Парк составов».")

    st.markdown("### Все заявки")
    reqs = get_all_requests(conn)
    if reqs:
        st.dataframe(
            [{"ID": r[0], "Клиент": r[1], "Маршрут": r[2], "Груз": r[3],
              "TEU": r[4], "Поезд": r[5], "Статус": r[6]} for r in reqs],
            use_container_width=True,
        )
    else:
        st.write("Заявок пока нет.")


# ВКЛАДКА 3: ПАРК СОСТАВОВ
with tab_fleet:
    st.subheader("Формирование нового контейнерного поезда")
    # st.caption("Каскадный поиск станций: локальный справочник → "
    #            "Nominatim (OSM) → Overpass API. Соответствует методологии "
    #            "Geischberger et al. (2026) по работе с OSM-инфраструктурой.")

    with st.form("new_train_form", clear_on_submit=True):
        c1, c2 = st.columns(2)

        with c1:
            new_num = st.text_input("Номер поезда:", placeholder="405Ш")
            new_route = st.text_input("Маршрут:",
                                      placeholder="Нахабино - Екатеринбург")
            new_cargo = st.selectbox("Спецификация груза:", CARGO_TYPES)

        with c2:
            new_teu = st.number_input("Ёмкость, TEU:", min_value=10,
                                      max_value=200, value=80)
            geo_mode = st.radio("Метод определения координат:",
                                ["Поиск станции (OSM)", "Ручной ввод"])

            if geo_mode == "Поиск станции (OSM)":
                station_input = st.text_input(
                    "Название ж/д станции:",
                    placeholder="Нахабино, Ховрино, Люберцы, Омск...",
                )
                manual_lat, manual_lon = 0.0, 0.0
            else:
                station_input = ""
                manual_lat = st.number_input("Широта:", min_value=40.0,
                                             max_value=80.0, value=55.04,
                                             format="%.4f")
                manual_lon = st.number_input("Долгота:", min_value=19.0,
                                             max_value=180.0, value=82.90,
                                             format="%.4f")

        submit_train = st.form_submit_button("Сформировать состав")

        if submit_train:
            if not new_num.strip() or not new_route.strip():
                st.warning("Номер поезда и маршрут обязательны.")
            else:
                final_lat, final_lon, src = None, None, "manual"

                if geo_mode == "Поиск станции (OSM)":
                    if not station_input.strip():
                        st.error("Введите название станции.")
                    else:
                        with st.spinner(f"Поиск станции «{station_input}» в OSM..."):
                            t0 = time.time()
                            res = find_station(station_input.strip())
                            dt = time.time() - t0
                        if res:
                            final_lat, final_lon, src, disp = res
                            st.success(f"Станция найдена через **{src}** "
                                       f"за {dt:.2f} с\n\n {disp}\n\n"
                                       f"({final_lat:.4f}, {final_lon:.4f})")
                        else:
                            st.error(f"Станция «{station_input}» не найдена. "
                                     f"Уточните название или используйте ручной ввод.")
                else:
                    final_lat, final_lon, src = manual_lat, manual_lon, "manual"

                if final_lat is not None:
                    ok, msg = add_train(conn, new_num.strip(), final_lat,
                                        final_lon, new_route.strip(),
                                        new_cargo, new_teu, src)
                    if ok:
                        st.success(f"Состав № {new_num} зарегистрирован "
                                   f"({final_lat:.4f}, {final_lon:.4f}).")
                        time.sleep(0.6)
                        st.rerun()
                    else:
                        st.error(msg)

    st.markdown("### Текущий парк составов")
    if raw_trains:
        st.dataframe(
            [{"ID": t[0], "Номер": t[1], "Широта": t[2], "Долгота": t[3],
              "Маршрут": t[4], "Груз": t[5],
              "Загрузка, TEU": f"{t[7]}/{t[6]}",
              "Источник координат": t[8]} for t in raw_trains],
            use_container_width=True,
        )