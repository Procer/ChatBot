import os
import sqlite3
import sys
import traceback
import shutil
import httpx
import json
from fastapi import FastAPI, Request, UploadFile, File, Form, BackgroundTasks, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.concurrency import run_in_threadpool
import secrets
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv
import uvicorn
from datetime import datetime, timedelta
import re
import base64
import mimetypes

# 1. CONFIGURACIÓN ESTRATÉGICA DE RUTAS
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) 
ROOT_DIR = os.path.dirname(BASE_DIR)

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

load_dotenv(os.path.join(ROOT_DIR, ".env"))

# 2. IMPORTACIÓN SEGURA DEL CEREBRO (GRAFO)
try:
    from src.agents.graph import app as chatbot_app, extract_text
    from src.database.whatsapp_manager import WhatsAppManager
    wa_manager = WhatsAppManager()
    print("[INFO] Cerebro del Bot y Gestor WhatsApp cargados correctamente.")
except Exception as e:
    print(f"[ERROR] No se pudo cargar el Cerebro del Bot: {e}")
    traceback.print_exc()
    chatbot_app = None
    wa_manager = None

# 3. CONFIGURACIÓN GREEN-API
GREEN_API_ID = os.getenv("GREEN_API_ID", "").strip('"')
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN", "").strip('"')

# CONFIGURACIÓN EVOLUTION API (LEGACY - COMENTADO)
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").strip('"').rstrip('/')
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "").strip('"')
INSTANCE_NAME = os.getenv("EVOLUTION_INSTANCE_NAME", "").strip('"')

# 4. CONFIGURACIÓN DE ENTORNO
ENVIRONMENT = os.getenv("ENVIRONMENT", "local").lower()
TELEGRAM_MODE = os.getenv("TELEGRAM_MODE", "polling").lower()
print(f"[*] ENTORNO: {ENVIRONMENT.upper()} | TELEGRAM: {TELEGRAM_MODE.upper()}")

# 5. INICIALIZACIÓN DE LA APLICACIÓN
app = FastAPI(title="ZSG-Bot-iA Admin")
app.mount("/static", StaticFiles(directory=os.path.join(ROOT_DIR, "static")), name="static")
app.mount("/uploads", StaticFiles(directory=os.path.join(ROOT_DIR, "uploads")), name="uploads")
templates = Jinja2Templates(directory=os.path.join(ROOT_DIR, "templates"))


@app.get("/acceso", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None):
    return templates.TemplateResponse(request=request, name="admin/login.html", context={"error": error})

@app.post("/acceso")
async def login_action(username: str = Form(...), password: str = Form(...)):
    admin_user = os.getenv("ADMIN_USER", "admin")
    admin_pass = os.getenv("ADMIN_PASSWORD", "admin")
    if username == admin_user and password == admin_pass:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        response = RedirectResponse(url="/admin", status_code=303)
        response.set_cookie(key="admin_session", value=token, httponly=True, max_age=86400 * 7)
        return response
    return RedirectResponse(url="/acceso?error=Credenciales+incorrectas", status_code=303)

@app.get("/logout")
async def logout_action():
    response = RedirectResponse(url="/acceso", status_code=303)
    response.delete_cookie("admin_session")
    return response

# --- AUTENTICACIÓN ---
# --- AUTENTICACIÓN PERSONALIZADA ---
from fastapi.responses import RedirectResponse

def verify_admin(request: Request):
    token = request.cookies.get("admin_session")
    expected_token = base64.b64encode(f"{os.getenv('ADMIN_USER', 'admin')}:{os.getenv('ADMIN_PASSWORD', 'admin')}".encode()).decode()
    if token != expected_token:
        # Si no es una petición de API (JSON), redirigir a login
        if "application/json" not in request.headers.get("accept", ""):
            raise HTTPException(status_code=303, detail="Redireccionando a acceso", headers={"Location": "/acceso"})
        raise HTTPException(status_code=401, detail="No autorizado")
    return token

# --- PROMPTS POR DEFECTO ---
MASTER_PROMPT = """### 🎭 PERSONALIDAD Y TONO:
- Sos el asistente virtual de [NOMBRE DE LA EMPRESA].
- Tu tono debe ser ARGENTINO (Voseo: che, decime, pasame, cómo andás).
- Saluda siempre de forma amable y CÁLIDA, como si estuvieras atendiendo en el mostrador de la escribanía.
- **PROHIBICIÓN ABSOLUTA:** No uses frases como "Tengo tu nombre registrado", "Procederemos a recolectar datos" o "Continuaremos con el trámite". Suenan robóticas y frías.
- Hablá con fluidez. Si ya sabés el nombre, decí: "¡Buenísimo [Nombre]! Ya te tengo agendado/a." o "Dale, [Nombre], anotado."

### 👤 MANEJO DEL CLIENTE:
- **PRIORIDAD:** Responder siempre a la duda del usuario de inmediato.
- Si no conocés su nombre, pedilo de forma muy natural: "Por cierto, ¿cómo es tu nombre? Así ya te agendo acá en la escribanía."
- NO esperes a tener el nombre para responder. La respuesta va primero.

### 🛠️ REGLAS DE OPERACIÓN:
1. **CONOCIMIENTO:** Responde solo basado en el CONOCIMIENTO OFICIAL cargado.
2. **GAPS:** Si no sabes algo, decí: "Che, mirá, justo de eso no tengo la info acá a mano. Pero si querés consulto y te aviso." (Pero usá la herramienta de gaps internamente).
3. **TRÁMITES:** Para iniciar un trámite, no preguntes formalmente si "desea recolectar datos". Decí algo como: "Si querés, podemos ir adelantando y te pido los datos ahora mismo, ¿te parece?".

### 📉 LÍMITES DE CONOCIMIENTO (GAPS):
- Si el usuario te pregunta por algo que NO está en el conocimiento, respondé que no tenés la info por ahora de forma amable y natural.
"""

GENERIC_PROMPT = MASTER_PROMPT

