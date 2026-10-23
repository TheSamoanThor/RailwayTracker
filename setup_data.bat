@echo off
chcp 65001 > nul

:: Переходим в директорию, где находится сам батник
cd /d "%~dp0"

:: Задаем относительные пути на основе структуры проекта
set "DATA_DIR=data"
set "ARCHIVE_NAME=hotosm_rus_railways_osm_geojson.zip"
set "OLD_FILE=railways.geojson"
set "NEW_FILE=russia_railway_stations.geojson"

echo [1/2] Распаковка архива %ARCHIVE_NAME% в папку %DATA_DIR%...
if exist "%DATA_DIR%\%ARCHIVE_NAME%" (
    powershell -Command "Expand-Archive -Path '%DATA_DIR%\%ARCHIVE_NAME%' -DestinationPath '%DATA_DIR%' -Force"
) else (
    echo Ошибка: Архив не найден по пути %DATA_DIR%\%ARCHIVE_NAME%
    pause
    exit /b
)

echo [2/2] Переименование файла...
if exist "%DATA_DIR%\%OLD_FILE%" (
    :: Удаляем целевой файл, если он уже существовал, чтобы избежать конфликта при переименовании
    if exist "%DATA_DIR%\%NEW_FILE%" del /f /q "%DATA_DIR%\%NEW_FILE%"
    
    ren "%DATA_DIR%\%OLD_FILE%" "%NEW_FILE%"
    echo Успешно: Файл %OLD_FILE% переименован в %NEW_FILE%
) else (
    echo Ошибка: Файл %OLD_FILE% не найден после распаковки.
    echo Проверьте точное имя файла внутри ZIP-архива.
)

pause
