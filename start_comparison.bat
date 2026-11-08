@echo off
chcp 65001 >nul

:: Переходим в директорию, где лежит сам .bat
cd /d "%~dp0"

:: Активация venv
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ОШИБКА: не удалось активировать .venv
    pause
    exit /b 1
)

echo Тестируем время исполнения

python benchmark_time.py

echo Тестируем потребление памяти

python benchmark_memory.py

pause
