# Ситуационный центр: Контейнерные перевозки ЖД

## Структура проекта

| Файл | Назначение |
|------|-----------|
| `app.py` | Точка входа Streamlit, только UI и оркестрация |
| `config.py` | Справочники (RAIL_HUBS, CARGO_TYPES), константы |
| `database.py` | SQLite: схема, CRUD для поездов и заявок |
| `geo_logic.py` | Чистая математика: центр масс, выбросы |
| `osm_client.py` | Каскадный поиск станций: локальный → Nominatim → Overpass |
| `ui_components.py` | Переиспользуемые UI-блоки (карта, манифест, метрики) |

## Запуск

```bash
pip install -r requirements.txt
streamlit run app.py
