"""Notificaciones push (Web Push estándar) del chat web.

- Claves VAPID PROPIAS de cada cliente (aislamiento por tenant): se generan solas la primera vez,
  la privada se guarda cifrada igual que las demás credenciales.
- El texto de la notificación es SIEMPRE genérico ("Tenés novedades"): se ve en la pantalla
  bloqueada y nunca lleva datos de salud.
- Los endpoints de suscripción solo pueden ser de los servicios de push conocidos (Google, Mozilla,
  Apple, Microsoft): el servidor hace un POST a esa URL, así que no se acepta cualquier dirección.
- Suscripciones muertas (404/410 del servicio de push) se borran solas.
"""
import base64
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime
from urllib.parse import urlparse

from src.database.gdrive_sync import decrypt_token, encrypt_token
from src.database.models import ClientSettings, WebPushSub
from src.database.session import SessionLocal

MAX_SUBS_PER_DEVICE = 5
MAX_FAILS = 5                 # fallos seguidos (no 404/410) antes de descartar una suscripcion
ACTIVE_WINDOW = 25            # seg: si el chat esta abierto (consulta reciente) no se manda push
PUSH_TTL = 12 * 3600
BODY_DEFAULT = "Tenés novedades"

_ALLOWED_HOST = re.compile(
    r"(^|\.)(fcm\.googleapis\.com|android\.googleapis\.com|push\.services\.mozilla\.com|"
    r"push\.apple\.com|notify\.windows\.com)$")
_last_poll = {}               # device_id -> monotonic de la ultima consulta del chat abierto


# ── actividad del chat (para no avisar a quien ya lo está mirando) ────────────

def mark_active(device_id: int):
    if len(_last_poll) > 5000:
        _last_poll.clear()
    _last_poll[device_id] = time.monotonic()


def is_active(device_id: int) -> bool:
    return time.monotonic() - _last_poll.get(device_id, -1e9) < ACTIVE_WINDOW


# ── claves VAPID por cliente ──────────────────────────────────────────────────

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def ensure_vapid(db, settings: ClientSettings) -> str:
    """Clave pública VAPID del cliente (base64url). Si todavía no tiene claves, las genera y guarda."""
    if settings.web_push_public_key and settings.web_push_private_key_encrypted:
        return settings.web_push_public_key
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid
    v = Vapid()
    v.generate_keys()
    pem = v.private_pem().decode()
    pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    settings.web_push_private_key_encrypted = encrypt_token(pem)
    settings.web_push_public_key = _b64url(pub)
    db.commit()
    return settings.web_push_public_key


def _vapid_for(settings: ClientSettings):
    from py_vapid import Vapid
    return Vapid.from_pem(decrypt_token(settings.web_push_private_key_encrypted).encode())


def _subject() -> str:
    base = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
    return base if base.startswith("https://") else "mailto:soporte@anka.ar"


# ── suscripciones ─────────────────────────────────────────────────────────────

def endpoint_allowed(endpoint: str) -> bool:
    try:
        u = urlparse(endpoint)
    except Exception:
        return False
    if os.getenv("WEB_PUSH_ALLOW_LOCAL") == "1" and u.hostname in ("127.0.0.1", "localhost"):
        return True                      # solo para pruebas automaticas
    return u.scheme == "https" and bool(u.hostname) and bool(_ALLOWED_HOST.search(u.hostname)) and len(endpoint) <= 2000


def push_state(db, device_id: int) -> dict:
    subs = db.query(WebPushSub).filter_by(device_id=device_id).all()
    return {"subscribed": bool(subs), "alerts": any(s.topic_alerts for s in subs), "news": any(s.topic_news for s in subs)}


