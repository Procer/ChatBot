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
    print("\n" + "="*50)
    print("🤖 INICIANDO POLLING DE TELEGRAM (MODO LOCAL)")
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
        print(f"❌ Error al leer la base de datos: {e}")
        return

    if not token:
        print("[AVISO] No se encontró un Token de Telegram. Configuralo en el Panel Admin.")
        return

    if enabled == '0':
        print("[AVISO] Telegram está desactivado en el Panel Admin.")
        # Seguiremos intentando por si el usuario lo activa mientras el script corre
    
    # 2. Limpiar webhook previo (obligatorio para usar polling)
    async with httpx.AsyncClient() as client:
        try:
            print(f"🧹 Limpiando webhooks previos para permitir polling...")
            await client.get(f"https://api.telegram.org/bot{token}/deleteWebhook")
        except: pass

    print(f"✅ Escuchando mensajes en Telegram (Token: {token[:10]}...)")
    
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
                            if message and "text" in message:
                                chat_id = str(message["chat"]["id"])
                                user_text = message.get("text", "")
                                print(f"📩 Telegram de {chat_id}: {user_text}")
                                
                                # Ejecutar el procesamiento (esto llama a LangGraph)
                                await process_bot_response(chat_id, user_text, "telegram")
                    
                except Exception as e:
                    print(f"❌ Error en conexión con Telegram: {e}")
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
