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
echo [WEB] Lanzando panel de administracion en breve...
start /b cmd /c "timeout /t 5 /nobreak >nul && start http://localhost:8000/admin"

:: Lanzar el polling de Telegram (el script decidira si debe correr segun el .env)
echo [TELEGRAM] Verificando modo de conexion...
start /b python src/telegram_polling.py

:: Ejecutar el servidor FastAPI
echo [SERVER] Iniciando FastAPI en puerto 8000...
python -m uvicorn src.main:app --reload --reload-dir src --host 0.0.0.0 --port 8000

pause
