import os
import httpx
import asyncio
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

GREEN_API_ID = os.getenv("GREEN_API_ID", "").strip('"')
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN", "").strip('"')

async def test_send():
    if not GREEN_API_ID or not GREEN_API_TOKEN:
        print("❌ Error: Faltan credenciales en el .env")
        return

    # Pon aquí tu número para probar (con código de país, ej: 549351...)
    number = input("Introduce el número de teléfono para la prueba (ej: 549351234567): ").strip()
    chat_id = f"{number}@c.us"
    text = "🚀 Prueba de conexión: ¡El bot Rondan ya habla vía Green-API!"

    url = f"https://api.green-api.com/waInstance{GREEN_API_ID}/sendMessage/{GREEN_API_TOKEN}"
    payload = {"chatId": chat_id, "message": text}

    print(f"[*] Enviando mensaje a {chat_id}...")
    
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload)
            if r.status_code == 200:
                print(f"✅ ¡Éxito! Mensaje enviado. Respuesta: {r.json()}")
            else:
                print(f"❌ Error API ({r.status_code}): {r.text}")
        except Exception as e:
            print(f"❌ Error de conexión: {e}")

if __name__ == "__main__":
    asyncio.run(test_send())
