"""Retención de datos del chat web (Fase 5).

Los chats web guardan datos personales (DNI, protocolo, nombre de pila, historial). Para no
acumularlos indefinidamente:
- Un celular que no abre el chat durante `web_chat_retention_days` (default 180; 0 = no borrar nunca)
  se borra por completo: vínculos, PDFs entregados (solo el registro, los archivos viven en Drive),
  suscripciones de avisos, mensajes, etiquetas, nombre y la memoria del bot de esa conversación.
- Los intentos de vinculación (que guardan el DNI tipeado) se borran a los 90 días.
No se tocan datos del negocio: turnos, formularios y consumo de IA quedan (no identifican al chat).
"""
import logging
import os
import sqlite3
from datetime import datetime, timedelta

from src.database.models import (ChatNote, ClientSettings, Message, Pause, UserProfile, UserTag, WebBroadcastRecipient,
                                 WebDelivery, WebDevice, WebEvent, WebLink, WebLinkAttempt, WebPushSub)
from src.database.session import SessionLocal

DEFAULT_RETENTION_DAYS = 180
ATTEMPTS_RETENTION_DAYS = 90
BATCH = 200
LOOP_SECONDS = 6 * 3600
CHECKPOINTS_PATH = "checkpoints.sqlite"   # mismo archivo que usa "borrar sesión" del panel


def retention_days(settings) -> int:
    d = settings.web_chat_retention_days
    return DEFAULT_RETENTION_DAYS if d is None else max(0, d)


def _purge_checkpoints(thread_ids: list):
    """Borra la memoria del bot (LangGraph) de esas conversaciones. Mismo archivo/tablas que 'borrar sesión' del panel."""
    path = CHECKPOINTS_PATH
    if not thread_ids or not os.path.exists(path):
        return
    try:
        conn = sqlite3.connect(path, timeout=30)
        for table in ("checkpoints", "writes", "blobs", "checkpoint_writes", "checkpoint_blobs"):
            for i in range(0, len(thread_ids), 500):
                chunk = thread_ids[i:i + 500]
                try:
                    conn.execute(f"DELETE FROM {table} WHERE thread_id IN ({','.join('?' * len(chunk))})", chunk)
                except sqlite3.OperationalError as e:
                    if "no such table" not in str(e).lower():
                        raise
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"[WebRetention] No se pudo limpiar la memoria del bot: {e}")


def purge_client(client_id: int, days: int, now: datetime = None) -> dict:
    """Borra los celulares del cliente inactivos hace más de `days` días. Devuelve los conteos."""
    now = now or datetime.utcnow()
    out = {"devices": 0, "events": 0, "messages": 0, "attempts": 0}
    db = SessionLocal()
    try:
        # Intentos de vinculación viejos (guardan el DNI tipeado)
        out["attempts"] = db.query(WebLinkAttempt).filter(
            WebLinkAttempt.client_id == client_id,
            WebLinkAttempt.created_at < now - timedelta(days=ATTEMPTS_RETENTION_DAYS)).delete(synchronize_session=False)
        db.commit()
        if days <= 0:
            return out
        cutoff = now - timedelta(days=days)
        while True:
            devs = db.query(WebDevice).filter(WebDevice.client_id == client_id, WebDevice.last_seen_at < cutoff) \
                .order_by(WebDevice.id.asc()).limit(BATCH).all()
            if not devs:
                break
            ids = [d.id for d in devs]
            threads = [d.thread_id for d in devs]
            out["events"] += db.query(WebEvent).filter(WebEvent.device_id.in_(ids)).delete(synchronize_session=False)
            db.query(WebDelivery).filter(WebDelivery.device_id.in_(ids)).delete(synchronize_session=False)
            db.query(WebLink).filter(WebLink.device_id.in_(ids)).delete(synchronize_session=False)
            db.query(WebPushSub).filter(WebPushSub.device_id.in_(ids)).delete(synchronize_session=False)
            db.query(WebBroadcastRecipient).filter(WebBroadcastRecipient.device_id.in_(ids)).delete(synchronize_session=False)
            out["messages"] += db.query(Message).filter(Message.client_id == client_id, Message.thread_id.in_(threads)).delete(synchronize_session=False)
            db.query(Pause).filter(Pause.client_id == client_id, Pause.user_id.in_(threads)).delete(synchronize_session=False)
            db.query(UserTag).filter(UserTag.client_id == client_id, UserTag.thread_id.in_(threads)).delete(synchronize_session=False)
            db.query(UserProfile).filter(UserProfile.client_id == client_id, UserProfile.user_phone.in_(threads)).delete(synchronize_session=False)
            db.query(ChatNote).filter(ChatNote.client_id == client_id, ChatNote.thread_id.in_(threads)).delete(synchronize_session=False)
            db.query(WebDevice).filter(WebDevice.id.in_(ids)).delete(synchronize_session=False)
            db.commit()
            _purge_checkpoints(threads)
            out["devices"] += len(ids)
    except Exception as e:
        db.rollback()
        logging.error(f"[WebRetention] Error limpiando el cliente {client_id}: {e}")
    finally:
        db.close()
    return out


def run_all() -> dict:
    """Aplica la retención a todos los clientes que tienen el chat web habilitado."""
    db = SessionLocal()
    try:
        rows = [(s.client_id, retention_days(s)) for s in db.query(ClientSettings).filter(ClientSettings.feat_web_chat == True).all()]  # noqa: E712
    finally:
        db.close()
    total = {"devices": 0, "events": 0, "messages": 0, "attempts": 0}
    for cid, days in rows:
        r = purge_client(cid, days)
        for k in total:
            total[k] += r[k]
        if r["devices"] or r["attempts"]:
            logging.info(f"[WebRetention] Cliente {cid}: {r}")
    return total