# --- BASE DE DATOS DE CONFIGURACIÓN ---
def init_db():
    db_path = os.path.join(ROOT_DIR, "settings.sqlite")
    conn = sqlite3.connect(db_path, timeout=30)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS knowledge (id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT, content TEXT, category TEXT, has_form INTEGER DEFAULT 0, form_fields TEXT, storage_dest TEXT, allow_scheduling INTEGER DEFAULT 0, interactive_options TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS external_services (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS bot_pauses (user_id TEXT PRIMARY KEY, paused_until TIMESTAMP)")
    cursor.execute("CREATE TABLE IF NOT EXISTS chat_notes (thread_id TEXT PRIMARY KEY, notes TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS knowledge_gaps (id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT UNIQUE, frequency INTEGER DEFAULT 1, status TEXT DEFAULT 'pending')")
    cursor.execute("CREATE TABLE IF NOT EXISTS attachments (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT, file_path TEXT, file_name TEXT, file_type TEXT, context TEXT, form_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute("CREATE TABLE IF NOT EXISTS form_submissions (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT, topic TEXT, data TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute("CREATE TABLE IF NOT EXISTS appointments (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT, date TEXT, time TEXT, service TEXT, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute("CREATE TABLE IF NOT EXISTS proceedings (id INTEGER PRIMARY KEY AUTOINCREMENT, tracking_number TEXT, client_name TEXT, topic TEXT, status TEXT, notes TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute("CREATE TABLE IF NOT EXISTS user_profiles (user_id TEXT PRIMARY KEY, full_name TEXT, avatar_url TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    
    # Migración segura
    try: cursor.execute("ALTER TABLE user_profiles ADD COLUMN avatar_url TEXT")
    except: pass
    cursor.execute("CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, action TEXT, details TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    
    # Migración segura para analytics.sqlite
    try:
        db_a = sqlite3.connect(os.path.join(ROOT_DIR, "analytics.sqlite"))
        cursor_a = db_a.cursor()
        cursor_a.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT,
            role TEXT,
            content TEXT,
            whatsapp_id TEXT,
            status TEXT DEFAULT 'sent',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        try: cursor_a.execute("ALTER TABLE messages ADD COLUMN whatsapp_id TEXT")
        except: pass
        try: cursor_a.execute("ALTER TABLE messages ADD COLUMN status TEXT DEFAULT 'sent'")
        except: pass
        db_a.commit(); db_a.close()
    except: pass

    # Migración para settings.sqlite (Knowledge)
    try:
        cursor.execute("ALTER TABLE knowledge ADD COLUMN allow_scheduling INTEGER DEFAULT 0")
    except: pass
    try:
        cursor.execute("ALTER TABLE knowledge ADD COLUMN interactive_options TEXT")
    except: pass
    
    defaults = [
        ('bot_name', 'Zárate IA'), ('bot_tone', 'argentino'),
        ('system_prompt', MASTER_PROMPT),
        ('company_name', 'Zárate System Group'), ('company_phone', '(03546) 420248'),
        ('company_email', 'contacto@zaratesystem.com.ar'), ('company_website', 'www.zaratesystem.com.ar'),
        ('company_address', 'Buenos Aires, Argentina'),
        ('whatsapp_enabled', '1'), ('whatsapp_instance_id', ''), ('whatsapp_api_token', ''),
        ('telegram_enabled', '0'), ('telegram_token', ''),
        ('webhook_base_url', ''), ('test_mode_enabled', '0'), ('test_numbers', ''),
        ('welcome_message_enabled', '0'), ('welcome_message_text', '¡Hola! Bienvenid@ de nuevo.'),
        ('welcome_threshold_days', '7'),
        ('out_of_office_enabled', '0'),
        ('out_of_office_message', 'Hola! En este momento estamos fuera de nuestro horario comercial. Te responderemos en cuanto volvamos. Gracias!')
    ]
    cursor.executemany("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", defaults)
    cursor.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('system_prompt', ?)", (MASTER_PROMPT,))
    conn.commit()
    conn.close()

def get_db_settings():
    db_path = os.path.join(ROOT_DIR, "settings.sqlite")
    return sqlite3.connect(db_path, timeout=30)

# Inicializar base de datos una sola vez
init_db()

def is_within_working_hours(working_hours_str: str) -> bool:
    """
    Intenta determinar si el momento actual está dentro del horario comercial.
    Soporta formatos comunes como 'Lunes a Viernes 09:00 - 18:00' o listas por día.
    """
    if not working_hours_str or "24/7" in working_hours_str.lower():
        return True
    
    try:
        from datetime import datetime
        import re
        
        now = datetime.now()
        day_names = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
        today_name = day_names[now.weekday()]
        
        # 1. Caso: Lista por días (Ej: "Lunes: 9:30 AM - 5:30 PM")
        # Buscamos el día actual en el texto
        pattern = rf"{today_name}.*?(\d{{1,2}}):?(\d{{0,2}})\s*(am|pm)?\s*-\s*(\d{{1,2}}):?(\d{{0,2}})\s*(am|pm)?"
        match = re.search(pattern, working_hours_str.lower())
        
        if match:
            h1, m1, p1, h2, m2, p2 = match.groups()
            h1, h2 = int(h1), int(h2)
            m1 = int(m1) if m1 else 0
            m2 = int(m2) if m2 else 0
            
            # Ajuste AM/PM
            if p1 == 'pm' and h1 < 12: h1 += 12
            if p1 == 'am' and h1 == 12: h1 = 0
            if p2 == 'pm' and h2 < 12: h2 += 12
            if p2 == 'am' and h2 == 12: h2 = 0
            
            start_time = now.replace(hour=h1, minute=m1, second=0, microsecond=0)
            end_time = now.replace(hour=h2, minute=m2, second=0, microsecond=0)
            
            # Manejo de horarios que cruzan la medianoche (ej: 22:00 - 06:00)
            if end_time < start_time:
                return now >= start_time or now <= end_time
            
            return start_time <= now <= end_time
            
        # 2. Caso: Rango general (Ej: "Lunes a Viernes 09:00 - 18:00")
        if "a" in working_hours_str.lower() or "to" in working_hours_str.lower():
            # Si hoy es Sábado o Domingo y dice "Lunes a Viernes", retornamos False
            is_weekend = now.weekday() >= 5
            if is_weekend and ("lunes a viernes" in working_hours_str.lower() or "mon to fri" in working_hours_str.lower()):
                return False
                
            match_range = re.search(r"(\d{1,2}):?(\d{0,2}).*?(\d{1,2}):?(\d{0,2})", working_hours_str)
            if match_range:
                h1, m1, h2, m2 = match_range.groups()
                h1, m1, h2, m2 = int(h1), int(m1 or 0), int(h2), int(m2 or 0)
                start_time = now.replace(hour=h1, minute=m1, second=0, microsecond=0)
                end_time = now.replace(hour=h2, minute=m2, second=0, microsecond=0)
                return start_time <= now <= end_time

        # Si hay algo como "Sábado: Cerrado" y hoy es sábado
        if f"{today_name}: cerrado" in working_hours_str.lower():
            return False

        # Por defecto, si el texto es muy complejo o no coincide, asumimos abierto para no bloquear
        return True
    except Exception as e:
        logging.error(f"Error parseando horario: {e}")
        return True

# --- FUNCIONES DE ENVÍO ---
async def set_whatsapp_presence(chat_id: str, presence: str = "composing"):
    db = get_db_settings(); cursor = db.cursor()
    cursor.execute("SELECT key, value FROM config WHERE key IN ('whatsapp_instance_id', 'whatsapp_api_token')")
    cfg = dict(cursor.fetchall()); db.close()
    g_id = cfg.get('whatsapp_instance_id') or os.getenv("GREEN_API_ID", "").strip('"')
    g_token = cfg.get('whatsapp_api_token') or os.getenv("GREEN_API_TOKEN", "").strip('"')
    if not g_id or not g_token: return
    url = f"https://api.green-api.com/waInstance{g_id}/setChatPresence/{g_token}"
    payload = {"chatId": chat_id, "presence": presence}
    async with httpx.AsyncClient() as client:
        try: await client.post(url, json=payload, timeout=5.0)
        except: pass

async def send_whatsapp_message(number: str, text: str):
    db = get_db_settings(); cursor = db.cursor()
    cursor.execute("SELECT key, value FROM config WHERE key IN ('whatsapp_enabled', 'whatsapp_instance_id', 'whatsapp_api_token')")
    cfg = dict(cursor.fetchall()); db.close()
    if cfg.get('whatsapp_enabled') == '0': return None
    g_id = cfg.get('whatsapp_instance_id') or os.getenv("GREEN_API_ID", "").strip('"')
    g_token = cfg.get('whatsapp_api_token') or os.getenv("GREEN_API_TOKEN", "").strip('"')
    if not g_id or not g_token: return None
    clean_number = str(number).split("@")[0]
    chat_id = f"{clean_number}@c.us"
    await set_whatsapp_presence(chat_id, "composing")
    import asyncio
    await asyncio.sleep(1.0)
    url = f"https://api.green-api.com/waInstance{g_id}/sendMessage/{g_token}"
    payload = {"chatId": chat_id, "message": text}
    async with httpx.AsyncClient() as client:
        try: 
            r = await client.post(url, json=payload, timeout=20.0)
            if r.status_code == 200: return r.json().get("idMessage")
        except Exception as e:
            logging.error(f"[GREEN-API] Error enviando mensaje: {e}")
    return None

    async with httpx.AsyncClient() as client:
        try: 
            r = await client.post(url, json=payload, timeout=20.0)
            logging.info(f"[GREEN-API] Message sent to {chat_id}: {r.status_code}")
        except Exception as e:
            logging.error(f"[GREEN-API] Error enviando mensaje: {e}")

async def send_whatsapp_file(number: str, file_url: str, filename: str, caption: str = ""):
    db = get_db_settings(); cursor = db.cursor()
    cursor.execute("SELECT key, value FROM config WHERE key IN ('whatsapp_enabled', 'whatsapp_instance_id', 'whatsapp_api_token')")
    cfg = dict(cursor.fetchall()); db.close()
    if cfg.get('whatsapp_enabled') == '0': return

    g_id = cfg.get('whatsapp_instance_id') or os.getenv("GREEN_API_ID", "").strip('"')
    g_token = cfg.get('whatsapp_api_token') or os.getenv("GREEN_API_TOKEN", "").strip('"')
    if not g_id or not g_token: return

    clean_number = number.split("@")[0]
    chat_id = f"{clean_number}@c.us"
    url = f"https://api.green-api.com/waInstance{g_id}/sendFileByUrl/{g_token}"
    payload = {"chatId": chat_id, "urlFile": file_url, "fileName": filename, "caption": caption}

    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload, timeout=30.0)
            logging.info(f"[GREEN-API] File sent to {chat_id}: {r.status_code}")
        except Exception as e:
            logging.error(f"[GREEN-API] Error enviando archivo: {e}")

async def send_whatsapp_interactive(number: str, text: str, options: list):
    db = get_db_settings(); cursor = db.cursor()
    cursor.execute("SELECT key, value FROM config WHERE key IN ('whatsapp_enabled', 'whatsapp_instance_id', 'whatsapp_api_token')")
    cfg = dict(cursor.fetchall()); db.close()
    if cfg.get('whatsapp_enabled') == '0': return

    g_id = cfg.get('whatsapp_instance_id') or os.getenv("GREEN_API_ID", "").strip('"')
    g_token = cfg.get('whatsapp_api_token') or os.getenv("GREEN_API_TOKEN", "").strip('"')
    if not g_id or not g_token: return

    clean_number = number.split("@")[0]
    chat_id = f"{clean_number}@c.us"
    
    # 1. BOTONES (Hasta 3 opciones)
    if 1 <= len(options) <= 3:
        url = f"https://api.green-api.com/waInstance{g_id}/sendButtons/{g_token}"
        buttons = []
        for i, opt in enumerate(options):
            buttons.append({"buttonId": f"btn_{i}", "buttonText": opt, "type": "quick_reply"})
        payload = {"chatId": chat_id, "message": text, "buttons": buttons}
    
    # 2. LISTAS (De 4 a 10 opciones)
    else:
        url = f"https://api.green-api.com/waInstance{g_id}/sendListMessage/{g_token}"
        rows = []
        for i, opt in enumerate(options):
            rows.append({"rowId": f"row_{i}", "title": opt})
        payload = {
            "chatId": chat_id,
            "message": text,
            "title": "Seleccionar opción",
            "buttonText": "Ver opciones",
            "sections": [{"title": "Sugerencias", "rows": rows}]
        }

    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload, timeout=30.0)
            if r.status_code == 200:
                return r.json().get("idMessage")
        except Exception as e:
            logging.error(f"[GREEN-API] Error enviando interactivo: {e}")
    return None

async def send_whatsapp_poll(number: str, question: str, options: list):
    db = get_db_settings(); cursor = db.cursor()
    cursor.execute("SELECT key, value FROM config WHERE key IN ('whatsapp_enabled', 'whatsapp_instance_id', 'whatsapp_api_token')")
    cfg = dict(cursor.fetchall()); db.close()
    if cfg.get('whatsapp_enabled') == '0': return

    g_id = cfg.get('whatsapp_instance_id') or os.getenv("GREEN_API_ID", "").strip('"')
    g_token = cfg.get('whatsapp_api_token') or os.getenv("GREEN_API_TOKEN", "").strip('"')
    if not g_id or not g_token: return

    clean_number = number.split("@")[0]
    chat_id = f"{clean_number}@c.us"
    url = f"https://api.green-api.com/waInstance{g_id}/sendPoll/{g_token}"
    
    poll_options = [{"optionName": opt} for opt in options]
    payload = {"chatId": chat_id, "message": question, "options": poll_options}

    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload, timeout=30.0)
            logging.info(f"[GREEN-API] Poll sent to {chat_id}: {r.status_code}")
        except Exception as e:
            logging.error(f"[GREEN-API] Error enviando encuesta: {e}")

async def send_telegram_message(chat_id: str, text: str):
    db = get_db_settings(); cursor = db.cursor()
    cursor.execute("SELECT value FROM config WHERE key = 'telegram_token'")
    row_t = cursor.fetchone(); token = row_t[0] if row_t else None
    cursor.execute("SELECT value FROM config WHERE key = 'telegram_enabled'")
    row_e = cursor.fetchone(); enabled = row_e[0] if row_e else '0'
    db.close()
    
    if not token or enabled == '0': return

    if ENVIRONMENT == 'local':
        text = f"📍 [LOCAL]\n{text}"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    async with httpx.AsyncClient() as client:
        try: 
            r = await client.post(url, json=payload, timeout=20.0)
            logging.info(f"[TELEGRAM] Message sent: {r.status_code}")
        except Exception as e:
            logging.error(f"[TELEGRAM] Error: {e}")

async def send_telegram_file(chat_id: str, file_url: str, caption: str = ""):
    db = get_db_settings(); cursor = db.cursor()
    cursor.execute("SELECT value FROM config WHERE key = 'telegram_token'")
    row_t = cursor.fetchone(); token = row_t[0] if row_t else None
    cursor.execute("SELECT value FROM config WHERE key = 'telegram_enabled'")
    row_e = cursor.fetchone(); enabled = row_e[0] if row_e else '0'
    db.close()
    if not token or enabled == '0': return

    method = "sendDocument"
    ext = os.path.splitext(file_url)[1].lower()
    if ext in ['.jpg', '.jpeg', '.png']: method = "sendPhoto"
    elif ext in ['.mp4', '.mov']: method = "sendVideo"

    url = f"https://api.telegram.org/bot{token}/{method}"
    payload = {"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"}
    
    key_file = "document"
    if method == "sendPhoto": key_file = "photo"
    elif method == "sendVideo": key_file = "video"
    payload[key_file] = file_url

    async with httpx.AsyncClient() as client:
        try: 
            r = await client.post(url, json=payload, timeout=30.0)
            logging.info(f"[TELEGRAM] File sent: {r.status_code}")
        except Exception as e: 
            logging.error(f"[TELEGRAM] Error enviando archivo: {e}")

# --- AUTO-CONFIGURACIÓN ---
async def setup_telegram_webhook(token: str, base_url: str):
    if not token or not base_url: return False
    webhook_url = f"{base_url}/webhook/telegram"
    api_url = f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(api_url)
            return r.json().get("ok", False)
        except Exception as e:
            logging.error(f"Error retornado False: {e}")
            return False

async def setup_whatsapp_webhook(base_url: str):
    db = get_db_settings(); cursor = db.cursor()
    cursor.execute("SELECT key, value FROM config WHERE key IN ('whatsapp_instance_id', 'whatsapp_api_token')")
    cfg = dict(cursor.fetchall())
    db.close()
    
    g_id = cfg.get('whatsapp_instance_id') or os.getenv("GREEN_API_ID", "").strip('"')
    g_token = cfg.get('whatsapp_api_token') or os.getenv("GREEN_API_TOKEN", "").strip('"')
    
    if not g_id or not g_token: return False

    url = f"https://api.green-api.com/waInstance{g_id}/setSettings/{g_token}"
    payload = {
        "webhookUrl": f"{base_url}/webhook/greenapi",
        "outgoingMessageWebhook": "yes",
        "stateInstanceWebhook": "yes",
        "incomingMessageWebhook": "yes"
    }
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload)
            logging.info(f"[GREEN-API] Webhook setup: {r.status_code} - {r.text}")
            return r.status_code == 200
        except Exception as e:
            logging.error(f"[GREEN-API] Error setting webhook: {e}")
            return False

# --- PROXY EVOLUTION API ---
async def get_whatsapp_status():
    db = get_db_settings(); cursor = db.cursor()
    cursor.execute("SELECT key, value FROM config WHERE key IN ('whatsapp_instance_id', 'whatsapp_api_token')")
    cfg = dict(cursor.fetchall())
    db.close()
    
    g_id = cfg.get('whatsapp_instance_id') or os.getenv("GREEN_API_ID", "").strip('"')
    g_token = cfg.get('whatsapp_api_token') or os.getenv("GREEN_API_TOKEN", "").strip('"')

    if not g_id or not g_token: return {"status": "disconnected", "error": "Faltan credenciales Green-API"}
    
    url = f"https://api.green-api.com/waInstance{g_id}/getStateInstance/{g_token}"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url)
            if r.status_code == 200:
                state = r.json().get("stateInstance")
                return {"status": "open" if state == "authorized" else "disconnected"}
            return {"status": "disconnected"}
        except: return {"status": "disconnected"}

async def get_whatsapp_qr():
    db = get_db_settings(); cursor = db.cursor()
    cursor.execute("SELECT key, value FROM config WHERE key IN ('whatsapp_instance_id', 'whatsapp_api_token')")
    cfg = dict(cursor.fetchall())
    db.close()
    
    g_id = cfg.get('whatsapp_instance_id') or os.getenv("GREEN_API_ID", "").strip('"')
    g_token = cfg.get('whatsapp_api_token') or os.getenv("GREEN_API_TOKEN", "").strip('"')

    if not g_id or not g_token: return {"status": "error", "message": "Faltan credenciales Green-API"}
    
    url = f"https://api.green-api.com/waInstance{g_id}/qr/{g_token}"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                if data.get("type") == "qrCode":
                    return {"status": "qr", "base64": data.get("message")}
                return {"status": "already_connected"}
            return {"status": "error", "message": f"Error Green-API: {r.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

async def whatsapp_logout_api():
    db = get_db_settings(); cursor = db.cursor()
    cursor.execute("SELECT key, value FROM config WHERE key IN ('whatsapp_instance_id', 'whatsapp_api_token')")
    cfg = dict(cursor.fetchall())
    db.close()
    
    g_id = cfg.get('whatsapp_instance_id') or os.getenv("GREEN_API_ID", "").strip('"')
    g_token = cfg.get('whatsapp_api_token') or os.getenv("GREEN_API_TOKEN", "").strip('"')

    if not g_id or not g_token: return False
    
    url = f"https://api.green-api.com/waInstance{g_id}/logout/{g_token}"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url)
            return r.status_code == 200
        except: return False

async def download_attachment(url: str, filename: str):
    uploads_dir = os.path.join(ROOT_DIR, "uploads")
    if not os.path.exists(uploads_dir): os.makedirs(uploads_dir)
    
    file_path = os.path.join(uploads_dir, filename)
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, timeout=30.0)
            if r.status_code == 200:
                with open(file_path, "wb") as f:
                    f.write(r.content)
                return f"/uploads/{filename}"
        except Exception as e:
            logging.error(f"Error descargando archivo: {e}")
    return None

# --- WEBHOOKS ---

@app.post("/webhook/greenapi")
async def green_api_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        type_webhook = data.get("typeWebhook")
        
        # 1. ESTADOS DE MENSAJE (Trazabilidad)
        if type_webhook == 'statusMessage':
            msg_id = data.get('idMessage')
            status = data.get('status') # delivered, read, sent
            if msg_id and status:
                conn_s = sqlite3.connect(os.path.join(ROOT_DIR, "analytics.sqlite"))
                conn_s.execute("UPDATE messages SET status = ? WHERE whatsapp_id = ?", (status, msg_id))
                conn_s.commit(); conn_s.close()
                logging.info(f"[GREEN-API] Status Update: {msg_id} -> {status}")
            return {"status": "ok"}
            
        if type_webhook != 'incomingMessageReceived':
            return JSONResponse({"status": "ignored"})
            
        # Captura de datos del remitente
        sender_data = data.get('senderData', {})
        chat_id = sender_data.get('chatId')
        sender_name = sender_data.get('senderName')
        
        if chat_id and sender_name:
            try:
                conn_u = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
                conn_u.execute("INSERT INTO user_profiles (user_id, full_name) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET full_name = CASE WHEN full_name IS NULL OR full_name = user_id THEN excluded.full_name ELSE full_name END", (chat_id, sender_name))
                conn_u.commit(); conn_u.close()
            except: pass
            
        message_data = data.get("messageData", {})
        type_msg = message_data.get("typeMessage")
        
        user_text = ""
        attachment = None
        if type_msg == "textMessage":
            user_text = message_data.get("textMessageData", {}).get("textMessage", "")
        elif type_msg == "extendedTextMessage":
            user_text = message_data.get("extendedTextMessageData", {}).get("text", "")
        elif type_msg in ["imageMessage", "videoMessage", "documentMessage", "audioMessage"]:
            media_data = message_data.get(type_msg, {})
            user_text = media_data.get("caption", "")
            attachment = {
                "url": media_data.get("downloadUrl"),
                "file_name": media_data.get("fileName", f"archivo_{int(datetime.now().timestamp())}"),
                "type": type_msg.replace("Message", ""),
                "mime": media_data.get("mimeType")
            }
            if not media_data.get("fileName"):
                ext = mimetypes.guess_extension(attachment["mime"]) or ".file"
                attachment["file_name"] += ext
        elif type_msg == "locationMessage":
            loc = message_data.get("locationMessageData", {})
            user_text = f"📍 Ubicación: {loc.get('name', 'Ver mapa')}\nhttps://www.google.com/maps?q={loc.get('latitude')},{loc.get('longitude')}"
        elif type_msg == "contactMessage":
            cont = message_data.get("contactMessageData", {})
            user_text = f"👤 Contacto: {cont.get('displayName')}"
        else:
            return JSONResponse({"status": "type_not_handled"})
            
        user_id = data.get("senderData", {}).get("chatId", "")
        
        logging.info(f"[DEBUG-WA] Webhook Recibido | Tipo: {type_webhook} | De: {user_id} | Msg: {type_msg}")

        if not user_text or not user_id:
            logging.warning(f"[DEBUG-WA] Datos incompletos. ID: {user_id}, Texto: {user_text}")
            return JSONResponse({"status": "incomplete_data"})

        logging.info(f"[GREEN-API] Mensaje procesable de {user_id}: {user_text}")
        
        background_tasks.add_task(process_bot_response, user_id, user_text, "whatsapp", attachment)
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logging.error(f"[GREEN-API WEBHOOK] Error: {e}")
        return JSONResponse({"status": "error"})

@app.post("/webhook")
async def evolution_webhook(request: Request, background_tasks: BackgroundTasks):
    # Mantener para retrocompatibilidad por si acaso, pero ya no se usará
    return JSONResponse({"status": "legacy_webhook_ignored"})

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        message = data.get("message")
        if not message: return JSONResponse({"status": "no_message"})
        chat_id = str(message.get("chat", {}).get("id"))
        user_text = message.get("text")
        # Procesamiento básico para adjuntos en Telegram
        attachment = None
        if "document" in message:
            file_id = message["document"]["file_id"]
            db = get_db_settings(); cursor = db.cursor()
            cursor.execute("SELECT value FROM config WHERE key = 'telegram_token'")
            token = cursor.fetchone()[0]
            db.close()
            attachment = await download_telegram_media(file_id, token)
        
        background_tasks.add_task(process_bot_response, chat_id, user_text, "telegram", attachment)
        return JSONResponse({"status": "ok"})
    except: return JSONResponse({"status": "error"})

async def process_bot_response(user_id: str, user_text: str, platform: str, attachment_data: dict = None):
    print(f"\n[LOCAL-PROCESS] Iniciando respuesta para {user_id} en {platform}...")
    
    # --- FILTRO MODO PRUEBAS ---
    try:
        conn_t = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
        cursor_t = conn_t.cursor()
        cursor_t.execute("SELECT value FROM config WHERE key = 'test_mode_enabled'")
        row_test = cursor_t.fetchone()
        test_mode = row_test[0] == '1' if row_test else False
        
        if test_mode:
            cursor_t.execute("SELECT value FROM config WHERE key = 'test_numbers'")
            row_numbers = cursor_t.fetchone()
            whitelist_raw = row_numbers[0] if row_numbers else ""
            whitelist = [n.strip() for n in whitelist_raw.split(",") if n.strip()]
            
            # Limpiar ID (quitar @c.us, etc)
            clean_id = "".join(filter(str.isdigit, str(user_id).split("@")[0]))
            
            is_whitelisted = False
            for n in whitelist:
                n_clean = "".join(filter(str.isdigit, n))
                if not n_clean: continue
                if clean_id.endswith(n_clean) or n_clean.endswith(clean_id):
                    if len(n_clean) >= 8 or n_clean == clean_id:
                        is_whitelisted = True
                        break
            
            if not is_whitelisted:
                logging.warning(f"[TEST MODE] BLOQUEADO: {user_id} ({platform}). No coincide con ninguno de: {whitelist}")
                conn_t.close()
                return
            else:
                logging.info(f"[TEST MODE] PERMITIDO: {user_id} coincide con la whitelist.")
        conn_t.close()
    except Exception as e:
        logging.error(f"[TEST MODE] Error verificando whitelist: {e}")

    if not chatbot_app:
        print("[DEBUG] chatbot_app is NONE. IA will not respond.")
        return
    try:
        from src.database.analytics_engine import log_token_usage, log_message
        
        # 0. Lógica de Mensaje de Bienvenida (Conversación nueva o antigua)
        conn_w = get_db_settings()
        cursor_w = conn_w.cursor()
        cursor_w.execute("SELECT key, value FROM config WHERE key IN ('welcome_message_enabled', 'welcome_message_text', 'welcome_threshold_days', 'welcome_media_path', 'webhook_base_url')")
        w_config = dict(cursor_w.fetchall())
        conn_w.close()

        if w_config.get('welcome_message_enabled') == '1':
            conn_a = sqlite3.connect(os.path.join(ROOT_DIR, "analytics.sqlite"))
            cursor_a = conn_a.cursor()
            cursor_a.execute("SELECT timestamp FROM messages WHERE CAST(thread_id AS TEXT) = ? AND role = 'bot' ORDER BY timestamp DESC LIMIT 1", (str(user_id),))
            last_bot_msg = cursor_a.fetchone()
            conn_a.close()

            should_send_welcome = False
            if not last_bot_msg:
                should_send_welcome = True
            else:
                try:
                    last_ts = datetime.fromisoformat(last_bot_msg[0])
                    threshold_days = int(w_config.get('welcome_threshold_days', 7))
                    if datetime.now() > last_ts + timedelta(days=threshold_days):
                        should_send_welcome = True
                except: pass

            if should_send_welcome:
                welcome_text = w_config.get('welcome_message_text', '¡Hola! Bienvenid@.')
                welcome_media = w_config.get('welcome_media_path')
                base_url = w_config.get('webhook_base_url', '').rstrip('/')
                
                if welcome_media and base_url:
                    public_media_url = f"{base_url}{welcome_media}"
                    filename = os.path.basename(welcome_media)
                    if platform == "whatsapp": 
                        await send_whatsapp_file(user_id, public_media_url, filename, welcome_text)
                    else: 
                        await send_telegram_file(user_id, public_media_url, welcome_text)
                else:
                    if platform == "whatsapp": await send_whatsapp_message(user_id, welcome_text)
                    else: await send_telegram_message(user_id, welcome_text)
                
                log_message(user_id, "bot", welcome_text + (f" [Media: {welcome_media}]" if welcome_media else ""))
        
        # 0.1 Lógica de Fuera de Horario
        conn_ooo = get_db_settings()
        cursor_ooo = conn_ooo.cursor()
        cursor_ooo.execute("SELECT key, value FROM config WHERE key IN ('out_of_office_enabled', 'out_of_office_message')")
        ooo_config = dict(cursor_ooo.fetchall())
        cursor_ooo.execute("SELECT value FROM external_services WHERE key = 'working_hours'")
        w_hours_row = cursor_ooo.fetchone()
        w_hours_str = w_hours_row[0] if w_hours_row else ""
        conn_ooo.close()

        if ooo_config.get('out_of_office_enabled') == '1':
            if not is_within_working_hours(w_hours_str):
                # Verificar si ya enviamos el mensaje de OOO recientemente para no spamear
                conn_a = sqlite3.connect(os.path.join(ROOT_DIR, "analytics.sqlite"))
                cursor_a = conn_a.cursor()
                # Si el último mensaje del bot fue hace menos de 4 horas y contenía el texto de OOO, no lo repetimos
                ooo_text = ooo_config.get('out_of_office_message', 'Estamos fuera de horario.')
                cursor_a.execute("SELECT timestamp FROM messages WHERE thread_id = ? AND role = 'bot' AND content LIKE ? ORDER BY timestamp DESC LIMIT 1", (user_id, f"%{ooo_text[:20]}%"))
                last_ooo = cursor_a.fetchone()
                conn_a.close()
                
                send_ooo = True
                if last_ooo:
                    try:
                        last_ts = datetime.fromisoformat(last_ooo[0])
                        if datetime.now() < last_ts + timedelta(hours=4):
                            send_ooo = False
                    except: pass
                
                if send_ooo:
                    if platform == "whatsapp": await send_whatsapp_message(user_id, ooo_text)
                    else: await send_telegram_message(user_id, ooo_text)
                    log_message(user_id, "bot", f"[AUTO-REPLY OOO] {ooo_text}")
                
                logging.info(f"Mensaje de fuera de horario enviado/omitido para {user_id}. Deteniendo procesamiento de IA.")
                return # Salimos para que la IA no responda

        # 1. Manejo de Adjuntos
        if attachment_data:
            logging.info(f"[ATTACHMENT] Procesando adjunto de {user_id}...")
            
            # Descargar archivo si es de WhatsApp (tiene URL)
            saved_path = None
            if attachment_data.get('url'):
                saved_path = await download_attachment(attachment_data['url'], attachment_data['file_name'])
            elif attachment_data.get('path'):
                saved_path = attachment_data['path']
            
            # Si no se pudo descargar, abortamos
            if not saved_path:
                logging.error(f"No se pudo procesar el adjunto de {user_id}")
                return

            contexto_detectado = user_text if user_text else None
            
            if not contexto_detectado:
                conn_check = sqlite3.connect(os.path.join(ROOT_DIR, "analytics.sqlite"))
                cursor_check = conn_check.cursor()
                cursor_check.execute("SELECT content, timestamp FROM messages WHERE thread_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1", (user_id,))
                last_m = cursor_check.fetchone()
                conn_check.close()
                if last_m:
                    contexto_detectado = f"Referente a: {last_m[0]}"
            
            conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO attachments (thread_id, file_path, file_name, file_type, context) VALUES (?, ?, ?, ?, ?)",
                (user_id, saved_path, attachment_data['file_name'], attachment_data['type'], contexto_detectado or "sin contexto")
            )
            conn.commit(); conn.close()
            
            if contexto_detectado:
                user_text = f"[SISTEMA: El usuario envió un archivo '{attachment_data['file_name']}' ({attachment_data['type']}). Contexto: {contexto_detectado}]"
            else:
                msg = "He recibido tu archivo. 📂 **¿A qué trámite corresponde este documento?**"
                if platform == "whatsapp": await send_whatsapp_message(user_id, msg)
                else: await send_telegram_message(user_id, msg)
                log_message(user_id, "bot", msg)
                return 

        # 2. Verificar si estamos esperando el contexto de un adjunto pendiente (flujo anterior)
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
        cursor = conn.cursor()
        cursor.execute("SELECT id, file_name FROM attachments WHERE thread_id = ? AND context = 'pendiente' ORDER BY created_at DESC LIMIT 1", (user_id,))
        pending_att = cursor.fetchone()
        
        if pending_att and user_text and not attachment_data:
            att_id, fname = pending_att
            cursor.execute("UPDATE attachments SET context = ? WHERE id = ?", (user_text, att_id))
            conn.commit(); conn.close()
            
            confirm_msg = f"Entendido. Registro el archivo **{fname}** como: '{user_text}'."
            if platform == "whatsapp": await send_whatsapp_message(user_id, confirm_msg)
            else: await send_telegram_message(user_id, confirm_msg)
            log_message(user_id, "bot", confirm_msg)
            user_text = f"[SISTEMA: El usuario confirmó que el archivo enviado anteriormente es: {user_text}]"
        else:
            conn.close()

        log_message(user_id, "user", user_text)
        
        # Verificar pausa
        conn_p = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
        cursor_p = conn_p.cursor()
        cursor_p.execute("SELECT paused_until FROM bot_pauses WHERE user_id = ?", (user_id,))
        row_p = cursor_p.fetchone()
        conn_p.close()
        
        if row_p:
            from datetime import datetime
            paused_until = datetime.strptime(row_p[0], "%Y-%m-%d %H:%M:%S")
            if datetime.now() < paused_until:
                logging.info(f"Bot en pausa para {user_id}. Ignorando IA.")
                return
                
        # Invocación de IA
        result = await run_in_threadpool(
            chatbot_app.invoke,
            {"messages": [HumanMessage(content=user_text)], "thread_id": user_id}, 
            config={"configurable": {"thread_id": user_id}}
        )
        last_msg = result["messages"][-1]
        bot_response = extract_text(last_msg.content)
        
        # --- LÓGICA DE ENVÍO DE ARCHIVOS AUTOMÁTICO (Tag [SEND_FILE: ...]) ---
        if "[SEND_FILE:" in bot_response:
            try:
                import re
                match_file = re.search(r"\[SEND_FILE:\s*(.*?)\]", bot_response)
                if match_file:
                    topic_to_send = match_file.group(1).strip()
                    # Buscar en DB
                    conn_f = get_db_settings()
                    cursor_f = conn_f.cursor()
                    cursor_f.execute("SELECT media_path FROM knowledge WHERE topic LIKE ?", (f"%{topic_to_send}%",))
                    row_f = cursor_f.fetchone()
                    
                    if row_f and row_f[0]:
                        media_path = row_f[0]
                        cursor_f.execute("SELECT value FROM config WHERE key = 'webhook_base_url'")
                        base_url = cursor_f.fetchone()[0].rstrip('/')
                        public_url = f"{base_url}{media_path}"
                        filename = os.path.basename(media_path)
                        
                        if platform == "whatsapp": await send_whatsapp_file(user_id, public_url, filename, "")
                        else: await send_telegram_file(user_id, public_url, "")
                        
                    conn_f.close()
                    # Limpiar el tag de la respuesta final
                    bot_response = re.sub(r"\[SEND_FILE:.*?\]", "", bot_response).strip()
            except Exception as e:
                logging.error(f"Error procesando envío automático de archivo: {e}")

        # Gap Detection (simplificado para este bloque)
        if "actualmente no tengo información" in bot_response.lower():
            try:
                conn_g = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
                conn_g.execute("INSERT INTO knowledge_gaps (topic) VALUES (?) ON CONFLICT(topic) DO UPDATE SET frequency = frequency + 1", (user_text,))
                conn_g.commit(); conn_g.close()
            except: pass
                
        # --- LÓGICA DE INTERACTIVIDAD (BOTONES/LISTAS) ---
        interactive_options = []
        try:
            # 1. Prioridad: ¿Estamos en un onboarding con opciones?
            onboarding_active = result.get("onboarding_active", False)
            if onboarding_active:
                fields = result.get("fields_to_collect", [])
                collected = result.get("collected_data", {})
                missing = [f for f in fields if f not in collected]
                if missing:
                    next_field = missing[0]
                    # Detectar patrón "Campo(Opcion1, Opcion2)"
                    import re
                    match = re.search(r"\((.*?)\)", next_field)
                    if match:
                        interactive_options = [o.strip() for o in match.group(1).split(",") if o.strip()]
            
            # 2. Secundario: Mapeo por Conocimiento (si no hay opciones de onboarding)
            if not interactive_options:
                conn_k = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
                cursor_k = conn_k.cursor()
                cursor_k.execute("SELECT topic, interactive_options FROM knowledge WHERE interactive_options IS NOT NULL AND interactive_options != ''")
                all_k = cursor_k.fetchall()
                conn_k.close()
                for topic, opts in all_k:
                    if topic.lower() in bot_response.lower() or bot_response.lower() in topic.lower():
                        interactive_options = [o.strip() for o in opts.split(",") if o.strip()]
                        break
        except Exception as e:
            logging.error(f"Error detectando opciones interactivas: {e}")

        wa_id = None
        if platform == "whatsapp": 
            if interactive_options:
                wa_id = await send_whatsapp_interactive(user_id, bot_response, interactive_options)
            else:
                wa_id = await send_whatsapp_message(user_id, bot_response)
        else: 
            await send_telegram_message(user_id, bot_response)
        
        log_message(user_id, "bot", bot_response, whatsapp_id=wa_id)
        
        usage = getattr(last_msg, "usage_metadata", None)
        if usage:
            log_token_usage(user_id, getattr(last_msg, "response_metadata", {}).get("model_name", "unknown"), usage.get("input_tokens", 0), usage.get("output_tokens", 0))
    except Exception as e: 
        logging.error(f"Error bot: {e}")
        traceback.print_exc()

async def download_telegram_media(file_id: str, token: str):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}")
            file_path = res.json()["result"]["file_path"]
            file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            
            ext = os.path.splitext(file_path)[1]
            local_filename = f"tg_{file_id}{ext}"
            local_path = os.path.join(ROOT_DIR, "uploads", local_filename)
            
            file_res = await client.get(file_url)
            with open(local_path, "wb") as f:
                f.write(file_res.content)
            
            return {"path": f"/uploads/{local_filename}", "name": local_filename, "type": mimetypes.guess_type(local_path)[0] or "application/octet-stream"}
    except Exception as e:
        logging.error(f"Error descargando media de Telegram: {e}")
        return None

