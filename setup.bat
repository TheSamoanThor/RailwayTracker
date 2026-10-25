@echo off
chcp 65001 >nul
echo ====================================================
echo Настройка окружения для проекта (Python 3.12)
echo ====================================================

:: Проверяем, установлен ли Python 3.12 через лаунчер
py -3.12 --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ОШИБКА: Python 3.12 не найден.
    echo Пожалуйста, скачайте и установите Python 3.12 с официального сайта.
    echo ВАЖНО: При установке обязательно отметьте галочки:
    echo   [x] Add Python to PATH
    echo   [x] Install py launcher for all users
    echo.
    pause
    exit /b
)

echo [1/3] Создание виртуального окружения в папке .venv...
py -3.12 -m venv .venv
if %errorlevel% neq 0 (
    echo.
    echo ОШИБКА при создании виртуального окружения.
    pause
    exit /b
)

echo [2/3] Активация виртуального окружения...
call .venv\Scripts\activate.bat

echo [3/3] Обновление pip и установка зависимостей из requirements.txt...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo ====================================================
echo Установка успешно завершена!
echo Теперь вы можете запустить приложение через start_app.bat
echo ====================================================
pause
