import os
import httpx
import logging
import base64
from typing import Dict, Any, Optional

class WhatsAppManager:
    def __init__(self):
        self.api_url = os.getenv("EVOLUTION_API_URL", "").strip('"').rstrip('/')
        self.api_key = os.getenv("EVOLUTION_API_KEY", "").strip('"')
        self.instance = os.getenv("EVOLUTION_INSTANCE_NAME", "").strip('"')
        self.headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json"
        }

    async def get_status(self) -> Dict[str, Any]:
        """Obtiene el estado detallado de la instancia."""
        if not self.api_url or not self.instance:
            return {"status": "error", "message": "Faltan variables de entorno (URL/Instancia)"}

        url = f"{self.api_url}/instance/connectionState/{self.instance}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, headers=self.headers)
                if r.status_code == 200:
                    data = r.json()
                    # Evolution API v2 structure
                    state = data.get("instance", {}).get("state") or data.get("state")
                    return {
                        "status": "success",
                        "state": state, # open, close, connecting, etc.
                        "data": data
                    }
                elif r.status_code == 404:
                    return {"status": "not_found", "message": "Instancia no existe en el servidor"}
                else:
                    return {"status": "error", "message": f"Error API: {r.status_code}"}
        except Exception as e:
            logging.error(f"Error en WhatsAppManager.get_status: {e}")
            return {"status": "error", "message": str(e)}

    async def get_qr(self) -> Dict[str, Any]:
        """Obtiene el código QR para vinculación."""
        url = f"{self.api_url}/instance/connect/{self.instance}"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.get(url, headers=self.headers)
                if r.status_code == 200:
                    return {"status": "success", "data": r.json()}
                return {"status": "error", "message": f"No se pudo obtener el QR: {r.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def restart_instance(self) -> bool:
        """Reinicia la instancia de WhatsApp."""
        url = f"{self.api_url}/instance/restart/{self.instance}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(url, headers=self.headers)
                return r.status_code in [200, 201]
        except:
            return False

    async def logout(self) -> bool:
        """Cierra la sesión de WhatsApp."""
        url = f"{self.api_url}/instance/logout/{self.instance}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.delete(url, headers=self.headers)
                return r.status_code == 200
        except:
            return False

    async def set_webhook(self, webhook_url: str) -> bool:
        """Configura el webhook en la instancia."""
        url = f"{self.api_url}/webhook/set/{self.instance}"
        payload = {
            "webhook": {
                "enabled": True,
                "url": webhook_url,
                "webhook_by_events": False,
                "events": ["MESSAGES_UPSERT"]
            }
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(url, json=payload, headers=self.headers)
                return r.status_code in [200, 201]
        except:
            return False