def get_time_from_uuid6(uuid_str):
    import uuid
    try:
        u = uuid.UUID(uuid_str)
        if u.version == 6:
            t = (u.time_low << 28) | (u.time_mid << 12) | (u.time_hi_version & 0x0FFF)
            return (t - 0x01b21dd213814000) / 10000000.0
    except: pass
    return None

def format_time_ago(timestamp):
    if not timestamp: return "Desconocido"
    from datetime import datetime
    now = datetime.now().timestamp()
    diff = int(now - timestamp)
    if diff < 60: return "Hace un momento"
    if diff < 3600: return f"Hace {diff//60} min"
    if diff < 86400: return f"Hace {diff//3600} horas"
    return f"Hace {diff//86400} días"

def get_thread_metadata(t_id, checkpoint_id, cursor_s):
    name = f"Usuario {t_id[-4:]}" if len(t_id) >= 4 else "Usuario"
    if t_id == "playground": name = "Entorno de Pruebas"
    elif t_id.startswith("usuario_nuevo_"): name = "Usuario Web"
    else:
        cursor_s.execute("SELECT full_name FROM user_profiles WHERE CAST(user_id AS TEXT) = ?", (str(t_id),))
        row_p = cursor_s.fetchone()
        if row_p and row_p[0]:
            name = row_p[0]
        else:
            cursor_s.execute("SELECT client_name FROM proceedings WHERE tracking_number LIKE ?", (f"%{str(t_id)[-4:]}%",))
            row = cursor_s.fetchone()
            if row and row['client_name']: name = row['client_name']
    
    if t_id == "playground": platform = "playground"
    elif t_id.startswith("usuario_nuevo_"): platform = "web"
    elif "@" in t_id or (isinstance(t_id, str) and t_id.startswith("549")): platform = "whatsapp"
    elif len(str(t_id)) == 36 and "-" in str(t_id): platform = "consola"
    elif str(t_id).isdigit(): platform = "telegram"
    else: platform = "local"
    
    timestamp = get_time_from_uuid6(checkpoint_id)
    time_ago = format_time_ago(timestamp)
    
    is_active = False
    if timestamp:
        from datetime import datetime
        if (datetime.now().timestamp() - timestamp) < 900: is_active = True
            
    return {"id": t_id, "name": name, "platform": platform, "time_ago": time_ago, "is_active": is_active}

