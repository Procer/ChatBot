"""Resultados de análisis dentro del chat web (Fase 2).

El paciente vincula su celular con DNI + número de protocolo (el del papel). La verificación es
contra la carpeta de Drive del cliente (la misma del portal "Mis Resultados", archivos
"<PROTOCOLO>-<DNI>.pdf"): el vínculo queda `verificado` solo cuando existe un archivo cuyo nombre
tiene EXACTAMENTE ese protocolo y ese DNI. Mientras no exista queda `pendiente` (10 días) y se
reintenta solo mientras el chat está abierto. Una vez verificado, los análisis nuevos de ese DNI
llegan solos, como una tarjeta dentro del chat.

Privacidad:
- La respuesta al vincular es siempre la misma exista o no el DNI en Drive (no se revela si un
  DNI tiene análisis ni si el protocolo no coincide).
- Los PDFs no se copian: se traen de Drive en el momento y solo los ve el celular vinculado.
- Tope de intentos por celular y por IP (registro de cada intento).
"""
import asyncio
import logging
import re
import time
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from src import results_portal as rp
from src.database.models import (ClientSettings, WebDelivery, WebDevice, WebEvent, WebLink, WebLinkAttempt)
from src.database.session import SessionLocal
from src.web_chat import add_event

PENDING_DAYS = 10             # ventana para que aparezca el PDF de un vínculo pendiente
ATTEMPTS_PER_DEVICE = 5       # intentos de vincular por celular por hora
ATTEMPTS_PER_IP = 20          # por IP por hora (la recepción comparte wifi)
ATTEMPT_WINDOW = 3600
SYNC_MIN_INTERVAL = 90        # segundos entre consultas a Drive por celular (mientras el chat está abierto)
MAX_DELIVER_PER_SYNC = 30

DEFAULT_CONSENT = ("Acepto que {negocio} use mi DNI y el número de protocolo solo para entregarme mis resultados "
                   "en este celular. Puedo desvincularme cuando quiera desde el menú.")

_last_sync = {}               # device_id -> monotonic del último sync
_syncing = set()              # device_ids con un sync en curso


# ── utilidades ────────────────────────────────────────────────────────────────

def results_enabled(settings) -> bool:
    """El chat entrega resultados solo si el cliente lo encendió y tiene carpeta + Drive configurados."""
    return bool(settings and settings.web_chat_results_enabled and settings.results_portal_folder_id
                and settings.gdrive_service_account_json_encrypted)


def mask_dni(dni: str) -> str:
    return "•••" + (dni or "")[-3:]


def normalize_protocol(raw: str):
    p = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    return p if re.fullmatch(r"[A-Z0-9]{3,12}", p) and re.search(r"\d", p) else None


def consent_text(settings, business_name: str) -> str:
    txt = (settings.web_chat_consent or "").strip() if settings else ""
    return txt or DEFAULT_CONSENT.format(negocio=business_name)


def serialize_link(l: WebLink) -> dict:
    return {"id": l.id, "dni_mask": mask_dni(l.dni), "name": l.name or "", "protocol": l.protocol, "status": l.status}


def attempts_allowed(db, client_id: int, device_id: int, ip: str) -> bool:
    since = datetime.utcnow() - timedelta(seconds=ATTEMPT_WINDOW)
    dev = db.query(WebLinkAttempt).filter(WebLinkAttempt.client_id == client_id, WebLinkAttempt.device_id == device_id,
                                          WebLinkAttempt.created_at >= since).count()
    if dev >= ATTEMPTS_PER_DEVICE:
        return False
    if ip:
        by_ip = db.query(WebLinkAttempt).filter(WebLinkAttempt.client_id == client_id, WebLinkAttempt.ip == ip,
                                                WebLinkAttempt.created_at >= since).count()
        if by_ip >= ATTEMPTS_PER_IP:
            return False
    return True


def record_attempt(db, client_id: int, device_id: int, ip: str, dni: str):
    db.add(WebLinkAttempt(client_id=client_id, device_id=device_id, ip=(ip or "")[:64], dni=dni[:12]))
    db.commit()


# ── entrega de archivos ───────────────────────────────────────────────────────

def _log_panel(client_id: int, thread_id: str, text: str):
    try:
        from src.database.analytics_engine_saas import log_message
        log_message(client_id, thread_id, "bot", text)
    except Exception as e:
        logging.warning(f"[WebResults] No se pudo registrar en el historial: {e}")


