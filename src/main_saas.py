import os
import io
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any

from fastapi import FastAPI, Request, BackgroundTasks, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse, StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
import uvicorn
from dotenv import load_dotenv

# Importaciones SaaS Módulo por Módulo
from src.database.session import get_db, SessionLocal
from src.database.models import Client, ClientSettings, Conversation, User
from src.database.analytics_engine_saas import log_message, log_token_usage, mark_human_intervention, get_dashboard_metrics
from src.agents.graph_saas import app as chatbot_app
import hashlib
import shutil

load_dotenv()

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Inicialización de FastAPI
app = FastAPI(title="ZSG-Bot-iA Multi-Tenant SaaS", version="2.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import httpx
import mimetypes

app.mount("/static", StaticFiles(directory="static"), name="static")
if not os.path.exists("uploads"):
    os.makedirs("uploads")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")

async def download_telegram_media_saas(file_id: str, token: str):
    try:
        logging.info(f"[SaaS TG Media] Descargando file_id: {file_id}")
        async with httpx.AsyncClient() as client:
            res = await client.get(f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}")
            res_json = res.json()
            if not res_json.get("ok"):
                logging.error(f"Error en getFile de Telegram: {res_json}")
                return None
                
            file_path = res_json["result"]["file_path"]
            file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            
            ext = os.path.splitext(file_path)[1]
            local_filename = f"tg_{file_id}{ext}"
            
            uploads_dir = os.path.abspath("uploads")
            if not os.path.exists(uploads_dir):
                os.makedirs(uploads_dir)
                
            local_path = os.path.join(uploads_dir, local_filename)
            
            file_res = await client.get(file_url)
            with open(local_path, "wb") as f:
                f.write(file_res.content)
            
            logging.info(f"[SaaS TG Media] Guardado en: {local_path}")
            return {
                "path": f"/uploads/{local_filename}",
                "name": local_filename,
                "type": mimetypes.guess_type(local_path)[0] or "application/octet-stream"
            }
    except Exception as e:
        logging.error(f"Error descargando media de Telegram SaaS: {e}")
        return None

# Modelos Pydantic para API Super Admin
class ClientCreate(BaseModel):
    business_name: str
    slug: str

class ClientSettingsUpdate(BaseModel):
    whatsapp_instance_id: str = None
    whatsapp_token: str = None
    bot_system_prompt: str = None
    feat_rag_enabled: bool = False
    feat_human_handoff: bool = False
    feat_pdf_export: bool = False
    feat_dashboard: bool = True
    feat_history: bool = True
    feat_contacts: bool = True
    feat_submissions: bool = True
    feat_appointments: bool = True
    feat_gaps: bool = True
    feat_channels: bool = True
    feat_config: bool = True
    feat_audit: bool = True
    feat_catalog: bool = False
    feat_catalog_dynamic_fields: bool = False
    feat_document_library: bool = False
    google_oauth_client_id: str = None
    google_oauth_client_secret: str = None  # vacío/None = no tocar el secreto ya guardado

# Locks para evitar Race Conditions por Usuario
user_locks: Dict[str, asyncio.Lock] = {}

DEFAULT_MENU_ITEMS = [
    {"key": "dashboard", "label": "Dashboard / Analíticas", "icon": "layout-dashboard", "section": "Control"},
    {"key": "history", "label": "Historial de Chats", "icon": "message-square", "section": "Operación"},
    {"key": "contacts", "label": "Contactos / Nómina", "icon": "users-round", "section": "Operación"},
    {"key": "submissions", "label": "Formularios Recibidos", "icon": "file-text", "section": "Operación"},
    {"key": "appointments", "label": "Gestión de Turnos", "icon": "calendar", "section": "Operación"},
    {"key": "catalog", "label": "Catálogo de Productos", "icon": "shopping-bag", "section": "Operación"},
    {"key": "document_library", "label": "Biblioteca de Documentos", "icon": "library", "section": "Operación"},
    {"key": "gaps", "label": "Base de Conocimiento", "icon": "database", "section": "Cerebro"},
    {"key": "config", "label": "Configuración del Bot", "icon": "settings", "section": "Configuración"},
    {"key": "channels", "label": "Canales (WhatsApp/TG)", "icon": "share-2", "section": "Configuración"},
    {"key": "audit", "label": "Auditoría de Acciones", "icon": "shield", "section": "Seguridad"},
    {"key": "users", "label": "Gestión de Usuarios", "icon": "users", "section": "Seguridad"}
]

def get_user_lock(user_id: str) -> asyncio.Lock:
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()
    return user_locks[user_id]

# ==========================================
# GESTIÓN DE SESIONES Y LOGIN (SAAS)
# ==========================================

def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Valida la cookie de sesión y devuelve el usuario y su cliente."""
    user_id = request.cookies.get("session_user_id")
    if not user_id: return None
    user = db.query(User).filter_by(id=int(user_id)).first()
    return user

def get_admin_context(request: Request, current_user: User, db: Session):
    """Helper para obtener el contexto Multi-Tenant y el estado de Impersonación."""
    if not current_user:
        return None, False, None
        
    target_client_id = current_user.client_id
    is_impersonating = False
    
    if not target_client_id:
        impersonated_id = request.cookies.get("impersonated_client_id")
        if impersonated_id:
            target_client_id = int(impersonated_id)
            is_impersonating = True
        else:
            return None, False, None
            
    client_obj = db.query(Client).filter_by(id=target_client_id).first()
    business_name = client_obj.business_name if client_obj else "Admin"
    
    settings = client_obj.settings if client_obj else None
    active_modules = []
    if settings:
        if getattr(settings, 'feat_dashboard', True): active_modules.extend(["dashboard", "analytics"])
        if getattr(settings, 'feat_history', True): active_modules.append("history")
        if getattr(settings, 'feat_contacts', True): active_modules.append("contacts")
        if getattr(settings, 'feat_submissions', True): active_modules.append("submissions")
        if getattr(settings, 'feat_appointments', True): active_modules.append("appointments")
        if getattr(settings, 'feat_gaps', True): active_modules.append("gaps")
        if getattr(settings, 'feat_channels', True): active_modules.append("channels")
        if getattr(settings, 'feat_config', True): active_modules.append("config")
        if getattr(settings, 'feat_audit', True): active_modules.append("audit")
        if getattr(settings, 'feat_catalog', False): active_modules.append("catalog")
        if getattr(settings, 'feat_document_library', False): active_modules.append("document_library")
    else:
        active_modules = ["dashboard", "analytics", "history", "contacts", "submissions", "appointments", "gaps", "channels", "config", "audit"]
    
    active_modules.append("users")
    
    if is_impersonating:
        permissions = active_modules
    else:
        from src.database.models import UserPermission
        perms = db.query(UserPermission).filter_by(user_id=current_user.id, can_access=True).all()
        permissions = [p.menu_key for p in perms if p.menu_key in active_modules]
            
    user_mock = {
        "full_name": f"Súper Admin ({business_name})" if is_impersonating else (current_user.client.business_name if current_user.client else "Admin"),
        "role": "superadmin" if is_impersonating else current_user.role_name,
        "permissions": permissions
    }
    
    return target_client_id, is_impersonating, user_mock

@app.get("/")
def home():
    return RedirectResponse(url="/admin")

@app.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin/login.html", context={"error": None})

@app.post("/acceso")
def login_post(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    pwd_hash = hashlib.md5(password.encode()).hexdigest()
    user = db.query(User).filter_by(email=username, password_hash=pwd_hash).first()
    
    if not user:
        return templates.TemplateResponse(request=request, name="admin/login.html", context={"error": "Credenciales inválidas."})
    
    # Login Exitoso (Para Súper Admin o Cliente)
    if not user.client_id:
        response = RedirectResponse(url="/super-admin", status_code=303)
    else:
        response = RedirectResponse(url="/admin", status_code=303)
        
    response.set_cookie(key="session_user_id", value=str(user.id), httponly=True)
    return response

async def get_user_avatar_url(client_id: int, user_id: str, db: Session):
    import os, httpx, logging
    local_filename = f"avatar_{user_id}.jpg"
    local_path = os.path.join(os.path.abspath("uploads"), local_filename)
    url_path = f"/uploads/{local_filename}"
    
    if os.path.exists(local_path):
        return url_path
        
    from src.database.models import ClientSettings
    settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
    if not settings:
        return None
        
    try:
        # Si es Telegram
        if user_id.isdigit():
            token = settings.telegram_token
            if token:
                async with httpx.AsyncClient() as client:
                    res = await client.get(f"https://api.telegram.org/bot{token}/getUserProfilePhotos?user_id={user_id}&limit=1")
                    res_json = res.json()
                    if res_json.get("ok") and res_json["result"]["total_count"] > 0:
                        photos = res_json["result"]["photos"][0]
                        file_id = photos[-1]["file_id"] # El de mayor tamaño
                        
                        res_file = await client.get(f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}")
                        res_file_json = res_file.json()
                        if res_file_json.get("ok"):
                            file_path = res_file_json["result"]["file_path"]
                            file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
                            
                            img_res = await client.get(file_url)
                            with open(local_path, "wb") as f:
                                f.write(img_res.content)
                            return url_path
        # Si es WhatsApp (Green API)
        elif "@" in user_id:
            inst = settings.whatsapp_instance_id
            tok = settings.whatsapp_token
            if inst and tok:
                async with httpx.AsyncClient() as client:
                    res = await client.post(
                        f"https://api.green-api.com/waInstance{inst}/getAvatar/{tok}",
                        json={"chatId": user_id},
                        timeout=5.0
                    )
                    res_json = res.json()
                    avatar_url = res_json.get("urlAvatar")
                    if avatar_url and avatar_url.startswith("http"):
                        img_res = await client.get(avatar_url)
                        with open(local_path, "wb") as f:
                            f.write(img_res.content)
                        return url_path
    except Exception as e:
        logging.error(f"[SaaS Avatar] Error obteniendo avatar para {user_id}: {e}")
        
    return None

@app.get("/logout")
def logout():
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie("session_user_id")
    return response

# ==========================================
# DASHBOARD DE INQUILINO (SAAS)
# ==========================================

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Renderiza el dashboard exclusivo para el cliente logueado o super-admin impersonando."""
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if not current_user: return RedirectResponse(url="/admin/login")
    if target_client_id is None: return RedirectResponse(url="/super-admin")
        
    metrics = get_dashboard_metrics(target_client_id)
    stats = metrics
    
    from src.database.models import Message
    recent_msgs = db.query(Message).filter_by(
        client_id=target_client_id, role='user'
    ).order_by(Message.timestamp.desc()).limit(8).all()
    
    threads = []
    seen_threads = set()
    for msg in recent_msgs:
        if msg.thread_id not in seen_threads:
            seen_threads.add(msg.thread_id)
            threads.append({
                "id": msg.thread_id,
                "name": msg.thread_id[:20],
                "platform": "WhatsApp" if "@c.us" in msg.thread_id else "Web",
                "time_ago": msg.timestamp.strftime("%d/%m %H:%M") if msg.timestamp else "Ahora"
            })
    
    return templates.TemplateResponse(request=request, name="admin/index.html", context={
        "stats": stats,
        "metrics": metrics,
        "threads": threads,
        "user": user_mock,
        "is_impersonating": is_impersonating
    })

@app.get("/admin/history", response_class=HTMLResponse)
async def view_all_history(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if not current_user: return RedirectResponse(url="/admin/login")
    if target_client_id is None: return RedirectResponse(url="/super-admin")

    from src.database.models import Message, Pause, UserProfile, Submission
    from sqlalchemy import func
    import datetime, json
    
    subquery = db.query(
        Message.thread_id,
        func.max(Message.timestamp).label("last_msg_time")
    ).filter(Message.client_id == target_client_id).group_by(Message.thread_id).subquery()
    
    recent_threads = db.query(subquery.c.thread_id, subquery.c.last_msg_time).order_by(subquery.c.last_msg_time.desc()).limit(30).all()
    
    threads = []
    for t_id, last_ts in recent_threads:
        is_paused = db.query(Pause).filter(Pause.client_id == target_client_id, Pause.user_id == t_id).first() is not None
        platform = "telegram" if t_id.isdigit() else ("whatsapp" if "@" in t_id else "web")
        
        # Buscar el nombre real del contacto
        prof = db.query(UserProfile).filter_by(client_id=target_client_id, user_phone=t_id).first()
        name = prof.full_name if (prof and prof.full_name) else None
        
        if not name:
            last_sub = db.query(Submission).filter_by(client_id=target_client_id, thread_id=t_id).order_by(Submission.created_at.desc()).first()
            if last_sub and last_sub.payload_json:
                try:
                    p_data = json.loads(last_sub.payload_json)
                    n = p_data.get("Nombre del Cliente", p_data.get("Nombre", p_data.get("nombre", p_data.get("Cliente"))))
                    if n: name = n
                except: pass
        
        if not name:
            name = t_id[:20] if t_id else "Usuario"
            
        avatar = await get_user_avatar_url(target_client_id, t_id, db)
        
        diff = int(datetime.datetime.utcnow().timestamp() - last_ts.timestamp()) if last_ts else 0
        if diff < 60: time_ago = "Hace un momento"
        elif diff < 3600: time_ago = f"Hace {diff//60} min"
        elif diff < 86400: time_ago = f"Hace {diff//3600} horas"
        else: time_ago = f"Hace {diff//86400} días"
        
        threads.append({
            "id": t_id,
            "name": name,
            "platform": platform,
            "time_ago": time_ago,
            "is_paused": is_paused,
            "avatar": avatar
        })

    return templates.TemplateResponse(request=request, name="admin/history.html", context={
        "threads": threads,
        "user": user_mock,
        "is_impersonating": is_impersonating
    })

@app.get("/admin/chat/{thread_id}", response_class=HTMLResponse)
async def view_chat_session(request: Request, thread_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if not current_user: return RedirectResponse(url="/admin/login")
    if target_client_id is None: return RedirectResponse(url="/super-admin")
    
    from src.database.models import Message, Pause, UserProfile, ChatNote, Attachment, Appointment, Proceeding, Submission
    from sqlalchemy import func
    import datetime
    import json

    messages = db.query(Message).filter(Message.client_id == target_client_id, Message.thread_id == thread_id).order_by(Message.timestamp.asc()).all()
    formatted_messages = []
    for msg in messages:
        formatted_messages.append({
            "type": "human" if msg.role == "user" else "bot",
            "content": msg.content,
            "timestamp": msg.timestamp.strftime("%Y-%m-%d %H:%M:%S") if msg.timestamp else "",
            "status": msg.status
        })

    # Cargar datos del usuario
    prof = db.query(UserProfile).filter_by(client_id=target_client_id, user_phone=thread_id).first()
    note_obj = db.query(ChatNote).filter_by(client_id=target_client_id, thread_id=thread_id).first()
    
    # Resolver nombre completo del chat
    name = thread_id[:20] if thread_id else "Usuario"
    if prof and prof.full_name:
        name = prof.full_name
    else:
        # Fallback a nombre en algún trámite si no hay perfil de usuario
        last_sub = db.query(Submission).filter_by(client_id=target_client_id, thread_id=thread_id).order_by(Submission.created_at.desc()).first()
        if last_sub and last_sub.payload_json:
            try:
                sub_data = json.loads(last_sub.payload_json)
                n = sub_data.get("Nombre del Cliente", sub_data.get("Nombre", sub_data.get("nombre", sub_data.get("Cliente"))))
                if n: name = n
            except: pass

    # Adjuntos
    atts = db.query(Attachment).filter_by(client_id=target_client_id, thread_id=thread_id).order_by(Attachment.id.asc()).all()
    attachments = []
    for a in atts:
        attachments.append({
            "id": a.id,
            "file_path": a.file_path,
            "file_name": a.file_name or "Archivo",
            "file_type": a.file_type,
            "context": a.context or "Adjunto"
        })

    # Turnos
    apps = db.query(Appointment).filter_by(client_id=target_client_id, thread_id=thread_id).order_by(Appointment.date.desc(), Appointment.time.desc()).all()
    appointments = []
    for ap in apps:
        formatted_date = ap.date
        if ap.date and len(ap.date) == 10 and ap.date[4] == '-' and ap.date[7] == '-':
            parts = ap.date.split('-')
            formatted_date = f"{parts[2]}/{parts[1]}/{parts[0]}"
        appointments.append({
            "date": formatted_date,
            "time": ap.time,
            "service": ap.service or ap.reason or "Turno",
            "status": ap.status
        })

    # Expedientes
    procs = db.query(Proceeding).filter(
        Proceeding.client_id == target_client_id,
        (Proceeding.client_name.like(f"%{name}%") | Proceeding.topic.like(f"%{thread_id}%"))
    ).order_by(Proceeding.updated_at.desc()).all()
    proceedings = []
    for p in procs:
        proceedings.append({
            "tracking_number": p.tracking_number,
            "topic": p.topic,
            "status": p.status,
            "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M:%S") if p.updated_at else ""
        })

    # Trámites / Submissions
    subs = db.query(Submission).filter_by(client_id=target_client_id, thread_id=thread_id).order_by(Submission.created_at.desc()).all()
    submissions = []
    for s in subs:
        try: parsed_data = json.loads(s.payload_json) if s.payload_json else {}
        except: parsed_data = {"Error": "Datos no legibles"}
        
        # Cargar los adjuntos de este trámite específico
        s_atts = db.query(Attachment).filter_by(client_id=target_client_id, form_id=s.id).all()
        att_list = []
        for a in s_atts:
            att_list.append({
                "id": a.id,
                "file_path": a.file_path,
                "file_name": a.file_name or "Archivo",
                "file_type": a.file_type,
                "context": a.context or "Adjunto"
            })
            
        submissions.append({
            "id": s.id,
            "topic": s.topic,
            "data": parsed_data,
            "created_at": s.created_at.strftime("%Y-%m-%d %H:%M:%S") if s.created_at else "",
            "attachments": att_list
        })

    # Avatar del usuario actual
    user_avatar = await get_user_avatar_url(target_client_id, thread_id, db)
    
    metadata = {
        "name": name,
        "platform": "telegram" if thread_id.isdigit() else ("whatsapp" if "@" in thread_id else "web"),
        "is_paused": db.query(Pause).filter(Pause.client_id == target_client_id, Pause.user_id == thread_id).first() is not None,
        "full_name": name,
        "phone": thread_id.split("@")[0] if "@" in thread_id else thread_id,
        "email": "No registrado",
        "notes": note_obj.notes if note_obj else "",
        "attachments": attachments,
        "appointments": appointments,
        "proceedings": proceedings,
        "submissions": submissions,
        "total_files": len(attachments),
        "total_appointments": len(appointments),
        "total_proceedings": len(proceedings),
        "total_forms": len(submissions),
        "avatar": user_avatar
    }

    # Cargar conversaciones del sidebar (Threads)
    subquery = db.query(
        Message.thread_id,
        func.max(Message.timestamp).label("last_msg_time")
    ).filter(Message.client_id == target_client_id).group_by(Message.thread_id).subquery()
    
    recent_threads = db.query(subquery.c.thread_id, subquery.c.last_msg_time).order_by(subquery.c.last_msg_time.desc()).limit(30).all()
    
    all_threads = []
    for t_id, last_ts in recent_threads:
        is_paused = db.query(Pause).filter(Pause.client_id == target_client_id, Pause.user_id == t_id).first() is not None
        platform = "telegram" if t_id.isdigit() else ("whatsapp" if "@" in t_id else "web")
        
        # Buscar el nombre de este thread
        t_prof = db.query(UserProfile).filter_by(client_id=target_client_id, user_phone=t_id).first()
        t_name = t_prof.full_name if (t_prof and t_prof.full_name) else None
        
        if not t_name:
            # Fallback a submissions
            t_last_sub = db.query(Submission).filter_by(client_id=target_client_id, thread_id=t_id).order_by(Submission.created_at.desc()).first()
            if t_last_sub and t_last_sub.payload_json:
                try:
                    sub_data = json.loads(t_last_sub.payload_json)
                    n = sub_data.get("Nombre del Cliente", sub_data.get("Nombre", sub_data.get("nombre", sub_data.get("Cliente"))))
                    if n: t_name = n
                except: pass
        
        if not t_name:
            t_name = t_id[:20] if t_id else "Usuario"
            
        t_avatar = await get_user_avatar_url(target_client_id, t_id, db)
            
        diff = int(datetime.datetime.utcnow().timestamp() - last_ts.timestamp()) if last_ts else 0
        if diff < 60: time_ago = "Hace un momento"
        elif diff < 3600: time_ago = f"Hace {diff//60} min"
        elif diff < 86400: time_ago = f"Hace {diff//3600} horas"
        else: time_ago = f"Hace {diff//86400} días"
        
        all_threads.append({
            "id": t_id,
            "name": t_name,
            "platform": platform,
            "time_ago": time_ago,
            "is_paused": is_paused,
            "phone": t_id.split("@")[0] if "@" in t_id else t_id,
            "avatar": t_avatar
        })

    from datetime import date, timedelta
    _today = date.today()
    return templates.TemplateResponse(request=request, name="admin/chat.html", context={
        "thread_id": thread_id,
        "messages": formatted_messages,
        "metadata": metadata,
        "threads": all_threads,
        "user": user_mock,
        "is_impersonating": is_impersonating,
        "today": _today.strftime("%Y-%m-%d"),
        "yesterday": (_today - timedelta(days=1)).strftime("%Y-%m-%d"),
    })

@app.post("/admin/chat/{thread_id}/send")
async def send_chat_message(request: Request, thread_id: str, message: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    if thread_id.isdigit():
        await send_telegram_message_saas(target_client_id, thread_id, message)
        wa_id = None
    else:
        wa_id = await send_whatsapp_message_saas(target_client_id, thread_id, message)
    
    try:
        log_message(target_client_id, thread_id, "admin", message, whatsapp_id=wa_id)
    except Exception as e:
        logging.error(f"Error update state admin: {e}")
    
    from src.database.models import Pause
    from datetime import datetime, timedelta
    paused_until = datetime.utcnow() + timedelta(hours=2)
    
    pause = db.query(Pause).filter_by(client_id=target_client_id, user_id=thread_id).first()
    if pause:
        pause.paused_until = paused_until
    else:
        pause = Pause(client_id=target_client_id, user_id=thread_id, paused_until=paused_until)
        db.add(pause)
    db.commit()
    
    return RedirectResponse(url=f"/admin/chat/{thread_id}", status_code=303)

@app.post("/admin/chat/{thread_id}/send-file")
async def chat_send_file(request: Request, thread_id: str, file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    uploads_dir = os.path.join("uploads")
    if not os.path.exists(uploads_dir): os.makedirs(uploads_dir)
    
    file_path = os.path.join(uploads_dir, file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    base_url = str(request.base_url).rstrip('/')
    public_url = f"{base_url}/uploads/{file.filename}"
    
    if thread_id.isdigit():
        await send_telegram_file_saas(target_client_id, thread_id, local_path=file_path, caption="Adjunto enviado desde el panel")
    else:
        await send_whatsapp_file_saas(target_client_id, thread_id, public_url, file.filename, "Adjunto enviado desde el panel")
    
    log_message(target_client_id, thread_id, "bot", f"[Archivo: {file.filename}]")
    return RedirectResponse(url=f"/admin/chat/{thread_id}", status_code=303)

@app.get("/admin/chat/resume/{thread_id}")
async def resume_bot(request: Request, thread_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import Pause
    db.query(Pause).filter_by(client_id=target_client_id, user_id=thread_id).delete()
    db.commit()
    return RedirectResponse(url=f"/admin/chat/{thread_id}", status_code=303)

@app.get("/admin/chat/pause/{thread_id}")
async def pause_bot(request: Request, thread_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import Pause
    from datetime import datetime, timedelta
    paused_until = datetime.utcnow() + timedelta(days=365)
    
    pause = db.query(Pause).filter_by(client_id=target_client_id, user_id=thread_id).first()
    if pause:
        pause.paused_until = paused_until
    else:
        pause = Pause(client_id=target_client_id, user_id=thread_id, paused_until=paused_until)
        db.add(pause)
    db.commit()
    return RedirectResponse(url=f"/admin/chat/{thread_id}", status_code=303)

@app.get("/admin/chat/{thread_id}/delete")
async def delete_chat_session(request: Request, thread_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import Message, Pause, Attachment, Appointment, Proceeding, ChatNote, Submission, SessionAnalytics, TokenUsage
    db.query(Message).filter_by(client_id=target_client_id, thread_id=thread_id).delete()
    db.query(Pause).filter_by(client_id=target_client_id, user_id=thread_id).delete()
    db.query(Attachment).filter_by(client_id=target_client_id, thread_id=thread_id).delete()
    db.query(Appointment).filter_by(client_id=target_client_id, thread_id=thread_id).delete()
    db.query(Proceeding).filter(Proceeding.client_id == target_client_id, Proceeding.topic.like(f"%{thread_id}%")).delete(synchronize_session=False)
    db.query(ChatNote).filter_by(client_id=target_client_id, thread_id=thread_id).delete()
    db.query(Submission).filter_by(client_id=target_client_id, thread_id=thread_id).delete()
    db.query(SessionAnalytics).filter_by(client_id=target_client_id, thread_id=thread_id).delete()
    db.query(TokenUsage).filter_by(client_id=target_client_id, thread_id=thread_id).delete()
    
    import sqlite3
    db_path_c = os.path.join("checkpoints.sqlite")
    if os.path.exists(db_path_c):
        try:
            conn_c = sqlite3.connect(db_path_c, timeout=30)
            for table in ["checkpoints", "writes", "blobs", "checkpoint_writes", "checkpoint_blobs"]:
                try:
                    conn_c.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
                except sqlite3.OperationalError as oe:
                    if "no such table" not in str(oe).lower():
                        raise oe
            conn_c.commit()
            conn_c.close()
        except Exception as e:
            logging.error(f"Error cleaning checkpoints: {e}")
            
    db.commit()
    return RedirectResponse(url="/admin/history?deleted=1", status_code=303)

@app.post("/admin/chat/{thread_id}/notes")
async def save_chat_notes(request: Request, thread_id: str, notes: str = Form(""), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import ChatNote
    note = db.query(ChatNote).filter_by(client_id=target_client_id, thread_id=thread_id).first()
    if note:
        note.notes = notes
    else:
        note = ChatNote(client_id=target_client_id, thread_id=thread_id, notes=notes)
        db.add(note)
    db.commit()
    return RedirectResponse(url=f"/admin/chat/{thread_id}", status_code=303)

@app.get("/admin/api/knowledge")
async def get_knowledge_api(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse({"status": "error"}, status_code=401)
    
    from src.database.models import Knowledge
    rows = db.query(Knowledge).filter_by(client_id=target_client_id).order_by(Knowledge.topic.asc()).all()
    return [{"id": r.id, "topic": r.topic, "content": r.content, "category": r.category} for r in rows]

@app.post("/admin/chat/{thread_id}/send-knowledge")
async def send_knowledge_to_chat(request: Request, thread_id: str, knowledge_id: int = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse({"status": "error"}, status_code=401)
    
    from src.database.models import Knowledge, Pause
    knowledge = db.query(Knowledge).filter_by(client_id=target_client_id, id=knowledge_id).first()
    if not knowledge: return JSONResponse({"status": "error", "message": "No encontrado"}, status_code=404)
    
    if knowledge.media_path:
        base_url = str(request.base_url).rstrip('/')
        public_url = f"{base_url}{knowledge.media_path}"
        filename = os.path.basename(knowledge.media_path)
        if thread_id.isdigit():
            await send_telegram_file_saas(target_client_id, thread_id, local_path=knowledge.media_path, caption=knowledge.content)
        else:
            await send_whatsapp_file_saas(target_client_id, thread_id, public_url, filename, knowledge.content)
    else:
        if thread_id.isdigit():
            await send_telegram_message_saas(target_client_id, thread_id, knowledge.content)
        else:
            await send_whatsapp_message_saas(target_client_id, thread_id, knowledge.content)
        
    log_message(target_client_id, thread_id, "admin", f"[Enviado Conocimiento: {knowledge.topic}]\n{knowledge.content}")
    
    db.query(Pause).filter_by(client_id=target_client_id, user_id=thread_id).delete()
    db.commit()
    return {"status": "ok", "message": "Enviado y bot reactivado"}

@app.get("/admin/analytics", response_class=HTMLResponse)
async def view_analytics(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    metrics = get_dashboard_metrics(target_client_id)
    return templates.TemplateResponse(request=request, name="admin/analytics.html", context={"stats": metrics, "user": user_mock, "is_impersonating": is_impersonating})

@app.get("/admin/submissions", response_class=HTMLResponse)
async def view_submissions(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import Submission, UserProfile, Attachment
    import json
    
    submissions = []
    raw_subs = db.query(Submission).filter_by(client_id=target_client_id).order_by(Submission.created_at.desc()).all()
    for s in raw_subs:
        sub = {"id": s.id, "thread_id": s.thread_id, "topic": s.topic, "status": s.status, "created_at": s.created_at.isoformat() if s.created_at else ""}
        
        try: sub['parsed_data'] = json.loads(s.payload_json) if s.payload_json else {}
        except: sub['parsed_data'] = {"Error": "Datos no legibles"}
        
        # Obtener perfil de usuario
        prof = db.query(UserProfile).filter_by(client_id=target_client_id, user_phone=s.thread_id).first()
        user_name = prof.full_name if prof else None
        
        # Fallback a los datos del JSON
        if not user_name:
            user_name = sub['parsed_data'].get("Nombre del Cliente", sub['parsed_data'].get("Nombre", sub['parsed_data'].get("nombre", sub['parsed_data'].get("Cliente"))))
            
        sub['user_name'] = user_name or "Usuario Desconocido"
        sub['formatted_date'] = s.created_at.strftime("%d/%m/%Y %H:%M") if s.created_at else ""
        
        # Cargar adjuntos del trámite
        atts = db.query(Attachment).filter_by(client_id=target_client_id, form_id=s.id).all()
        sub['attachments'] = [
            {
                "id": a.id,
                "file_path": a.file_path,
                "file_name": a.file_name or "Archivo",
                "file_type": a.file_type,
                "context": a.context or "Adjunto"
            }
            for a in atts
        ]
        
        # Fallback a adjuntos huérfanos del hilo si no hay adjuntos asociados al form_id
        if not sub['attachments']:
            orphan_atts = db.query(Attachment).filter_by(client_id=target_client_id, thread_id=s.thread_id, form_id=None).all()
            sub['attachments'] = [
                {
                    "id": a.id,
                    "file_path": a.file_path,
                    "file_name": a.file_name or "Archivo",
                    "file_type": a.file_type,
                    "context": a.context or "Adjunto"
                }
                for a in orphan_atts
            ]
            
        submissions.append(sub)
        
    return templates.TemplateResponse(request=request, name="admin/submissions.html", context={"submissions": submissions, "user": user_mock, "is_impersonating": is_impersonating})

@app.get("/admin/submissions/delete/{sub_id}")
async def delete_submission(
    request: Request,
    sub_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None:
        return RedirectResponse(url="/admin/login")
    
    from src.database.models import Submission, Attachment
    # Eliminar adjuntos asociados al trámite
    db.query(Attachment).filter_by(client_id=target_client_id, form_id=sub_id).delete()
    # Eliminar el trámite
    db.query(Submission).filter_by(client_id=target_client_id, id=sub_id).delete()
    db.commit()
    
    return RedirectResponse(url="/admin/submissions", status_code=303)

@app.get("/admin/contacts", response_class=HTMLResponse)
async def view_contacts(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login", status_code=303)
    
    from src.database.models import UserProfile, Tag
    profiles = db.query(UserProfile).filter_by(client_id=target_client_id).order_by(UserProfile.full_name.asc()).all()
    all_tags = db.query(Tag).filter_by(client_id=target_client_id).all()
    
    from src.database.tagging_manager import get_user_tags
    contacts_data = []
    for p in profiles:
        u_tags = get_user_tags(target_client_id, p.user_phone)
        contacts_data.append({
            "id": p.id,
            "user_phone": p.user_phone,
            "full_name": p.full_name or "Desconocido",
            "role": p.role or "General",
            "created_at": p.created_at,
            "tags": [t["name"] for t in u_tags]
        })
        
    return templates.TemplateResponse(
        request=request,
        name="admin/contacts.html",
        context={
            "contacts": contacts_data,
            "all_tags": [t.name for t in all_tags],
            "user": user_mock,
            "is_impersonating": is_impersonating,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error")
        }
    )

@app.post("/admin/contacts/update")
async def update_contact_role_tags(
    request: Request,
    user_phone: str = Form(...),
    role: str = Form(...),
    tags_csv: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})
    
    from src.database.tagging_manager import set_user_role, assign_tag_by_name, clear_user_tags
    try:
        set_user_role(target_client_id, user_phone, role)
        clear_user_tags(target_client_id, user_phone)
        if tags_csv:
            tags_list = [t.strip() for t in tags_csv.split(",") if t.strip()]
            for tag_name in tags_list:
                assign_tag_by_name(target_client_id, user_phone, tag_name)
                
        return RedirectResponse(url="/admin/contacts?success=Contacto+actualizado+exitosamente.", status_code=303)
    except Exception as e:
        logging.error(f"Error actualizando contacto: {e}")
        return RedirectResponse(url=f"/admin/contacts?error={str(e)}", status_code=303)

@app.post("/admin/contacts/sync-whatsapp")
async def sync_whatsapp_contacts(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})
    
    from src.database.models import UserProfile, ClientSettings
    from src.database.tagging_manager import assign_tag_by_name
    
    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    if not settings or not settings.whatsapp_enabled or not settings.whatsapp_instance_id or not settings.whatsapp_token:
        return JSONResponse(status_code=400, content={"status": "error", "message": "La instancia de WhatsApp no está configurada o habilitada."})
    
    import httpx
    url = f"https://api.green-api.com/waInstance{settings.whatsapp_instance_id}/GetContacts/{settings.whatsapp_token}"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=15.0)
            if r.status_code != 200:
                return JSONResponse(status_code=400, content={"status": "error", "message": f"Error de GreenAPI: Código {r.status_code}"})
            contacts = r.json()
    except Exception as e:
        logging.error(f"[WhatsApp Sync] HTTP Request Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Error al conectar con GreenAPI: {str(e)}"})
        
    created_count = 0
    updated_count = 0
    
    try:
        for c in contacts:
            c_id = c.get("id", "")
            c_type = c.get("type", "")
            c_name = c.get("name", "")
            
            # Solo procesar usuarios individuales, no grupos o canales
            if c_type == "user" and c_id.endswith("@c.us"):
                phone = c_id.split("@")[0]
                # Buscar perfil existente
                prof = db.query(UserProfile).filter_by(client_id=target_client_id, user_phone=phone).first()
                if not prof:
                    # Crear nuevo
                    prof = UserProfile(
                        client_id=target_client_id,
                        user_phone=phone,
                        full_name=c_name or "Usuario WhatsApp",
                        role="General"
                    )
                    db.add(prof)
                    db.flush()
                    # Asignar etiquetas por defecto
                    assign_tag_by_name(target_client_id, phone, "👋 Nuevo Contacto", assigned_by="whatsapp_sync")
                    assign_tag_by_name(target_client_id, phone, "📱 Canal: WhatsApp", assigned_by="whatsapp_sync")
                    created_count += 1
                else:
                    # Actualizar nombre si era desconocido o genérico y ahora tenemos un nombre real
                    if c_name and (not prof.full_name or prof.full_name.lower() in ["desconocido", "usuario whatsapp", "cliente"]):
                        prof.full_name = c_name
                        updated_count += 1
                        
        db.commit()
        return JSONResponse(content={
            "status": "success",
            "message": f"Sincronización completada con éxito. Creados: {created_count}, Actualizados: {updated_count}",
            "created": created_count,
            "updated": updated_count
        })
    except Exception as e:
        db.rollback()
        logging.error(f"[WhatsApp Sync] DB Error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Error al guardar contactos en la base de datos: {str(e)}"})

@app.post("/admin/contacts/import")
async def import_contacts_csv(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})
    
    import csv
    from src.database.models import UserProfile
    from src.database.tagging_manager import set_user_role, assign_tag_by_name, clear_user_tags
    
    try:
        contents = await file.read()
        decoded = contents.decode("utf-8-sig").splitlines()
        reader = csv.DictReader(decoded, delimiter=";")
        
        if not reader.fieldnames or len(reader.fieldnames) == 1:
            reader = csv.DictReader(decoded, delimiter=",")
            
        field_map = {f.lower().strip(): f for f in reader.fieldnames} if reader.fieldnames else {}
        
        phone_key = None
        for k in ["telefono", "teléfono", "phone", "whatsapp", "user_phone", "celular", "contacto"]:
            if k in field_map:
                phone_key = field_map[k]
                break
                
        name_key = None
        for k in ["nombre", "name", "full_name", "nombre_completo", "nombre completo"]:
            if k in field_map:
                name_key = field_map[k]
                break
                
        role_key = None
        for k in ["rol", "role", "permiso", "cargo"]:
            if k in field_map:
                role_key = field_map[k]
                break
                
        tags_key = None
        for k in ["etiquetas", "tags", "etiqueta"]:
            if k in field_map:
                tags_key = field_map[k]
                break
                
        if not phone_key:
            return RedirectResponse(url="/admin/contacts?error=No+se+encontro+la+columna+de+Telefono+en+el+CSV", status_code=303)
            
        success_count = 0
        for row in reader:
            phone = row.get(phone_key, "").strip()
            if not phone: continue
            
            phone_clean = "".join(c for c in phone if c.isdigit() or c == "+")
            if not phone_clean: continue
            
            name = row.get(name_key, "").strip() if name_key else "Importado"
            role = row.get(role_key, "").strip() if role_key else "General"
            tags_str = row.get(tags_key, "").strip() if tags_key else ""
            
            prof = db.query(UserProfile).filter_by(client_id=target_client_id, user_phone=phone_clean).first()
            if not prof:
                prof = UserProfile(client_id=target_client_id, user_phone=phone_clean, full_name=name, role=role)
                db.add(prof)
            else:
                prof.full_name = name
                prof.role = role
            db.commit()
            
            clear_user_tags(target_client_id, phone_clean)
            if tags_str:
                sep = "," if "," in tags_str else "|"
                tags_list = [t.strip() for t in tags_str.split(sep) if t.strip()]
                for tag_name in tags_list:
                    assign_tag_by_name(target_client_id, phone_clean, tag_name)
                    
            success_count += 1
            
        return RedirectResponse(url=f"/admin/contacts?success={success_count}+contactos+importados+exitosamente.", status_code=303)
    except Exception as e:
        logging.error(f"Error importando CSV de contactos: {e}")
        return RedirectResponse(url=f"/admin/contacts?error=Error+al+procesar+CSV:+{str(e)}", status_code=303)

@app.get("/admin/files/view/{attachment_id}")
async def view_attachment(
    request: Request,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None:
        raise HTTPException(status_code=401, detail="No autorizado")
        
    from src.database.models import Attachment, ClientSettings
    att = db.query(Attachment).filter_by(client_id=target_client_id, id=attachment_id).first()
    if not att:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
        
    path = att.file_path
    
    # Si es una ID de Telegram (no tiene slashes ni extensiones locales)
    if path and not path.startswith("http") and not path.startswith("/") and not "/" in path and not "\\" in path:
        # Intentar descargar de Telegram
        settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
        token = settings.telegram_token if settings else None
        if token:
            res_dl = await download_telegram_media_saas(path, token)
            if res_dl:
                # Actualizar base de datos
                att.file_path = res_dl["path"]
                att.file_name = res_dl["name"]
                att.file_type = res_dl["type"]
                db.commit()
                path = res_dl["path"]
                
    if not path:
        raise HTTPException(status_code=404, detail="Ruta de archivo no válida")
        
    if path.startswith("/uploads/"):
        # Servir el archivo local
        filename = path.replace("/uploads/", "")
        local_path = os.path.join(os.path.abspath("uploads"), filename)
        if os.path.exists(local_path):
            from fastapi.responses import FileResponse
            return FileResponse(local_path)
            
    # Si es una URL externa redirigir
    if path.startswith("http"):
        return RedirectResponse(url=path)
        
    raise HTTPException(status_code=404, detail="Archivo no encontrado físicamente")



@app.get("/admin/appointments", response_class=HTMLResponse)
async def appointments_panel(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import Appointment, Knowledge
    apps = db.query(Appointment).filter_by(client_id=target_client_id).order_by(Appointment.date.desc(), Appointment.time.desc()).all()
    appointments = [{"id": a.id, "thread_id": a.thread_id, "client_name": a.client_name, "date": a.date, "time": a.time, "reason": a.reason, "status": a.status} for a in apps]
    
    services = db.query(Knowledge).filter_by(client_id=target_client_id, allow_scheduling=True).all()
    services_list = [{"id": s.id, "topic": s.topic} for s in services]
    
    return templates.TemplateResponse(
        request=request, 
        name="admin/appointments.html", 
        context={
            "appointments": appointments, 
            "services_list": services_list,
            "active_section": "turnos", 
            "user": user_mock, 
            "is_impersonating": is_impersonating
        }
    )

@app.post("/admin/appointments/add")
async def add_appointment_manual(
    request: Request,
    client_name: str = Form(...),
    thread_id: str = Form(""),
    date: str = Form(...),
    time: str = Form(...),
    service_topic: str = Form(None),
    reason: str = Form(""),
    sync_google: int = Form(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    t_id = thread_id.strip() if thread_id.strip() else "manual"
    
    real_reason = reason.strip()
    if service_topic and service_topic.strip():
        if real_reason:
            real_reason = f"{service_topic.strip()} - {real_reason}"
        else:
            real_reason = service_topic.strip()
            
    from src.database.models import Appointment, ClientSettings
    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    provider = settings.scheduling_provider if settings else "local"
    calendar_id = settings.google_calendar_id if settings else "primary"
    
    duration = None
    if service_topic:
        from src.database.models import Knowledge
        kb = db.query(Knowledge).filter_by(client_id=target_client_id, topic=service_topic).first()
        if kb and kb.appointment_duration:
            duration = kb.appointment_duration
            
    if not duration:
        duration = settings.appointment_duration if settings else 30
        
    google_success = True
    if sync_google == 1 and provider == "google":
        from src.agents.scheduling import get_calendar_service
        service = get_calendar_service()
        if service:
            start_dt = f"{date}T{time}:00"
            try:
                from datetime import datetime, timedelta
                end_dt = (datetime.strptime(start_dt, "%Y-%m-%dT%H:%M:%S") + timedelta(minutes=duration)).isoformat()
                event = {
                    'summary': f'Turno: {client_name}',
                    'description': f'Motivo: {real_reason}\nID Chat: {t_id} (Manual)',
                    'start': {'dateTime': start_dt, 'timeZone': 'America/Argentina/Buenos_Aires'},
                    'end': {'dateTime': end_dt, 'timeZone': 'America/Argentina/Buenos_Aires'},
                }
                service.events().insert(calendarId=calendar_id, body=event).execute()
            except Exception as e:
                import logging
                logging.error(f"Error registrando manual en Google Calendar: {e}")
                google_success = False
        else:
            google_success = False
            
    formatted_time = time.strip() if time else "00:00"
    if ":" in formatted_time:
        parts = formatted_time.split(":")
        formatted_time = f"{parts[0].zfill(2)}:{parts[1].zfill(2)}"
    else:
        try:
            val = int(formatted_time)
            formatted_time = f"{str(val).zfill(2)}:00"
        except ValueError:
            pass

    new_app = Appointment(
        client_id=target_client_id,
        thread_id=t_id,
        client_name=client_name,
        date=date,
        time=formatted_time,
        reason=real_reason,
        service=real_reason,
        status="confirmed"
    )
    db.add(new_app)
    db.commit()
    
    return RedirectResponse(url="/admin/appointments?success=1", status_code=303)

@app.post("/admin/appointments/cancel/{app_id}")
async def cancel_appointment_route(
    request: Request,
    app_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})
    
    from src.database.models import Appointment
    app_obj = db.query(Appointment).filter_by(client_id=target_client_id, id=app_id).first()
    if not app_obj:
        return JSONResponse(status_code=404, content={"error": "Turno no encontrado"})
        
    app_obj.status = "cancelled"
    db.commit()
    return {"status": "ok"}

@app.get("/admin/gaps", response_class=HTMLResponse)
async def view_gaps(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import KnowledgeGap
    gaps_raw = db.query(KnowledgeGap).filter_by(client_id=target_client_id, status='pending').order_by(KnowledgeGap.frequency.desc()).all()
    gaps = [{"id": g.id, "topic": g.topic, "frequency": g.frequency, "status": g.status} for g in gaps_raw]
    
    return templates.TemplateResponse(request=request, name="admin/gaps.html", context={"gaps": gaps, "active_section": "control", "user": user_mock, "is_impersonating": is_impersonating})

@app.get("/admin/channels", response_class=HTMLResponse)
async def view_channels(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import ClientSettings
    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    config = {
        "webhook_base_url": settings.webhook_base_url if settings else "",
        "whatsapp_enabled": "1" if settings and settings.whatsapp_enabled else "0",
        "whatsapp_instance_id": settings.whatsapp_instance_id if settings else "",
        "whatsapp_api_token": settings.whatsapp_token if settings else "",
        "test_mode_enabled": "1" if settings and settings.test_mode_enabled else "0",
        "test_numbers": settings.test_numbers if settings else "",
        "telegram_enabled": "1" if settings and settings.telegram_enabled else "0",
        "telegram_token": settings.telegram_token if settings else ""
    }
    
    return templates.TemplateResponse(request=request, name="admin/channels.html", context={"config": config, "user": user_mock, "is_impersonating": is_impersonating})

@app.get("/admin/config", response_class=HTMLResponse)
async def config_panel(request: Request, active_tab: str = "identidad", active_section: str = "control", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import ClientSettings, Knowledge, Client
    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    client_obj = db.query(Client).filter_by(id=target_client_id).first()
    
    config = {
        "company_name": client_obj.business_name if client_obj else "",
        "company_address": settings.company_address if settings else "",
        "company_phone": settings.company_phone if settings else "",
        "bot_name": settings.bot_name if settings else "",
        "bot_tone": settings.bot_tone if settings else "",
        "out_of_office_enabled": "1" if settings and settings.out_of_office_enabled else "0",
        "out_of_office_message": settings.out_of_office_message if settings else "",
        "welcome_message_enabled": "1" if settings and settings.welcome_message_enabled else "0",
        "welcome_message_text": settings.welcome_message_text if settings else "",
        "welcome_threshold_days": settings.welcome_threshold_days if settings else 7,
        "welcome_media_path": settings.welcome_media_path if settings else "",
        "test_mode_enabled": "1" if settings and settings.test_mode_enabled else "0",
        "test_numbers": settings.test_numbers if settings else "",
        "system_prompt": settings.bot_system_prompt if settings else "",
        "working_hours": settings.working_hours if settings else "",
        "enable_working_hours_for_scheduling": "1" if settings and settings.enable_working_hours_for_scheduling else "0",
        "feat_rag_enabled": "1" if settings and settings.feat_rag_enabled else "0",
        "feat_pdf_export": "1" if settings and settings.feat_pdf_export else "0",
        "feat_human_handoff": "1" if settings and settings.feat_human_handoff else "0",
        "reminder_24h_enabled": "1" if settings and settings.reminder_24h_enabled else "0",
        "reminder_24h_template": settings.reminder_24h_template if settings else "",
        "reminder_2h_enabled": "1" if settings and settings.reminder_2h_enabled else "0",
        "reminder_2h_template": settings.reminder_2h_template if settings else ""
    }
    
    knowledge_raw = db.query(Knowledge).filter_by(client_id=target_client_id).order_by(Knowledge.category.asc()).all()
    knowledge_items = [{"id": k.id, "topic": k.topic, "content": k.content, "category": k.category, "has_form": k.has_form, "form_fields": k.form_fields, "storage_dest": k.storage_dest, "allow_scheduling": k.allow_scheduling, "scheduling_hours": k.scheduling_hours, "appointment_duration": k.appointment_duration, "scheduling_capacity": k.scheduling_capacity, "interactive_options": k.interactive_options, "media_path": k.media_path} for k in knowledge_raw]
    
    from src.database.models import SchedulingException
    exceptions_raw = db.query(SchedulingException).filter_by(client_id=target_client_id).order_by(SchedulingException.date.asc()).all()
    exceptions = [{"id": e.id, "date": e.date, "start_time": e.start_time, "end_time": e.end_time, "description": e.description} for e in exceptions_raw]

    from src.database.models import FollowupContent
    followup_raw = db.query(FollowupContent).filter_by(client_id=target_client_id).order_by(FollowupContent.valid_from.asc()).all()
    followup_items = [{"id": f.id, "name": f.name, "message_text": f.message_text, "media_path": f.media_path, "interval_minutes": f.interval_minutes, "valid_from": f.valid_from, "valid_until": f.valid_until, "is_active": f.is_active} for f in followup_raw]

    return templates.TemplateResponse(request=request, name="admin/config.html", context={
        "config": config, "external": {}, "knowledge_items": knowledge_items, "exceptions": exceptions,
        "followup_items": followup_items,
        "data_files": [], "sync_needed": request.query_params.get("sync_needed") == "1", "success_reset": False,
        "error_reset": False, "external_env": {}, "active_tab": active_tab, "active_section": active_section,
        "ai_config": {}, "user": user_mock, "is_impersonating": is_impersonating
    })

@app.post("/admin/config/save-all")
async def save_all_config(
    request: Request,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    form_data = await request.form()
    from src.database.models import Client
    
    client_obj = db.query(Client).filter_by(id=target_client_id).first()
    if client_obj and "company_name" in form_data:
        client_obj.business_name = form_data.get("company_name")
    
    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    if not settings:
        settings = ClientSettings(client_id=target_client_id)
        db.add(settings)
        
    settings.bot_system_prompt = form_data.get("system_prompt", settings.bot_system_prompt)
    settings.working_hours = form_data.get("working_hours", settings.working_hours)
    settings.enable_working_hours_for_scheduling = form_data.get("enable_working_hours_for_scheduling") == "1"
    
    settings.reminder_24h_enabled = form_data.get("reminder_24h_enabled") == "1"
    settings.reminder_24h_template = form_data.get("reminder_24h_template", settings.reminder_24h_template)
    if "reminder_24h_hours" in form_data:
        try: settings.reminder_24h_hours = int(form_data.get("reminder_24h_hours") or 24)
        except ValueError: pass
    settings.reminder_2h_enabled = form_data.get("reminder_2h_enabled") == "1"
    settings.reminder_2h_template = form_data.get("reminder_2h_template", settings.reminder_2h_template)
    if "reminder_2h_hours" in form_data:
        try: settings.reminder_2h_hours = int(form_data.get("reminder_2h_hours") or 2)
        except ValueError: pass
    
    if "company_address" in form_data: settings.company_address = form_data.get("company_address")
    if "company_phone" in form_data: settings.company_phone = form_data.get("company_phone")
    if "bot_name" in form_data: settings.bot_name = form_data.get("bot_name")
    if "bot_tone" in form_data: settings.bot_tone = form_data.get("bot_tone")
    if "out_of_office_enabled" in form_data: settings.out_of_office_enabled = form_data.get("out_of_office_enabled") == "1"
    else: settings.out_of_office_enabled = False
    
    if "out_of_office_message" in form_data: settings.out_of_office_message = form_data.get("out_of_office_message")
    
    if "welcome_message_enabled" in form_data: settings.welcome_message_enabled = form_data.get("welcome_message_enabled") == "1"
    else: settings.welcome_message_enabled = False
    
    if "welcome_message_text" in form_data: settings.welcome_message_text = form_data.get("welcome_message_text")
    if "welcome_threshold_days" in form_data: settings.welcome_threshold_days = int(form_data.get("welcome_threshold_days") or 7)
    
    if "test_mode_enabled" in form_data: settings.test_mode_enabled = form_data.get("test_mode_enabled") == "1"
    else: settings.test_mode_enabled = False
    
    if "test_numbers" in form_data: settings.test_numbers = form_data.get("test_numbers")
    
    welcome_media = form_data.get("welcome_media")
    if welcome_media and getattr(welcome_media, "filename", None):
        import os, shutil, re
        uploads_dir = os.path.join("uploads", f"client_{target_client_id}")
        if not os.path.exists(uploads_dir): os.makedirs(uploads_dir)
        clean_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', welcome_media.filename)
        file_path = os.path.join(uploads_dir, f"welcome_{clean_name}")
        with open(file_path, "wb") as f:
            shutil.copyfileobj(welcome_media.file, f)
        settings.welcome_media_path = f"/uploads/client_{target_client_id}/welcome_{clean_name}"
    elif "remove_welcome_media" in form_data and form_data.get("remove_welcome_media") == "1":
        settings.welcome_media_path = None
    
    db.commit()
    
    tab = form_data.get("active_tab", "identidad")
    return RedirectResponse(url=f"/admin/config?active_tab={tab}&success=1", status_code=303)

@app.get("/admin/config/remove-welcome-media")
async def remove_welcome_media_route(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    if settings:
        settings.welcome_media_path = None
        db.commit()
    
    return RedirectResponse(url="/admin/config?active_tab=identidad&success=1", status_code=303)

@app.post("/admin/channels/save")
async def save_channels_config(
    request: Request,
    webhook_base_url: str = Form(""),
    whatsapp_enabled: str = Form(None),
    whatsapp_instance_id: str = Form(""),
    whatsapp_api_token: str = Form(""),
    test_mode_enabled: str = Form(None),
    test_numbers: str = Form(""),
    telegram_enabled: str = Form(None),
    telegram_token: str = Form(""),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    if not settings:
        settings = ClientSettings(client_id=target_client_id)
        db.add(settings)
        
    settings.webhook_base_url = webhook_base_url
    settings.whatsapp_enabled = (whatsapp_enabled == "1")
    settings.whatsapp_instance_id = whatsapp_instance_id
    settings.whatsapp_token = whatsapp_api_token
    settings.test_mode_enabled = (test_mode_enabled == "1")
    settings.test_numbers = test_numbers
    settings.telegram_enabled = (telegram_enabled == "1")
    settings.telegram_token = telegram_token
    db.commit()
    
    return RedirectResponse(url="/admin/channels?success=1", status_code=303)

from typing import List

@app.post("/admin/knowledge/add")
async def add_knowledge(
    request: Request,
    topic: str = Form(...), content: str = Form(...), category: str = Form(""),
    has_form: int = Form(0), form_fields: str = Form(""),
    allow_scheduling: int = Form(0), storage_dest: str = Form("database"),
    scheduling_hours: str = Form(None), appointment_duration_kb: int = Form(None),
    scheduling_capacity: int = Form(1),
    interactive_options: str = Form(None), media: List[UploadFile] = File(None),
    analyze_rag: int = Form(0), send_as_file: int = Form(0),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    saved_paths = []
    if media:
        for m in media:
            if m and m.filename:
                import re, os, shutil
                uploads_dir = os.path.join("uploads", f"client_{target_client_id}")
                if not os.path.exists(uploads_dir): os.makedirs(uploads_dir)
                clean_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', m.filename)
                file_path = os.path.join(uploads_dir, clean_name)
                with open(file_path, "wb") as f:
                     shutil.copyfileobj(m.file, f)
                saved_paths.append(f"/uploads/client_{target_client_id}/{clean_name}")

    media_path_str = ",".join(saved_paths) if saved_paths else None

    from src.database.models import Knowledge
    k = Knowledge(
        client_id=target_client_id,
        topic=topic, content=content, category=category,
        has_form=bool(has_form), form_fields=form_fields,
        allow_scheduling=bool(allow_scheduling),
        scheduling_hours=scheduling_hours,
        appointment_duration=appointment_duration_kb,
        scheduling_capacity=scheduling_capacity,
        storage_dest=storage_dest,
        interactive_options=interactive_options, media_path=media_path_str,
        analyze_rag=bool(analyze_rag), send_as_file=bool(send_as_file)
    )
    db.add(k)
    db.commit()
    return RedirectResponse(url="/admin/config?active_tab=conocimiento&sync_needed=1&success=1", status_code=303)

@app.post("/admin/knowledge/update")
async def update_knowledge(
    request: Request,
    item_id: int = Form(...), topic: str = Form(...), content: str = Form(...),
    category: str = Form(""), has_form: int = Form(0), form_fields: str = Form(None),
    storage_dest: str = Form("database"), allow_scheduling: int = Form(0),
    scheduling_hours: str = Form(None), appointment_duration_kb: int = Form(None),
    scheduling_capacity: int = Form(1),
    interactive_options: str = Form(None), media: List[UploadFile] = File(None),
    analyze_rag: int = Form(0), send_as_file: int = Form(0),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import Knowledge
    k = db.query(Knowledge).filter_by(client_id=target_client_id, id=item_id).first()
    if not k: return RedirectResponse(url="/admin/config?active_tab=conocimiento&error=1", status_code=303)
    
    saved_paths = []
    if k.media_path:
        saved_paths = [p for p in k.media_path.split(",") if p.strip()]

    if media:
        for m in media:
            if m and m.filename:
                import re, os, shutil
                uploads_dir = os.path.join("uploads", f"client_{target_client_id}")
                if not os.path.exists(uploads_dir): os.makedirs(uploads_dir)
                clean_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', m.filename)
                file_path = os.path.join(uploads_dir, clean_name)
                with open(file_path, "wb") as f:
                    shutil.copyfileobj(m.file, f)
                new_path = f"/uploads/client_{target_client_id}/{clean_name}"
                if new_path not in saved_paths:
                    saved_paths.append(new_path)

    k.media_path = ",".join(saved_paths) if saved_paths else None

    k.topic = topic
    k.content = content
    k.category = category
    k.has_form = bool(has_form)
    k.form_fields = form_fields
    k.storage_dest = storage_dest
    k.allow_scheduling = bool(allow_scheduling)
    k.scheduling_hours = scheduling_hours
    k.appointment_duration = appointment_duration_kb
    k.scheduling_capacity = scheduling_capacity
    k.interactive_options = interactive_options
    k.analyze_rag = bool(analyze_rag)
    k.send_as_file = bool(send_as_file)
    
    db.commit()
    return RedirectResponse(url="/admin/config?active_tab=conocimiento&sync_needed=1&success=1", status_code=303)

@app.get("/admin/knowledge/delete/{item_id}")
async def delete_knowledge(request: Request, item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import Knowledge
    db.query(Knowledge).filter_by(client_id=target_client_id, id=item_id).delete()
    db.commit()
    return RedirectResponse(url="/admin/config?active_tab=conocimiento&sync_needed=1&success=1", status_code=303)

@app.get("/admin/knowledge/get/{item_id}")
async def get_knowledge(request: Request, item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(content={"error": "Unauthorized"}, status_code=401)
    
    from src.database.models import Knowledge
    k = db.query(Knowledge).filter_by(client_id=target_client_id, id=item_id).first()
    if not k: return JSONResponse(content={"error": "Not Found"}, status_code=404)
    
    return JSONResponse(content={
        "id": k.id,
        "topic": k.topic,
        "content": k.content,
        "category": k.category,
        "interactive_options": k.interactive_options,
        "media_path": k.media_path,
        "has_form": k.has_form,
        "form_fields": k.form_fields,
        "allow_scheduling": k.allow_scheduling,
        "scheduling_hours": k.scheduling_hours,
        "appointment_duration": k.appointment_duration,
        "scheduling_capacity": k.scheduling_capacity,
        "storage_dest": k.storage_dest,
        "analyze_rag": k.analyze_rag,
        "send_as_file": k.send_as_file
    })

@app.get("/admin/knowledge/remove-media/{item_id}")
async def remove_knowledge_media(request: Request, item_id: int, index: int = -1, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import Knowledge
    k = db.query(Knowledge).filter_by(client_id=target_client_id, id=item_id).first()
    if k and k.media_path:
        paths = [p.strip() for p in k.media_path.split(",") if p.strip()]
        if index >= 0 and index < len(paths):
            paths.pop(index)
            k.media_path = ",".join(paths) if paths else None
        else:
            k.media_path = None
        db.commit()
    return RedirectResponse(url="/admin/config?active_tab=conocimiento&sync_needed=1&success=1", status_code=303)

def _followup_dates_overlap(a_from: str, a_until: str, b_from: str, b_until: str) -> bool:
    """True si los rangos [a_from, a_until] y [b_from, b_until] (YYYY-MM-DD) se solapan."""
    return not (a_until < b_from or a_from > b_until)

@app.post("/admin/followup/add")
async def add_followup(
    request: Request,
    name: str = Form(...), message_text: str = Form(...),
    interval_minutes: int = Form(120), valid_from: str = Form(...), valid_until: str = Form(...),
    is_active: int = Form(0), media: UploadFile = File(None),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")

    from src.database.models import FollowupContent
    active_flag = bool(is_active)

    if active_flag:
        others = db.query(FollowupContent).filter_by(client_id=target_client_id, is_active=True).all()
        for o in others:
            if _followup_dates_overlap(valid_from, valid_until, o.valid_from, o.valid_until):
                return RedirectResponse(url="/admin/config?active_tab=seguimiento&error_overlap=1", status_code=303)

    media_path_str = None
    if media and media.filename:
        import re, os, shutil
        uploads_dir = os.path.join("uploads", f"client_{target_client_id}")
        if not os.path.exists(uploads_dir): os.makedirs(uploads_dir)
        clean_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', media.filename)
        file_path = os.path.join(uploads_dir, f"followup_{clean_name}")
        with open(file_path, "wb") as f:
            shutil.copyfileobj(media.file, f)
        media_path_str = f"/uploads/client_{target_client_id}/followup_{clean_name}"

    f = FollowupContent(
        client_id=target_client_id, name=name, message_text=message_text,
        media_path=media_path_str, interval_minutes=interval_minutes,
        valid_from=valid_from, valid_until=valid_until, is_active=active_flag
    )
    db.add(f)
    db.commit()
    return RedirectResponse(url="/admin/config?active_tab=seguimiento&success=1", status_code=303)

@app.post("/admin/followup/update")
async def update_followup(
    request: Request,
    item_id: int = Form(...), name: str = Form(...), message_text: str = Form(...),
    interval_minutes: int = Form(120), valid_from: str = Form(...), valid_until: str = Form(...),
    is_active: int = Form(0), media: UploadFile = File(None),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")

    from src.database.models import FollowupContent
    f = db.query(FollowupContent).filter_by(client_id=target_client_id, id=item_id).first()
    if not f: return RedirectResponse(url="/admin/config?active_tab=seguimiento&error=1", status_code=303)

    active_flag = bool(is_active)
    if active_flag:
        others = db.query(FollowupContent).filter_by(client_id=target_client_id, is_active=True).filter(FollowupContent.id != item_id).all()
        for o in others:
            if _followup_dates_overlap(valid_from, valid_until, o.valid_from, o.valid_until):
                return RedirectResponse(url="/admin/config?active_tab=seguimiento&error_overlap=1", status_code=303)

    if media and media.filename:
        import re, os, shutil
        uploads_dir = os.path.join("uploads", f"client_{target_client_id}")
        if not os.path.exists(uploads_dir): os.makedirs(uploads_dir)
        clean_name = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', media.filename)
        file_path = os.path.join(uploads_dir, f"followup_{clean_name}")
        with open(file_path, "wb") as f_out:
            shutil.copyfileobj(media.file, f_out)
        f.media_path = f"/uploads/client_{target_client_id}/followup_{clean_name}"

    f.name = name
    f.message_text = message_text
    f.interval_minutes = interval_minutes
    f.valid_from = valid_from
    f.valid_until = valid_until
    f.is_active = active_flag

    db.commit()
    return RedirectResponse(url="/admin/config?active_tab=seguimiento&success=1", status_code=303)

@app.get("/admin/followup/delete/{item_id}")
async def delete_followup(request: Request, item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")

    from src.database.models import FollowupContent
    db.query(FollowupContent).filter_by(client_id=target_client_id, id=item_id).delete()
    db.commit()
    return RedirectResponse(url="/admin/config?active_tab=seguimiento&success=1", status_code=303)

@app.get("/admin/followup/get/{item_id}")
async def get_followup(request: Request, item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    from src.database.models import FollowupContent
    f = db.query(FollowupContent).filter_by(client_id=target_client_id, id=item_id).first()
    if not f: return JSONResponse(content={"error": "No encontrado"}, status_code=404)

    return JSONResponse(content={
        "id": f.id, "name": f.name, "message_text": f.message_text, "media_path": f.media_path,
        "interval_minutes": f.interval_minutes, "valid_from": f.valid_from, "valid_until": f.valid_until,
        "is_active": f.is_active
    })

@app.get("/admin/followup/remove-media/{item_id}")
async def remove_followup_media(request: Request, item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")

    from src.database.models import FollowupContent
    f = db.query(FollowupContent).filter_by(client_id=target_client_id, id=item_id).first()
    if f:
        f.media_path = None
        db.commit()
    return RedirectResponse(url="/admin/config?active_tab=seguimiento&success=1", status_code=303)

@app.post("/admin/config/sync")
async def sync_knowledge_saas(
    request: Request,
    background_tasks: BackgroundTasks,
    active_tab: str = Form("conocimiento"),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.ingest_saas import ingest_data_saas
    background_tasks.add_task(ingest_data_saas, target_client_id)
    
    return RedirectResponse(url=f"/admin/config?active_tab={active_tab}&success=1", status_code=303)

@app.get("/admin/audit", response_class=HTMLResponse)
async def view_audit(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import AuditLog
    logs_raw = db.query(AuditLog).filter_by(client_id=target_client_id).order_by(AuditLog.timestamp.desc()).limit(100).all()
    logs = [{"id": l.id, "user_id": l.user_id, "action": l.action, "details": l.details, "timestamp": l.timestamp.strftime("%d/%m/%Y %H:%M")} for l in logs_raw]
    
    return templates.TemplateResponse(request=request, name="admin/audit.html", context={"logs": logs, "active_section": "control", "user": user_mock, "is_impersonating": is_impersonating})

@app.get("/admin/users", response_class=HTMLResponse)
async def users_panel(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import User as DBUser
    users_raw = db.query(DBUser).filter_by(client_id=target_client_id).all()
    
    users_list = []
    for u in users_raw:
        email_prefix = u.email.split('@')[0] if u.email else "usuario"
        users_list.append({
            "id": u.id,
            "username": email_prefix,
            "full_name": email_prefix.capitalize(),
            "email": u.email,
            "role": u.role_name,
            "is_active": 1,
            "last_login_fmt": "—"
        })
    
    return templates.TemplateResponse(
        request=request,
        name="admin/users.html",
        context={
            "users_list": users_list,
            "menu_items_list": DEFAULT_MENU_ITEMS,
            "user": user_mock,
            "is_impersonating": is_impersonating,
            "active_section": "sistema"
        }
    )

# ── API Y RUTAS: Catálogo de Productos ───────────────────────────────────────────────────

class CatalogProductPayload(BaseModel):
    id: int = None
    sku: str = None
    name: str
    price: float = 0.0
    stock: int = 0
    min_quantity: int = 1
    is_active: bool = True
    custom_attributes: str = None
    price_rules: str = None
    image_path: str = None

@app.get("/admin/catalog", response_class=HTMLResponse)
async def catalog_panel(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import ClientSettings
    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    
    if not settings or not getattr(settings, 'feat_catalog', False):
        return RedirectResponse(url="/admin") # No tiene permiso
        
    return templates.TemplateResponse(
        request=request,
        name="admin/catalog.html",
        context={
            "user": user_mock,
            "settings": settings,
            "is_impersonating": is_impersonating,
            "active_section": "operacion"
        }
    )

@app.get("/admin/catalog-requests", response_class=HTMLResponse)
async def catalog_requests_panel(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")

    from src.database.models import CatalogRequest, CatalogSearchLog
    import json

    raw = db.query(CatalogRequest).filter_by(client_id=target_client_id).order_by(CatalogRequest.created_at.desc()).all()
    requests_list = []
    for r in raw:
        try:
            contact = json.loads(r.contact_data) if r.contact_data else {}
        except Exception:
            contact = {}
        requests_list.append({
            "tipo": r.tipo,
            "producto_nombre": r.producto_nombre,
            "producto_sku": r.producto_sku,
            "cantidad": r.cantidad,
            "contact": contact,
            "pdf_path": r.pdf_path,
            "status": r.status,
            "formatted_date": r.created_at.strftime("%d/%m/%Y %H:%M") if r.created_at else ""
        })

    raw_logs = db.query(CatalogSearchLog).filter_by(client_id=target_client_id).order_by(CatalogSearchLog.created_at.desc()).limit(300).all()
    search_logs = [{
        "query": l.query,
        "found": l.found,
        "results_count": l.results_count,
        "producto_nombre": l.producto_nombre,
        "producto_sku": l.producto_sku,
        "formatted_date": l.created_at.strftime("%d/%m/%Y %H:%M") if l.created_at else ""
    } for l in raw_logs]

    return templates.TemplateResponse(
        request=request,
        name="admin/catalog_requests.html",
        context={"requests": requests_list, "search_logs": search_logs, "user": user_mock, "is_impersonating": is_impersonating}
    )

@app.delete("/api/admin/catalog-requests/clear")
async def api_clear_catalog_requests(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.models import CatalogRequest
    deleted_count = db.query(CatalogRequest).filter_by(client_id=target_client_id).delete()
    db.commit()
    return {"status": "ok", "deleted_count": deleted_count}

@app.delete("/api/admin/catalog-requests/logs/clear")
async def api_clear_catalog_search_logs(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.models import CatalogSearchLog
    deleted_count = db.query(CatalogSearchLog).filter_by(client_id=target_client_id).delete()
    db.commit()
    return {"status": "ok", "deleted_count": deleted_count}

@app.get("/api/admin/catalog")
async def api_get_catalog(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})
    
    from src.database.models import CatalogProduct
    products = db.query(CatalogProduct).filter_by(client_id=target_client_id).order_by(CatalogProduct.id.desc()).all()
    
    data = []
    for p in products:
        data.append({
            "id": p.id,
            "sku": p.sku or "",
            "name": p.name,
            "price": p.price,
            "stock": p.stock,
            "min_quantity": p.min_quantity,
            "is_active": p.is_active,
            "image_path": p.image_path or "",
            "custom_attributes": p.custom_attributes or "",
            "price_rules": p.price_rules or ""
        })
        
    return data

@app.post("/api/admin/catalog/save")
async def api_save_catalog_product(
    request: Request,
    payload: CatalogProductPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})
    
    from src.database.models import CatalogProduct
    
    if payload.id:
        p = db.query(CatalogProduct).filter_by(client_id=target_client_id, id=payload.id).first()
        if p:
            p.sku = payload.sku
            p.name = payload.name
            p.price = payload.price
            p.stock = payload.stock
            p.min_quantity = payload.min_quantity
            p.is_active = payload.is_active
            p.custom_attributes = payload.custom_attributes
            p.price_rules = payload.price_rules
            if payload.image_path is not None:
                p.image_path = payload.image_path
    else:
        p = CatalogProduct(
            client_id=target_client_id,
            sku=payload.sku,
            name=payload.name,
            price=payload.price,
            stock=payload.stock,
            min_quantity=payload.min_quantity,
            is_active=payload.is_active,
            custom_attributes=payload.custom_attributes,
            price_rules=payload.price_rules,
            image_path=payload.image_path
        )
        db.add(p)
        
    db.commit()
    db.refresh(p)
    return {"status": "ok", "id": p.id}

@app.delete("/api/admin/catalog/delete/{prod_id}")
async def api_delete_catalog_product(
    request: Request,
    prod_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})
    
    from src.database.models import CatalogProduct
    db.query(CatalogProduct).filter_by(client_id=target_client_id, id=prod_id).delete()
    db.commit()
    return {"status": "ok"}

@app.delete("/api/admin/catalog/clear_all")
async def api_clear_catalog(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.models import CatalogProduct
    deleted_count = db.query(CatalogProduct).filter_by(client_id=target_client_id).delete()
    db.commit()
    return {"status": "ok", "deleted_count": deleted_count}

class CatalogResponseSettingsPayload(BaseModel):
    catalog_require_lead_before_price: bool = False
    catalog_lead_fields: list[str] = []
    catalog_send_pdf_quote: bool = False
    catalog_order_fields: list[str] = []
    catalog_min_lead_days: int = 0
    catalog_confirm_attributes: bool = False
    catalog_include_images: bool = True
    catalog_response_style: str = None

@app.post("/api/admin/catalog/response_settings")
async def api_save_catalog_response_settings(
    request: Request,
    payload: CatalogResponseSettingsPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.models import ClientSettings
    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    if not settings:
        return JSONResponse(status_code=404, content={"error": "Configuración no encontrada"})

    settings.catalog_require_lead_before_price = payload.catalog_require_lead_before_price
    settings.catalog_lead_fields = json.dumps(payload.catalog_lead_fields) if payload.catalog_lead_fields else None
    settings.catalog_send_pdf_quote = payload.catalog_send_pdf_quote
    settings.catalog_order_fields = json.dumps(payload.catalog_order_fields) if payload.catalog_order_fields else None
    settings.catalog_min_lead_days = payload.catalog_min_lead_days
    settings.catalog_confirm_attributes = payload.catalog_confirm_attributes
    settings.catalog_include_images = payload.catalog_include_images
    settings.catalog_response_style = payload.catalog_response_style or None
    db.commit()
    return {"status": "ok"}

@app.post("/api/admin/catalog/upload_image/{prod_id}")
async def api_upload_catalog_image(
    request: Request,
    prod_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})
    
    from src.database.models import CatalogProduct
    product = db.query(CatalogProduct).filter_by(client_id=target_client_id, id=prod_id).first()
    if not product:
        return JSONResponse(status_code=404, content={"error": "Producto no encontrado"})
        
    # Crear directorio del cliente si no existe
    client_dir = os.path.join("uploads", f"client_{target_client_id}", "catalog")
    os.makedirs(client_dir, exist_ok=True)
    
    # Nombre seguro
    filename = f"prod_{prod_id}_{int(datetime.now().timestamp())}{os.path.splitext(file.filename)[1]}"
    file_path = os.path.join(client_dir, filename).replace("\\", "/")
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        product.image_path = f"/{file_path}"
        db.commit()
        return {"status": "ok", "image_path": product.image_path}
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

class MassUpdatePayload(BaseModel):
    update_type: str # 'percent' or 'fixed'
    action: str # 'increase' or 'decrease'
    value: float
    filter_text: str = None

@app.post("/api/admin/catalog/mass_update")
async def api_mass_update_catalog(
    request: Request,
    payload: MassUpdatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})
    
    from src.database.models import CatalogProduct, CatalogPriceHistory
    
    query = db.query(CatalogProduct).filter_by(client_id=target_client_id, is_active=True)
    if payload.filter_text and payload.filter_text.strip():
        search = f"%{payload.filter_text.strip()}%"
        query = query.filter((CatalogProduct.name.ilike(search)) | (CatalogProduct.sku.ilike(search)))
        
    products = query.all()
    
    updated_count = 0
    for p in products:
        old_price = p.price
        if payload.update_type == 'percent':
            factor = (payload.value / 100.0)
            if payload.action == 'increase':
                new_price = old_price * (1 + factor)
            else:
                new_price = old_price * (1 - factor)
        else: # fixed
            if payload.action == 'increase':
                new_price = old_price + payload.value
            else:
                new_price = old_price - payload.value
                
        new_price = round(new_price, 2)
        if new_price < 0: new_price = 0.0
        
        if old_price != new_price:
            p.price = new_price
            history = CatalogPriceHistory(
                client_id=target_client_id,
                product_id=p.id,
                old_price=old_price,
                new_price=new_price,
                reason=f"Ajuste masivo: {payload.action} {payload.value} {payload.update_type}"
            )
            db.add(history)
            updated_count += 1
            
    db.commit()
    return {"status": "ok", "updated_count": updated_count}

@app.post("/api/admin/catalog/import_csv")
async def api_import_catalog_csv(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})
    
    import csv, io
    from src.database.models import CatalogProduct
    
    try:
        content = await file.read()
        decoded = content.decode('utf-8', errors='replace')
        reader = csv.DictReader(io.StringIO(decoded), delimiter=',')
        
        imported = 0
        for row in reader:
            # Soportar diferentes nombres de columnas comunes
            name = row.get('nombre') or row.get('name') or row.get('Nombre') or row.get('Name')
            if not name: continue
            
            sku = row.get('sku') or row.get('codigo') or row.get('SKU') or row.get('Codigo') or ""
            price_str = row.get('precio') or row.get('price') or row.get('Precio') or "0"
            stock_str = row.get('stock') or row.get('Stock') or "0"
            
            try: price = float(price_str)
            except: price = 0.0
            
            try: stock = int(stock_str)
            except: stock = 0
            
            p = CatalogProduct(
                client_id=target_client_id,
                sku=str(sku).strip(),
                name=str(name).strip(),
                price=price,
                stock=stock,
                min_quantity=1,
                is_active=True
            )
            db.add(p)
            imported += 1
            
        db.commit()
        return {"status": "ok", "imported": imported}
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

# ==========================================
# BIBLIOTECA DE DOCUMENTOS
# ==========================================

class DocSegmentPayload(BaseModel):
    id: int | None = None
    name: str
    is_public: bool = True
    auth_mode: str = "generic"  # "generic" | "individual" (solo aplica si is_public=False)
    generic_password: str | None = None  # se hashea acá; si se deja vacío en una edición, se conserva la clave existente
    session_expiry_days: int | None = None  # None = sesión permanente
    is_active: bool = True

class DocumentPayload(BaseModel):
    id: int | None = None
    title: str
    keywords: str | None = None
    description: str | None = None
    segment_ids: list[int] = []
    is_active: bool = True

class DocLibraryUserPayload(BaseModel):
    id: int | None = None
    username: str
    password: str | None = None  # opcional en edición: si se deja vacío, se conserva la clave existente
    full_name: str | None = None
    segment_ids: list[int] = []
    is_active: bool = True

class DocLibrarySettingsPayload(BaseModel):
    trigger_phrases: list[str] = []

@app.get("/admin/document-library", response_class=HTMLResponse)
async def document_library_panel(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")

    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    if not settings or not getattr(settings, 'feat_document_library', False):
        return RedirectResponse(url="/admin")

    return templates.TemplateResponse(
        request=request,
        name="admin/document_library.html",
        context={
            "user": user_mock,
            "settings": settings,
            "is_impersonating": is_impersonating,
            "active_section": "operacion"
        }
    )

@app.get("/admin/document-library-logs", response_class=HTMLResponse)
async def document_library_logs_panel(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, is_impersonating, user_mock = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")

    from src.database.models import DocSearchLog
    raw_logs = db.query(DocSearchLog).filter_by(client_id=target_client_id).order_by(DocSearchLog.created_at.desc()).limit(300).all()
    search_logs = [{
        "query": l.query,
        "found": l.found,
        "results_count": l.results_count,
        "document_title": l.document_title,
        "auth_blocked": l.auth_blocked,
        "formatted_date": l.created_at.strftime("%d/%m/%Y %H:%M") if l.created_at else ""
    } for l in raw_logs]

    return templates.TemplateResponse(
        request=request,
        name="admin/document_library_logs.html",
        context={"search_logs": search_logs, "user": user_mock, "is_impersonating": is_impersonating}
    )

# --- Segmentos ---

@app.get("/api/admin/document_library/segments")
async def api_get_doc_segments(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.models import DocSegment
    segments = db.query(DocSegment).filter_by(client_id=target_client_id).order_by(DocSegment.name).all()
    return [{
        "id": s.id,
        "name": s.name,
        "is_public": s.is_public,
        "auth_mode": s.auth_mode,
        "has_generic_password": bool(s.generic_password_hash),
        "session_expiry_days": s.session_expiry_days,
        "is_active": s.is_active,
    } for s in segments]

@app.post("/api/admin/document_library/segments/save")
async def api_save_doc_segment(request: Request, payload: DocSegmentPayload, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.models import DocSegment
    from src.database.document_library import hash_password

    if payload.id:
        s = db.query(DocSegment).filter_by(client_id=target_client_id, id=payload.id).first()
        if not s:
            return JSONResponse(status_code=404, content={"error": "Segmento no encontrado"})
    else:
        s = DocSegment(client_id=target_client_id)
        db.add(s)

    s.name = payload.name.strip()
    s.is_public = payload.is_public
    s.auth_mode = payload.auth_mode if payload.auth_mode in ("generic", "individual") else "generic"
    s.session_expiry_days = payload.session_expiry_days
    s.is_active = payload.is_active
    if not payload.is_public and payload.auth_mode == "generic" and payload.generic_password:
        s.generic_password_hash = hash_password(payload.generic_password)

    db.commit()
    db.refresh(s)
    return {"status": "ok", "id": s.id}

@app.delete("/api/admin/document_library/segments/delete/{segment_id}")
async def api_delete_doc_segment(request: Request, segment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.models import DocSegment
    db.query(DocSegment).filter_by(client_id=target_client_id, id=segment_id).delete()
    db.commit()
    return {"status": "ok"}

# --- Documentos ---

@app.get("/api/admin/document_library/documents")
async def api_get_documents(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.models import Document, DocumentSegmentLink
    docs = db.query(Document).filter_by(client_id=target_client_id).order_by(Document.id.desc()).all()

    data = []
    for d in docs:
        segment_ids = [l.segment_id for l in db.query(DocumentSegmentLink).filter_by(document_id=d.id).all()]
        data.append({
            "id": d.id,
            "title": d.title,
            "keywords": d.keywords or "",
            "description": d.description or "",
            "file_path": d.file_path or "",
            "source_type": d.source_type or "local",
            "segment_ids": segment_ids,
            "is_active": d.is_active,
        })
    return data

@app.post("/api/admin/document_library/documents/save")
async def api_save_document(request: Request, payload: DocumentPayload, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.models import Document, DocumentSegmentLink

    if payload.id:
        d = db.query(Document).filter_by(client_id=target_client_id, id=payload.id).first()
        if not d:
            return JSONResponse(status_code=404, content={"error": "Documento no encontrado"})
    else:
        d = Document(client_id=target_client_id)
        db.add(d)

    d.title = payload.title.strip()
    d.keywords = payload.keywords
    d.description = payload.description
    d.is_active = payload.is_active
    db.commit()
    db.refresh(d)

    db.query(DocumentSegmentLink).filter_by(document_id=d.id).delete()
    for seg_id in (payload.segment_ids or []):
        db.add(DocumentSegmentLink(client_id=target_client_id, document_id=d.id, segment_id=seg_id))
    db.commit()

    from src.database.document_library import sync_document_to_chroma
    sync_document_to_chroma(d.id)

    return {"status": "ok", "id": d.id}

@app.delete("/api/admin/document_library/documents/delete/{doc_id}")
async def api_delete_document(request: Request, doc_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.models import Document
    doc = db.query(Document).filter_by(client_id=target_client_id, id=doc_id).first()
    if not doc:
        return JSONResponse(status_code=404, content={"error": "Documento no encontrado"})

    if doc.file_path:
        local_path = doc.file_path.lstrip("/")
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception as e:
                logging.error(f"[DocLibrary] Error borrando archivo {local_path}: {e}")

    from src.database.document_library import remove_document_from_chroma
    remove_document_from_chroma(doc_id, target_client_id)

    db.delete(doc)
    db.commit()
    return {"status": "ok"}

@app.post("/api/admin/document_library/documents/upload_file/{doc_id}")
async def api_upload_document_file(
    request: Request,
    doc_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.models import Document
    doc = db.query(Document).filter_by(client_id=target_client_id, id=doc_id).first()
    if not doc:
        return JSONResponse(status_code=404, content={"error": "Documento no encontrado"})

    client_dir = os.path.join("uploads", f"client_{target_client_id}", "documents")
    os.makedirs(client_dir, exist_ok=True)

    filename = f"doc_{doc_id}_{int(datetime.now().timestamp())}{os.path.splitext(file.filename)[1]}"
    file_path = os.path.join(client_dir, filename).replace("\\", "/")

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        doc.file_path = f"/{file_path}"
        db.commit()
        return {"status": "ok", "file_path": doc.file_path}
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- Usuarios de Biblioteca (credenciales individuales) ---

@app.get("/api/admin/document_library/users")
async def api_get_doc_library_users(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.models import DocLibraryUser, DocLibraryUserSegment
    users = db.query(DocLibraryUser).filter_by(client_id=target_client_id).order_by(DocLibraryUser.username).all()

    data = []
    for u in users:
        segment_ids = [l.segment_id for l in db.query(DocLibraryUserSegment).filter_by(library_user_id=u.id).all()]
        data.append({
            "id": u.id,
            "username": u.username,
            "full_name": u.full_name or "",
            "segment_ids": segment_ids,
            "is_active": u.is_active,
        })
    return data

@app.post("/api/admin/document_library/users/save")
async def api_save_doc_library_user(request: Request, payload: DocLibraryUserPayload, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.models import DocLibraryUser, DocLibraryUserSegment
    from src.database.document_library import hash_password

    if payload.id:
        u = db.query(DocLibraryUser).filter_by(client_id=target_client_id, id=payload.id).first()
        if not u:
            return JSONResponse(status_code=404, content={"error": "Usuario no encontrado"})
    else:
        if not payload.password:
            return JSONResponse(status_code=400, content={"error": "La contraseña es obligatoria para un usuario nuevo"})
        u = DocLibraryUser(client_id=target_client_id, password_hash=hash_password(payload.password))
        db.add(u)

    u.username = payload.username.strip()
    u.full_name = payload.full_name
    u.is_active = payload.is_active
    if payload.password:
        u.password_hash = hash_password(payload.password)

    db.commit()
    db.refresh(u)

    db.query(DocLibraryUserSegment).filter_by(library_user_id=u.id).delete()
    for seg_id in (payload.segment_ids or []):
        db.add(DocLibraryUserSegment(client_id=target_client_id, library_user_id=u.id, segment_id=seg_id))
    db.commit()

    return {"status": "ok", "id": u.id}

@app.delete("/api/admin/document_library/users/delete/{user_id}")
async def api_delete_doc_library_user(request: Request, user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.models import DocLibraryUser, DocSession
    # DocSession.library_user_id no tiene ON DELETE CASCADE (a propósito, para no perder
    # sesiones por error): hay que soltar la referencia a mano antes de borrar el usuario.
    db.query(DocSession).filter_by(client_id=target_client_id, library_user_id=user_id).delete()
    db.query(DocLibraryUser).filter_by(client_id=target_client_id, id=user_id).delete()
    db.commit()
    return {"status": "ok"}

# --- Configuración (frases gatillo) ---

@app.get("/api/admin/document_library/settings")
async def api_get_doc_library_settings(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    try:
        phrases = json.loads(settings.doc_library_trigger_phrases) if settings and settings.doc_library_trigger_phrases else []
    except Exception:
        phrases = []
    return {"trigger_phrases": phrases}

@app.post("/api/admin/document_library/settings")
async def api_save_doc_library_settings(request: Request, payload: DocLibrarySettingsPayload, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    if not settings:
        return JSONResponse(status_code=404, content={"error": "Configuración no encontrada"})

    settings.doc_library_trigger_phrases = json.dumps(payload.trigger_phrases) if payload.trigger_phrases else None
    db.commit()
    return {"status": "ok"}

# ── API: Google Drive (sync de la Biblioteca de Documentos) ───────────────────

class GDriveSetFolderPayload(BaseModel):
    folder_id: str

@app.get("/api/admin/gdrive/oauth/start")
async def api_gdrive_oauth_start(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.gdrive_sync import build_oauth_flow, get_oauth_redirect_uri, generate_oauth_state
    try:
        redirect_uri = get_oauth_redirect_uri(str(request.base_url))
        flow = build_oauth_flow(redirect_uri, target_client_id)
        state = generate_oauth_state(target_client_id)
        auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent", state=state)
        return RedirectResponse(url=auth_url)
    except Exception as e:
        logging.error(f"[GDrive] Error iniciando OAuth: {e}")
        return RedirectResponse(url="/admin/document-library?gdrive_error=1")

@app.get("/api/admin/gdrive/oauth/callback")
async def api_gdrive_oauth_callback(request: Request, current_user: User = Depends(get_current_user)):
    from src.database.gdrive_sync import build_oauth_flow, get_oauth_redirect_uri, pop_oauth_state, save_oauth_tokens

    state = request.query_params.get("state")
    code = request.query_params.get("code")
    client_id = pop_oauth_state(state) if state else None
    if not client_id or not code:
        return RedirectResponse(url="/admin/document-library?gdrive_error=1")

    # Defensa en profundidad: el admin logueado debe seguir teniendo permiso sobre ese cliente
    # (respeta impersonación de super-admin, pero no confía únicamente en la cookie de sesión).
    if current_user.client_id is not None and current_user.client_id != client_id:
        return JSONResponse(status_code=403, content={"error": "No autorizado para este cliente"})

    try:
        redirect_uri = get_oauth_redirect_uri(str(request.base_url))
        flow = build_oauth_flow(redirect_uri, client_id)
        flow.fetch_token(code=code)
        save_oauth_tokens(client_id, flow.credentials)
    except Exception as e:
        logging.error(f"[GDrive] Error en callback OAuth (client_id={client_id}): {e}")
        return RedirectResponse(url="/admin/document-library?gdrive_error=1")

    return RedirectResponse(url="/admin/document-library?gdrive=connected")

@app.post("/api/admin/gdrive/disconnect")
async def api_gdrive_disconnect(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.gdrive_sync import disconnect_drive
    disconnect_drive(target_client_id)
    return {"status": "ok"}

@app.get("/api/admin/gdrive/status")
async def api_gdrive_status(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    if not settings:
        return {"connected": False}

    summary = None
    if settings.gdrive_last_sync_summary:
        try:
            summary = json.loads(settings.gdrive_last_sync_summary)
        except Exception:
            summary = None

    return {
        "connected": bool(settings.gdrive_refresh_token_encrypted),
        "email": settings.gdrive_connected_email,
        "root_folder_name": settings.gdrive_root_folder_name,
        "last_sync_at": settings.gdrive_last_sync_at.isoformat() if settings.gdrive_last_sync_at else None,
        "last_sync_summary": summary,
        "needs_reconnect": bool(settings.gdrive_needs_reconnect),
    }

@app.get("/api/admin/gdrive/folders")
async def api_gdrive_folders(request: Request, parent_id: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.gdrive_sync import list_folder_contents_for_picker
    folders = list_folder_contents_for_picker(target_client_id, parent_id)
    if folders is None:
        return JSONResponse(status_code=400, content={"error": "Google Drive no está conectado"})
    return {"folders": folders}

@app.post("/api/admin/gdrive/set_root_folder")
async def api_gdrive_set_root_folder(request: Request, payload: GDriveSetFolderPayload, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.gdrive_sync import parse_folder_id_from_input, get_folder_info
    folder_id = parse_folder_id_from_input(payload.folder_id)
    info = get_folder_info(target_client_id, folder_id)
    if not info:
        return JSONResponse(status_code=400, content={"error": "No se pudo acceder a esa carpeta. Verificá el link/ID y que la cuenta conectada tenga acceso."})

    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    settings.gdrive_root_folder_id = info["id"]
    settings.gdrive_root_folder_name = info["name"]
    db.commit()
    return {"status": "ok", "folder_name": info["name"]}

@app.post("/api/admin/gdrive/sync_now")
async def api_gdrive_sync_now(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})

    from src.database.gdrive_sync import sync_client_drive
    summary = sync_client_drive(target_client_id)
    return summary

@app.get("/api/gdrive/stream/{token}")
async def api_gdrive_stream_file(token: str):
    """Endpoint público (sin sesión de admin): lo llaman los servidores de Green-API/Telegram para
    descargar el archivo mientras lo envían al usuario final. Protegido por token opaco + TTL corto +
    re-verificación de autorización en vivo (ver create_download_token/get_authorized_document_file)."""
    from src.database.gdrive_sync import peek_download_token, resolve_file_download
    from src.database.document_library import get_authorized_document_file

    entry = peek_download_token(token)
    if not entry:
        return Response(status_code=404)

    doc_info = get_authorized_document_file(entry["client_id"], entry["thread_id"], entry["document_id"])
    if not doc_info or doc_info.get("source_type") != "gdrive":
        return Response(status_code=404)

    try:
        content, filename, mimetype = resolve_file_download(entry["client_id"], doc_info["external_file_id"])
    except Exception as e:
        logging.error(f"[GDrive] Error resolviendo descarga para stream (token={token}): {e}")
        return Response(status_code=404)

    return StreamingResponse(io.BytesIO(content), media_type=mimetype,
                              headers={"Content-Disposition": f'attachment; filename="{filename}"'})

# ── API: Gestión de Usuarios ───────────────────────────────────────────────────
class UserCreatePayload(BaseModel):
    full_name: str
    username: str
    email: str = None
    role: str
    password: str

class UserUpdatePayload(BaseModel):
    full_name: str = None
    email: str = None
    role: str = None
    is_active: int = None

class PasswordResetPayload(BaseModel):
    password: str

class PermissionsUpdate(BaseModel):
    permissions: list[str]

@app.get("/api/admin/users")
async def api_list_users(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None:
        return JSONResponse({"status": "error", "message": "No autorizado"}, status_code=401)
        
    from src.database.models import User as DBUser
    users_raw = db.query(DBUser).filter_by(client_id=target_client_id).all()
    rows = []
    for u in users_raw:
        email_prefix = u.email.split('@')[0] if u.email else "usuario"
        rows.append({
            "id": u.id,
            "username": email_prefix,
            "full_name": email_prefix.capitalize(),
            "email": u.email,
            "role": u.role_name,
            "is_active": True
        })
    return {"status": "ok", "users": rows}

@app.post("/api/admin/users")
async def api_create_user(
    request: Request,
    payload: UserCreatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None:
        return JSONResponse({"status": "error", "message": "No autorizado"}, status_code=401)
        
    email_to_save = payload.email.strip() if (payload.email and payload.email.strip()) else f"{payload.username.strip()}@rondan.com"
    
    existing = db.query(User).filter_by(email=email_to_save).first()
    if existing:
        return JSONResponse({"status": "error", "message": "El email o username ya existe"}, status_code=409)
        
    pwd_hash = hashlib.md5(payload.password.encode()).hexdigest()
    
    new_user = User(
        client_id=target_client_id,
        email=email_to_save,
        password_hash=pwd_hash,
        role_name=payload.role
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {"status": "ok", "id": new_user.id}

@app.patch("/api/admin/users/{uid}")
async def api_edit_user(
    request: Request,
    uid: int,
    payload: UserUpdatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None:
        return JSONResponse({"status": "error", "message": "No autorizado"}, status_code=401)
        
    user = db.query(User).filter_by(client_id=target_client_id, id=uid).first()
    if not user:
        return JSONResponse({"status": "error", "message": "Usuario no encontrado"}, status_code=404)
        
    if payload.email is not None:
        user.email = payload.email
    if payload.role is not None:
        user.role_name = payload.role
        
    db.commit()
    return {"status": "ok"}

@app.patch("/api/admin/users/{uid}/reset-password")
async def api_reset_password(
    request: Request,
    uid: int,
    payload: PasswordResetPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None:
        return JSONResponse({"status": "error", "message": "No autorizado"}, status_code=401)
        
    user = db.query(User).filter_by(client_id=target_client_id, id=uid).first()
    if not user:
        return JSONResponse({"status": "error", "message": "Usuario no encontrado"}, status_code=404)
        
    pwd_hash = hashlib.md5(payload.password.encode()).hexdigest()
    user.password_hash = pwd_hash
    db.commit()
    
    return {"status": "ok"}

@app.get("/api/admin/users/{uid}/permissions")
async def api_get_permissions(
    request: Request,
    uid: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None:
        return JSONResponse({"status": "error", "message": "No autorizado"}, status_code=401)
        
    user = db.query(User).filter_by(client_id=target_client_id, id=uid).first()
    if not user:
        return JSONResponse({"status": "error", "message": "Usuario no encontrado"}, status_code=404)
        
    if user.role_name == "superadmin":
        permissions = [item["key"] for item in DEFAULT_MENU_ITEMS]
    else:
        from src.database.models import UserPermission
        perms = db.query(UserPermission).filter_by(user_id=uid, can_access=True).all()
        permissions = [p.menu_key for p in perms]
        
    return {"status": "ok", "permissions": permissions, "role": user.role_name}

@app.post("/api/admin/users/{uid}/permissions")
async def api_save_permissions(
    request: Request,
    uid: int,
    payload: PermissionsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None:
        return JSONResponse({"status": "error", "message": "No autorizado"}, status_code=401)
        
    user = db.query(User).filter_by(client_id=target_client_id, id=uid).first()
    if not user:
        return JSONResponse({"status": "error", "message": "Usuario no encontrado"}, status_code=404)
        
    from src.database.models import UserPermission
    db.query(UserPermission).filter_by(user_id=uid).delete()
    
    for key in payload.permissions:
        perm = UserPermission(user_id=uid, menu_key=key, can_access=True)
        db.add(perm)
        
    db.commit()
    return {"status": "ok"}

@app.get("/admin/{telegram_file_id}")
async def resolve_legacy_telegram_file_id(
    request: Request,
    telegram_file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Si la ruta parece un file_id de Telegram (ej. largo, sin extensiones comunes ni barras)
    if len(telegram_file_id) > 20 and "." not in telegram_file_id and "/" not in telegram_file_id and "\\" not in telegram_file_id:
        target_client_id, _, _ = get_admin_context(request, current_user, db)
        if target_client_id is not None:
            from src.database.models import Attachment, ClientSettings
            # Buscar el attachment con este file_path
            att = db.query(Attachment).filter_by(client_id=target_client_id, file_path=telegram_file_id).first()
            if att:
                return RedirectResponse(url=f"/admin/files/view/{att.id}")
            else:
                # Si no lo encuentra pero tiene el token, intentar descargar y retornar FileResponse
                settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
                token = settings.telegram_token if settings else None
                if token:
                    res_dl = await download_telegram_media_saas(telegram_file_id, token)
                    if res_dl:
                        local_path = os.path.join(os.path.abspath("uploads"), res_dl["name"])
                        if os.path.exists(local_path):
                            from fastapi.responses import FileResponse
                            return FileResponse(local_path)
                            
    raise HTTPException(status_code=404, detail="Not Found")

# ==========================================
# GESTIÓN DE WEBHOOKS (SAAS)
# ==========================================

async def setup_whatsapp_webhook(base_url: str, client_slug: str):
    """Configura el webhook en Green-API para un cliente específico."""
    try:
        db = SessionLocal()
        client = db.query(Client).filter_by(slug=client_slug).first()
        if not client or not client.settings: return False
        
        g_id = client.settings.whatsapp_instance_id
        g_token = client.settings.whatsapp_token
        
        if not g_id or not g_token: return False

        import httpx
        url = f"https://api.green-api.com/waInstance{g_id}/setSettings/{g_token}"
        webhook_final = f"{base_url}/webhook/{client_slug}/greenapi"
        
        payload = {
            "webhookUrl": webhook_final,
            "outgoingMessageWebhook": "yes",
            "stateInstanceWebhook": "yes",
            "incomingMessageWebhook": "yes",
            "outgoingAPIMessageWebhook": "yes",
            "statusMessageWebhook": "yes"
        }
        
        async with httpx.AsyncClient() as http_client:
            await http_client.post(url, json=payload, timeout=10.0)
            
        logging.info(f"[SaaS] Webhook configurado para cliente '{client_slug}': {webhook_final}")
        return True
    except Exception as e:
        logging.error(f"Error configurando webhook SaaS: {e}")
        return False
    finally:
        db.close()


@app.post("/webhook/{client_slug}/telegram")
async def telegram_webhook(client_slug: str, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        if "message" not in data:
            return JSONResponse({"status": "ignored"})
            
        # 1. Validación Multi-Cliente
        client = db.query(Client).filter(Client.slug == client_slug, Client.status == 'active').first()
        if not client:
            return JSONResponse({"status": "ignored", "reason": "Client not found"})
            
        message = data["message"]
        user_id = str(message["chat"]["id"])
        user_text = message.get("text", "")
        
        attachment = None
        if "document" in message:
            doc = message["document"]
            attachment = {
                "file_id": doc.get("file_id"),
                "file_name": doc.get("file_name", "documento"),
                "mime_type": doc.get("mime_type", "application/octet-stream")
            }
        elif "photo" in message:
            photos = message["photo"]
            if photos:
                attachment = {
                    "file_id": photos[-1].get("file_id"),
                    "file_name": "Imagen.jpg",
                    "mime_type": "image/jpeg"
                }
            if not user_text:
                user_text = "[Archivo Adjunto]"
        elif "document" in message:
            if not user_text:
                user_text = "[Archivo Adjunto]"
        
        if not user_text:
            return JSONResponse({"status": "ignored"})
            
        logging.info(f"[SaaS Telegram] Mensaje recibido de {user_id} para cliente {client_slug}")
        
        # 4. Procesamiento Asíncrono
        background_tasks.add_task(process_bot_response, client.id, user_id, user_text, "telegram", attachment)
        
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logging.error(f"[SaaS Telegram] Error webhook: {e}")
        return JSONResponse({"status": "error"})

@app.post("/admin/whatsapp/sync-webhooks")
async def sync_webhooks(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return JSONResponse(status_code=401, content={"error": "No autorizado"})
    
    settings = db.query(ClientSettings).filter_by(client_id=target_client_id).first()
    client = db.query(Client).filter_by(id=target_client_id).first()
    
    base_url = settings.webhook_base_url or str(request.base_url).rstrip('/')
    base_url = base_url.rstrip('/')
    errors = []
    
    if settings.whatsapp_enabled and settings.whatsapp_instance_id and settings.whatsapp_token:
        wa_webhook = f"{base_url}/webhook/{client.slug}/greenapi"
        import httpx
        url = f"https://api.green-api.com/waInstance{settings.whatsapp_instance_id}/SetSettings/{settings.whatsapp_token}"
        payload = {"webhookUrl": wa_webhook, "outgoingWebhook": "yes", "stateWebhook": "yes", "incomingWebhook": "yes"}
        try:
            async with httpx.AsyncClient() as hc:
                r = await hc.post(url, json=payload, timeout=10.0)
                if r.status_code != 200: errors.append("Error GreenAPI")
        except Exception as e: errors.append(f"GreenAPI err: {e}")
        
    if settings.telegram_enabled and settings.telegram_token:
        tg_webhook = f"{base_url}/webhook/{client.slug}/telegram"
        import httpx
        url = f"https://api.telegram.org/bot{settings.telegram_token}/setWebhook?url={tg_webhook}"
        try:
            async with httpx.AsyncClient() as hc:
                r = await hc.get(url, timeout=10.0)
                if r.status_code != 200: errors.append("Error Telegram API")
        except Exception as e: errors.append(f"Telegram err: {e}")
        
    if errors: return JSONResponse(status_code=400, content={"status": "error", "message": " | ".join(errors)})
    return JSONResponse(content={"status": "ok"})

def is_within_working_hours(working_hours_str: str) -> bool:
    if not working_hours_str or "24/7" in working_hours_str.lower():
        return True
    try:
        from datetime import datetime
        import re
        now = datetime.now()
        day_names = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
        today_name = day_names[now.weekday()]
        
        pattern = rf"{today_name}.*?(\d{{1,2}}):?(\d{{0,2}})\s*(am|pm)?\s*-\s*(\d{{1,2}}):?(\d{{0,2}})\s*(am|pm)?"
        match = re.search(pattern, working_hours_str.lower())
        if match:
            h1, m1, p1, h2, m2, p2 = match.groups()
            h1, h2 = int(h1), int(h2)
            m1 = int(m1) if m1 else 0
            m2 = int(m2) if m2 else 0
            if p1 == 'pm' and h1 < 12: h1 += 12
            if p1 == 'am' and h1 == 12: h1 = 0
            if p2 == 'pm' and h2 < 12: h2 += 12
            if p2 == 'am' and h2 == 12: h2 = 0
            start_time = now.replace(hour=h1, minute=m1, second=0, microsecond=0)
            end_time = now.replace(hour=h2, minute=m2, second=0, microsecond=0)
            if end_time < start_time: return now >= start_time or now <= end_time
            return start_time <= now <= end_time
            
        if "a" in working_hours_str.lower() or "to" in working_hours_str.lower():
            is_weekend = now.weekday() >= 5
            if is_weekend and ("lunes a viernes" in working_hours_str.lower() or "mon to fri" in working_hours_str.lower()):
                return False
            match_range = re.search(r"(\d{1,2}):?(\d{0,2}).*?(\d{1,2}):?(\d{0,2})", working_hours_str)
            if match_range:
                h1, m1, h2, m2 = match_range.groups()
                start_time = now.replace(hour=int(h1), minute=int(m1 or 0), second=0, microsecond=0)
                end_time = now.replace(hour=int(h2), minute=int(m2 or 0), second=0, microsecond=0)
                return start_time <= now <= end_time

        if f"{today_name}: cerrado" in working_hours_str.lower(): return False
        return True
    except Exception as e:
        logging.error(f"Error parseando horario: {e}")
        return True

@app.post("/webhook/{client_slug}/greenapi")
async def green_api_webhook(client_slug: str, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Recepción de mensajes de WhatsApp filtrados por cliente."""
    try:
        raw_body = await request.body()
        data = json.loads(raw_body)
        type_webhook = data.get("typeWebhook")
        
        # 1. Validación Multi-Cliente
        client = db.query(Client).filter(Client.slug == client_slug, Client.status == 'active').first()
        if not client:
            logging.warning(f"[SaaS Webhook] Ignorado: Cliente '{client_slug}' no encontrado o inactivo.")
            return JSONResponse({"status": "ignored", "reason": "Client not found"})
            
        client_id = client.id

        from src.database.models import ClientSettings, Message
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()

        # 2. Ignorar eventos que no sean mensajes entrantes (Simplificado)
        if type_webhook != 'incomingMessageReceived':
            return JSONResponse({"status": "ignored"})
            
        # 3. Extracción de Datos
        user_id = data.get("senderData", {}).get("chatId", "")
        message_data = data.get("messageData", {})
        type_msg = message_data.get("typeMessage")
        
        user_text = ""
        attachment = None
        
        if type_msg == "textMessage":
            user_text = message_data.get("textMessageData", {}).get("textMessage", "")
        elif type_msg == "extendedTextMessage":
            user_text = message_data.get("extendedTextMessageData", {}).get("text", "")
            
        if not user_id or not user_text:
            return JSONResponse({"status": "incomplete_data"})

        logging.info(f"[SaaS Webhook] Mensaje recibido de {user_id} para cliente {client_slug}")
        
        # 4. Procesamiento Asíncrono
        background_tasks.add_task(process_bot_response, client_id, user_id, user_text, "whatsapp", attachment)
        
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logging.error(f"[SaaS Webhook] Error: {e}")
        return JSONResponse({"status": "error"})

# ==========================================
# CEREBRO Y RESPUESTA (SAAS)
# ==========================================


def format_message_for_whatsapp(text: str) -> str:
    if not text:
        return text
    import re
    # Convertir **texto** a *texto*
    return re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)

def format_message_for_telegram(text: str) -> str:
    if not text:
        return text
    # Escapar caracteres HTML reservados primero
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Ahora aplicar la conversión de ** a <b>
    import re
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    # Restaurar los tags de negrita que se escaparon
    text = text.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    return text

async def send_telegram_message_saas(client_id: int, user_id: str, message: str):
    """Envía un mensaje vía Telegram usando credenciales SQL Server."""
    try:
        from src.database.session import SessionLocal
        from src.database.models import ClientSettings
        import httpx, logging
        db = SessionLocal()
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings or not settings.telegram_token or not settings.telegram_enabled: return None
        
        formatted_message = format_message_for_telegram(message)
        url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"
        payload = {"chat_id": user_id, "text": formatted_message, "parse_mode": "HTML"}
        
        async with httpx.AsyncClient() as http_client:
            res = await http_client.post(url, json=payload, timeout=20.0)
            data = res.json()
            return str(data.get('result', {}).get('message_id', ''))
    except Exception as e:
        logging.error(f"[SaaS Telegram] Error: {e}")
        return None
    finally:
        db.close()

async def send_telegram_file_saas(client_id: int, user_id: str, local_path: str, caption: str = ""):
    try:
        from src.database.session import SessionLocal
        from src.database.models import ClientSettings
        import httpx, logging, os
        db = SessionLocal()
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        token = settings.telegram_token if settings else None
        db.close()
        if not token or not settings.telegram_enabled: return None

        formatted_caption = format_message_for_telegram(caption)
        is_remote_url = local_path.startswith("http://") or local_path.startswith("https://")
        ext = local_path.split("?")[0].lower()
        is_image = ext.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))
        file_key = "photo" if is_image else "document"
        url = f"https://api.telegram.org/bot{token}/{'sendPhoto' if is_image else 'sendDocument'}"

        async with httpx.AsyncClient() as hc:
            if is_remote_url:
                # Imagen alojada externamente: Telegram la descarga directo de la URL
                payload = {"chat_id": user_id, "caption": formatted_caption, "parse_mode": "HTML", file_key: local_path}
                r = await hc.post(url, json=payload, timeout=30.0)
            else:
                actual_path = local_path.lstrip('/')
                if not os.path.exists(actual_path):
                    logging.error(f"[SaaS Telegram File] Archivo no encontrado localmente: {actual_path}")
                    return None
                payload = {"chat_id": user_id, "caption": formatted_caption, "parse_mode": "HTML"}
                with open(actual_path, "rb") as f:
                    files = {file_key: f}
                    r = await hc.post(url, data=payload, files=files, timeout=30.0)

            if r.status_code == 200:
                res = r.json()
                return str(res.get("result", {}).get("message_id", ""))
            else:
                logging.error(f"[SaaS Telegram File] Error: {r.text}")
    except Exception as e:
        logging.error(f"[SaaS Telegram File] Error: {e}")
    return None

async def send_whatsapp_message_saas(client_id: int, user_id: str, message: str):
    """Envía un mensaje de texto vía Green-API leyendo credenciales de SQL Server."""
    try:
        db = SessionLocal()
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings or not settings.whatsapp_instance_id: return None
        
        formatted_message = format_message_for_whatsapp(message)
        import httpx
        url = f"https://api.green-api.com/waInstance{settings.whatsapp_instance_id}/sendMessage/{settings.whatsapp_token}"
        payload = {"chatId": user_id, "message": formatted_message}
        
        async with httpx.AsyncClient() as http_client:
            res = await http_client.post(url, json=payload, timeout=20.0)
            data = res.json()
            return data.get('idMessage')
    except Exception as e:
        logging.error(f"[SaaS Envio] Error: {e}")
        return None
    finally:
        db.close()

async def send_whatsapp_file_saas(client_id: int, user_id: str, file_url: str, filename: str, caption: str = ""):
    """Envía un archivo vía Green-API leyendo credenciales de SQL Server."""
    try:
        db = SessionLocal()
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings or not settings.whatsapp_instance_id: return None
        
        formatted_caption = format_message_for_whatsapp(caption)
        import httpx
        url = f"https://api.green-api.com/waInstance{settings.whatsapp_instance_id}/sendFileByUrl/{settings.whatsapp_token}"
        payload = {
            "chatId": user_id,
            "urlFile": file_url,
            "fileName": filename,
            "caption": formatted_caption
        }
        
        async with httpx.AsyncClient() as http_client:
            res = await http_client.post(url, json=payload, timeout=30.0)
            data = res.json()
            return data.get('idMessage')
    except Exception as e:
        logging.error(f"[SaaS Envio Archivo] Error: {e}")
        return None
    finally:
        db.close()

async def process_bot_response(client_id: int, user_id: str, user_text: str, platform: str, attachment_data: dict = None):
    """Orquestador principal que conecta el Webhook con LangGraph."""
    async with get_user_lock(user_id):
        # --- Modo Prueba: si está activo, ignorar a cualquiera que no esté en test_numbers ---
        try:
            from src.database.models import ClientSettings
            db_tm = SessionLocal()
            tm_settings = db_tm.query(ClientSettings).filter_by(client_id=client_id).first()
            db_tm.close()
            if tm_settings and tm_settings.test_mode_enabled:
                allowed = {n.strip() for n in (tm_settings.test_numbers or "").split(",") if n.strip()}
                sender_id = str(user_id)
                sender_phone = sender_id.split("@")[0]
                if sender_phone not in allowed and sender_id not in allowed:
                    logging.info(f"[TestMode] Ignorando mensaje de {sender_id} (no está en test_numbers) para cliente {client_id}")
                    return
        except Exception as e:
            logging.error(f"[TestMode] Error chequeando modo prueba: {e}")

        print(f"\n[SaaS Process] Iniciando respuesta para cliente {client_id}, usuario {user_id}...")
        
        try:
            # --- Auto-Etiquetado Inicial ---
            try:
                from src.database.tagging_manager import assign_tag_by_name, ensure_default_tags
                from src.database.models import UserProfile
                ensure_default_tags(client_id)
                db_t = SessionLocal()
                prof_exists = db_t.query(UserProfile).filter_by(client_id=client_id, user_phone=str(user_id)).first()
                db_t.close()
                if not prof_exists:
                    assign_tag_by_name(client_id, str(user_id), "👋 Nuevo Contacto")
                channel_tag = "📱 Canal: WhatsApp" if platform == "whatsapp" else "💬 Canal: Telegram"
                assign_tag_by_name(client_id, str(user_id), channel_tag)
                assign_tag_by_name(client_id, str(user_id), "⚡ Activo Reciente")
            except Exception as te:
                logging.error(f"[Tagging] Error in initial auto-tagging: {te}")

            if attachment_data:
                try:
                    from src.database.models import Attachment, ClientSettings
                    db_local = SessionLocal()
                    
                    # Manejo básico de adjuntos de Telegram/WhatsApp
                    file_id = "Desconocido"
                    file_name = "Archivo Adjunto (SaaS)"
                    file_type = "media/document"
                    if isinstance(attachment_data, dict):
                        file_id = attachment_data.get("file_id", attachment_data.get("url", "Adjunto"))
                        file_name = attachment_data.get("file_name", file_name)
                        file_type = attachment_data.get("mime_type", file_type)
                    elif isinstance(attachment_data, list) and len(attachment_data) > 0:
                        file_id = attachment_data[-1].get("file_id", "Adjunto_Foto")
                        
                    file_path = file_id
                    
                    if platform == "telegram" and file_id != "Desconocido":
                        settings = db_local.query(ClientSettings).filter_by(client_id=client_id).first()
                        token = settings.telegram_token if settings else None
                        if token:
                            res_dl = await download_telegram_media_saas(file_id, token)
                            if res_dl:
                                file_path = res_dl["path"]
                                file_type = res_dl["type"]
                                # Solo sobreescribir el nombre si no tenemos un nombre original válido
                                if not file_name or file_name == "Archivo Adjunto (SaaS)":
                                    file_name = res_dl["name"]
                                
                    new_att = Attachment(
                        client_id=client_id,
                        thread_id=str(user_id),
                        file_path=file_path,
                        file_name=file_name,
                        file_type=file_type,
                        context="pendiente"
                    )
                    db_local.add(new_att)
                    db_local.commit()
                    db_local.close()
                    logging.info(f"[SaaS Process] Adjunto registrado para usuario {user_id}: {file_path}")
                except Exception as e:
                    logging.error(f"[SaaS Process] Error guardando adjunto: {e}")
                    
            if user_text.strip().lower() == "reset":
                import sqlite3, os
                try:
                    conn_chk = sqlite3.connect("checkpoints.sqlite")
                    conn_chk.execute("DELETE FROM checkpoints WHERE thread_id = ?", (str(user_id),))
                    conn_chk.execute("DELETE FROM writes WHERE thread_id = ?", (str(user_id),))
                    conn_chk.commit()
                    conn_chk.close()
                except Exception as e:
                    logging.error(f"[SaaS Reset] Error limpiando checkpoints: {e}")
                
                msg = "✅ Memoria de conversación borrada. Comenzando de cero."
                if platform == 'telegram':
                    await send_telegram_message_saas(client_id, user_id, msg)
                else:
                    await send_whatsapp_message_saas(client_id, user_id, msg)
                return

            from src.database.models import ClientSettings, Message
            import datetime
            db_local = SessionLocal()
            settings = db_local.query(ClientSettings).filter_by(client_id=client_id).first()
            
            # --- Lógica de Bienvenida ---
            if settings and settings.welcome_message_enabled:
                last_bot_msg = db_local.query(Message).filter(
                    Message.client_id == client_id,
                    Message.thread_id == user_id,
                    Message.role == 'bot'
                ).order_by(Message.timestamp.desc()).first()
                
                should_send_welcome = False
                if not last_bot_msg:
                    should_send_welcome = True
                else:
                    threshold_days = settings.welcome_threshold_days or 7
                    if datetime.datetime.utcnow() > last_bot_msg.timestamp + datetime.timedelta(days=threshold_days):
                        should_send_welcome = True
                
                if should_send_welcome:
                    welcome_text = settings.welcome_message_text or "¡Hola! Bienvenid@."
                    welcome_media = settings.welcome_media_path
                    base_url = (settings.webhook_base_url or "").rstrip('/')
                    
                    if welcome_media and base_url:
                        media_path = welcome_media if welcome_media.startswith('/') else f"/{welcome_media}"
                        public_media_url = f"{base_url}{media_path}"
                        import os
                        filename = os.path.basename(media_path)
                        if platform == "whatsapp":
                            await send_whatsapp_file_saas(client_id, user_id, public_media_url, filename, welcome_text)
                        else:
                            await send_telegram_file_saas(client_id, user_id, local_path=media_path.lstrip('/'), caption=welcome_text)
                    else:
                        if platform == "whatsapp":
                            await send_whatsapp_message_saas(client_id, user_id, welcome_text)
                        else:
                            await send_telegram_message_saas(client_id, user_id, welcome_text)
                    
                    log_message(client_id, user_id, "bot", welcome_text + (f" [Media: {welcome_media}]" if welcome_media else ""))

            # --- Lógica de Seguimiento por Inactividad (piezas programadas, solo WhatsApp) ---
            if platform == "whatsapp":
                try:
                    from src.database.models import FollowupContent, FollowupLog
                    today_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")
                    pieces = db_local.query(FollowupContent).filter_by(client_id=client_id, is_active=True).all()
                    active_piece = next((p for p in pieces if p.valid_from <= today_str <= p.valid_until), None)

                    if active_piece:
                        last_user_msg = db_local.query(Message).filter(
                            Message.client_id == client_id,
                            Message.thread_id == user_id,
                            Message.role == 'user'
                        ).order_by(Message.timestamp.desc()).first()

                        if last_user_msg and datetime.datetime.utcnow() >= last_user_msg.timestamp + datetime.timedelta(minutes=active_piece.interval_minutes):
                            already_sent = db_local.query(FollowupLog).filter_by(
                                client_id=client_id, thread_id=user_id, content_id=active_piece.id
                            ).first()

                            if not already_sent:
                                followup_text = active_piece.message_text
                                followup_media = active_piece.media_path
                                base_url = (settings.webhook_base_url or "").rstrip('/') if settings else ""

                                if followup_media and base_url:
                                    media_path = followup_media if followup_media.startswith('/') else f"/{followup_media}"
                                    public_media_url = f"{base_url}{media_path}"
                                    import os
                                    filename = os.path.basename(media_path)
                                    await send_whatsapp_file_saas(client_id, user_id, public_media_url, filename, followup_text)
                                else:
                                    await send_whatsapp_message_saas(client_id, user_id, followup_text)

                                db_local.add(FollowupLog(client_id=client_id, thread_id=user_id, content_id=active_piece.id))
                                db_local.commit()
                                log_message(client_id, user_id, "bot", followup_text + (f" [Media: {followup_media}]" if followup_media else ""))
                except Exception as fe:
                    logging.error(f"[Followup] Error procesando seguimiento por inactividad: {fe}")

            # --- Lógica de Fuera de Horario (OOO) ---
            if settings and settings.out_of_office_enabled:
                if not is_within_working_hours(settings.working_hours):
                    four_hours_ago = datetime.datetime.utcnow() - datetime.timedelta(hours=4)
                    last_ooo = db_local.query(Message).filter(
                        Message.client_id == client_id,
                        Message.thread_id == user_id, Message.role == 'bot',
                        Message.content.ilike(f"%{settings.out_of_office_message[:20]}%"),
                        Message.timestamp >= four_hours_ago
                    ).first()
                    if not last_ooo:
                        ooo_msg = settings.out_of_office_message or "Actualmente estamos fuera de horario. Responderemos a la brevedad."
                        if platform == 'telegram':
                            await send_telegram_message_saas(client_id, user_id, ooo_msg)
                        else:
                            await send_whatsapp_message_saas(client_id, user_id, ooo_msg)
                        log_message(client_id, user_id, "bot", ooo_msg)
            db_local.close()

            # 1. Registrar Mensaje de Usuario
            log_message(client_id, user_id, "user", user_text)
            
            # 2. Configuración para LangGraph (El Muro Multi-Cliente)
            config = {"configurable": {"thread_id": user_id, "client_id": client_id}}
            
            from langchain_core.messages import HumanMessage
            inputs = {
                "messages": [HumanMessage(content=user_text)],
                "client_id": client_id,
                "thread_id": user_id
            }
            
            # 3. Invocar Inteligencia Artificial
            final_state = chatbot_app.invoke(inputs, config=config)
            
            # 4. Enviar Respuesta
            if "messages" in final_state and len(final_state["messages"]) > 0:
                from langchain_core.messages import HumanMessage, AIMessage
                new_ai_texts = []
                for msg in reversed(final_state["messages"]):
                    if isinstance(msg, HumanMessage):
                        break
                    if isinstance(msg, AIMessage) and msg.content:
                        new_ai_texts.append(msg.content)
                
                new_ai_texts.reverse()
                bot_msg = "\n\n".join(new_ai_texts).strip()

                # Entrega determinística del presupuesto en PDF: se genera únicamente
                # cuando process_form_completion confirma un pedido de catálogo, y no
                # depende de que el modelo recuerde escribir el tag por su cuenta.
                pending_pdf_path = final_state.get("pending_pdf_path")
                if pending_pdf_path:
                    bot_msg = f"{bot_msg}\n\n[SEND_PRODUCT_PDF: {pending_pdf_path}]".strip()
                    try:
                        chatbot_app.update_state(config, {"pending_pdf_path": None})
                    except Exception as e:
                        logging.error(f"[SaaS] Error limpiando pending_pdf_path: {e}")

                if bot_msg:
                    # --- LÓGICA DE ENVÍO DE ARCHIVOS AUTOMÁTICO (Tag [SEND_FILE: ...]) ---
                    file_to_send_payloads = []
                    
                    if "[SEND_FILE:" in bot_msg:
                        try:
                            import re, os
                            match_file = re.search(r"\[SEND_FILE:\s*(.*?)\]", bot_msg)
                            if match_file:
                                topic_to_send = match_file.group(1).strip()
                                topic_clean = topic_to_send
                                for ext in ['.pdf', '.png', '.jpg', '.jpeg', '.docx', '.xlsx']:
                                    if topic_clean.lower().endswith(ext):
                                        topic_clean = topic_clean[:-len(ext)].strip()
                                
                                logging.info(f"[SaaS SEND_FILE] Buscando '{topic_clean}' para cliente {client_id}")
                                db_local = SessionLocal()
                                from src.database.models import Knowledge, ClientSettings
                                row_f = db_local.query(Knowledge).filter(Knowledge.client_id == client_id, Knowledge.topic.ilike(f"%{topic_clean}%"), Knowledge.media_path.isnot(None)).first()
                                if row_f:
                                    media_paths = [p.strip() for p in row_f.media_path.split(',') if p.strip()]
                                    settings = db_local.query(ClientSettings).filter_by(client_id=client_id).first()
                                    base_url = (settings.webhook_base_url or "").rstrip('/')
                                    
                                    for mp in media_paths:
                                        media_slash = mp if mp.startswith('/') else f"/{mp}"
                                        public_url = f"{base_url}{media_slash}"
                                        filename = os.path.basename(mp)
                                        
                                        file_to_send_payloads.append({
                                            "public_url": public_url,
                                            "filename": filename,
                                            "media_path": mp
                                        })
                                else:
                                    logging.warning(f"[SaaS SEND_FILE] No se encontró adjunto para '{topic_clean}'")
                                db_local.close()
                                bot_msg = re.sub(r"\[SEND_FILE:.*?\]", "", bot_msg).strip()
                        except Exception as e:
                            logging.error(f"[SaaS SEND_FILE] Error: {e}")

                    if "[SEND_PRODUCT_IMAGE:" in bot_msg:
                        try:
                            import re, os
                            from src.database.models import ClientSettings
                            db_local = SessionLocal()
                            settings = db_local.query(ClientSettings).filter_by(client_id=client_id).first()
                            base_url = (settings.webhook_base_url or "").rstrip('/')
                            
                            matches = re.finditer(r"\[SEND_PRODUCT_IMAGE:\s*(.*?)\]", bot_msg)
                            for match in matches:
                                img_path = match.group(1).strip()
                                if img_path.startswith("http://") or img_path.startswith("https://"):
                                    # Imagen alojada externamente (URL completa cargada en el catálogo)
                                    public_url = img_path
                                else:
                                    media_slash = img_path if img_path.startswith('/') else f"/{img_path}"
                                    public_url = f"{base_url}{media_slash}"
                                filename = os.path.basename(img_path.split("?")[0])

                                file_to_send_payloads.append({
                                    "public_url": public_url,
                                    "filename": filename,
                                    "media_path": img_path
                                })
                            
                            db_local.close()
                            bot_msg = re.sub(r"\[SEND_PRODUCT_IMAGE:.*?\]", "", bot_msg).strip()
                        except Exception as e:
                            logging.error(f"[SaaS SEND_PRODUCT_IMAGE] Error: {e}")

                    if "[SEND_PRODUCT_PDF:" in bot_msg:
                        try:
                            import re, os
                            from src.database.models import ClientSettings
                            db_local = SessionLocal()
                            settings = db_local.query(ClientSettings).filter_by(client_id=client_id).first()
                            base_url = (settings.webhook_base_url or "").rstrip('/')

                            matches = re.finditer(r"\[SEND_PRODUCT_PDF:\s*(.*?)\]", bot_msg)
                            for match in matches:
                                pdf_path = match.group(1).strip()
                                if pdf_path.startswith("http://") or pdf_path.startswith("https://"):
                                    public_url = pdf_path
                                else:
                                    media_slash = pdf_path if pdf_path.startswith('/') else f"/{pdf_path}"
                                    public_url = f"{base_url}{media_slash}"
                                filename = os.path.basename(pdf_path.split("?")[0])

                                file_to_send_payloads.append({
                                    "public_url": public_url,
                                    "filename": filename,
                                    "media_path": pdf_path
                                })

                            db_local.close()
                            bot_msg = re.sub(r"\[SEND_PRODUCT_PDF:.*?\]", "", bot_msg).strip()
                        except Exception as e:
                            logging.error(f"[SaaS SEND_PRODUCT_PDF] Error: {e}")

                    if "[SEND_DOC:" in bot_msg:
                        try:
                            import re, os
                            from src.database.models import ClientSettings
                            from src.database.document_library import get_authorized_document_file
                            db_local = SessionLocal()
                            settings = db_local.query(ClientSettings).filter_by(client_id=client_id).first()
                            base_url = (settings.webhook_base_url or "").rstrip('/')
                            db_local.close()

                            matches = re.finditer(r"\[SEND_DOC:\s*(\d+)\]", bot_msg)
                            for match in matches:
                                doc_id = int(match.group(1))
                                # Verificación server-side obligatoria: nunca confiar en que el LLM
                                # solo emitió el tag para un documento realmente autorizado para este thread.
                                doc_info = get_authorized_document_file(client_id, user_id, doc_id)
                                if doc_info and doc_info.get("source_type") == "gdrive":
                                    from src.database.gdrive_sync import check_file_available, create_download_token
                                    if check_file_available(client_id, doc_info["external_file_id"]):
                                        token = create_download_token(client_id, user_id, doc_id)
                                        stream_url = f"{base_url}/api/gdrive/stream/{token}"
                                        file_to_send_payloads.append({
                                            "public_url": stream_url,
                                            "filename": doc_info["title"],
                                            "media_path": stream_url
                                        })
                                    else:
                                        bot_msg += f"\n\n_(No pude acceder a \"{doc_info['title']}\" en este momento, puede que ya no esté disponible.)_"
                                elif doc_info:
                                    media_slash = doc_info["file_path"] if doc_info["file_path"].startswith('/') else f"/{doc_info['file_path']}"
                                    public_url = f"{base_url}{media_slash}"
                                    filename = os.path.basename(doc_info["file_path"])
                                    file_to_send_payloads.append({
                                        "public_url": public_url,
                                        "filename": filename,
                                        "media_path": doc_info["file_path"]
                                    })
                                else:
                                    logging.warning(f"[SaaS SEND_DOC] Denegado o inexistente doc_id={doc_id} thread={user_id} client={client_id}")

                            bot_msg = re.sub(r"\[SEND_DOC:.*?\]", "", bot_msg).strip()
                        except Exception as e:
                            logging.error(f"[SaaS SEND_DOC] Error: {e}")

                    # 1. Enviar primero el texto (ya limpio sin el tag)
                    wa_id = None
                    if bot_msg:
                        if platform == 'telegram':
                            wa_id = await send_telegram_message_saas(client_id, user_id, bot_msg)
                        else:
                            wa_id = await send_whatsapp_message_saas(client_id, user_id, bot_msg)
                        log_message(client_id, user_id, "bot", bot_msg, whatsapp_id=wa_id)
                        
                    # 2. Enviar después el archivo adjunto
                    for payload in file_to_send_payloads:
                        logging.info(f"[SaaS SEND_FILE] Enviando archivo: {payload['public_url']}")
                        if platform == "whatsapp":
                            await send_whatsapp_file_saas(client_id, user_id, payload["public_url"], payload["filename"], "")
                        else:
                            await send_telegram_file_saas(client_id, user_id, payload["media_path"], "")
                    
            # 5. Calcular Tokens (Simulado para demostración)
            log_token_usage(client_id, user_id, "gpt-4o-mini", 100, 50)
            
        except Exception as e:
            logging.error(f"[SaaS Process] Falla Crítica: {e}")

# ==========================================
# PANEL SUPER ADMIN (MODO DIOS)
# ==========================================

@app.get("/super-admin", response_class=HTMLResponse)
async def super_admin_panel(request: Request, db: Session = Depends(get_db)):
    """Renderiza el panel de control maestro para gestionar inquilinos."""
    # TODO: Añadir protección de login de Super Admin
    clients = db.query(Client).all()
    user_mock = {"full_name": "Súper Admin", "role": "superadmin", "permissions": []}
    return templates.TemplateResponse(request=request, name="admin/super_admin.html", context={
        "clients": clients,
        "user": user_mock
    })

@app.get("/super-admin/impersonate/{client_id}")
async def impersonate_client(client_id: int):
    """Permite al Súper Admin ingresar al panel de un cliente específico."""
    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(key="impersonated_client_id", value=str(client_id), httponly=True)
    return response

@app.get("/super-admin/stop-impersonate")
async def stop_impersonate():
    """Finaliza la sesión impersonada y devuelve al panel Súper Admin."""
    response = RedirectResponse(url="/super-admin", status_code=303)
    response.delete_cookie("impersonated_client_id")
    return response

DEFAULT_SYSTEM_PROMPT = """Eres el asistente virtual oficial de [NOMBRE DE LA EMPRESA]. Tu objetivo es brindar una atención al cliente excepcional, rápida y profesional.

### 🎭 TU IDENTIDAD Y TONO
- Nombre del Asistente: [TU NOMBRE, ej. Sofía / Asistente Virtual]
- Tono de Comunicación: [TONO, ej. Cercano, empático, profesional pero amigable]
- Personalidad: Eres resolutivo y siempre buscas facilitar la vida del cliente. Hablas de forma natural, sin sonar como un robot aburrido.

### 💼 SOBRE LA EMPRESA
- Rubro/Industria: [A QUÉ SE DEDICA LA EMPRESA]
- Qué ofrecemos: [PRODUCTOS O SERVICIOS PRINCIPALES]
- Nuestro valor: [POR QUÉ EL CLIENTE DEBERÍA ELEGIRNOS]

### 🚫 RESTRICCIONES ESTRICTAS (NUNCA DEBES ROMPERLAS)
1. Cero Alucinaciones: NUNCA inventes precios, horarios, direcciones ni servicios que no estén explícitamente en tu base de conocimientos.
2. Derivación Humana: Si el usuario pregunta algo que no sabes, responde: "Por el momento no tengo esa información exacta, ¿te gustaría que un agente humano te contacte?"
3. Fuera de Contexto: Si el usuario te habla de temas que no tienen nada que ver con la empresa (política, clima, etc.), redirige la conversación amablemente hacia nuestros servicios.

### 📝 INSTRUCCIONES DE FORMATO
- Usa emojis con moderación para darle vida al texto (✅, 📅, 🚀, 📍), pero sin saturar.
- Resalta en **negrita** los datos importantes (como requisitos, fechas límite o precios).
- Escribe respuestas cortas y fáciles de leer desde un teléfono móvil. Evita bloques gigantes de texto."""

@app.post("/api/superadmin/clients")
async def create_client(client_data: ClientCreate, db: Session = Depends(get_db)):
    """Crea un nuevo inquilino en la base de datos."""
    try:
        new_client = Client(business_name=client_data.business_name, slug=client_data.slug, status="active")
        db.add(new_client)
        db.commit()
        db.refresh(new_client)
        
        # Crear settings por defecto
        settings = ClientSettings(
            client_id=new_client.id,
            bot_system_prompt=DEFAULT_SYSTEM_PROMPT
        )
        db.add(settings)
        db.commit()
        return {"status": "ok", "client_id": new_client.id}
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=400, content={"error": str(e)})

@app.get("/api/superadmin/clients/{client_id}")
async def get_client(client_id: int, db: Session = Depends(get_db)):
    """Obtiene los detalles de un cliente específico."""
    client = db.query(Client).filter_by(id=client_id).first()
    if not client: return JSONResponse(status_code=404, content={"error": "Not found"})
    
    settings_dict = {}
    if client.settings:
        settings_dict = {
            "whatsapp_instance_id": client.settings.whatsapp_instance_id,
            "whatsapp_token": client.settings.whatsapp_token,
            "bot_system_prompt": client.settings.bot_system_prompt,
            "feat_rag_enabled": client.settings.feat_rag_enabled,
            "feat_human_handoff": client.settings.feat_human_handoff,
            "feat_pdf_export": client.settings.feat_pdf_export,
            "feat_dashboard": getattr(client.settings, 'feat_dashboard', True),
            "feat_history": getattr(client.settings, 'feat_history', True),
            "feat_contacts": getattr(client.settings, 'feat_contacts', True),
            "feat_submissions": getattr(client.settings, 'feat_submissions', True),
            "feat_appointments": getattr(client.settings, 'feat_appointments', True),
            "feat_gaps": getattr(client.settings, 'feat_gaps', True),
            "feat_channels": getattr(client.settings, 'feat_channels', True),
            "feat_config": getattr(client.settings, 'feat_config', True),
            "feat_audit": getattr(client.settings, 'feat_audit', True),
            "feat_catalog": getattr(client.settings, 'feat_catalog', False),
            "feat_catalog_dynamic_fields": getattr(client.settings, 'feat_catalog_dynamic_fields', False),
            "feat_document_library": getattr(client.settings, 'feat_document_library', False),
            "google_oauth_client_id": getattr(client.settings, 'google_oauth_client_id', None) or '',
            "google_oauth_configured": bool(getattr(client.settings, 'google_oauth_client_id', None) and getattr(client.settings, 'google_oauth_client_secret_encrypted', None))
        }
        
    return {
        "id": client.id,
        "business_name": client.business_name,
        "slug": client.slug,
        "status": client.status,
        "settings": settings_dict
    }

@app.put("/api/superadmin/clients/{client_id}/settings")
async def update_client_settings(client_id: int, settings_data: ClientSettingsUpdate, db: Session = Depends(get_db)):
    """Actualiza la configuración y Feature Flags de un inquilino."""
    settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
    if not settings: return JSONResponse(status_code=404, content={"error": "Not found"})
    
    settings.whatsapp_instance_id = settings_data.whatsapp_instance_id
    settings.whatsapp_token = settings_data.whatsapp_token
    settings.bot_system_prompt = settings_data.bot_system_prompt
    settings.feat_rag_enabled = settings_data.feat_rag_enabled
    settings.feat_human_handoff = settings_data.feat_human_handoff
    settings.feat_pdf_export = settings_data.feat_pdf_export
    settings.feat_dashboard = settings_data.feat_dashboard
    settings.feat_history = settings_data.feat_history
    settings.feat_contacts = settings_data.feat_contacts
    settings.feat_submissions = settings_data.feat_submissions
    settings.feat_appointments = settings_data.feat_appointments
    settings.feat_gaps = settings_data.feat_gaps
    settings.feat_channels = settings_data.feat_channels
    settings.feat_config = settings_data.feat_config
    settings.feat_audit = settings_data.feat_audit
    settings.feat_catalog = settings_data.feat_catalog
    settings.feat_catalog_dynamic_fields = settings_data.feat_catalog_dynamic_fields
    settings.feat_document_library = settings_data.feat_document_library

    oauth_client_id = (settings_data.google_oauth_client_id or "").strip()
    if oauth_client_id:
        from src.database.gdrive_sync import encrypt_token
        settings.google_oauth_client_id = oauth_client_id
        oauth_secret = (settings_data.google_oauth_client_secret or "").strip()
        if oauth_secret:
            try:
                settings.google_oauth_client_secret_encrypted = encrypt_token(oauth_secret)
            except RuntimeError as e:
                return JSONResponse(status_code=500, content={"error": f"No se pudo guardar el Client Secret: {e}. Configurá GDRIVE_TOKEN_ENCRYPTION_KEY en el .env del servidor y reiniciá."})

    # Trigger webhook update in Green API
    client = db.query(Client).filter_by(id=client_id).first()

    db.commit()

    if settings.whatsapp_instance_id and settings.whatsapp_token:
        public_base_url = os.getenv("PUBLIC_BASE_URL", "http://TU_DOMINIO_VPS")
        asyncio.create_task(setup_whatsapp_webhook(public_base_url, client.slug))

    return {"status": "ok"}


@app.post("/admin/config/exceptions/add")
async def add_exception(
    request: Request,
    date: str = Form(...),
    start_time: str = Form(None),
    end_time: str = Form(None),
    description: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import SchedulingException
    
    s_time = start_time.strip() if start_time and start_time.strip() else None
    e_time = end_time.strip() if end_time and end_time.strip() else None
    
    new_exc = SchedulingException(
        client_id=target_client_id,
        date=date,
        start_time=s_time,
        end_time=e_time,
        description=description
    )
    db.add(new_exc)
    db.commit()
    return RedirectResponse(url="/admin/config?active_tab=empresa&success=1", status_code=303)


@app.get("/admin/config/exceptions/delete/{exc_id}")
async def delete_exception(
    request: Request,
    exc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    target_client_id, _, _ = get_admin_context(request, current_user, db)
    if target_client_id is None: return RedirectResponse(url="/admin/login")
    
    from src.database.models import SchedulingException
    exc = db.query(SchedulingException).filter_by(client_id=target_client_id, id=exc_id).first()
    if exc:
        db.delete(exc)
        db.commit()
    return RedirectResponse(url="/admin/config?active_tab=empresa&success=1", status_code=303)


async def scheduler_reminders_loop():
    import asyncio
    from datetime import datetime, timedelta
    from src.database.session import SessionLocal
    from src.database.models import Appointment, ClientSettings
    
    logging.info("[Scheduler] Starting automatic scheduling reminder service...")
    
    while True:
        try:
            db = SessionLocal()
            now_utc = datetime.utcnow()
            # Argentina timezone (UTC-3)
            now = now_utc - timedelta(hours=3)
            
            active_apps = db.query(Appointment).filter(
                Appointment.status.in_(["confirmed", "pending"])
            ).all()
            
            for app in active_apps:
                try:
                    app_dt = datetime.strptime(f"{app.date} {app.time}", "%Y-%m-%d %H:%M")
                except Exception:
                    continue
                
                time_diff = app_dt - now
                
                settings = db.query(ClientSettings).filter_by(client_id=app.client_id).first()
                if not settings:
                    continue
                
                # 1. Check 24h reminder
                r_24h_offset = settings.reminder_24h_hours if settings.reminder_24h_hours is not None else 24
                if settings.reminder_24h_enabled and timedelta(hours=r_24h_offset - 2) <= time_diff <= timedelta(hours=r_24h_offset):
                    from src.database.models import AuditLog
                    already_sent = db.query(AuditLog).filter_by(
                        client_id=app.client_id,
                        action="reminder_24h_sent",
                        details=str(app.id)
                    ).first()
                    
                    if not already_sent:
                        template = settings.reminder_24h_template or "Hola {nombre}, te recordamos tu turno del {fecha} a las {hora} hs para {motivo}."
                        message = template.format(
                            nombre=app.client_name or "Cliente",
                            hora=app.time,
                            fecha=app.date,
                            motivo=app.reason or "Trámite"
                        )
                        
                        success = False
                        if settings.telegram_enabled and app.thread_id.isdigit():
                            res = await send_telegram_message_saas(app.client_id, app.thread_id, message)
                            if res:
                                success = True
                        if not success and settings.whatsapp_enabled:
                            wa_id = app.thread_id
                            if not wa_id.endswith("@c.us") and not wa_id.endswith("@us") and wa_id.isdigit():
                                wa_id = f"{wa_id}@c.us"
                            res = await send_whatsapp_message_saas(app.client_id, wa_id, message)
                            if res:
                                success = True
                                
                        log_entry = AuditLog(
                            client_id=app.client_id,
                            user_id="system_scheduler",
                            action="reminder_24h_sent",
                            details=str(app.id)
                        )
                        db.add(log_entry)
                        db.commit()
                        logging.info(f"[Scheduler] Sent 24h reminder for app {app.id}")
                
                # 2. Check 2h reminder
                r_2h_offset = settings.reminder_2h_hours if settings.reminder_2h_hours is not None else 2
                if settings.reminder_2h_enabled and timedelta(minutes=(r_2h_offset * 60) - 30) <= time_diff <= timedelta(hours=r_2h_offset):
                    from src.database.models import AuditLog
                    already_sent = db.query(AuditLog).filter_by(
                        client_id=app.client_id,
                        action="reminder_2h_sent",
                        details=str(app.id)
                    ).first()
                    
                    if not already_sent:
                        template = settings.reminder_2h_template or "Hola {nombre}, te recordamos tu turno de hoy a las {hora} hs para {motivo}."
                        message = template.format(
                            nombre=app.client_name or "Cliente",
                            hora=app.time,
                            fecha=app.date,
                            motivo=app.reason or "Trámite"
                        )
                        
                        success = False
                        if settings.telegram_enabled and app.thread_id.isdigit():
                            res = await send_telegram_message_saas(app.client_id, app.thread_id, message)
                            if res:
                                success = True
                        if not success and settings.whatsapp_enabled:
                            wa_id = app.thread_id
                            if not wa_id.endswith("@c.us") and not wa_id.endswith("@us") and wa_id.isdigit():
                                wa_id = f"{wa_id}@c.us"
                            res = await send_whatsapp_message_saas(app.client_id, wa_id, message)
                            if res:
                                success = True
                                
                        log_entry = AuditLog(
                            client_id=app.client_id,
                            user_id="system_scheduler",
                            action="reminder_2h_sent",
                            details=str(app.id)
                        )
                        db.add(log_entry)
                        db.commit()
                        logging.info(f"[Scheduler] Sent 2h reminder for app {app.id}")
            db.close()
        except Exception as e:
            logging.error(f"[Scheduler] Error in loop: {e}")
        
        await asyncio.sleep(300)


async def gdrive_sync_loop():
    """Sync automático de Google Drive: solo metadata (título/keywords a Chroma), cada 8hs.
    El contenido real siempre se trae fresco al momento de enviar, así que no hace falta
    near-real-time. Mismo patrón defensivo que scheduler_reminders_loop (try/except por
    cliente para que un error no tumbe el loop)."""
    from src.database.gdrive_sync import sync_client_drive

    logging.info("[GDrive] Starting automatic sync service...")

    while True:
        try:
            db = SessionLocal()
            clients = db.query(ClientSettings).filter(
                ClientSettings.gdrive_refresh_token_encrypted.isnot(None),
                ClientSettings.gdrive_needs_reconnect == False
            ).all()
            client_ids = [c.client_id for c in clients]
            db.close()

            for cid in client_ids:
                try:
                    summary = sync_client_drive(cid)
                    logging.info(f"[GDrive] Sync client_id={cid}: {summary}")
                except Exception as e:
                    logging.error(f"[GDrive] Error sincronizando client_id={cid}: {e}")
        except Exception as e:
            logging.error(f"[GDrive] Error in loop: {e}")

        await asyncio.sleep(28800)  # 8 horas


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(scheduler_reminders_loop())
    asyncio.create_task(gdrive_sync_loop())


# ==========================================
# INICIO DE SERVIDOR
# ==========================================

if __name__ == "__main__":
    print("🚀 Iniciando Servidor Multi-Tenant SaaS (ZSG-Bot-iA)")
    # Ejecutamos en el puerto 8001 para no pisar el servidor legacy (8000)
    uvicorn.run("src.main_saas:app", host="0.0.0.0", port=8001, reload=True)
