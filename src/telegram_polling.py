import os
import sys
import asyncio
import httpx
from dotenv import load_dotenv

# Configurar rutas para que las importaciones funcionen
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

load_dotenv(os.path.join(ROOT_DIR, ".env"))

# Importamos las funciones necesarias de la app SaaS Multi-Tenant
from src.database.session import SessionLocal
from src.database.models import Client, ClientSettings
from src.main_saas import process_bot_response, download_telegram_media_saas

REFRESH_INTERVAL = 15  # segundos entre chequeos de clientes con Telegram habilitado


def get_active_telegram_clients():
    """Devuelve {client_id: (slug, token)} para cada cliente activo con Telegram habilitado."""
    db = SessionLocal()
    try:
        rows = (
            db.query(Client.id, Client.slug, ClientSettings.telegram_token)
            .join(ClientSettings, ClientSettings.client_id == Client.id)
            .filter(Client.status == "active")
            .filter(ClientSettings.telegram_enabled == True)
            .filter(ClientSettings.telegram_token.isnot(None))
            .filter(ClientSettings.telegram_token != "")
            .all()
        )
        return {client_id: (slug, token) for client_id, slug, token in rows}
    finally:
        db.close()


async def poll_client(client_id: int, slug: str, token: str):
    """Loop de polling de Telegram para un único cliente (tenant)."""
    async with httpx.AsyncClient() as client:
        try:
            await client.get(f"https://api.telegram.org/bot{token}/deleteWebhook")
        except Exception as e:
            print(f"[!] [{slug}] No se pudo limpiar el webhook: {e}")

        print(f"[OK] [{slug}] Escuchando mensajes en Telegram (Token: {token[:10]}...)")

        offset = 0
        while True:
            try:
                url = f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=20"
                response = await client.get(url, timeout=25)
                data = response.json()

                if data.get("ok"):
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        message = update.get("message")
                        if not message:
                            continue

                        user_id = str(message["chat"]["id"])
                        user_text = message.get("text", message.get("caption", ""))
                        attachment = None

                        # Media Detection
                        if "photo" in message:
                            file_id = message["photo"][-1]["file_id"]
                            attachment = await download_telegram_media_saas(file_id, token)
                        elif "document" in message:
                            file_id = message["document"]["file_id"]
                            attachment = await download_telegram_media_saas(file_id, token)

                        if user_text or attachment:
                            print(f"[MSG] [{slug}] Telegram de {user_id}: {user_text}")
                            await process_bot_response(client_id, user_id, user_text, "telegram", attachment)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[ERROR] [{slug}] Error en conexión con Telegram: {e}")
                await asyncio.sleep(5)

            await asyncio.sleep(0.5)


async def telegram_polling():
    """
    Script de polling multi-tenant para Telegram.
    Detecta qué clientes tienen Telegram habilitado (con token propio) y mantiene
    un loop de polling independiente por cada uno, sin depender de webhooks públicos.
    """
    mode = os.getenv("TELEGRAM_MODE", "polling").lower()
    env = os.getenv("ENVIRONMENT", "local").lower()

    if mode != "polling":
        print(f"\n[AVISO] El modo de Telegram está configurado como '{mode}'.")
        print("El script de polling no se ejecutará para no interferir con los webhooks.")
        return

    print("\n" + "=" * 50)
    print(f"[BOT] INICIANDO POLLING DE TELEGRAM MULTI-TENANT (MODO: {mode.upper()} | ENV: {env.upper()})")
    print("=" * 50)

    tasks = {}  # client_id -> (asyncio.Task, (slug, token))

    while True:
        try:
            active = get_active_telegram_clients()
        except Exception as e:
            print(f"[ERROR] Error al leer la base de datos: {e}")
            active = {}

        # Detener clientes que ya no están activos o cuyo token cambió
        for client_id in list(tasks.keys()):
            task, config = tasks[client_id]
            if client_id not in active or active[client_id] != config:
                task.cancel()
                del tasks[client_id]

        # Iniciar clientes nuevos (o reiniciados por cambio de token)
        for client_id, config in active.items():
            if client_id not in tasks:
                slug, token = config
                task = asyncio.create_task(poll_client(client_id, slug, token))
                tasks[client_id] = (task, config)

        if not tasks:
            print(f"[AVISO] Ningún cliente tiene Telegram habilitado con token configurado. Reintentando en {REFRESH_INTERVAL}s...")

        await asyncio.sleep(REFRESH_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(telegram_polling())
    except KeyboardInterrupt:
        print("\nStopping Telegram Polling...")