def _deliver(db, device: WebDevice, link: WebLink, f: dict, text: str = "") -> bool:
    """Crea el evento-tarjeta y la entrega. False si ese archivo ya se había entregado a este celular."""
    if db.query(WebDelivery).filter_by(device_id=device.id, file_id=f["file_id"]).first():
        return False
    label = "Análisis del " + rp.format_date_label(f["created"])
    attach = {"type": "result", "link": link.id, "protocol": f["protocolo"], "label": label, "dni_mask": mask_dni(link.dni),
              "name": f"Analisis-{re.sub(r'[^A-Za-z0-9-]', '', f['protocolo'])}.pdf"}
    ev = add_event(db, link.client_id, device.id, "bot", text, attach)
    try:
        db.add(WebDelivery(client_id=link.client_id, device_id=device.id, link_id=link.id, file_id=f["file_id"],
                           protocol=f["protocolo"][:20], event_id=ev.id))
        db.commit()
    except IntegrityError:          # otro sync lo entregó justo antes
        db.rollback()
        db.delete(db.get(WebEvent, ev.id))
        db.commit()
        return False
    _log_panel(link.client_id, device.thread_id, f"[Análisis entregado en el chat · Protocolo {f['protocolo']}]")
    return True


def sync_links(client_id: int, device_id: int, force: bool = False, notify: bool = False):
    """Consulta Drive para los vínculos activos de un celular: verifica los pendientes y entrega los
    análisis nuevos de los verificados. Devuelve la cantidad de entregas, o None si no se pudo
    consultar Drive. notify=True manda un aviso push (genérico) si hubo entregas y el chat no está
    abierto. Bloqueante: llamarlo con asyncio.to_thread."""
    res = _sync_links(client_id, device_id, force)
    if notify and res and res[0] > 0:
        try:
            from src import web_push
            web_push.notify_device(client_id, device_id, "alerts", res[1])
        except Exception as e:
            logging.error(f"[WebResults] No se pudo mandar el aviso push: {e}")
    return None if res is None else res[0]


def _sync_links(client_id: int, device_id: int, force: bool = False):
    """Núcleo de sync_links. Devuelve (entregas, id del último evento entregado) o None si Drive falló."""
    now_m = time.monotonic()
    if not force and now_m - _last_sync.get(device_id, 0) < SYNC_MIN_INTERVAL:
        return 0, 0
    if device_id in _syncing:
        return 0, 0
    _syncing.add(device_id)
    _last_sync[device_id] = now_m
    last_event = 0
    if len(_last_sync) > 5000:
        _last_sync.clear()
    db = SessionLocal()
    delivered = 0
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        device = db.query(WebDevice).filter_by(id=device_id, client_id=client_id).first()
        if not device or not results_enabled(settings):
            return 0, 0
        links = db.query(WebLink).filter(WebLink.device_id == device_id,
                                         WebLink.status.in_(("pendiente", "verificado"))).all()
        if not links:
            return 0, 0
        days = settings.results_portal_days or rp.DEFAULT_DAYS
        phone = (settings.results_portal_phone or settings.company_phone or "").strip()
        contact = f" o consultá en el laboratorio ({phone})" if phone else " o consultá en el laboratorio"
        for link in links:
            if link.status == "pendiente" and link.expires_at and link.expires_at < datetime.utcnow():
                link.status = "vencido"
                db.commit()
                add_event(db, client_id, device.id, "bot",
                          f"No encontramos el análisis del protocolo **{link.protocol}** en {PENDING_DAYS} días. "
                          f"Revisá que el DNI y el protocolo estén bien escritos y volvé a vincular{contact}.")
                continue
            try:
                files = rp.search_result_files(client_id, settings.results_portal_folder_id, link.dni, days)
            except Exception as e:
                logging.error(f"[WebResults] Drive falló (cliente {client_id}, dispositivo {device_id}): {e}")
                return None
            link.last_check_at = datetime.utcnow()
            db.commit()
            files.sort(key=lambda x: x["created"])          # más viejo primero: el más nuevo queda abajo
            if link.status == "pendiente":
                if not any((f["protocolo"] or "").upper() == link.protocol for f in files):
                    continue
                link.status, link.verified_at, link.expires_at = "verificado", datetime.utcnow(), None
                db.commit()
                who = f", {link.name}" if link.name else ""
                add_event(db, client_id, device.id, "sys", f"Paciente vinculado · DNI {mask_dni(link.dni)}")
                add_event(db, client_id, device.id, "bot",
                          f"¡Listo{who}! Encontré tu análisis. Lo podés ver, bajar o compartir desde acá.")
                # Análisis de los últimos días de ese DNI, sin aviso (verificado por el protocolo del papel)
                for f in files[-MAX_DELIVER_PER_SYNC:]:
                    if _deliver(db, device, link, f):
                        delivered += 1
                        last_event = _last_delivered(db, device.id)
            else:
                for f in files[-MAX_DELIVER_PER_SYNC:]:
                    if _deliver(db, device, link, f, text="Llegó un análisis nuevo."):
                        delivered += 1
                        last_event = _last_delivered(db, device.id)
    except Exception as e:
        db.rollback()
        logging.error(f"[WebResults] Error en sync (cliente {client_id}, dispositivo {device_id}): {e}")
        return None
    finally:
        _syncing.discard(device_id)
        db.close()
    return delivered, last_event


