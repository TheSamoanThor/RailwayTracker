"""
Ситуационный центр: Контейнерные перевозки ЖД.
Точка входа: аутентификация + Streamlit UI + оркестрация модулей.
Вся логика вынесена в отдельные модули.

Изменения этапа:
  • боковая панель убрана; параметры фильтрации и выбор поезда
    перенесены внутрь вкладки «Мониторинг сети»;
  • при инициализации БД подгружается локальный GeoJSON со станциями
    (если файл существует) — приложение работает офлайн для них.
"""

import os
import time
import streamlit as st

from auth import authenticate
from config import CARGO_TYPES, STATIONS_GEOJSON_PATH
from database import (
    init_db, get_all_trains, add_train,
    find_matching_train, add_request_aggregated, add_request_pending,
    get_all_requests, find_request_by_tracker, get_client_requests,
    get_wagons, add_wagon, get_train_by_id,
    load_stations_from_geojson, count_cached_stations,
)
from geo_logic import filter_outliers
from osm_client import find_station
from simulation import position_at
from ui_components import (
    build_rail_map, render_map, render_train_manifest,
    render_analytics_panel, render_client_tracking, render_wagon_manifest,
)

# ───────────────────────────────────────────────
# Настройка страницы
# ───────────────────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="Мониторинг контейнерных перевозок",
    page_icon="🚂",
)

# ───────────────────────────────────────────────
# АУТЕНТИФИКАЦИЯ
# ───────────────────────────────────────────────
if "user" not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    st.title("Вход в систему")
    with st.form("login_form"):
        username = st.text_input("Логин", placeholder="admin / client")
        password = st.text_input("Пароль", type="password")
        submitted = st.form_submit_button("Войти")
        if submitted:
            role = authenticate(username, password)
            if role:
                st.session_state.user = {
                    "name": username.strip().lower(),
                    "role": role,
                }
                st.rerun()
            else:
                st.error("Неверный логин или пароль.")
    st.caption("Демо-учётки: admin / admin123, client / client123")
    st.stop()

user = st.session_state.user

# ───────────────────────────────────────────────
# БД + загрузка локального справочника станций
# ───────────────────────────────────────────────
if "db_conn" not in st.session_state:
    conn = init_db()

    # Локальный GeoJSON со станциями (офлайн-справочник).
    # Если файла нет — просто пропускаем, приложение работает через OSM.
    if os.path.exists(STATIONS_GEOJSON_PATH):
        n = load_stations_from_geojson(conn, STATIONS_GEOJSON_PATH)
        st.session_state["stations_loaded"] = n
    else:
        st.session_state["stations_loaded"] = 0

    st.session_state.db_conn = conn

conn = st.session_state.db_conn

# ───────────────────────────────────────────────
# ХЕДЕР: приветствие + выход
# ───────────────────────────────────────────────
col_title, col_logout = st.columns([5, 1])
col_title.title(f"Ситуационный центр: ЖД — роль: **{user['role']}**")
if col_logout.button("Выйти"):
    st.session_state.user = None
    st.rerun()

