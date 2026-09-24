"""Avisos masivos del chat web (Fase 4).

El cliente escribe un aviso desde el panel y se manda como notificación push SOLO a los celulares
que aceptaron "Novedades" (tema aparte del de los resultados: un mal aviso masivo no puede hacer
que el paciente apague el aviso de "llegó tu análisis").

Protecciones:
- Tope mensual por cliente (default 3) y ventana horaria permitida (default 9 a 20 h, hora Argentina):
  fuera de la ventana el envío se corre al próximo horario permitido.
- Audiencia elegible: todos los que aceptaron novedades, o los que recibieron un análisis en los
  últimos N días.
- El envío es a lo sumo una vez: pasa de "programado" a "enviando" de forma atómica.
"""
import logging
from datetime import datetime, timedelta

from src.database.models import (ClientSettings, WebBroadcast, WebBroadcastRecipient, WebDelivery, WebDevice,
                                 WebEvent, WebPushSub)
from src.database.session import SessionLocal

DEFAULT_CAP = 3
DEFAULT_FROM, DEFAULT_TO = 9, 20
MAX_TITLE, MAX_BODY, MAX_CHAT = 65, 140, 1000
UNSUB_HINT = "\n\n_Para dejar de recibir estas novedades: Menú → Avisos en este celular._"
_AR = timedelta(hours=3)          # Argentina = UTC-3 todo el año


def to_local(dt_utc: datetime) -> datetime:
    return dt_utc - _AR


def to_utc(dt_local: datetime) -> datetime:
    return dt_local + _AR


def hours_window(settings) -> tuple:
    f = settings.web_chat_broadcast_from if settings.web_chat_broadcast_from is not None else DEFAULT_FROM
    t = settings.web_chat_broadcast_to if settings.web_chat_broadcast_to is not None else DEFAULT_TO
    f = max(0, min(23, f))
    t = max(f + 1, min(24, t))
    return f, t


def adjust_to_window(dt_utc: datetime, hfrom: int, hto: int) -> datetime:
    """Si `dt_utc` cae fuera de la ventana horaria permitida, lo corre al próximo inicio de ventana."""
    loc = to_local(dt_utc)
    if hfrom <= loc.hour < hto:
        return dt_utc
    day = loc if loc.hour < hfrom else loc + timedelta(days=1)
    return to_utc(day.replace(hour=hfrom, minute=0, second=0, microsecond=0))


def _month_bounds_utc(ref_utc: datetime):
    loc = to_local(ref_utc)
    start = loc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = (start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1))
    return to_utc(start), to_utc(nxt)


def used_in_month(db, client_id: int, ref_utc: datetime) -> int:
    a, b = _month_bounds_utc(ref_utc)
    return db.query(WebBroadcast).filter(
        WebBroadcast.client_id == client_id, WebBroadcast.status.in_(("programado", "enviando", "enviado")),
        WebBroadcast.scheduled_at >= a, WebBroadcast.scheduled_at < b).count()


def cap_of(settings) -> int:
    return settings.web_chat_broadcast_cap if settings.web_chat_broadcast_cap is not None else DEFAULT_CAP


def audience_devices(db, client_id: int, audience: str, days: int = None) -> list:
    """ids de los celulares que recibirían el aviso ahora."""
    news = {d for (d,) in db.query(WebPushSub.device_id).filter(
        WebPushSub.client_id == client_id, WebPushSub.topic_news == True).all()}   # noqa: E712
    if not news:
        return []
    blocked = {d for (d,) in db.query(WebDevice.id).filter(WebDevice.client_id == client_id, WebDevice.blocked == True).all()}  # noqa: E712
    ids = news - blocked
    if audience == "recent":
        since = datetime.utcnow() - timedelta(days=max(1, days or 30))
        recent = {d for (d,) in db.query(WebDelivery.device_id).filter(
            WebDelivery.client_id == client_id, WebDelivery.created_at >= since).all()}
        ids &= recent
    return sorted(ids)


def send_broadcast(broadcast_id: int) -> str:
    """Envía un aviso programado. Bloqueante (usar asyncio.to_thread). Devuelve el estado final."""
    from src import web_push
    db = SessionLocal()
    try:
        # Reclamo atómico: si otro proceso/tarea ya lo tomó, no se manda dos veces
        claimed = db.query(WebBroadcast).filter(WebBroadcast.id == broadcast_id, WebBroadcast.status == "programado") \
            .update({"status": "enviando"}, synchronize_session=False)
        db.commit()
        if not claimed:
            return "omitido"
        b = db.get(WebBroadcast, broadcast_id)
        settings = db.query(ClientSettings).filter_by(client_id=b.client_id).first()
        if not settings or not settings.feat_web_chat or not settings.web_chat_enabled:
            b.status = "cancelado"
            db.commit()
            return "cancelado"
        devices = audience_devices(db, b.client_id, b.audience, b.audience_days)
        b.recipients = len(devices)
        db.commit()
        text = ((b.chat_message or "").strip() + UNSUB_HINT) if (b.chat_message or "").strip() else ""
        sent = failed = 0
        for dev_id in devices:
            ev_id = 0
            try:
                if text:
                    ev = WebEvent(client_id=b.client_id, device_id=dev_id, kind="bot", text=text)
                    db.add(ev)
                    db.commit()
                    ev_id = ev.id
                ok = web_push.notify_device(b.client_id, dev_id, "news", ev_id, body=b.body, skip_if_active=False,
                                            broadcast_id=b.id, title=b.title) > 0
            except Exception as e:
                db.rollback()
                logging.error(f"[WebBroadcast] Error con el dispositivo {dev_id} (aviso {b.id}): {e}")
                ok = False
            db.add(WebBroadcastRecipient(broadcast_id=b.id, device_id=dev_id, ok=ok))
            db.commit()
            sent += 1 if ok else 0
            failed += 0 if ok else 1
        b.sent, b.failed, b.status, b.sent_at = sent, failed, "enviado", datetime.utcnow()
        db.commit()
        logging.info(f"[WebBroadcast] Aviso {b.id} (cliente {b.client_id}): {sent} enviados, {failed} fallidos de {len(devices)}")
        return "enviado"
    except Exception as e:
        db.rollback()
        logging.error(f"[WebBroadcast] Error enviando el aviso {broadcast_id}: {e}")
        try:
            db.query(WebBroadcast).filter(WebBroadcast.id == broadcast_id, WebBroadcast.status == "enviando") \
                .update({"status": "error"}, synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
        return "error"
    finally:
        db.close()


def run_due() -> int:
    """Manda los avisos programados cuyo horario ya llegó (los llama el bucle cada minuto)."""
    now = datetime.utcnow()
    db = SessionLocal()
    ids = []
    try:
        for b in db.query(WebBroadcast).filter(WebBroadcast.status == "programado", WebBroadcast.scheduled_at <= now).all():
            settings = db.query(ClientSettings).filter_by(client_id=b.client_id).first()
            hfrom, hto = hours_window(settings) if settings else (DEFAULT_FROM, DEFAULT_TO)
            adj = adjust_to_window(now, hfrom, hto)
            if adj != now:                       # el servidor estuvo caido y ya es de noche: se corre al próximo horario permitido
                b.scheduled_at = adj
                continue
            ids.append(b.id)
        db.commit()
    finally:
        db.close()
    for i in ids:
        send_broadcast(i)
    return len(ids)
