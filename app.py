"""
Ситуационный центр: Контейнерные перевозки ЖД.
Точка входа: аутентификация + Streamlit UI + оркестрация модулей.
Вся логика вынесена в отдельные модули.
"""

import os
import time
import streamlit as st
from datetime import timedelta

from auth import authenticate
from config import CARGO_TYPES, STATIONS_GEOJSON_PATH
from database import (
    init_db, get_all_trains, add_train,
    find_matching_train, add_request_aggregated, add_request_pending,
    get_all_requests, find_request_by_tracker, get_client_requests,
    get_wagons, add_wagon, get_train_by_id,
    load_stations_from_geojson, count_cached_stations,
    get_active_incident,
)
from geo_logic import filter_outliers
from osm_client import find_station
from simulation import position_at, train_position, simulation_now
from ui_components import (
    build_rail_map, render_map, render_train_manifest,
    render_analytics_panel, render_client_tracking,
    render_wagon_manifest, render_incident_manager,
)

# ═══════════════════════════════════════════════
# Настройка страницы
# ═══════════════════════════════════════════════
st.set_page_config(
    layout="wide",
    page_title="Мониторинг контейнерных перевозок",
    page_icon="*",
)

# ═══════════════════════════════════════════════
# АУТЕНТИФИКАЦИЯ
# ═══════════════════════════════════════════════
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

# ═══════════════════════════════════════════════
# БД + загрузка локального справочника станций
# ═══════════════════════════════════════════════
if "db_conn" not in st.session_state:
    conn = init_db()

    # Локальный GeoJSON со станциями (офлайн-справочник).
    if os.path.exists(STATIONS_GEOJSON_PATH):
        n = load_stations_from_geojson(conn, STATIONS_GEOJSON_PATH)
        st.session_state["stations_loaded"] = n
    else:
        st.session_state["stations_loaded"] = 0

    st.session_state.db_conn = conn

conn = st.session_state.db_conn

# ═══════════════════════════════════════════════
# ХЕДЕР: приветствие + выход
# ═══════════════════════════════════════════════
col_title, col_logout = st.columns([5, 1])
col_title.title(f"Ситуационный центр: ЖД — роль: **{user['role']}**")
if col_logout.button("Выйти"):
    st.session_state.user = None
    st.rerun()

# ═══════════════════════════════════════════════
# Симуляция времени
# ═══════════════════════════════════════════════

def _shift_sim_time(delta_min: int):
    st.session_state.sim_offset_min = (
        int(st.session_state.get("sim_offset_min", 0)) + int(delta_min)
    )


def _reset_sim_time():
    st.session_state.sim_offset_min = 0


if "simulation_enabled" not in st.session_state:
    st.session_state.simulation_enabled = True
if "sim_offset_min" not in st.session_state:
    st.session_state.sim_offset_min = 0

sim_now = simulation_now(st.session_state.sim_offset_min)

