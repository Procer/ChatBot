import logging

import requests

MP_API_BASE = "https://api.mercadopago.com"


def create_preference(access_token: str, title: str, amount: float, currency_id: str,
                       external_reference: str, notification_url: str, back_url: str = "https://anka.ar/"):
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
