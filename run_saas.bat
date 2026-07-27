@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo    ZARATE IA - ENTORNO SAAS (LOCAL TEST)
echo ==========================================
echo.

:: Verificar entorno virtual
if not exist .venv (
    echo [ERROR] No existe el entorno virtual. Ejecuta primero setup.bat.
    pause
    exit /b
)

:: Cargar entorno virtual
call .venv\Scripts\activate

:: 1. Iniciar Servidor Principal Multi-Cliente
echo [SERVER] Iniciando FastAPI Multi-Tenant (SaaS) en puerto 8001...
start "ZSG Bot - Servidor SaaS (Puerto 8001)" cmd /k "call .venv\Scripts\activate && python -m uvicorn src.main_saas:app --host 0.0.0.0 --port 8001 --reload"

:: 2. Iniciar Polling de Telegram (modo polling, no depende de ngrok/webhook)
echo [TELEGRAM] Iniciando polling de Telegram multi-tenant...
start "ZSG Bot - Telegram Polling" cmd /k "call .venv\Scripts\activate && python src/telegram_polling.py"

:: 3. Iniciar ngrok
echo [NGROK] Iniciando ngrok para exponer el puerto 8001...
set NGROK_CMD=tools\ngrok.exe
if not exist "tools\ngrok.exe" (
    where ngrok >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] No se encontro ngrok. Colocalo en tools\ngrok.exe o instalalo en el PATH del sistema.
        echo Descargalo de https://ngrok.com/download
        pause
        exit /b
    )
    set NGROK_CMD=ngrok
)
start "ZSG Bot - Ngrok (Puerto 8001)" cmd /k "%NGROK_CMD% http 8001"

:: 4. Abrir Panel de Administración en el navegador
echo [BROWSER] Abriendo el Panel de Administracion...
timeout /t 3 /nobreak >nul
start http://localhost:8001/admin

echo.
echo ==========================================
echo   Sistema SaaS iniciado correctamente.
echo   - Webhook Activo: http://localhost:8001/webhook/rondan/greenapi
echo   - Base de Datos Activa: SQL Server (Docker)
echo.
echo   Nota: El panel de administracion sigue corriendo en el puerto 8000
echo   si ejecutas el viejo run.bat en paralelo.
echo   Cerrando esta ventana no detiene el bot SaaS.
echo ==========================================
pause