def _last_delivered(db, device_id: int) -> int:
    row = db.query(WebDelivery.event_id).filter_by(device_id=device_id).order_by(WebDelivery.id.desc()).first()
    return row[0] if row and row[0] else 0


def link_patient(client_id: int, device_id: int, dni: str, protocol: str, name: str):
    """Crea o actualiza el vínculo (siempre queda pendiente) y verifica en el acto si el PDF ya está.
    Devuelve (status, drive_ok). Bloqueante."""
    db = SessionLocal()
    try:
        link = db.query(WebLink).filter_by(device_id=device_id, dni=dni).first()
        now = datetime.utcnow()
        if link is None:
            link = WebLink(client_id=client_id, device_id=device_id, dni=dni)
            db.add(link)
        elif link.status == "verificado" and link.protocol == protocol:
            link.name = name or link.name
            db.commit()
            return "verificado", True
        link.protocol, link.name = protocol, (name or link.name)
        link.status, link.consent_at, link.expires_at = "pendiente", now, now + timedelta(days=PENDING_DAYS)
        link.verified_at = None
        db.commit()
    finally:
        db.close()
    res = sync_links(client_id, device_id, force=True, notify=False)
    db = SessionLocal()
    try:
        link = db.query(WebLink).filter_by(device_id=device_id, dni=dni).first()
        return (link.status if link else "pendiente"), res is not None
    finally:
        db.close()


def revoke_link(db, link: WebLink, status: str = "revocado"):
    """Desvincula: el archivo deja de ser accesible y las tarjetas de ese paciente se borran del chat."""
    ev_ids = [d.event_id for d in db.query(WebDelivery).filter_by(link_id=link.id).all() if d.event_id]
    db.query(WebDelivery).filter_by(link_id=link.id).delete()
    if ev_ids:
        db.query(WebEvent).filter(WebEvent.id.in_(ev_ids)).delete(synchronize_session=False)
    link.status, link.expires_at = status, None
    db.commit()


def purge_device(db, device_id: int):
    """Borra todo lo de un celular (para 'borrar sesión' desde el panel)."""
    db.query(WebDelivery).filter_by(device_id=device_id).delete()
    db.query(WebLink).filter_by(device_id=device_id).delete()
    db.query(WebEvent).filter_by(device_id=device_id).delete()
    db.commit()


async def sync_in_background(client_id: int, device_id: int, force: bool = False):
    await asyncio.to_thread(sync_links, client_id, device_id, force, True)


WATCH_OVERLAP = timedelta(minutes=5)     # se revisa un poco hacia atras para no perder archivos que Drive demora en reflejar
WATCH_TICK_SECONDS = 180


def watch_client(client_id: int):
    """Vigía de la carpeta de PROTOCOLOS: busca archivos nuevos desde la última revisión y, para los
    DNI que tienen un celular vinculado (o pendiente), entrega el análisis y avisa por push.
    No hace falta que el paciente tenga el chat abierto. Bloqueante."""
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not results_enabled(settings) or not settings.web_chat_enabled:
            return 0
        started = datetime.utcnow()
        if settings.web_chat_watch_at is None:       # primera vez: solo se marca el punto de partida
            settings.web_chat_watch_at = started
            db.commit()
            return 0
        since = settings.web_chat_watch_at - WATCH_OVERLAP
        active = db.query(WebLink).filter(WebLink.client_id == client_id, WebLink.status.in_(("pendiente", "verificado")))
        if active.count() == 0:                      # nadie a quien avisar: ni se consulta Drive
            settings.web_chat_watch_at = started
            db.commit()
            return 0
        try:
            dnis = rp.list_recent_dnis(client_id, settings.results_portal_folder_id, since)
        except Exception as e:
            logging.error(f"[WebWatch] Drive falló (cliente {client_id}): {e}")
            return 0
        device_ids = set()
        if dnis:
            device_ids = {d for (d,) in active.filter(WebLink.dni.in_(list(dnis))).with_entities(WebLink.device_id).all()}
        settings.web_chat_watch_at = started
        db.commit()
    finally:
        db.close()
    total = 0
    for dev_id in device_ids:
        res = sync_links(client_id, dev_id, force=True, notify=True)
        total += res or 0
    if device_ids:
        logging.info(f"[WebWatch] Cliente {client_id}: {len(dnis)} DNI con archivos nuevos, {len(device_ids)} celulares, {total} entregas")
    return total