# ═══════════════════════════════════════════════
# АДМИН
# ═══════════════════════════════════════════════
if user["role"] == "admin":
    raw_trains = get_all_trains(conn)

    # Для фильтрации берём те же позиции, которые будут на карте
    points_for_algo = []
    for t in raw_trains:
        lat, lon, *_ = train_position(
            t,
            simulation_enabled=st.session_state.simulation_enabled,
            now=sim_now,
        )
        points_for_algo.append((t[0], lat, lon))

    tab_monitor, tab_requests, tab_fleet, tab_wagons, tab_incidents = st.tabs([
        "Мониторинг сети",
        "Заявки",
        "Парк составов",
        "Состав вагонов",
        "Аномалии",
    ])

    # ---- Вкладка 1: Мониторинг ----
    with tab_monitor:
        col1, col2 = st.columns([3, 1])
        
        with col2:
            # Сначала рендерим элементы управления, чтобы получить multiplier и selected
            st.subheader("Параметры фильтрации и поиска")
            c1, c2 = st.columns(2)
            with c1:
                multiplier = st.slider(
                    "Множитель расстояния (multiplier)",
                    min_value=0.1, max_value=3.0, value=1.0, step=0.1,
                )
            with c2:
                train_numbers = ["Все"] + [str(t[1]) for t in raw_trains]
                selected = st.selectbox(
                    "Выберите номер поезда для вывода манифеста:",
                    train_numbers,
                )
        
        # пересчитываем фильтрацию на основе полученного multiplier до рендеринга карты и аналитики!
        valid_ids, center, threshold, avg_dist = filter_outliers(
            points_for_algo, multiplier
        )
        
        with col1:
            # Теперь строим карту — все переменные гарантированно инициализированы
            st.subheader("Интерактивная карта движения")
            m = build_rail_map(
                center, raw_trains, valid_ids,
                avg_dist, threshold, multiplier,
                now=sim_now,
                simulation_enabled=st.session_state.simulation_enabled,
            )
            render_map(m)
            
            # Элементы управления временем симуляции
            st.markdown("---")  # Отделим визуально карту от кнопок

            # Задаем очень маленькие веса колонкам, чтобы элементы прижались друг к другу
            c_toggle, c_input, c_minus, c_plus, c_reset = st.columns([1.5, 1.8, 0.7, 0.7, 1.0])

            with c_toggle:
                # Используем контейнер, чтобы выровнять по высоте с кнопками (чуть опустить переключатель)
                st.markdown("<div style='padding-top: 25px;'></div>", unsafe_allow_html=True)
                st.toggle("Симуляция движения", key="simulation_enabled")

            with c_input:
                st.number_input(
                    "Сдвиг времени, мин",
                    min_value=-10080, max_value=10080, step=30,
                    key="sim_offset_min",
                )

            with c_minus:
                st.markdown("<div style='padding-top: 24px;'></div>", unsafe_allow_html=True)
                st.button("-1 ч", on_click=_shift_sim_time, args=(-60,), use_container_width=True)

            with c_plus:
                st.markdown("<div style='padding-top: 24px;'></div>", unsafe_allow_html=True)
                st.button("+1 ч", on_click=_shift_sim_time, args=(60,), use_container_width=True)

            with c_reset:
                st.markdown("<div style='padding-top: 24px;'></div>", unsafe_allow_html=True)
                st.button("Сбросить", on_click=_reset_sim_time, use_container_width=True)

            
        with col2:
            # Выводим аналитику и манифест (они используют актуальные valid_ids)
            render_analytics_panel(raw_trains, valid_ids, threshold, avg_dist)
            
            if selected != "Все":
                target = next((t for t in raw_trains if str(t[1]) == selected), None)
                if target:
                    render_train_manifest(target, target[0] in valid_ids)
                else:
                    st.warning("Выбранный состав не найден. Возможно, база данных обновилась.")
            else:
                st.write("*Выберите поезд для вывода манифеста.*")

    # ---- Вкладка 2: Заявки ----
    with tab_requests:
        st.subheader("Рассмотрение и распределение входящих заявок")
        
        from database import get_pending_requests, approve_request, reject_request, find_matching_train
        
        pending_list = get_pending_requests(conn)
        
        if not pending_list:
            st.success("Все клиентские заявки обработаны. Новых запросов нет.")
        else:
            for req in pending_list:
                r_id, r_tracker, r_client, r_route, r_cargo, r_teu, r_date = req
                
                # Создаем аккуратный бокс для каждой заявки
                with st.container(border=True):
                    col_info, col_action = st.columns([2, 1])
                    
                    with col_info:
                        st.markdown(f"**Заявка:** `{r_tracker}` от {r_date}")
                        st.markdown(f"**Клиент:** {r_client} | **Груз:** {r_cargo} ({r_teu} TEU)")
                        st.markdown(f"**Заявленный маршрут:** `{r_route}`")
                    
                    with col_action:
                        # Ищем подходящие поезда для этого маршрута
                        match = find_matching_train(conn, r_route, r_teu)
                        
                        if match:
                            train_id, t_cap, t_used = match
                            # Находим номер поезда для вывода на кнопку
                            t_num = next((t[1] for t in raw_trains if t[0] == train_id), f"ID {train_id}")
                            
                            st.caption(f"Доступен поезд {t_num} (Свободно: {t_cap - t_used} TEU)")
                            
                            # Уникальный ключ для каждой кнопки обязателен в Streamlit списочной верстки
                            if st.button(f"Утвердить в состав {t_num}", key=f"app_{r_id}", use_container_width=True):
                                approve_request(conn, r_id, train_id, r_teu)
                                st.success(f"Заявка {r_tracker} успешно добавлена в состав {t_num}!")
                                time.sleep(0.5)
                                st.rerun()
                        else:
                            st.warning("Нет подходящего состава свободной ёмкости под этот маршрут.")
                        
                        if st.button("Отклонить заявку", key=f"rej_{r_id}", use_container_width=True, type="secondary"):
                            reject_request(conn, r_id)
                            st.info(f"Заявка {r_tracker} отклонена.")
                            time.sleep(0.5)
                            st.rerun()
                            
        st.markdown("---")
        st.markdown("### Журнал всех решений")
        reqs = get_all_requests(conn)
        if reqs:
            st.dataframe(
                [{"ID": r[0], "Трекер": r[1], "Клиент": r[2],
                  "Маршрут": r[3], "Груз": r[4], "TEU": r[5],
                  "Поезд": r[6], "Статус": r[7], "Создана": r[8]}
                 for r in reqs],
                width="stretch",
            )
        else:
            st.write("Заявок пока нет.")

    # ---- Вкладка 3: Парк составов ----
    with tab_fleet:
        st.subheader("Формирование нового контейнерного поезда")

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
                width="stretch",
            )

    # ---- Вкладка 4: Состав вагонов ----
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
    
    # ---- Вкладка 5: Аномалии / инциденты ----
    with tab_incidents:
        render_incident_manager(conn, raw_trains, valid_ids)

