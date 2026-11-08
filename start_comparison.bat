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

python benchmark_compare.py

pause
