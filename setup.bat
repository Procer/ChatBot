@echo off
echo ==========================================
echo CONFIGURANDO ENTORNO PARA CHATBOT WHATSAPP
echo ==========================================

:: Verificar si Python está instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no esta instalado o no esta en el PATH.
    pause
    exit /b
)

:: Crear entorno virtual si no existe
if not exist .venv (
    echo [1/3] Creando entorno virtual...
    python -m venv .venv
) else (
    echo [1/3] El entorno virtual ya existe.
)

:: Instalar dependencias
echo [2/3] Instalando dependencias desde requirements.txt...
call .venv\Scripts\activate
pip install -r requirements.txt

:: Crear .env si no existe
if not exist .env (
    echo [3/3] Creando archivo .env desde el ejemplo...
    copy .env.example .env
    echo [!] RECUERDA EDITAR EL ARCHIVO .env CON TUS API KEYS.
) else (
    echo [3/3] El archivo .env ya existe.
)

echo ==========================================
echo SETUP COMPLETADO CON EXITO.
echo ==========================================
pause