# ═══════════════════════════════════════════════
# АДМИН
# ═══════════════════════════════════════════════
if user["role"] == "admin":
    raw_trains = get_all_trains(conn)
    points_for_algo = [(t[0], t[2], t[3]) for t in raw_trains]

    tab_monitor, tab_requests, tab_fleet, tab_wagons = st.tabs([
        "Мониторинг сети",
        "Заявки",
        "Парк составов",
        "Состав вагонов",
    ])

    # ─── Вкладка 1: Мониторинг ───
    with tab_monitor:
        # Параметры фильтрации — на экране (не в сайдбаре)
        with st.container(border=True):
            st.subheader("Параметры фильтрации и поиска")
            c1, c2 = st.columns(2)
            with c1:
                multiplier = st.slider(
                    "Множитель расстояния (multiplier)",
                    min_value=0.1, max_value=3.0, value=1.0, step=0.1,
                )
            with c2:
                train_numbers = ["Все"] + [t[1] for t in raw_trains]
                selected = st.selectbox(
                    "Выберите номер поезда для вывода манифеста:",
                    train_numbers,
                )

        # Пересчитываем фильтрацию с учётом выбранного multiplier
        valid_ids, center, threshold, avg_dist = filter_outliers(
            points_for_algo, multiplier)

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
                st.write("*Выберите поезд для вывода манифеста.*")

    # ─── Вкладка 2: Заявки ───
    with tab_requests:
        st.subheader("Регистрация клиентской заявки на перевозку")
        st.caption("Заявка автоматически прикрепляется к подходящему по "
                   "маршруту составу, если есть свободная ёмкость (TEU).")

        with st.form("new_request", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                client = st.text_input("Клиент:", placeholder="ООО «Ромашка»")
                route = st.text_input("Маршрут:",
                                      placeholder="Владивосток - Москва")
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
                        tracker = add_request_aggregated(
                            conn, client.strip(), route.strip(),
                            cargo, teu_req, train_id)
                        st.success(f"Заявка прикреплена к составу "
                                   f"(ID={train_id}).\n\n"
                                   f"**Трекер-номер: `{tracker}`** — "
                                   f"передайте его клиенту.")
                    else:
                        tracker = add_request_pending(
                            conn, client.strip(), route.strip(),
                            cargo, teu_req)
                        st.info(f"Заявка зарегистрирована как «ожидает "
                                f"агрегации».\n\n"
                                f"**Трекер-номер: `{tracker}`**")

        st.markdown("### Все заявки")
        reqs = get_all_requests(conn)
        if reqs:
            st.dataframe(
                [{"ID": r[0], "Трекер": r[1], "Клиент": r[2],
                  "Маршрут": r[3], "Груз": r[4], "TEU": r[5],
                  "Поезд": r[6], "Статус": r[7], "Создана": r[8]}
                 for r in reqs],
                use_container_width=True,
            )
        else:
            st.write("Заявок пока нет.")

    # ─── Вкладка 3: Парк составов ───
    with tab_fleet:
        st.subheader("Формирование нового контейнерного поезда")

        # Информация о локальном справочнике станций
        n_stations = count_cached_stations(conn)
        if n_stations:
            st.caption(f"Локальный справочник станций: "
                       f"**{n_stations}** записей (поиск без сети для них).")
        else:
            st.caption("Локальный справочник станций пуст — поиск идёт "
                       "через Nominatim/Overpass.")

        with st.form("new_train_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                new_num = st.text_input("Номер поезда:", placeholder="405Ш")
                new_route = st.text_input(
                    "Маршрут:", placeholder="Нахабино - Екатеринбург")
                new_cargo = st.selectbox("Спецификация груза:", CARGO_TYPES)
            with c2:
                new_teu = st.number_input("Ёмкость, TEU:", min_value=10,
                                          max_value=200, value=80)
                geo_mode = st.radio("Метод определения координат:",
                                    ["Поиск станции (OSM)", "Ручной ввод"])
                if geo_mode == "Поиск станции (OSM)":
                    station_input = st.text_input(
                        "Название ж/д станции:",
                        placeholder="Нахабино, Ховрино, Люберцы, Омск...")
                    manual_lat, manual_lon = 0.0, 0.0
                else:
                    station_input = ""
                    manual_lat = st.number_input(
                        "Широта:", min_value=40.0, max_value=80.0,
                        value=55.04, format="%.4f")
                    manual_lon = st.number_input(
                        "Долгота:", min_value=19.0, max_value=180.0,
                        value=82.90, format="%.4f")

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
                            with st.spinner(f"Поиск станции "
                                            f"«{station_input}»..."):
                                t0 = time.time()
                                res = find_station(station_input.strip(),
                                                   conn=conn)
                                dt = time.time() - t0
                            if res:
                                final_lat, final_lon, src, disp = res
                                st.success(
                                    f"Станция найдена через **{src}** "
                                    f"за {dt:.2f} с\n\n{disp}\n\n"
                                    f"({final_lat:.4f}, {final_lon:.4f})")
                            else:
                                st.error(f"Станция «{station_input}» "
                                         f"не найдена. Уточните название "
                                         f"или используйте ручной ввод.")
                    else:
                        final_lat = manual_lat
                        final_lon = manual_lon
                        src = "manual"

                    if final_lat is not None:
                        # Для симуляции: from = to = текущая точка
                        # (поезд стоит на месте; расширяется формой маршрута).
                        ok, msg = add_train(
                            conn, new_num.strip(), final_lat, final_lon,
                            new_route.strip(), new_cargo, new_teu, src,
                            from_lat=final_lat, from_lon=final_lon,
                            to_lat=final_lat, to_lon=final_lon,
                        )
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

    # ─── Вкладка 4: Состав вагонов ───
    with tab_wagons:
        if not raw_trains:
            st.info("Парк пуст — сначала добавьте состав.")
        else:
            train_opts = {f"{t[1]} ({t[4]})": t[0] for t in raw_trains}
            picked = st.selectbox("Выберите поезд", list(train_opts.keys()))
            tid = train_opts[picked]

            render_wagon_manifest(get_wagons(conn, tid), picked)

            st.markdown("### Добавить вагон")
            with st.form("wagon_form", clear_on_submit=True):
                a, b, c = st.columns(3)
                wno = a.text_input("Номер вагона", placeholder="WG-XXX-01")
                pos = b.number_input("Позиция", 1, 200, 1)
                cargo = c.selectbox("Груз", CARGO_TYPES)
                d, e, f = st.columns(3)
                wt = d.number_input("Вес, т", 1.0, 100.0, 20.0, step=0.5)
                teu = e.number_input("TEU", 0, 200, 10)
                cons = f.text_input("Грузополучатель",
                                    placeholder="ООО «Получатель»")
                if st.form_submit_button("Добавить") and wno.strip():
                    add_wagon(conn, tid, wno.strip(), pos, cargo, wt, teu,
                              cons.strip())
                    st.success("Вагон добавлен.")
                    time.sleep(0.4)
                    st.rerun()

# ═══════════════════════════════════════════════
# КЛИЕНТ
# ═══════════════════════════════════════════════
else:
    st.subheader("Отслеживание заказа")

    tracker = st.text_input("Введите трекер-номер заказа",
                            placeholder="RZ-2026-A1B2C3")
    if tracker.strip():
        row = find_request_by_tracker(conn, tracker)
        if row:
            render_client_tracking(row)
        else:
            st.error("Заказ с таким трекером не найден. "
                     "Проверьте номер или обратитесь в диспетчерскую.")

    # Дополнительно: история заявок клиента (по имени пользователя)
    st.markdown("---")
    st.subheader("Мои заявки")
    my_reqs = get_client_requests(conn, user["name"])
    if my_reqs:
        st.dataframe(
            [{"Трекер": r[1], "Маршрут": r[2], "Груз": r[3],
              "TEU": r[4], "Поезд": r[5], "Статус": r[6]}
             for r in my_reqs],
            use_container_width=True,
        )
        st.caption("Для просмотра позиции на карте введите трекер выше.")
    else:
        st.info("У вас пока нет заявок. Обратитесь к администратору "
                "для оформления.")