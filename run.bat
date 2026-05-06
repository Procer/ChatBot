@echo off
echo ==========================================
echo INICIANDO CHATBOT WHATSAPP (FASTAPI + ADMIN)
echo ==========================================

:: Verificar entorno virtual
if not exist .venv (
    echo [ERROR] No existe el entorno virtual. Ejecuta primero setup.bat.
    pause
    exit /b
)

:: Lanzar contenedores de Docker (WhatsApp API)
echo [DOCKER] Iniciando servicios de WhatsApp...
docker-compose -f docker/docker-compose.yml up -d

:: Cargar entorno virtual
call .venv\Scripts\activate

:: Lanzar el panel de administración en el navegador (en 3 segundos para dar tiempo al servidor)
start /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000/admin"

:: Lanzar el polling de Telegram en segundo plano (para que funcione localmente sin webhooks)
start /b python src/telegram_polling.py

:: Ejecutar el servidor FastAPI
python -m uvicorn src.main:app --reload --reload-dir src --host 0.0.0.0 --port 8000

pause
