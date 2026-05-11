import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").strip('"').rstrip('/')
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "").strip('"')
INSTANCE_NAME = os.getenv("EVOLUTION_INSTANCE_NAME", "").strip('"')

async def check_whatsapp():
    print(f"--- DIAGNÓSTICO WHATSAPP ---")
    print(f"API URL: {EVOLUTION_API_URL}")
    print(f"Instance: {INSTANCE_NAME}")
    
    headers = {"apikey": EVOLUTION_API_KEY}
    
    async with httpx.AsyncClient() as client:
        # 1. Probar conexión base
        try:
            res = await client.get(f"{EVOLUTION_API_URL}/instance/connectionState/{INSTANCE_NAME}", headers=headers)
            print(f"1. Estado de Instancia: {res.status_code}")
            if res.status_code == 200:
                print(f"   Detalle: {res.json()}")
            else:
                print(f"   Error: {res.text}")
        except Exception as e:
            print(f"1. Error de conexión: {e}")

        # 2. Probar Webhooks configurados
        try:
            res = await client.get(f"{EVOLUTION_API_URL}/webhook/find/{INSTANCE_NAME}", headers=headers)
            print(f"\n2. Webhooks configurados: {res.status_code}")
            if res.status_code == 200:
                print(f"   Detalle: {res.json()}")
            else:
                print(f"   Error: {res.text}")
        except Exception as e:
            print(f"2. Error consultando webhooks: {e}")

if __name__ == "__main__":
    asyncio.run(check_whatsapp())
