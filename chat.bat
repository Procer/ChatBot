@echo off
setlocal enabledelayedexpansion
title Chatbot Rondan - Modo Consola

:menu
cls
echo ======================================================
echo          CONFIGURACION DE PRUEBA DEL CHATBOT
echo ======================================================
echo.
echo  [1] INICIAR CHAT VIRGEN (Sin memoria previa)
echo  [2] CONTINUAR CHAT ANTERIOR (Con memoria persistente)
echo  [3] SALIR
echo.
echo ======================================================
set /p opcion="Seleccione una opcion [1-3]: "

if "%opcion%"=="1" (
    :: Generar un ID aleatorio basado en la hora para que sea siempre virgen
    set session_id=usuario_nuevo_%time:~6,2%%time:~9,2%
    echo.
    echo Instando sesion virgen...
    goto run_chat
)

if "%opcion%"=="2" (
    set session_id=usuario_persistente
    echo.
    echo Cargando sesion anterior...
    goto run_chat
)

if "%opcion%"=="3" (
    exit
)

echo Opcion no valida. Intente de nuevo.
timeout /t 2 >nul
goto menu

:run_chat
echo.
call .venv\Scripts\activate
python src/test_local.py !session_id!
pause
goto menu
