@echo off
echo ==========================================
echo INICIANDO CHATBOT LOCAL (MODO PRUEBA)
echo ==========================================

:: Verificar entorno virtual
if not exist .venv (
    echo [ERROR] No existe el entorno virtual. Ejecuta primero setup.bat.
    pause
    exit /b
)

:: Cargar .env y ejecutar el simulador local
call .venv\Scripts\activate
python src/test_local.py

pause
