import os
import sqlite3
import httpx
import asyncio
import sys
from dotenv import load_dotenv

# Configurar rutas para que las importaciones funcionen
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Importamos las funciones necesarias de main.py
from src.main import process_bot_response, get_db_settings

load_dotenv(os.path.join(ROOT_DIR, ".env"))

async def telegram_polling():
    """
    Script de polling para Telegram. 
    Permite recibir mensajes sin necesidad de webhooks o URLs públicas.
    """
    # Cargar configuraciones de entorno adicionales
    mode = os.getenv("TELEGRAM_MODE", "polling").lower()
    env = os.getenv("ENVIRONMENT", "local").lower()

    if mode != "polling":
        print(f"\n[AVISO] El modo de Telegram está configurado como '{mode}'.")
        print("El script de polling no se ejecutará para no interferir con los webhooks.")
        return

    print("\n" + "="*50)
    print(f"[BOT] INICIANDO POLLING DE TELEGRAM (MODO: {mode.upper()} | ENV: {env.upper()})")
    print("="*50)
    
    # 1. Obtener configuración de la base de datos
    try:
        conn = get_db_settings()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = 'telegram_token'")
        row = cursor.fetchone()
        token = row[0] if row and row[0] else None
        
        cursor.execute("SELECT value FROM config WHERE key = 'telegram_enabled'")
        enabled_row = cursor.fetchone()
        enabled = enabled_row[0] if enabled_row else '0'
        conn.close()
    except Exception as e:
        print(f"[ERROR] Error al leer la base de datos: {e}")
        return

    if not token:
        print("[AVISO] No se encontró un Token de Telegram. Configuralo en el Panel Admin.")
        return

    if enabled == '0':
        print("[AVISO] Telegram está desactivado en el Panel Admin.")
        # Seguiremos intentando por si el usuario lo activa mientras el script corre
    
    # 2. Limpiar webhook previo (obligatorio para usar polling)
    # Solo lo hacemos si estamos en local o si el modo es polling explícito
    async with httpx.AsyncClient() as client:
        try:
            print(f"[*] Limpiando webhooks previos para permitir polling...")
            await client.get(f"https://api.telegram.org/bot{token}/deleteWebhook")
        except Exception as e:
            print(f"[!] No se pudo limpiar el webhook (podría estar ya limpio): {e}")

    print(f"[OK] Escuchando mensajes en Telegram (Token: {token[:10]}...)")
    
    offset = 0
    async with httpx.AsyncClient() as client:
        while True:
            # Re-verificar si está habilitado cada 30 segundos
            if offset % 10 == 0:
                try:
                    conn = get_db_settings(); cursor = conn.cursor()
                    cursor.execute("SELECT value FROM config WHERE key = 'telegram_enabled'")
                    enabled = cursor.fetchone()[0]; conn.close()
                except: pass

            if enabled == '1':
                try:
                    url = f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=20"
                    response = await client.get(url, timeout=25)
                    data = response.json()
                    
                    if data.get("ok"):
                        for update in data.get("result", []):
                            offset = update["update_id"] + 1
                            message = update.get("message")
                            if not message: continue
                            
                            user_id = str(message["chat"]["id"])
                            user_text = message.get("text", message.get("caption", ""))
                            attachment = None
                            
                            # Detectar Media
                            if "photo" in message:
                                # Tomamos la versión de mayor resolución
                                file_id = message["photo"][-1]["file_id"]
                                from src.main import download_telegram_media
                                attachment = await download_telegram_media(file_id, token)
                            elif "document" in message:
                                file_id = message["document"]["file_id"]
                                from src.main import download_telegram_media
                                attachment = await download_telegram_media(file_id, token)
                            elif "video" in message:
                                file_id = message["video"]["file_id"]
                                from src.main import download_telegram_media
                                attachment = await download_telegram_media(file_id, token)
                            
                            if user_text or attachment:
                                print(f"[MSG] Telegram de {user_id}: {user_text} {'[ADJUNTO]' if attachment else ''}")
                                # Ejecutar el procesamiento (esto llama a LangGraph)
                                await process_bot_response(user_id, user_text, "telegram", attachment)
                    
                except Exception as e:
                    print(f"[ERROR] Error en conexión con Telegram: {e}")
                    await asyncio.sleep(5)
            else:
                # Si está desactivado, esperamos un poco antes de volver a chequear
                await asyncio.sleep(5)
            
            await asyncio.sleep(0.5)

if __name__ == "__main__":
    try:
        asyncio.run(telegram_polling())
    except KeyboardInterrupt:
        print("\nStopping Telegram Polling...")
