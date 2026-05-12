@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo    ZARATE IA - GESTOR DE INICIO
echo ==========================================
echo.
echo Selecciona que servicios deseas activar:
echo [1] Todo (WhatsApp + Telegram + Admin)
echo [2] Solo WhatsApp (+ Admin)
echo [3] Solo Telegram (+ Admin)
echo [4] Solo Admin
echo.
set /p choice="Elige una opcion (1-4): "

:: Verificar entorno virtual
if not exist .venv (
    echo [ERROR] No existe el entorno virtual. Ejecuta primero setup.bat.
    pause
    exit /b
)

:: Cargar entorno virtual
call .venv\Scripts\activate

:: Procesar Eleccion
if "%choice%"=="1" goto :ALL
if "%choice%"=="2" goto :WHATSAPP
if "%choice%"=="3" goto :TELEGRAM
if "%choice%"=="4" goto :ADMIN
goto :ADMIN

:ALL
echo [DOCKER] Iniciando servicios de WhatsApp...
docker-compose -f docker/docker-compose.yml up -d
echo [TELEGRAM] Iniciando polling...
start /b python src/telegram_polling.py
goto :SERVER

:WHATSAPP
echo [DOCKER] Iniciando servicios de WhatsApp...
docker-compose -f docker/docker-compose.yml up -d
goto :SERVER

:TELEGRAM
echo [TELEGRAM] Iniciando polling...
start /b python src/telegram_polling.py
goto :SERVER

:ADMIN
echo [INFO] Iniciando solo el Panel de Administracion...
goto :SERVER

:SERVER
:: Lanzar el panel de administración en el navegador
echo [WEB] Lanzando panel de administracion en breve...
start /b cmd /c "timeout /t 5 /nobreak >nul && start http://localhost:8000/admin"

:: Ejecutar el servidor FastAPI
echo [SERVER] Iniciando FastAPI en puerto 8000...
python -m uvicorn src.main:app --reload --reload-dir src --host 0.0.0.0 --port 8000

pause