def save_subscription(db, client_id: int, device_id: int, sub: dict, alerts: bool, news: bool):
    """Alta o actualización de la suscripción. Devuelve (ok, error)."""
    endpoint = (sub or {}).get("endpoint") or ""
    keys = (sub or {}).get("keys") or {}
    p256dh, auth = keys.get("p256dh") or "", keys.get("auth") or ""
    if not endpoint_allowed(endpoint):
        return False, "endpoint"
    if not (10 <= len(p256dh) <= 200 and 8 <= len(auth) <= 100):
        return False, "keys"
    h = hashlib.sha256(endpoint.encode()).hexdigest()
    row = db.query(WebPushSub).filter_by(endpoint_hash=h).first()
    if row and (row.device_id != device_id or row.client_id != client_id):
        # El mismo navegador pasa a ser de este dispositivo (p. ej. borraron los datos del sitio): se reasigna.
        row.device_id, row.client_id = device_id, client_id
    if not row:
        if db.query(WebPushSub).filter_by(device_id=device_id).count() >= MAX_SUBS_PER_DEVICE:
            oldest = db.query(WebPushSub).filter_by(device_id=device_id).order_by(WebPushSub.id.asc()).first()
            db.delete(oldest)
        row = WebPushSub(client_id=client_id, device_id=device_id, endpoint=endpoint, endpoint_hash=h)
        db.add(row)
    row.p256dh, row.auth, row.fail_count = p256dh, auth, 0
    row.topic_alerts, row.topic_news = bool(alerts), bool(news)
    db.commit()
    return True, None


def set_topics(db, device_id: int, alerts: bool, news: bool):
    for s in db.query(WebPushSub).filter_by(device_id=device_id).all():
        s.topic_alerts, s.topic_news = bool(alerts), bool(news)
    db.commit()


def remove_subscriptions(db, device_id: int):
    db.query(WebPushSub).filter_by(device_id=device_id).delete()
    db.commit()


# ── envío ─────────────────────────────────────────────────────────────────────

def _send_one(settings, sub: WebPushSub, payload: dict) -> int:
    """Manda un push. Devuelve el código HTTP del servicio de push (0 si falló sin respuesta)."""
    from pywebpush import WebPushException, webpush
    try:
        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=_vapid_for(settings),
            vapid_claims={"sub": _subject()},
            ttl=PUSH_TTL, timeout=10,
        )
        return 201
    except WebPushException as e:
        return getattr(getattr(e, "response", None), "status_code", 0) or 0


def notify_device(client_id: int, device_id: int, topic: str = "alerts", event_id: int = None,
                  body: str = BODY_DEFAULT, skip_if_active: bool = True, broadcast_id: int = 0, title: str = None) -> int:
    """Manda el aviso a todas las suscripciones del celular que aceptaron ese tema.
    Bloqueante (usar asyncio.to_thread). Devuelve cuántos se enviaron."""
    if skip_if_active and is_active(device_id):
        return 0
    db = SessionLocal()
    sent = 0
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings or not settings.web_push_private_key_encrypted:
            return 0
        col = WebPushSub.topic_news if topic == "news" else WebPushSub.topic_alerts
        subs = db.query(WebPushSub).filter(WebPushSub.device_id == device_id, WebPushSub.client_id == client_id, col == True).all()  # noqa: E712
        if not subs:
            return 0
        from src.web_chat import get_config
        from src.database.models import Client
        client = db.query(Client).filter_by(id=client_id).first()
        title = title or (get_config(client, settings)["title"] if client else "Novedades")
        payload = {"title": title, "body": body, "m": event_id or 0}
        if broadcast_id:
            payload["b"] = broadcast_id          # para contar cuantos tocaron el aviso
        for s in subs:
            code = _send_one(settings, s, payload)
            if 200 <= code < 300:
                s.fail_count, s.last_ok_at = 0, datetime.utcnow()
                sent += 1
            elif code in (404, 410):          # el navegador ya no acepta avisos: se elimina sola
                db.delete(s)
            else:
                s.fail_count = (s.fail_count or 0) + 1
                logging.warning(f"[WebPush] Falló un aviso (cliente {client_id}, dispositivo {device_id}): HTTP {code}")
                if s.fail_count >= MAX_FAILS:
                    db.delete(s)
        db.commit()
    except Exception as e:
        db.rollback()
        logging.error(f"[WebPush] Error avisando al dispositivo {device_id}: {e}")
    finally:
        db.close()
    return sent
