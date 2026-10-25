@echo off
chcp 65001 >nul

:: Проверяем, создано ли виртуальное окружение
if not exist ".venv\Scripts\activate.bat" (
    echo ====================================================
    echo ОШИБКА: Виртуальное окружение не найдено.
    echo Пожалуйста, сначала запустите setup.bat для установки зависимостей.
    echo ====================================================
    pause
    exit /b
)

echo Активация виртуального окружения (Python 3.12)...
call .venv\Scripts\activate.bat

echo Запуск приложения...
streamlit run app.py --server.enableStaticServing=false

pause
