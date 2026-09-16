import logging
import time

import httpx

from src.database.system_config import get_system_config, OPENAI_ADMIN_KEY_CONFIG_KEY

COSTS_API_URL = "https://api.openai.com/v1/organization/costs"
_MAX_PAGES = 50  # tope de seguridad para no loopear indefinidamente si hay muchísimo historial


async def get_real_spent_usd(project_id: str, since_unix: int = 0) -> float | None:
    """Suma el gasto REAL facturado por OpenAI (Costs API, no estimado por nosotros) para un
    Project puntual, desde `since_unix` (epoch, default = desde siempre) hasta ahora.

    Requiere una Admin API Key de organización cargada en SystemConfig (distinta de las API
    keys normales de cada cliente/Project). Devuelve None si no hay Admin Key configurada, si
    el cliente no tiene `openai_project_id`, o si la consulta falla por cualquier motivo — en
    ese caso el llamador debe caer de vuelta a la estimación interna (TokenUsage logueado)."""
    if not project_id:
        return None
    admin_key = get_system_config(OPENAI_ADMIN_KEY_CONFIG_KEY)
    if not admin_key:
        return None

    headers = {"Authorization": f"Bearer {admin_key}"}
    total = 0.0
    page_cursor = None
    pages_read = 0

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            while pages_read < _MAX_PAGES:
                params = {
                    "start_time": since_unix,
                    "bucket_width": "1d",
                    "limit": 180,
                    "project_ids[]": project_id,
                }
                if page_cursor:
                    params["page"] = page_cursor

                resp = await client.get(COSTS_API_URL, headers=headers, params=params)
                resp.raise_for_status()
                payload = resp.json()

                for bucket in payload.get("data", []):
                    for result in bucket.get("results", []):
                        if result.get("project_id") not in (None, project_id):
                            continue  # por si la API no filtró del todo server-side
                        amount = result.get("amount") or {}
                        total += float(amount.get("value") or 0.0)

                pages_read += 1
                if payload.get("has_more") and payload.get("next_page"):
                    page_cursor = payload["next_page"]
                else:
                    break
            else:
                logging.warning(f"[OpenAICosts] Se alcanzó el tope de {_MAX_PAGES} páginas para project_id={project_id}, el total puede estar incompleto")

        return round(total, 4)
    except Exception as e:
        logging.error(f"[OpenAICosts] No se pudo consultar el gasto real de project_id={project_id}: {e}")
        return None


async def check_admin_key_valid() -> tuple[bool, str]:
    """Prueba rápida de la Admin API Key contra la Costs API (1 día, sin filtrar project).
    Devuelve (ok, mensaje) para mostrar feedback inmediato al guardarla desde el panel."""
    admin_key = get_system_config(OPENAI_ADMIN_KEY_CONFIG_KEY)
    if not admin_key:
        return False, "No hay Admin API Key cargada"
    headers = {"Authorization": f"Bearer {admin_key}"}
    since_unix = int(time.time()) - 86400
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(COSTS_API_URL, headers=headers, params={"start_time": since_unix, "bucket_width": "1d", "limit": 1})
        if resp.status_code == 200:
            return True, "OK"
        return False, f"OpenAI devolvió {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)