def log_audit(user_id: str, action: str, details: str = ""):
    try:
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
        conn.execute("INSERT INTO audit_logs (user_id, action, details) VALUES (?, ?, ?)", (user_id, action, details))
        conn.commit(); conn.close()
    except Exception as e:
        logging.error(f"Error logging audit: {e}")

# --- RUTAS DE ADMINISTRACIÓN ---
@app.get("/")
async def root(): return RedirectResponse(url="/admin")

@app.get("/admin", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def admin_dashboard(request: Request):
    threads, stats, notifications = [], {"total_chats": 0, "total_alerts": 0}, []
    from src.database.analytics_engine import get_dashboard_metrics
    metrics = get_dashboard_metrics()
    
    try:
        db_path = os.path.join(ROOT_DIR, "checkpoints.sqlite")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT thread_id, MAX(checkpoint_id) as last_cp FROM checkpoints GROUP BY thread_id ORDER BY last_cp DESC LIMIT 10")
            raw_threads = cursor.fetchall()
            conn.close()
            
            conn_s = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
            conn_s.row_factory = sqlite3.Row
            cursor_s = conn_s.cursor()
            threads = [get_thread_metadata(str(r[0]), str(r[1]), cursor_s) for r in raw_threads]
            conn_s.close()
            
            stats["total_chats"] = metrics["total_sessions"]
        
        notif_path = os.path.join(ROOT_DIR, "notifications.sqlite")
        if os.path.exists(notif_path):
            conn = sqlite3.connect(notif_path); conn.row_factory = sqlite3.Row
            cursor = conn.cursor(); cursor.execute("SELECT motivo, fecha FROM alerts ORDER BY id DESC LIMIT 5")
            notifications = [dict(row) for row in cursor.fetchall()]
            stats["total_alerts"] = len(notifications); conn.close()
            
        conn_s = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
        cursor_s = conn_s.cursor()
        cursor_s.execute("SELECT COUNT(*) FROM form_submissions")
        stats["total_submissions"] = cursor_s.fetchone()[0] or 0
        conn_s.close()
            
    except Exception as e:
        logging.error(f"Error en Dashboard: {e}")
        
    return templates.TemplateResponse(request=request, name="admin/index.html", context={
        "threads": threads, 
        "stats": stats, 
        "metrics": metrics,
        "notifications": notifications,
        "env": ENVIRONMENT,
        "active_section": "operacion"
    })

@app.get("/admin/channels", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def view_channels(request: Request):
    conn = get_db_settings(); cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM config WHERE key IN ('whatsapp_enabled', 'whatsapp_instance_id', 'whatsapp_api_token', 'telegram_enabled', 'telegram_token', 'webhook_base_url')")
    config = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return templates.TemplateResponse(request=request, name="admin/channels.html", context={"config": config})


@app.post("/admin/whatsapp/logout", dependencies=[Depends(verify_admin)])
async def whatsapp_logout_route():
    success = await whatsapp_logout_api()
    return {"status": "ok" if success else "error"}

@app.get("/admin/whatsapp/status", dependencies=[Depends(verify_admin)])
async def whatsapp_status_route():
    return await get_whatsapp_status()

@app.get("/admin/whatsapp/qr", dependencies=[Depends(verify_admin)])
async def whatsapp_qr_route():
    return await get_whatsapp_qr()

@app.post("/admin/channels/save", dependencies=[Depends(verify_admin)])
async def save_channels_config(
    request: Request, 
    whatsapp_enabled: str = Form("0"), 
    whatsapp_instance_id: str = Form(""),
    whatsapp_api_token: str = Form(""),
    telegram_enabled: str = Form("0"), 
    telegram_token: str = Form(""), 
    webhook_base_url: str = Form("")
):
    if webhook_base_url:
        parsed_url = re.match(r"(https?://[^/]+)", webhook_base_url)
        if parsed_url:
            webhook_base_url = parsed_url.group(1)

    conn = get_db_settings()
    updates = [
        ('whatsapp_enabled', whatsapp_enabled), 
        ('whatsapp_instance_id', whatsapp_instance_id),
        ('whatsapp_api_token', whatsapp_api_token),
        ('telegram_enabled', telegram_enabled), 
        ('telegram_token', telegram_token), 
        ('webhook_base_url', webhook_base_url)
    ]
    for k, v in updates: conn.execute("UPDATE config SET value = ? WHERE key = ?", (v, k))
    conn.commit(); conn.close()
    
    if webhook_base_url:
        base_url = webhook_base_url.rstrip('/')
    else:
        host = request.headers.get("host")
        scheme = request.headers.get("x-forwarded-proto", "http")
        base_url = f"{scheme}://{host}"
    
    if telegram_enabled == '1' and telegram_token: await setup_telegram_webhook(telegram_token, base_url)
    if whatsapp_enabled == '1': await setup_whatsapp_webhook(base_url)
    return RedirectResponse(url="/admin/channels?success=1", status_code=303)

@app.get("/admin/history", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def view_all_history(request: Request):
    threads = []
    try:
        db_path = os.path.join(ROOT_DIR, "checkpoints.sqlite")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path); cursor = conn.cursor()
            cursor.execute("SELECT thread_id, MAX(checkpoint_id) as last_cp FROM checkpoints GROUP BY thread_id ORDER BY last_cp DESC")
            raw_threads = cursor.fetchall()
            conn.close()
            
            conn_s = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
            conn_s.row_factory = sqlite3.Row
            cursor_s = conn_s.cursor()
            
            for r in raw_threads:
                threads.append(get_thread_metadata(str(r[0]), str(r[1]), cursor_s))
            conn_s.close()
    except Exception as e:
        logging.error(f"Error silenciado previamente: {e}")
    return templates.TemplateResponse(request=request, name="admin/history.html", context={"threads": threads, "active_section": "operacion"})

@app.get("/admin/chat/{thread_id}", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def view_chat_session(request: Request, thread_id: str):
    messages = []
    metadata = {"name": "Usuario", "platform": "Desconocido", "is_active": False}
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        db_path = os.path.join(ROOT_DIR, "checkpoints.sqlite")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path, check_same_thread=False); memory = SqliteSaver(conn)
            
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(checkpoint_id) FROM checkpoints WHERE thread_id = ?", (thread_id,))
            row_cp = cursor.fetchone()
            last_cp = row_cp[0] if row_cp else None
            
            conn_s = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
            conn_s.row_factory = sqlite3.Row
            cursor_s = conn_s.cursor()
            metadata = get_thread_metadata(thread_id, last_cp, cursor_s)
            
            cursor_s.execute("SELECT notes FROM chat_notes WHERE thread_id = ?", (thread_id,))
            note_row = cursor_s.fetchone()
            metadata["notes"] = note_row[0] if note_row else ""
            
            cursor_s.execute("SELECT paused_until FROM bot_pauses WHERE user_id = ?", (thread_id,))
            pause_row = cursor_s.fetchone()
            metadata["is_paused"] = False
            if pause_row:
                from datetime import datetime
                try:
                    paused_until = datetime.strptime(pause_row[0], "%Y-%m-%d %H:%M:%S")
                    if datetime.now() < paused_until: metadata["is_paused"] = True
                except: pass
                
            cursor_s.execute("SELECT id, file_path, file_name, file_type, context, created_at FROM attachments WHERE thread_id = ? OR CAST(thread_id AS TEXT) = ? ORDER BY created_at ASC", (thread_id, str(thread_id)))
            metadata["attachments"] = [dict(row) for row in cursor_s.fetchall()]
            
            cursor_s.execute("SELECT date, time, reason as service, status FROM appointments WHERE thread_id = ? ORDER BY date DESC", (thread_id,))
            metadata["appointments"] = [dict(row) for row in cursor_s.fetchall()]
            
            cursor_s.execute("SELECT tracking_number, topic, status, updated_at FROM proceedings WHERE client_name LIKE ? OR topic LIKE ?", (f"%{metadata['name']}%", f"%{thread_id}%"))
            metadata["proceedings"] = [dict(row) for row in cursor_s.fetchall()]

            cursor_s.execute("SELECT full_name FROM user_profiles WHERE user_id = ?", (thread_id,))
            prof = cursor_s.fetchone()
            metadata["full_name"] = prof[0] if prof else metadata["name"]
            metadata["phone"] = thread_id.split("@")[0] if "@" in thread_id else thread_id
            metadata["email"] = "No registrado" 

            cursor_s.execute("SELECT topic, data, created_at FROM form_submissions WHERE thread_id = ? ORDER BY created_at DESC", (thread_id,))
            metadata["submissions"] = []
            for row_sub in cursor_s.fetchall():
                try: 
                    row_dict = dict(row_sub)
                    row_dict["data"] = json.loads(row_dict["data"])
                    metadata["submissions"].append(row_dict)
                except: pass

            cursor_s.execute("SELECT COUNT(*) FROM attachments WHERE thread_id = ?", (thread_id,))
            metadata["total_files"] = cursor_s.fetchone()[0]
            cursor_s.execute("SELECT COUNT(*) FROM appointments WHERE thread_id = ?", (thread_id,))
            metadata["total_appointments"] = cursor_s.fetchone()[0]
            cursor_s.execute("SELECT COUNT(*) FROM proceedings WHERE client_name LIKE ? OR topic LIKE ?", (f"%{metadata['name']}%", f"%{thread_id}%"))
            metadata["total_proceedings"] = cursor_s.fetchone()[0]
            cursor_s.execute("SELECT COUNT(*) FROM form_submissions WHERE thread_id = ?", (thread_id,))
            metadata["total_forms"] = cursor_s.fetchone()[0]
            
            conn_s.close()
            
            conn_a = sqlite3.connect(os.path.join(ROOT_DIR, "analytics.sqlite"))
            conn_a.row_factory = sqlite3.Row
            cursor_a = conn_a.cursor()
            clean_id = thread_id.split("@")[0]
            cursor_a.execute("""
                SELECT role, content, timestamp 
                FROM messages 
                WHERE thread_id = ? OR thread_id LIKE ? 
                ORDER BY timestamp ASC
            """, (thread_id, f"%{clean_id}%"))
            rows = cursor_a.fetchall()
            messages = []
            for row in rows:
                role, content, ts = row['role'], row['content'], row['timestamp']
                m_type = "human" if role == "user" else "bot"
                messages.append({"type": m_type, "content": content, "timestamp": ts})
            conn_a.close()
            logging.info(f"[CHAT] Thread {thread_id}: Loaded {len(messages)} messages.")
            conn.close() 
    except Exception as e:
        logging.error(f"Error cargando sesión de chat: {e}")
        traceback.print_exc()

    all_threads = []
    try:
        db_path = os.path.join(ROOT_DIR, "checkpoints.sqlite")
        if os.path.exists(db_path):
            conn_cp = sqlite3.connect(db_path); cursor_cp = conn_cp.cursor()
            cursor_cp.execute("SELECT thread_id, MAX(checkpoint_id) as last_cp FROM checkpoints GROUP BY thread_id ORDER BY last_cp DESC LIMIT 30")
            raw_threads = cursor_cp.fetchall()
            conn_cp.close()
            
            conn_s = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
            conn_s.row_factory = sqlite3.Row
            cursor_s = conn_s.cursor()
            for r in raw_threads:
                t_meta = get_thread_metadata(str(r[0]), str(r[1]), cursor_s)
                cursor_s.execute("SELECT 1 FROM bot_pauses WHERE user_id = ?", (str(r[0]),))
                t_meta["is_paused"] = cursor_s.fetchone() is not None
                all_threads.append(t_meta)
            conn_s.close()
    except: pass

    return templates.TemplateResponse(request=request, name="admin/chat.html", context={
        "thread_id": thread_id, 
        "messages": messages, 
        "metadata": metadata, 
        "threads": all_threads,
        "active_section": "operacion"
    })

@app.post("/admin/chat/{thread_id}/send", dependencies=[Depends(verify_admin)])
async def send_chat_message(thread_id: str, message: str = Form(...), background_tasks: BackgroundTasks = None):
    print(f"[DEBUG] Admin sending message to {thread_id}")
    platform = "whatsapp" if "@" in thread_id else "telegram"
    print(f"[DEBUG] Detected platform for {thread_id}: {platform}")
    
    if platform == "whatsapp": await send_whatsapp_message(thread_id, message)
    else: await send_telegram_message(thread_id, message)
    
    try:
        from src.database.analytics_engine import log_message
        log_message(thread_id, "admin", message)
    except Exception as e: print(f"Error update state admin: {e}")
    
    from datetime import datetime, timedelta
    paused_until = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_settings()
    conn.execute("INSERT OR REPLACE INTO bot_pauses (user_id, paused_until) VALUES (?, ?)", (thread_id, paused_until))
    conn.commit()
    conn.close()
    
    return RedirectResponse(url=f"/admin/chat/{thread_id}", status_code=303)

@app.post("/admin/chat/{thread_id}/send-file", dependencies=[Depends(verify_admin)])
async def chat_send_file(thread_id: str, file: UploadFile = File(...)):
    uploads_dir = os.path.join(ROOT_DIR, "uploads")
    if not os.path.exists(uploads_dir): os.makedirs(uploads_dir)
    
    file_path = os.path.join(uploads_dir, file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    conn = get_db_settings(); cursor = conn.cursor()
    cursor.execute("SELECT value FROM config WHERE key = 'webhook_base_url'")
    row = cursor.fetchone()
    base_url = row[0] if row else None
    conn.close()
    
    if not base_url:
        return RedirectResponse(url=f"/admin/chat/{thread_id}?error=no_base_url", status_code=303)
        
    public_url = f"{base_url.rstrip('/')}/uploads/{file.filename}"
    
    if "@c.us" in thread_id:
        await send_whatsapp_file(thread_id, public_url, file.filename, "Adjunto enviado desde el panel")
    else:
        await send_telegram_file(thread_id, public_url, "Adjunto enviado desde el panel")
    
    from src.database.analytics_engine import log_message
    log_message(thread_id, "bot", f"[Archivo: {file.filename}]")
    
    return RedirectResponse(url=f"/admin/chat/{thread_id}", status_code=303)

@app.get("/admin/chat/resume/{thread_id}", dependencies=[Depends(verify_admin)])
async def resume_bot(thread_id: str):
    conn = get_db_settings()
    conn.execute("DELETE FROM bot_pauses WHERE user_id = ?", (thread_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/admin/chat/{thread_id}", status_code=303)

@app.get("/admin/chat/pause/{thread_id}", dependencies=[Depends(verify_admin)])
async def pause_bot(thread_id: str):
    from datetime import datetime, timedelta
    paused_until = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_settings()
    conn.execute("INSERT OR REPLACE INTO bot_pauses (user_id, paused_until) VALUES (?, ?)", (thread_id, paused_until))
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/admin/chat/{thread_id}", status_code=303)

@app.get("/admin/chat/{thread_id}/delete", dependencies=[Depends(verify_admin)])
async def delete_chat_session(thread_id: str):
    try:
        logging.info(f"[DELETE] Iniciando purga total para la sesión: {thread_id}")
        t_id_str = str(thread_id)
        
        db_path_c = os.path.join(ROOT_DIR, "checkpoints.sqlite")
        if os.path.exists(db_path_c):
            conn_c = sqlite3.connect(db_path_c, timeout=30)
            for table in ["checkpoints", "writes", "blobs", "checkpoint_writes", "checkpoint_blobs"]:
                try:
                    conn_c.execute(f"DELETE FROM {table} WHERE thread_id = ? OR CAST(thread_id AS TEXT) = ?", (thread_id, t_id_str))
                except: pass
            conn_c.commit(); conn_c.close()
            logging.info(f"[DELETE] Checkpoints limpiados para {thread_id}")
        
        db_path_a = os.path.join(ROOT_DIR, "analytics.sqlite")
        if os.path.exists(db_path_a):
            conn_a = sqlite3.connect(db_path_a, timeout=30)
            for table in ["messages", "token_usage", "session_analytics"]:
                try:
                    conn_a.execute(f"DELETE FROM {table} WHERE thread_id = ? OR CAST(thread_id AS TEXT) = ?", (thread_id, t_id_str))
                except: pass
            conn_a.commit(); conn_a.close()
            logging.info(f"[DELETE] Analytics limpiado para {thread_id}")
        
        conn_s = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"), timeout=30)
        cursor_s = conn_s.cursor()
        
        try:
            cursor_s.execute("SELECT file_path FROM attachments WHERE thread_id = ? OR CAST(thread_id AS TEXT) = ?", (thread_id, t_id_str))
            for row in cursor_s.fetchall():
                try:
                    filename = row[0].replace("/uploads/", "")
                    full_path = os.path.join(ROOT_DIR, "uploads", filename)
                    if os.path.exists(full_path): os.remove(full_path)
                except: pass
        except: pass
            
        all_settings_tables = [
            ("chat_notes", "thread_id"), ("form_submissions", "thread_id"), 
            ("appointments", "thread_id"), ("attachments", "thread_id"),
            ("user_profiles", "user_id"), ("bot_pauses", "user_id"),
            ("proceedings", "tracking_number")
        ]
        
        for table, col in all_settings_tables:
            try:
                if table == "proceedings":
                    conn_s.execute(f"DELETE FROM {table} WHERE {col} LIKE ?", (f"%{t_id_str}%",))
                else:
                    conn_s.execute(f"DELETE FROM {table} WHERE {col} = ? OR CAST({col} AS TEXT) = ?", (thread_id, t_id_str))
            except: pass
            
        conn_s.commit(); conn_s.close()
        
        log_audit("admin", "Eliminación de sesión", f"Hilo: {thread_id}")
        logging.info(f"[DELETE] Settings limpiado por completo para {thread_id}")
        return RedirectResponse(url="/admin/history?deleted=1", status_code=303)
    except Exception as e:
        logging.error(f"Error crítico eliminando sesión {thread_id}: {e}")
        return RedirectResponse(url="/admin/history?error=1", status_code=303)

@app.post("/admin/chat/{thread_id}/notes", dependencies=[Depends(verify_admin)])
async def save_chat_notes(thread_id: str, notes: str = Form(""), background_tasks: BackgroundTasks = None):
    conn = get_db_settings()
    conn.execute("INSERT OR REPLACE INTO chat_notes (thread_id, notes) VALUES (?, ?)", (thread_id, notes))
    conn.commit()
    conn.close()
    log_audit("admin", "Actualización de notas", f"Hilo: {thread_id}")
    return RedirectResponse(url=f"/admin/chat/{thread_id}", status_code=303)

@app.get("/admin/api/knowledge", dependencies=[Depends(verify_admin)])
async def get_knowledge_api():
    try:
        conn = get_db_settings()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, topic, content, category FROM knowledge ORDER BY topic ASC")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/admin/chat/{thread_id}/send-knowledge", dependencies=[Depends(verify_admin)])
async def send_knowledge_to_chat(thread_id: str, knowledge_id: int = Form(...)):
    try:
        conn = get_db_settings()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT topic, content, media_path FROM knowledge WHERE id = ?", (knowledge_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return JSONResponse({"status": "error", "message": "Conocimiento no encontrado"}, status_code=404)
        
        topic = row['topic']
        content = row['content']
        media_path = row['media_path']
        
        cursor.execute("SELECT value FROM config WHERE key = 'webhook_base_url'")
        cfg_row = cursor.fetchone()
        base_url = cfg_row[0].rstrip('/') if cfg_row else ""
        
        platform = "whatsapp" if "@" in thread_id else "telegram"
        
        if media_path and base_url:
            public_url = f"{base_url}{media_path}"
            filename = os.path.basename(media_path)
            if platform == "whatsapp": await send_whatsapp_file(thread_id, public_url, filename, content)
            else: await send_telegram_file(thread_id, public_url, content)
        else:
            if platform == "whatsapp": await send_whatsapp_message(thread_id, content)
            else: await send_telegram_message(thread_id, content)
        
        from src.database.analytics_engine import log_message
        log_message(thread_id, "admin", f"[Enviado Conocimiento: {topic}]\n{content}")
        
        conn.execute("DELETE FROM bot_pauses WHERE user_id = ?", (thread_id,))
        conn.commit()
        conn.close()
        
        log_audit("admin", "Envío de conocimiento en chat", f"Hilo: {thread_id} | Tema: {topic}")
        return {"status": "ok", "message": "Enviado y bot reactivado"}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.get("/admin/kanban", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def view_kanban(request: Request):
    grouped = {"Pendiente": [], "En_Proceso": [], "Listo_para_Firmar": [], "Finalizado": []}
    try:
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite")); conn.row_factory = sqlite3.Row
        cursor = conn.cursor(); cursor.execute("SELECT * FROM proceedings ORDER BY updated_at DESC")
        items = [dict(row) for row in cursor.fetchall()]; conn.close()
        for item in items:
            status = item['status']
            key = status.replace(" ", "_")
            if key in grouped: grouped[key].append(item)
    except Exception as e:
        logging.error(f"Error silenciado previamente: {e}")
    return templates.TemplateResponse(request=request, name="admin/kanban.html", context={"grouped": grouped, "active_section": "tramites"})

@app.get("/admin/kanban/move/{item_id}", dependencies=[Depends(verify_admin)])
async def move_kanban_item(item_id: int, status: str):
    try:
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
        conn.execute("UPDATE proceedings SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, item_id))
        conn.commit(); conn.close()
    except Exception as e:
        logging.error(f"Error silenciado previamente: {e}")
    return RedirectResponse(url="/admin/kanban", status_code=303)

@app.get("/admin/appointments", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def appointments_panel(request: Request):
    conn = get_db_settings(); cursor = conn.cursor()
    cursor.execute("SELECT id, thread_id, client_name, date, time, reason, status FROM appointments ORDER BY date DESC, time DESC")
    appointments = [{"id": r[0], "thread_id": r[1], "client_name": r[2], "date": r[3], "time": r[4], "reason": r[5], "status": r[6]} for r in cursor.fetchall()]
    conn.close()
    return templates.TemplateResponse(request=request, name="admin/appointments.html", context={"appointments": appointments, "active_section": "turnos"})

@app.get("/admin/playground", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def view_playground(request: Request):
    return templates.TemplateResponse(request=request, name="admin/playground.html", context={})

@app.post("/admin/playground/chat", dependencies=[Depends(verify_admin)])
async def playground_chat(request: Request):
    try:
        data = await request.json(); user_text = data.get("message")
        if not chatbot_app: return JSONResponse({"status": "error", "message": "IA no cargada."})
        result = chatbot_app.invoke(
            {"messages": [HumanMessage(content=user_text)], "thread_id": "playground"}, 
            config={"configurable": {"thread_id": "playground"}}
        )
        return JSONResponse({"status": "ok", "response": extract_text(result["messages"][-1].content)})
    except: return JSONResponse({"status": "error"})

@app.get("/admin/analytics", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def view_analytics(request: Request):
    from src.database.analytics_engine import get_dashboard_metrics
    return templates.TemplateResponse(request=request, name="admin/analytics.html", context={"stats": get_dashboard_metrics()})


@app.get("/admin/proceedings", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def view_proceedings(request: Request):
    proceedings = []
    try:
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite")); conn.row_factory = sqlite3.Row
        cursor = conn.cursor(); cursor.execute("SELECT * FROM proceedings ORDER BY updated_at DESC")
        proceedings = [dict(row) for row in cursor.fetchall()]; conn.close()
    except Exception as e:
        logging.error(f"Error silenciado previamente: {e}")
    return templates.TemplateResponse(request=request, name="admin/proceedings.html", context={"proceedings": proceedings, "active_section": "tramites"})

@app.get("/admin/submissions", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def view_submissions(request: Request):
    submissions = []
    try:
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite")); conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT topic FROM form_submissions LIMIT 1")
        except:
            cursor.execute("ALTER TABLE form_submissions RENAME COLUMN form_topic TO topic")
            conn.commit()

        cursor.execute("SELECT * FROM form_submissions ORDER BY created_at DESC")
        raw_submissions = cursor.fetchall()
        
        for s in raw_submissions:
            sub = dict(s)
            cursor.execute("SELECT full_name FROM user_profiles WHERE user_id = ? OR CAST(user_id AS TEXT) = ?", (sub['thread_id'], str(sub['thread_id'])))
            name_row = cursor.fetchone()
            sub['user_name'] = name_row[0] if name_row else "Usuario Desconocido"
            
            try:
                sub['parsed_data'] = json.loads(sub['data'])
            except:
                sub['parsed_data'] = {"Error": "Datos no legibles"}
            
            try:
                dt = datetime.fromisoformat(sub['created_at'].replace(' ', 'T'))
                sub['formatted_date'] = dt.strftime("%d/%m/%Y %H:%M")
            except:
                sub['formatted_date'] = sub['created_at']
            
            cursor.execute("SELECT file_path, file_name, file_type, context FROM attachments WHERE form_id = ? ORDER BY created_at DESC", (sub['id'],))
            sub['attachments'] = [dict(a) for a in cursor.fetchall()]
            
            if not sub['attachments']:
                cursor.execute("SELECT file_path, file_name, file_type, context FROM attachments WHERE thread_id = ? AND form_id IS NULL ORDER BY created_at DESC", (sub['thread_id'],))
                sub['attachments'] = [dict(a) for a in cursor.fetchall()]
            
            submissions.append(sub)
            
        conn.close()
    except Exception as e:
        logging.error(f"Error cargando submissions: {e}")
    return templates.TemplateResponse(request=request, name="admin/submissions.html", context={"submissions": submissions, "active_section": "tramites"})

@app.get("/admin/config", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def config_panel(request: Request, sync_needed: bool = False, success_reset: bool = False, error_reset: bool = False, active_tab: str = "asistente", active_section: str = "control"):
    conn = get_db_settings(); cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM config"); config = {row[0]: row[1] for row in cursor.fetchall()}
    cursor.execute("SELECT key, value FROM external_services"); external = {row[0]: row[1] for row in cursor.fetchall()}
    cursor.execute("SELECT id, topic, content, category, has_form, form_fields, storage_dest, allow_scheduling, interactive_options, media_path FROM knowledge ORDER BY category ASC")
    knowledge_items = [{"id": r[0], "topic": r[1], "content": r[2], "category": r[3], "has_form": r[4], "form_fields": r[5], "storage_dest": r[6], "allow_scheduling": r[7], "interactive_options": r[8], "media_path": r[9]} for r in cursor.fetchall()]
    conn.close(); data_files = []
    if os.path.exists(os.path.join(ROOT_DIR, "data")):
        for f in os.listdir(os.path.join(ROOT_DIR, "data")):
            if f.endswith((".pdf", ".txt")): data_files.append({"name": f})
    
    openai_key = os.getenv("OPENAI_API_KEY", "")
    google_key = os.getenv("GOOGLE_API_KEY", "")
    ai_provider = os.getenv("AI_PROVIDER", "openai")
    
    masked_openai = f"{openai_key[:8]}...{openai_key[-4:]}" if len(openai_key) > 12 else "No configurada"
    masked_google = f"{google_key[:8]}...{google_key[-4:]}" if len(google_key) > 12 else "No configurada"

    external_env = {"EVOLUTION_API_URL": EVOLUTION_API_URL, "INSTANCE_NAME": INSTANCE_NAME}
    return templates.TemplateResponse(request=request, name="admin/config.html", context={
        "config": config, 
        "external": external, 
        "knowledge_items": knowledge_items, 
        "data_files": data_files, 
        "sync_needed": sync_needed, 
        "success_reset": success_reset,
        "error_reset": error_reset,
        "external_env": external_env,
        "active_tab": active_tab,
        "active_section": active_section,
        "ai_config": {
            "provider": ai_provider,
            "openai_masked": masked_openai,
            "google_masked": masked_google
        }
    })

@app.get("/admin/knowledge", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def knowledge_panel(request: Request):
    return await config_panel(request, active_tab="cerebro", active_section="cerebro")

@app.get("/admin/company", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def company_panel(request: Request):
    return await config_panel(request, active_tab="empresa", active_section="cerebro")

@app.get("/admin/appointments/config", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def appointments_config_panel(request: Request):
    return await config_panel(request, active_tab="turnos_config", active_section="turnos")

@app.get("/admin/connectivity", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def connectivity_panel(request: Request):
    return await config_panel(request, active_tab="conectividad", active_section="control")

@app.post("/admin/knowledge/add", dependencies=[Depends(verify_admin)])
async def add_knowledge(
    topic: str = Form(...), content: str = Form(...), category: str = Form(""),
    interactive_options: str = Form(None), media: UploadFile = File(None)
):
    media_path = None
    if media and media.filename:
        uploads_dir = os.path.join(ROOT_DIR, "uploads")
        if not os.path.exists(uploads_dir): os.makedirs(uploads_dir)
        filename = f"knw_{int(datetime.now().timestamp())}_{media.filename}"
        with open(os.path.join(uploads_dir, filename), "wb") as f:
            shutil.copyfileobj(media.file, f)
        media_path = f"/uploads/{filename}"

    conn = get_db_settings()
    conn.execute("INSERT INTO knowledge (topic, content, category, media_path, interactive_options) VALUES (?, ?, ?, ?, ?)", (topic, content, category, media_path, interactive_options))
    conn.commit(); conn.close()
    return RedirectResponse(url="/admin/knowledge?success=1", status_code=303)

@app.get("/admin/knowledge/remove-media/{item_id}", dependencies=[Depends(verify_admin)])
async def remove_knowledge_media(item_id: int):
    conn = get_db_settings()
    conn.execute("UPDATE knowledge SET media_path = NULL WHERE id = ?", (item_id,))
    conn.commit(); conn.close()
    return RedirectResponse(url="/admin/knowledge?success=1", status_code=303)

@app.get("/admin/knowledge/get/{item_id}", dependencies=[Depends(verify_admin)])
async def get_knowledge(item_id: int):
    conn = get_db_settings()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM knowledge WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    conn.close()
    if row: return dict(row)
    return JSONResponse({"error": "No encontrado"}, status_code=404)

@app.post("/admin/knowledge/update", dependencies=[Depends(verify_admin)])
async def update_knowledge(
    item_id: int = Form(...), topic: str = Form(...), content: str = Form(...), 
    category: str = Form(""), interactive_options: str = Form(None), media: UploadFile = File(None)
):
    media_path = None
    if media and media.filename:
        uploads_dir = os.path.join(ROOT_DIR, "uploads")
        if not os.path.exists(uploads_dir): os.makedirs(uploads_dir)
        filename = f"knw_{int(datetime.now().timestamp())}_{media.filename}"
        with open(os.path.join(uploads_dir, filename), "wb") as f:
            shutil.copyfileobj(media.file, f)
        media_path = f"/uploads/{filename}"

    conn = get_db_settings()
    if media_path:
        conn.execute("UPDATE knowledge SET topic = ?, content = ?, category = ?, media_path = ?, interactive_options = ? WHERE id = ?", (topic, content, category, media_path, interactive_options, item_id))
    else:
        conn.execute("UPDATE knowledge SET topic = ?, content = ?, category = ?, interactive_options = ? WHERE id = ?", (topic, content, category, interactive_options, item_id))
    conn.commit(); conn.close()
    return RedirectResponse(url="/admin/knowledge?success=1", status_code=303)

@app.post("/admin/whatsapp/sync-webhooks", dependencies=[Depends(verify_admin)])
async def whatsapp_sync_webhooks():
    conn = get_db_settings(); cursor = conn.cursor()
    cursor.execute("SELECT value FROM config WHERE key = 'webhook_base_url'")
    base_url = cursor.fetchone()[0]
    conn.close()
    if base_url:
        success = await setup_whatsapp_webhook(base_url.rstrip('/'))
        return {"status": "ok" if success else "error"}
    return {"status": "error", "message": "No hay URL de Webhook configurada"}

@app.get("/admin/playground", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def ia_playground(request: Request):
    return templates.TemplateResponse(request=request, name="admin/playground.html", context={"active_section": "control"})

@app.post("/admin/playground/send", dependencies=[Depends(verify_admin)])
async def playground_send(request: Request):
    try:
        data = await request.json()
        user_text = data.get("message")
        thread_id = data.get("thread_id", "playground")
        
        if not chatbot_app: return JSONResponse({"status": "error", "message": "Bot no cargado"})
        
        from src.database.analytics_engine import log_message
        log_message(thread_id, "user", user_text)
        
        result = await run_in_threadpool(
            chatbot_app.invoke,
            {"messages": [HumanMessage(content=user_text)], "thread_id": thread_id}, 
            config={"configurable": {"thread_id": thread_id}}
        )
        
        last_msg = result["messages"][-1]
        bot_response = extract_text(last_msg.content)
        log_message(thread_id, "bot", bot_response)
        return {"status": "ok", "response": bot_response}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.post("/admin/config/save-all", dependencies=[Depends(verify_admin)])
async def save_all_config(
    request: Request,
    bot_name: str = Form(...), bot_tone: str = Form(...), system_prompt: str = Form(...),
    company_name: str = Form(""), company_phone: str = Form(""), company_email: str = Form(""), 
    company_website: str = Form(""), company_address: str = Form(""),
    whatsapp_enabled: str = Form("0"), telegram_enabled: str = Form("0"), 
    telegram_token: str = Form(""), webhook_base_url: str = Form(""),
    test_mode_enabled: str = Form("0"), test_numbers: str = Form(""),
    welcome_message_enabled: str = Form("0"), welcome_message_text: str = Form(""), welcome_threshold_days: str = Form("7"),
    welcome_media: UploadFile = File(None),
    scheduling_enabled: str = Form("0"), scheduling_provider: str = Form("local"), 
    appointment_duration: str = Form("30"), working_hours: str = Form(""), 
    scheduling_hours: str = Form(""), google_calendar_id: str = Form("primary"),
    scheduling_capacity: str = Form("1")
):
    form_data = await request.form()
    scheduling_days = ",".join(form_data.getlist("scheduling_days"))
    
    # Manejo de archivo de bienvenida
    welcome_media_path = None
    if welcome_media and welcome_media.filename:
        uploads_dir = os.path.join(ROOT_DIR, "uploads")
        if not os.path.exists(uploads_dir): os.makedirs(uploads_dir)
        filename = f"welcome_{int(datetime.now().timestamp())}_{welcome_media.filename}"
        file_path = os.path.join(uploads_dir, filename)
        with open(file_path, "wb") as f:
            shutil.copyfileobj(welcome_media.file, f)
        welcome_media_path = f"/uploads/{filename}"

    # 1. Limpiar Webhook URL
    if webhook_base_url:
        parsed_url = re.match(r"(https?://[^/]+)", webhook_base_url)
        if parsed_url: webhook_base_url = parsed_url.group(1)

    # 2. Configuración General (Tabla 'config')
    conn = get_db_settings()
    config_updates = [
        ('bot_name', bot_name), ('bot_tone', bot_tone), ('system_prompt', system_prompt),
        ('company_name', company_name), ('company_phone', company_phone), ('company_email', company_email),
        ('company_website', company_website), ('company_address', company_address),
        ('whatsapp_enabled', whatsapp_enabled), ('telegram_enabled', telegram_enabled),
        ('telegram_token', telegram_token), ('webhook_base_url', webhook_base_url),
        ('test_mode_enabled', test_mode_enabled), ('test_numbers', test_numbers),
        ('welcome_message_enabled', welcome_message_enabled), ('welcome_message_text', welcome_message_text),
        ('welcome_threshold_days', welcome_threshold_days),
        ('out_of_office_enabled', form_data.get('out_of_office_enabled', '0')),
        ('out_of_office_message', form_data.get('out_of_office_message', ''))
    ]
    if welcome_media_path:
        config_updates.append(('welcome_media_path', welcome_media_path))

    for k, v in config_updates:
        conn.execute("UPDATE config SET value = ? WHERE key = ?", (v, k))
    
    # 3. Servicios Externos (Tabla 'external_services')
    external_updates = [
        ('scheduling_enabled', scheduling_enabled),
        ('scheduling_provider', scheduling_provider),
        ('appointment_duration', appointment_duration),
        ('working_hours', working_hours),
        ('scheduling_hours', scheduling_hours),
        ('google_calendar_id', google_calendar_id),
        ('scheduling_days', scheduling_days),
        ('scheduling_capacity', scheduling_capacity)
    ]
    for k, v in external_updates:
        conn.execute("INSERT OR REPLACE INTO external_services (key, value) VALUES (?, ?)", (k, v))
    
    conn.commit()
    conn.close()

    # 4. Re-configurar Webhooks si cambiaron
    if webhook_base_url:
        base_url = webhook_base_url.rstrip('/')
        if telegram_enabled == '1' and telegram_token: await setup_telegram_webhook(telegram_token, base_url)
        if whatsapp_enabled == '1': await setup_whatsapp_webhook(base_url)

    active_tab = form_data.get("active_tab", "asistente")
    redirect_url = "/admin/config"
    if active_tab == "cerebro": redirect_url = "/admin/knowledge"
    elif active_tab == "empresa": redirect_url = "/admin/company"
    elif active_tab == "turnos_config": redirect_url = "/admin/appointments/config"
    elif active_tab == "conectividad": redirect_url = "/admin/connectivity"
    
    log_audit("admin", "Actualización de configuración", f"Cambios en parámetros globales (Sección: {active_tab})")
    return RedirectResponse(url=f"{redirect_url}?success=1", status_code=303)

@app.get("/admin/config/remove-welcome-media", dependencies=[Depends(verify_admin)])
async def remove_welcome_media():
    conn = get_db_settings()
    conn.execute("UPDATE config SET value = '' WHERE key = 'welcome_media_path'")
    conn.commit(); conn.close()
    return RedirectResponse(url="/admin/config?active_tab=identidad&success=1", status_code=303)

@app.post("/admin/config/upload-service-account", dependencies=[Depends(verify_admin)])
async def upload_service_account(file: UploadFile = File(...)):
    if not file.filename.endswith(".json"):
        return RedirectResponse(url="/admin/config?error_file=1&tab=empresa", status_code=303)
    
    file_path = os.path.join(ROOT_DIR, "service_account.json")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    log_audit("admin", "Carga de credenciales Google", "Archivo service_account.json subido")
    return RedirectResponse(url="/admin/config?success_file=1&tab=empresa", status_code=303)

@app.get("/admin/knowledge/delete/{item_id}", dependencies=[Depends(verify_admin)])
async def delete_knowledge(item_id: int):
    log_audit("admin", "Eliminación de conocimiento", f"ID: {item_id}")
    conn = get_db_settings(); conn.execute("DELETE FROM knowledge WHERE id = ?", (item_id,))
    conn.commit(); conn.close()
    return RedirectResponse(url="/admin/config?sync_needed=1", status_code=303)

@app.post("/admin/proceedings/add", dependencies=[Depends(verify_admin)])
async def add_proceeding(tracking: str = Form(...), client: str = Form(...), topic: str = Form(...), status: str = Form(...), notes: str = Form("")):
    conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
    conn.execute("INSERT INTO proceedings (tracking_number, client_name, topic, status, notes) VALUES (?, ?, ?, ?, ?)", (tracking, client, topic, status, notes))
    conn.commit(); conn.close()
    log_audit("admin", "Nuevo expediente", f"Tracking: {tracking}")
    return RedirectResponse(url="/admin/proceedings", status_code=303)

@app.get("/admin/submissions/delete/{sub_id}", dependencies=[Depends(verify_admin)])
async def delete_submission(sub_id: int):
    log_audit("admin", "Eliminación en Recepción", f"ID: {sub_id}")
    conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
    conn.execute("DELETE FROM form_submissions WHERE id = ?", (sub_id,))
    conn.commit(); conn.close()
    return RedirectResponse(url="/admin/submissions", status_code=303)

@app.get("/admin/proceedings/delete/{proc_id}", dependencies=[Depends(verify_admin)])
async def delete_proceeding(proc_id: int):
    log_audit("admin", "Eliminación de expediente", f"ID: {proc_id}")
    conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
    conn.execute("DELETE FROM proceedings WHERE id = ?", (proc_id,))
    conn.commit(); conn.close()
    return RedirectResponse(url="/admin/proceedings", status_code=303)

@app.post("/admin/system/reset-total", dependencies=[Depends(verify_admin)])
async def reset_total_system():
    logging.info("[RESET] Iniciando reinicio total del sistema...")
    try:
        # 1. Reset de Settings (Config, Knowledge, etc.)
        logging.info("[RESET] Limpiando settings.sqlite...")
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"), timeout=10)
        cursor = conn.cursor()
        tables_to_clear = [
            "knowledge", "appointments", "proceedings", "form_submissions", 
            "bot_pauses", "external_services", "knowledge_gaps", "user_profiles", "chat_notes"
        ]
        for table in tables_to_clear:
            try: cursor.execute(f"DELETE FROM {table}")
            except: pass
            
        cursor.execute("DELETE FROM config")
        defaults = [
            ('bot_name', 'Nuevo Asistente'), ('bot_tone', 'neutro'), 
            ('system_prompt', GENERIC_PROMPT), ('company_name', 'Mi Empresa'), 
            ('company_phone', ''), ('company_email', ''), ('company_website', ''), ('company_address', ''),
            ('whatsapp_enabled', '0'), ('telegram_enabled', '0'), ('telegram_token', ''),
            ('webhook_base_url', ''), ('test_mode_enabled', '0'), ('test_numbers', '')
        ]
        cursor.executemany("INSERT INTO config (key, value) VALUES (?, ?)", defaults)
        
        ext_defaults = [
            ('scheduling_enabled', '0'), ('scheduling_provider', 'local'),
            ('appointment_duration', '30'), ('working_hours', 'No especificados')
        ]
        cursor.executemany("INSERT INTO external_services (key, value) VALUES (?, ?)", ext_defaults)
        conn.commit(); conn.close()
        
        # 2. Reset de Analíticas
        logging.info("[RESET] Limpiando analytics.sqlite...")
        conn_an = sqlite3.connect(os.path.join(ROOT_DIR, "analytics.sqlite"), timeout=10)
        conn_an.execute("DELETE FROM messages")
        conn_an.execute("DELETE FROM token_usage")
        conn_an.execute("DELETE FROM session_analytics")
        conn_an.commit(); conn_an.close()
        
        # 3. Reset de Notificaciones
        logging.info("[RESET] Limpiando notifications.sqlite...")
        notif_path = os.path.join(ROOT_DIR, "notifications.sqlite")
        if os.path.exists(notif_path):
            conn_not = sqlite3.connect(notif_path, timeout=10)
            conn_not.execute("DELETE FROM alerts")
            conn_not.commit(); conn_not.close()
            
        # 4. Reset de Checkpoints (LangGraph) - Intentar borrar tablas sin bloquear
        logging.info("[RESET] Limpiando checkpoints.sqlite...")
        cp_path = os.path.join(ROOT_DIR, "checkpoints.sqlite")
        if os.path.exists(cp_path):
            try:
                conn_cp = sqlite3.connect(cp_path, timeout=10)
                cursor_cp = conn_cp.cursor()
                cursor_cp.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor_cp.fetchall()
                for table in tables:
                    if table[0] not in ['sqlite_sequence']:
                        cursor_cp.execute(f"DELETE FROM {table[0]}")
                conn_cp.commit(); conn_cp.close()
            except Exception as e:
                logging.warning(f"[RESET] No se pudo limpiar checkpoints completamente: {e}")
            
        # 5. Limpiar Archivos (Data)
        logging.info("[RESET] Borrando archivos en /data...")
        data_dir = os.path.join(ROOT_DIR, "data")
        if os.path.exists(data_dir):
            for f in os.listdir(data_dir):
                try: os.remove(os.path.join(data_dir, f))
                except: pass
                
        # 6. Limpiar ChromaDB (Base Vectorial)
        logging.info("[RESET] Borrando /chroma_db...")
        chroma_dir = os.path.join(ROOT_DIR, "chroma_db")
        if os.path.exists(chroma_dir):
            # En Windows, shutil.rmtree suele fallar si hay procesos usando los archivos
            # Intentamos borrar el contenido y luego el directorio
            try:
                shutil.rmtree(chroma_dir, ignore_errors=True)
            except:
                logging.warning("[RESET] No se pudo borrar el directorio chroma_db. Se intentará limpiar en el próximo reinicio.")
            
        log_audit("admin", "REINICIO TOTAL", "El sistema ha sido reseteado a valores de fábrica")
        logging.info("[RESET] Reinicio total completado con éxito.")
        return RedirectResponse(url="/admin/config?success_reset=1", status_code=303)
    except Exception as e:
        logging.error(f"[RESET] Error crítico en reinicio: {e}")
        return RedirectResponse(url="/admin/config?error_reset=1", status_code=303)

@app.get("/admin/knowledge/get/{item_id}", dependencies=[Depends(verify_admin)])
async def get_knowledge_item(item_id: int):
    conn = get_db_settings(); cursor = conn.cursor()
    cursor.execute("SELECT id, topic, content, category, has_form, form_fields, storage_dest, allow_scheduling, interactive_options FROM knowledge WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "topic": row[1], "content": row[2], "category": row[3], "has_form": row[4], "form_fields": row[5], "storage_dest": row[6], "allow_scheduling": row[7], "interactive_options": row[8]}
    return JSONResponse({"status": "error", "message": "No encontrado"}, status_code=404)

@app.post("/admin/knowledge/update", dependencies=[Depends(verify_admin)])
async def update_knowledge(
    item_id: int = Form(...), 
    topic: str = Form(...), 
    content: str = Form(...), 
    category: str = Form(...), 
    has_form: int = Form(0), 
    form_fields: str = Form(None), 
    storage_dest: str = Form("database"),
    interactive_options: str = Form(None)
):
    conn = get_db_settings()
    conn.execute(
        "UPDATE knowledge SET topic = ?, content = ?, category = ?, has_form = ?, form_fields = ?, storage_dest = ?, interactive_options = ? WHERE id = ?", 
        (topic, content, category, has_form, form_fields, storage_dest, interactive_options, item_id)
    )
    conn.commit(); conn.close()
    log_audit("admin", "Actualización de conocimiento", f"Tema: {topic}")
    return RedirectResponse(url="/admin/config?sync_needed=1", status_code=303)

@app.post("/admin/knowledge/add", dependencies=[Depends(verify_admin)])
async def add_knowledge(
    topic: str = Form(...), 
    content: str = Form(...), 
    category: str = Form(...),
    has_form: int = Form(0), 
    form_fields: str = Form(""), 
    item_id: str = Form(""),
    allow_scheduling: int = Form(0),
    interactive_options: str = Form(None)
):
    conn = get_db_settings()
    if item_id:
        conn.execute(
            "UPDATE knowledge SET topic=?, content=?, category=?, has_form=?, form_fields=?, allow_scheduling=?, interactive_options=? WHERE id=?", 
            (topic, content, category, has_form, form_fields, allow_scheduling, interactive_options, item_id)
        )
    else:
        conn.execute(
            "INSERT INTO knowledge (topic, content, category, has_form, form_fields, allow_scheduling, interactive_options) VALUES (?, ?, ?, ?, ?, ?, ?)", 
            (topic, content, category, has_form, form_fields, allow_scheduling, interactive_options)
        )
    conn.commit(); conn.close()
    return RedirectResponse(url="/admin/knowledge?success=1", status_code=303)

@app.post("/admin/files/upload", dependencies=[Depends(verify_admin)])
async def upload_file(file: UploadFile = File(...)):
    data_dir = os.path.join(ROOT_DIR, "data")
    if not os.path.exists(data_dir): os.makedirs(data_dir)
    with open(os.path.join(data_dir, file.filename), "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    log_audit("admin", "Carga de archivo", f"Nombre: {file.filename}")
    return RedirectResponse(url="/admin/config?sync_needed=1", status_code=303)

@app.get("/admin/files/delete/{filename}", dependencies=[Depends(verify_admin)])
async def delete_file(filename: str):
    file_path = os.path.join(ROOT_DIR, "data", filename)
    if os.path.exists(file_path): os.remove(file_path)
    log_audit("admin", "Eliminación de archivo", f"Nombre: {filename}")
    return RedirectResponse(url="/admin/config?sync_needed=1", status_code=303)

@app.post("/admin/config/sync", dependencies=[Depends(verify_admin)])
async def sync_knowledge(background_tasks: BackgroundTasks):
    from src.database.ingest import ingest_data
    background_tasks.add_task(ingest_data)
    return RedirectResponse(url="/admin/config", status_code=303)

@app.get("/admin/gaps", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def view_gaps(request: Request):
    gaps = []
    try:
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM knowledge_gaps WHERE status = 'pending' ORDER BY frequency DESC")
        gaps = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        logging.error(f"Error cargando gaps: {e}")
    return templates.TemplateResponse(request=request, name="admin/gaps.html", context={"gaps": gaps, "active_section": "control"})

@app.get("/admin/gaps/resolve/{gap_id}", dependencies=[Depends(verify_admin)])
async def resolve_gap(gap_id: int):
    try:
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
        conn.execute("UPDATE knowledge_gaps SET status = 'resolved' WHERE id = ?", (gap_id,))
        conn.commit()
        conn.close()
    except: pass
    return RedirectResponse(url="/admin/gaps", status_code=303)

@app.get("/admin/audit", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def view_audit(request: Request):
    logs = []
    try:
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 100")
        logs = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        logging.error(f"Error cargando auditoría: {e}")
    return templates.TemplateResponse(request=request, name="admin/audit.html", context={"logs": logs, "active_section": "control"})

if __name__ == "__main__":
    import uvicorn
    # Obtener el puerto de la variable de entorno, por defecto 8000
    port_env = int(os.getenv("PORT", 8000))
    # En producción (VPS) el reload debe ser False para evitar reinicios por cambios en la BD
    uvicorn.run("src.main:app", host="0.0.0.0", port=port_env, reload=False)