# ═══════════════════════════════════════════════
# КЛИЕНТ
# ═══════════════════════════════════════════════
else:
    tab_track, tab_new_req = st.tabs(["Отслеживание груза", "Подать заявку на перевозку"])
        
    with tab_track:
        st.subheader("Отслеживание текущего заказа")
        tracker = st.text_input("Введите трекер-номер заказа", placeholder="RZ-2026-A1B2C3")
        
        if tracker.strip():
            row = find_request_by_tracker(conn, tracker)
            if row:
                incident = get_active_incident(conn, row[7]) if row[7] is not None else None
                render_client_tracking(
                    row,
                    incident=incident,
                    now=sim_now,
                    simulation_enabled=st.session_state.simulation_enabled,
                )
            else:
                st.error("Заказ с таким трекером не найден. Проверьте номер.")

        st.markdown("---")
        st.subheader("История моих заказов и статусы")
        my_reqs = get_client_requests(conn, user["name"])
        if my_reqs:
            # Стилизуем отображение статусов для наглядности
            formatted_reqs = []
            for r in my_reqs:
                status_raw = r[6]
                if "отклонена" in status_raw:
                    status_view = f"{status_raw}"
                elif "утверждена" in status_raw:
                    status_view = f"{status_raw}"
                else:
                    status_view = f"{status_raw}"
                    
                formatted_reqs.append({
                    "Трекер": r[1], 
                    "Маршрут": r[2], 
                    "Груз": r[3],
                    "TEU": r[4], 
                    "Назначенный Поезд": r[5], 
                    "Текущий Статус": status_view,
                    "Дата подачи": r[7]
                })
            st.dataframe(formatted_reqs, width="stretch")
        else:
            st.info("У вас пока нет оформленных заявок.")

    with tab_new_req:
        st.subheader("Оформление нового запроса на транспортировку")
        st.caption("После отправки заявка отправляется в ситуационный центр на проверку диспетчером.")
        
        with st.form("client_new_request", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                # Имя клиента берется автоматически из сессии авторизации! Это исключает подлог данных
                st.text_input("Заявитель (Вы):", value=user["name"].upper(), disabled=True)
                req_route = st.text_input("Желаемый Маршрут:", placeholder="Владивосток - Москва")
            with c2:
                req_cargo = st.selectbox("Категория груза:", CARGO_TYPES)
                req_teu = st.number_input("Необходимый объем, TEU:", min_value=1, max_value=200, value=20)
                
            submit_req = st.form_submit_button("Отправить запрос диспетчеру")
            
            if submit_req:
                if not req_route.strip():
                    st.warning("Пожалуйста, укажите конечные точки маршрута.")
                else:
                    new_tracker = add_request_pending(conn, user["name"], req_route.strip(), req_cargo, req_teu)
                    st.success(f"Заявка успешно отправлена на рассмотрение операторам!")
                    st.markdown(f"Ваш персональный трекер-номер: **`{new_tracker}`** (сохраните его для проверки статуса)")
                    time.sleep(1.0)
                    st.rerun()
