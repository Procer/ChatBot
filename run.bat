@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo    ZARATE IA - GESTOR LOCAL PRO
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

:: 1. Iniciar Servidor Principal PRIMERO (en su propia ventana)
echo [SERVER] Iniciando FastAPI en puerto 8000...
start "ZSG Bot - Servidor FastAPI" cmd /k "call .venv\Scripts\activate && python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload"

:: 2. Esperar a que el servidor levante completamente antes de iniciar Telegram
echo [WAIT] Esperando que el servidor inicialice (8 segundos)...
timeout /t 8 /nobreak >nul

:: 3. Iniciar Telegram Polling (ahora el server ya está listo)
echo [TELEGRAM] Abriendo ventana de escucha de Telegram...
start "ZSG Bot - Telegram Polling" cmd /k "call .venv\Scripts\activate && python src/telegram_polling.py"

:: 4. Abrir el Panel Admin en el navegador
echo [BROWSER] Abriendo panel de administracion...
start http://localhost:8000/admin

echo.
echo ==========================================
echo   Sistema iniciado correctamente.
echo   Panel Admin: http://localhost:8000/admin
echo   Cerrando esta ventana no detiene el bot.
echo ==========================================
pause
