"""Chat web propio de anka: una pagina a pantalla completa (link/QR) que habla con el mismo bot
que WhatsApp, respondiendo con los Conocimientos del cliente.

Cada celular/navegador es una conversacion: thread_id = "web:<public_id>". El celular guarda un
token secreto (localStorage + cookie HttpOnly); el servidor solo guarda su hash. Las respuestas del
bot, de una persona del panel y del sistema NO salen por WhatsApp/Telegram: se guardan como eventos
(web_events) y la pagina los consulta con polling.

Este modulo contiene los helpers, los envios "web" y el router publico. main_saas.py lo incluye
(build_router) y llama a send_web_message_saas / send_web_file_saas desde los puntos donde antes
solo habia whatsapp/telegram.
"""
import asyncio
import hashlib
import io
import json
import logging
import os
import re
import secrets
import time
from collections import deque
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.models import Client, ClientSettings, Pause, WebDevice, WebEvent
from src.database.session import SessionLocal, get_db

THREAD_PREFIX = "web:"
DEFAULT_COLOR = "#0F766E"
MAX_TEXT = 1000            # largo maximo de un mensaje del paciente
HISTORY_LIMIT = 100        # eventos que se devuelven al abrir el chat
DEFAULT_DAILY_CAP = 30     # mensajes al bot por celular por dia
DEFAULT_GLOBAL_CAP = 1000  # mensajes al bot de todo el chat de un cliente por dia
IP_MSGS_PER_HOUR = 90      # mensajes por IP por hora (varios celulares pueden compartir wifi)
IP_NEW_DEVICES_PER_HOUR = 20
DEFAULT_BUTTONS = [
    "Sacar turno",
    "Horarios y dirección",
    "Preparación para análisis",
    "Hablar con una persona",
]
DEFAULT_WELCOME = "¡Hola! Soy el asistente virtual. Puedo ayudarte con horarios, turnos y consultas. ¿En qué te ayudo?"

_busy = set()              # thread_ids con una respuesta del bot en curso (para mostrar "escribiendo...")
_ip_msgs = {}              # ip -> deque[timestamps]
_ip_devices = {}           # ip -> deque[timestamps]
_icon_cache = {}


# ── utilidades ────────────────────────────────────────────────────────────────

def is_web_thread(thread_id) -> bool:
    return isinstance(thread_id, str) and thread_id.startswith(THREAD_PREFIX)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _day_start_utc() -> datetime:
    """Inicio del dia en Argentina (UTC-3, sin horario de verano) expresado en UTC naive."""
    now_ar = datetime.utcnow() - timedelta(hours=3)
    return now_ar.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=3)


def _hit(store: dict, key: str, limit: int, window: int) -> bool:
    """Registra un pedido; True si todavia esta dentro del limite."""
    now = time.time()
    dq = store.setdefault(key, deque())
    while dq and now - dq[0] > window:
        dq.popleft()
    if len(dq) >= limit:
        return False
    dq.append(now)
    return True


def _norm_color(value) -> str:
    v = (value or "").strip()
    return v if re.fullmatch(r"#[0-9A-Fa-f]{6}", v) else DEFAULT_COLOR


def parse_buttons(raw) -> list:
    """web_chat_buttons es un JSON con una lista de textos. Vacio/invalido = botones por defecto."""
    if raw is None or not str(raw).strip():
        return list(DEFAULT_BUTTONS)
    try:
        data = json.loads(raw)
        items = [str(x).strip()[:60] for x in data if str(x).strip()] if isinstance(data, list) else []
    except Exception:
        return list(DEFAULT_BUTTONS)
    return items[:8]


def get_config(client, settings) -> dict:
    logo = getattr(settings, "logo_path", None) or ""
    return {
        "title": (settings.web_chat_title or "").strip() or client.business_name,
        "subtitle": (settings.web_chat_subtitle or "").strip() or "Asistente virtual",
        "welcome": (settings.web_chat_welcome or "").strip() or DEFAULT_WELCOME,
        "color": _norm_color(settings.web_chat_color),
        "buttons": parse_buttons(settings.web_chat_buttons),
        "logo": logo if logo.startswith("/uploads/") else "",
        "phone": (settings.company_phone or "").strip(),
    }


