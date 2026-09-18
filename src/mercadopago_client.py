import logging

import requests

MP_API_BASE = "https://api.mercadopago.com"


def create_preference(access_token: str, title: str, amount: float, currency_id: str,
                       external_reference: str, notification_url: str, back_url: str = "https://anka.ar/",
                       payer_name: str = None):
    """Crea una preferencia de Checkout Pro en la cuenta de Mercado Pago del cliente.
    Devuelve el dict de la respuesta de MP (incluye 'id' e 'init_point'), o None si falló."""
    payload = {
        "items": [{
            "title": title,
            "quantity": 1,
            "unit_price": float(amount),
            "currency_id": currency_id,
        }],
        "external_reference": external_reference,
        "notification_url": notification_url,
        "back_urls": {
            "success": back_url,
            "pending": back_url,
            "failure": back_url,
        },
    }
    # Sin datos del comprador, Mercado Pago trata el checkout como "anónimo" y a veces limita
    # las opciones de pago sin cuenta a algo más restringido (ej. solo tarjeta prepaga) — reporte
    # real de un usuario probando en vivo (2026-09-16). Mandar al menos el nombre ya conocido del
    # cliente (no tenemos su email, es un bot de WhatsApp) para mitigar, aunque no lo garantiza:
    # es política de riesgo propia de MP, no 100% controlable desde acá.
    if payer_name and payer_name.strip():
        parts = payer_name.strip().split(" ", 1)
        payload["payer"] = {
            "name": parts[0],
            "surname": parts[1] if len(parts) > 1 else "",
        }
    try:
        resp = requests.post(
            f"{MP_API_BASE}/checkout/preferences",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logging.error(f"[MercadoPago] Error creando preferencia: {e}")
        return None


def validate_access_token(access_token: str):
    """Verifica el access_token contra la API de Mercado Pago (GET /users/me).
    Devuelve (True, info) con info={'email','nickname','site_id'} si es válido,
    o (False, mensaje_para_mostrar_al_usuario) si no."""
    try:
        resp = requests.get(
            f"{MP_API_BASE}/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if resp.status_code == 401:
            return False, ("Mercado Pago rechazó el Access Token (credencial inválida o vencida). "
                            "Volvé a mercadopago.com.ar/developers/panel, entrá a la aplicación → "
                            "\"Credenciales de producción\" y copiá el Access Token completo de nuevo.")
        resp.raise_for_status()
        data = resp.json()
        return True, {
            "email": data.get("email"),
            "nickname": data.get("nickname"),
            "site_id": data.get("site_id"),
        }
    except Exception as e:
        logging.error(f"[MercadoPago] Error validando access token: {e}")
        return False, "No se pudo contactar a Mercado Pago para verificar la credencial (error de red). Probá de nuevo en un momento."


def get_payment(access_token: str, payment_id: str):
    """Consulta un pago por id usando el access_token del cliente dueño de la cuenta MP.
    Devuelve el dict de la respuesta de MP, o None si falló (id inexistente para esa cuenta,
    credencial inválida, etc.)."""
    try:
        resp = requests.get(
            f"{MP_API_BASE}/v1/payments/{payment_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if resp.status_code != 200:
            logging.error(f"[MercadoPago] get_payment {payment_id} -> HTTP {resp.status_code}: {resp.text[:300]}")
            return None
        return resp.json()
    except Exception as e:
        logging.error(f"[MercadoPago] Error consultando pago {payment_id}: {e}")
        return None