def get_available(db: Session, slug: str):
    """(client, settings) si el chat web de ese slug esta habilitado y encendido; si no (None, None)."""
    client = db.query(Client).filter_by(slug=slug).first()
    if not client or client.status != "active":
        return None, None
    settings = db.query(ClientSettings).filter_by(client_id=client.id).first()
    if not settings or not settings.feat_web_chat or not settings.web_chat_enabled:
        return None, None
    return client, settings


def _cookie_name(slug: str) -> str:
    return "wcd_" + re.sub(r"[^A-Za-z0-9_-]", "", slug)


def authenticate(db: Session, client_id: int, slug: str, request: Request):
    """Dispositivo dueño del token (header X-Device-Token o cookie) para ese cliente; None si no existe."""
    token = request.headers.get("x-device-token") or request.cookies.get(_cookie_name(slug)) or ""
    if not (20 <= len(token) <= 200):
        return None
    return db.query(WebDevice).filter_by(client_id=client_id, token_hash=hash_token(token)).first()


def serialize_event(e: WebEvent) -> dict:
    attach = None
    if e.attach_json:
        try:
            attach = json.loads(e.attach_json)
        except Exception:
            attach = None
    return {"id": e.id, "kind": e.kind, "text": e.text or "", "attach": attach,
            "ts": (e.created_at or datetime.utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")}


def add_event(db: Session, client_id: int, device_id: int, kind: str, text: str, attach: dict = None) -> WebEvent:
    ev = WebEvent(client_id=client_id, device_id=device_id, kind=kind, text=text,
                  attach_json=json.dumps(attach) if attach else None)
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def _device_by_thread(db: Session, client_id: int, thread_id: str):
    if not is_web_thread(thread_id):
        return None
    return db.query(WebDevice).filter_by(client_id=client_id, public_id=thread_id[len(THREAD_PREFIX):]).first()


def add_event_for_thread(client_id: int, thread_id: str, kind: str, text: str, attach: dict = None):
    """Agrega un evento a la conversacion web de un thread_id; devuelve su id (o None si no existe)."""
    db = SessionLocal()
    try:
        dev = _device_by_thread(db, client_id, thread_id)
        if not dev:
            logging.warning(f"[WebChat] Envio a un dispositivo inexistente: {thread_id} (cliente {client_id})")
            return None
        return add_event(db, client_id, dev.id, kind, text, attach).id
    except Exception as e:
        db.rollback()
        logging.error(f"[WebChat] Error guardando evento para {thread_id}: {e}")
        return None
    finally:
        db.close()


async def send_web_message_saas(client_id: int, thread_id: str, message: str, kind: str = "bot"):
    """Equivalente web de send_whatsapp_message_saas: guarda el mensaje como evento del chat."""
    ev_id = await asyncio.to_thread(add_event_for_thread, client_id, thread_id, kind, message)
    return f"web-{ev_id}" if ev_id else None


def _safe_attach_url(url: str) -> str:
    url = (url or "").strip()
    return url if (url.startswith("https://") or url.startswith("http://") or (url.startswith("/") and not url.startswith("//"))) else ""


async def send_web_file_saas(client_id: int, thread_id: str, file_url: str, filename: str, caption: str = "", kind: str = "bot"):
    """Equivalente web de send_whatsapp_file_saas: tarjeta de archivo en el chat (con su texto opcional)."""
    url = _safe_attach_url(file_url)
    if not url:
        return None
    ev_id = await asyncio.to_thread(
        add_event_for_thread, client_id, thread_id, kind, caption or "", {"url": url, "name": (filename or "archivo")[:120]}
    )
    return f"web-{ev_id}" if ev_id else None


def _is_paused(client_id: int, thread_id: str) -> bool:
    db = SessionLocal()
    try:
        p = db.query(Pause).filter_by(client_id=client_id, user_id=thread_id).first()
        return bool(p and p.paused_until > datetime.utcnow())
    finally:
        db.close()


def _last_reply_id(client_id: int, thread_id: str) -> int:
    db = SessionLocal()
    try:
        dev = _device_by_thread(db, client_id, thread_id)
        if not dev:
            return 0
        row = (db.query(WebEvent.id).filter(WebEvent.device_id == dev.id, WebEvent.kind.in_(("bot", "admin")))
               .order_by(WebEvent.id.desc()).first())
        return row[0] if row else 0
    finally:
        db.close()


async def run_bot_turn(process_fn, client_id: int, thread_id: str, text: str, fallback: str):
    """Corre un turno del bot para un mensaje web. Si el bot no contesta nada (error, respuesta
    vacia) y no esta pausado por una persona, deja un aviso para que el chat no quede "escribiendo..."."""
    _busy.add(thread_id)
    try:
        before = await asyncio.to_thread(_last_reply_id, client_id, thread_id)
        try:
            await process_fn(client_id, thread_id, text, "web")
        except Exception as e:
            logging.error(f"[WebChat] Error en el turno del bot ({thread_id}): {e}")
        after = await asyncio.to_thread(_last_reply_id, client_id, thread_id)
        if after == before and not await asyncio.to_thread(_is_paused, client_id, thread_id):
            await asyncio.to_thread(add_event_for_thread, client_id, thread_id, "bot", fallback)
    finally:
        _busy.discard(thread_id)


# ── icono de la app (generado con la inicial y el color del cliente) ──────────

def _local_logo(logo_url: str):
    """Ruta local del logo del cliente (/uploads/...), solo si esta realmente dentro de uploads/."""
    if not logo_url or not logo_url.startswith("/uploads/"):
        return None
    base = os.path.realpath("uploads")
    path = os.path.realpath(os.path.join(base, logo_url[len("/uploads/"):]))
    return path if path.startswith(base + os.sep) and os.path.isfile(path) else None


def _icon_png(letter: str, color: str, size: int, logo_path: str = None) -> bytes:
    """Icono de la app: el logo del cliente sobre blanco si lo hay; si no, su inicial sobre el color de marca."""
    mtime = os.path.getmtime(logo_path) if logo_path else 0
    key = (letter, color, size, logo_path, mtime)
    if key in _icon_cache:
        return _icon_cache[key]
    from PIL import Image, ImageDraw, ImageFont
    im = None
    if logo_path:
        try:
            logo = Image.open(logo_path).convert("RGBA")
            inner = int(size * 0.8)
            logo.thumbnail((inner, inner), Image.LANCZOS)
            im = Image.new("RGB", (size, size), "white")
            im.paste(logo, ((size - logo.width) // 2, (size - logo.height) // 2), logo)
        except Exception as e:
            logging.warning(f"[WebChat] Logo no usable para el icono ({logo_path}): {e}")
            im = None
    if im is None:
        im = Image.new("RGB", (size, size), color)
        d = ImageDraw.Draw(im)
        font = None
        for path in ("C:/Windows/Fonts/segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
            try:
                font = ImageFont.truetype(path, int(size * 0.55))
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default(int(size * 0.55))
        d.text((size / 2, size / 2), letter, font=font, fill="white", anchor="mm")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    _icon_cache[key] = buf.getvalue()
    return _icon_cache[key]


SW_JS = """// Service worker del chat web (avisos: se completa en la fase de notificaciones).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) {}
  e.waitUntil(self.registration.showNotification(d.title || 'Novedades', {
    body: d.body || 'Tenés novedades', icon: 'icon-192.png', badge: 'icon-192.png', data: { m: d.m || '' }
  }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    for (const c of list) { if ('focus' in c) return c.focus(); }
    return self.clients.openWindow('./');
  }));
});
"""


# ── router publico ────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    text: str


def build_router(process_bot_response, public_ip, templates) -> APIRouter:
    """process_bot_response: el orquestador del bot (main_saas). public_ip: funcion Request -> IP real.
    templates: Jinja2Templates de la app."""
    router = APIRouter()
    NO_STORE = {"Cache-Control": "no-store"}

    def _unavailable_page(request: Request):
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<meta name=robots content=noindex><body style='font-family:system-ui;text-align:center;padding:4rem 1.5rem;color:#334'>"
            "<h2>Este chat no está disponible</h2><p>Probá de nuevo más tarde.</p></body>",
            status_code=404, headers=NO_STORE)

    def _page(slug: str, request: Request, db: Session):
        client, settings = get_available(db, slug)
        if not client:
            return _unavailable_page(request)
        return templates.TemplateResponse(
            request=request, name="public/web_chat.html",
            context={"slug": slug, "cfg": get_config(client, settings)},
            headers={**NO_STORE, "X-Robots-Tag": "noindex, nofollow"})

    @router.get("/chat/{slug}", response_class=HTMLResponse)
    async def chat_page(slug: str, request: Request, db: Session = Depends(get_db)):
        return _page(slug, request, db)

    @router.get("/chat/{slug}/", response_class=HTMLResponse)
    async def chat_page_slash(slug: str, request: Request, db: Session = Depends(get_db)):
        return _page(slug, request, db)

    @router.get("/chat/{slug}/manifest.json")
    async def chat_manifest(slug: str, db: Session = Depends(get_db)):
        client, settings = get_available(db, slug)
        if not client:
            return JSONResponse(status_code=404, content={"error": "not_found"})
        cfg = get_config(client, settings)
        base = f"/chat/{slug}/"
        return JSONResponse({
            "name": cfg["title"], "short_name": cfg["title"][:12], "description": cfg["subtitle"],
            "start_url": base, "scope": base, "display": "standalone", "orientation": "portrait",
            "background_color": cfg["color"], "theme_color": cfg["color"], "lang": "es-AR",
            "icons": [
                {"src": f"{base}icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": f"{base}icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            ],
        }, media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})

    @router.get("/chat/{slug}/sw.js")
    async def chat_sw(slug: str):
        return Response(SW_JS, media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @router.get("/chat/{slug}/icon-{size}.png")
    async def chat_icon(slug: str, size: int, db: Session = Depends(get_db)):
        client, settings = get_available(db, slug)
        if not client or size not in (180, 192, 512):
            return Response(status_code=404)
        cfg = get_config(client, settings)
        letter = (cfg["title"].strip()[:1] or "A").upper()
        png = await asyncio.to_thread(_icon_png, letter, cfg["color"], size, _local_logo(cfg["logo"]))
        return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})

    @router.post("/api/chat/{slug}/session")
    async def chat_session(slug: str, request: Request, db: Session = Depends(get_db)):
        client, settings = get_available(db, slug)
        if not client:
            return JSONResponse(status_code=404, content={"error": "unavailable"}, headers=NO_STORE)
        ip = public_ip(request)
        device = authenticate(db, client.id, slug, request)
        new_token = None
        if device and device.blocked:
            return JSONResponse(status_code=403, content={"error": "blocked"}, headers=NO_STORE)
        if not device:
            if not _hit(_ip_devices, ip, IP_NEW_DEVICES_PER_HOUR, 3600):
                return JSONResponse(status_code=429, content={"error": "limit"}, headers=NO_STORE)
            new_token = secrets.token_urlsafe(32)
            device = WebDevice(client_id=client.id, public_id=secrets.token_hex(8), token_hash=hash_token(new_token),
                               user_agent=(request.headers.get("user-agent") or "")[:255])
            db.add(device)
            db.commit()
            db.refresh(device)
        else:
            device.last_seen_at = datetime.utcnow()
            db.commit()
        rows = (db.query(WebEvent).filter_by(device_id=device.id).order_by(WebEvent.id.desc()).limit(HISTORY_LIMIT).all())
        rows.reverse()
        resp = JSONResponse({
            "token": new_token,
            "config": get_config(client, settings),
            "events": [serialize_event(e) for e in rows],
            "busy": device.thread_id in _busy,
        }, headers=NO_STORE)
        if new_token:
            resp.set_cookie(_cookie_name(slug), new_token, max_age=365 * 86400, httponly=True, samesite="lax",
                            secure=(request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"), path="/")
        return resp

    @router.post("/api/chat/{slug}/message")
    async def chat_message(slug: str, payload: ChatMessage, request: Request, background_tasks: BackgroundTasks,
                           db: Session = Depends(get_db)):
        client, settings = get_available(db, slug)
        if not client:
            return JSONResponse(status_code=404, content={"error": "unavailable"}, headers=NO_STORE)
        device = authenticate(db, client.id, slug, request)
        if not device:
            return JSONResponse(status_code=401, content={"error": "session"}, headers=NO_STORE)
        if device.blocked:
            return JSONResponse(status_code=403, content={"error": "blocked"}, headers=NO_STORE)
        text = (payload.text or "").strip()[:MAX_TEXT]
        if not text:
            return JSONResponse(status_code=400, content={"error": "empty"}, headers=NO_STORE)

        phone = (settings.company_phone or "").strip()
        contact = f" o comunicate al {phone}" if phone else ""
        day_start = _day_start_utc()
        dev_cap = settings.web_chat_daily_cap if settings.web_chat_daily_cap is not None else DEFAULT_DAILY_CAP
        glob_cap = settings.web_chat_global_daily_cap if settings.web_chat_global_daily_cap is not None else DEFAULT_GLOBAL_CAP
        limit_msg = None
        if not _hit(_ip_msgs, public_ip(request), IP_MSGS_PER_HOUR, 3600):
            limit_msg = "Enviaste muchos mensajes seguidos. Esperá un rato y volvé a intentar."
        elif dev_cap and db.query(WebEvent).filter(WebEvent.device_id == device.id, WebEvent.kind == "user",
                                                   WebEvent.created_at >= day_start).count() >= dev_cap:
            limit_msg = f"Llegaste al límite de mensajes de hoy. Volvé mañana{contact}."
        elif glob_cap and db.query(WebEvent).filter(WebEvent.client_id == client.id, WebEvent.kind == "user",
                                                    WebEvent.created_at >= day_start).count() >= glob_cap:
            limit_msg = f"El asistente no está disponible en este momento. Probá más tarde{contact}."
        if limit_msg:
            return JSONResponse(status_code=429, content={"error": "limit", "message": limit_msg}, headers=NO_STORE)

        ev = add_event(db, client.id, device.id, "user", text)
        device.last_seen_at = datetime.utcnow()
        db.commit()
        fallback = f"No pude responder en este momento. Probá de nuevo en un rato{contact}."
        background_tasks.add_task(run_bot_turn, process_bot_response, client.id, device.thread_id, text, fallback)
        return JSONResponse({"ok": True, "event": serialize_event(ev)}, headers=NO_STORE)

    @router.get("/api/chat/{slug}/events")
    async def chat_events(slug: str, request: Request, after: int = 0, db: Session = Depends(get_db)):
        client, settings = get_available(db, slug)
        if not client:
            return JSONResponse(status_code=404, content={"error": "unavailable"}, headers=NO_STORE)
        device = authenticate(db, client.id, slug, request)
        if not device:
            return JSONResponse(status_code=401, content={"error": "session"}, headers=NO_STORE)
        rows = (db.query(WebEvent).filter(WebEvent.device_id == device.id, WebEvent.id > max(0, after))
                .order_by(WebEvent.id.asc()).limit(200).all())
        return JSONResponse({"events": [serialize_event(e) for e in rows], "busy": device.thread_id in _busy}, headers=NO_STORE)

    return router
