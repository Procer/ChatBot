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

# 1. CONFIGURACIÓN ESTRATÉGICA DE RUTAS
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) 
ROOT_DIR = os.path.dirname(BASE_DIR)

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

load_dotenv(os.path.join(ROOT_DIR, ".env"))

# 2. IMPORTACIÓN SEGURA DEL CEREBRO (GRAFO)
try:
    from src.agents.graph import app as chatbot_app, extract_text
    print("[INFO] Cerebro del Bot cargado correctamente.")
except Exception as e:
    print(f"[ERROR] No se pudo cargar el Cerebro del Bot: {e}")
    traceback.print_exc()
    chatbot_app = None

# 3. CONFIGURACIÓN EVOLUTION API
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").strip('"').rstrip('/')
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "").strip('"')
INSTANCE_NAME = os.getenv("EVOLUTION_INSTANCE_NAME", "").strip('"')

# --- AUTENTICACIÓN ---
security = HTTPBasic()
def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, os.getenv("ADMIN_USER", "admin"))
    correct_password = secrets.compare_digest(credentials.password, os.getenv("ADMIN_PASSWORD", "admin"))
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


MASTER_PROMPT = """### 🎭 PERSONALIDAD Y TONO:
- Sos un asistente de Rondan Escribanía. Tu tono es Argentino (Voseo), profesional pero muy cálido y humano.
- **PROHIBICIÓN ABSOLUTA:** No digas frases robóticas como "He registrado el dato", "He activado el trámite", "Dato guardado". Actuá como una persona real: "Buenísimo, ¿y el estado civil?", "Dale, anotado. ¿Me pasás el DNI del otro padre?".
- Evitá ser redundante. Si el usuario ya te dio un dato, pasá al siguiente de forma fluida.

### 👤 MANEJO DEL CLIENTE:
- Si no conocés el nombre de la persona con la que hablás, buscalo en el historial o preguntalo de forma amable al inicio: "¿Con quién tengo el gusto de hablar?".
- Una vez que lo sepas, usalo para dirigirte a él.

### 🛠️ REGLAS CRÍTICAS DE OPERACIÓN:
1. **BÚSQUEDA Y TRÁMITES:** Ante cualquier trámite, buscá info y activá el onboarding. Pero no digas "Activando onboarding", decí algo como: "Dale, te ayudo con eso. Para empezar, necesito unos datos...".
2. **FIDELIDAD:** No inventes datos. Si falta algo en un campo plural, pedilo específicamente.
3. **REGISTRO SILENCIOSO:** Usá 'registrar_dato_tramite' en segundo plano (con tus tools) sin anunciar que lo estás haciendo. La confirmación debe ser natural en tu charla.
4. **TODOS LOS CAMPOS:** Asegurate de pedir CADA UNO de los campos configurados. Si el trámite pide 5 cosas, no termines hasta tener las 5.

### 📝 FLUJO HUMANIZADO:
- Usuario: "Hola" -> Bot: "Hola! ¿Cómo va? Soy el asistente de Rondan. ¿Con quién tengo el gusto de hablar?"
- Usuario: "Juan" -> Bot: "Un placer Juan! ¿En qué puedo ayudarte hoy?"

### 📉 LÍMITES DE CONOCIMIENTO (GAPS):
- Si el usuario te pregunta por información, horarios, precios, servicios o trámites de los cuales NO tenés información en tu base de datos (RAG), NO INVENTES NADA.
- Es CRÍTICO que respondas de forma amable y EXACTAMENTE con esta frase en algún punto de tu respuesta: "Actualmente no tengo información sobre eso". No uses variaciones para que el sistema pueda detectarlo.
"""

# --- BASE DE DATOS DE CONFIGURACIÓN ---
def get_db_settings():
    db_path = os.path.join(ROOT_DIR, "settings.sqlite")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS knowledge (id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT, content TEXT, category TEXT, has_form INTEGER DEFAULT 0, form_fields TEXT, storage_dest TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS external_services (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS bot_pauses (user_id TEXT PRIMARY KEY, paused_until TIMESTAMP)")
    cursor.execute("CREATE TABLE IF NOT EXISTS chat_notes (thread_id TEXT PRIMARY KEY, notes TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS knowledge_gaps (id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT UNIQUE, frequency INTEGER DEFAULT 1, status TEXT DEFAULT 'pending')")
    
    defaults = [
        ('bot_name', 'Zárate IA'), ('bot_tone', 'argentino'),
        ('system_prompt', MASTER_PROMPT),
        ('company_name', 'Zárate System Group'), ('company_phone', '(03546) 420248'),
        ('company_email', 'contacto@zaratesystem.com.ar'), ('company_website', 'www.zaratesystem.com.ar'),
        ('company_address', 'Buenos Aires, Argentina'),
        ('whatsapp_enabled', '1'), ('telegram_enabled', '0'), ('telegram_token', ''),
        ('webhook_base_url', ''), ('test_mode_enabled', '0'), ('test_numbers', '')
    ]
    # Asegurar que todos los defaults existan
    cursor.executemany("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", defaults)
    
    # Insertar el prompt maestro por defecto solo si no existe.
    # Eliminamos el UPDATE forzado para que los cambios en el Admin persistan tras reiniciar.
    cursor.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('system_prompt', ?)", (MASTER_PROMPT,))
    
    conn.commit()
    return conn

# --- FUNCIONES DE ENVÍO ---
async def send_whatsapp_message(number: str, text: str):
    db = get_db_settings(); cursor = db.cursor()
    cursor.execute("SELECT value FROM config WHERE key = 'whatsapp_enabled'")
    row = cursor.fetchone()
    db.close()
    if row and row[0] == '0': return

    url = f"{EVOLUTION_API_URL}/message/sendText/{INSTANCE_NAME}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    payload = {"number": number, "options": {"delay": 1200, "presence": "composing"}, "textMessage": {"text": text}}
    async with httpx.AsyncClient() as client:
        try: await client.post(url, json=payload, headers=headers)
        except Exception as e:
            logging.error(f"Error silenciado previamente: {e}")

async def send_telegram_message(chat_id: str, text: str):
    print(f"[DEBUG] send_telegram_message: chat_id={chat_id}")
    db = get_db_settings(); cursor = db.cursor()
    cursor.execute("SELECT value FROM config WHERE key = 'telegram_token'")
    row_t = cursor.fetchone(); token = row_t[0] if row_t else None
    cursor.execute("SELECT value FROM config WHERE key = 'telegram_enabled'")
    row_e = cursor.fetchone(); enabled = row_e[0] if row_e else '0'
    db.close()
    
    if not token or enabled == '0': return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    async with httpx.AsyncClient() as client:
        try: 
            r = await client.post(url, json=payload)
            print(f"[DEBUG] Telegram Response for {chat_id}: {r.status_code} - {r.text}")
        except Exception as e:
            print(f"[DEBUG] Telegram Error for {chat_id}: {e}")
            logging.error(f"Error silenciado previamente: {e}")

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
    # En V2 la estructura debe estar envuelta en un objeto "webhook"
    url = f"{EVOLUTION_API_URL}/webhook/set/{INSTANCE_NAME}"
    headers = {"apikey": EVOLUTION_API_KEY}
    payload = {
        "webhook": {
            "url": f"{base_url}/webhook",
            "enabled": True,
            "webhook_by_events": False,
            "events": [
                "MESSAGES_UPSERT"
            ]
        }
    }
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload, headers=headers)
            logging.info(f"[SETUP] Webhook set: {r.status_code} - {r.text}")
            return r.status_code == 200 or r.status_code == 201
        except Exception as e:
            logging.error(f"[SETUP] Error webhook: {e}")
            return False

# --- PROXY EVOLUTION API ---
async def get_whatsapp_status():
    if not EVOLUTION_API_URL or not INSTANCE_NAME: return {"status": "disconnected", "error": "Faltan variables de entorno"}
    url = f"{EVOLUTION_API_URL}/instance/connectionStatus/{INSTANCE_NAME}"
    headers = {"apikey": EVOLUTION_API_KEY}
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                data = r.json()
                state = data.get("instance", {}).get("state") or data.get("state")
                return {"status": "open" if state == "open" else "disconnected"}
            return {"status": "disconnected"}
        except: return {"status": "disconnected"}

async def get_whatsapp_qr():
    if not EVOLUTION_API_URL or not INSTANCE_NAME: return {"status": "error", "message": "Faltan variables de entorno"}
    
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            # 1. Intentar conectar (pedir QR)
            url = f"{EVOLUTION_API_URL}/instance/connect/{INSTANCE_NAME}"
            r = await client.get(url, headers=headers)
            if r.status_code == 200: return r.json()
            
            # 2. Si no existe (404), intentar crearla
            if r.status_code == 404:
                create_url = f"{EVOLUTION_API_URL}/instance/create"
                # En V2, el token de la instancia puede ser el mismo apikey global para simplificar
                payload = {
                    "instanceName": INSTANCE_NAME,
                    "token": EVOLUTION_API_KEY,
                    "qrcode": True,
                    "integration": "WHATSAPP-BAILEYS"
                }
                cr = await client.post(create_url, json=payload, headers=headers)
                if cr.status_code != 201 and cr.status_code != 200:
                    return {"status": "error", "message": f"Error creando instancia: {cr.status_code} - {cr.text}"}
                
                # Configurar Webhook automáticamente si tenemos la URL base
                conn = get_db_settings(); cursor = conn.cursor()
                cursor.execute("SELECT value FROM config WHERE key = 'webhook_base_url'")
                base_url = cursor.fetchone()[0]
                conn.close()
                if base_url:
                    await setup_whatsapp_webhook(base_url.rstrip('/'))

                # Reintentar obtener QR
                r = await client.get(url, headers=headers)
                return r.json()
            
            return {"status": "error", "message": f"Error API: {r.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

async def whatsapp_logout():
    url = f"{EVOLUTION_API_URL}/instance/logout/{INSTANCE_NAME}"
    headers = {"apikey": EVOLUTION_API_KEY}
    async with httpx.AsyncClient() as client:
        try:
            r = await client.delete(url, headers=headers)
            return r.status_code == 200
        except: return False

# --- WEBHOOKS ---
app = FastAPI(title="Zárate IA | Sistema de Gestión Multicanal")
app.mount("/static", StaticFiles(directory=os.path.join(ROOT_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(ROOT_DIR, "templates"))

@app.post("/webhook")
async def evolution_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        logging.info(f"[WEBHOOK] Datos recibidos: {data.get('event')}")
        
        if data.get("event") != "messages.upsert": return JSONResponse({"status": "ignored"})
        msg_data = data.get("data", {})
        if msg_data.get("key", {}).get("fromMe"): return JSONResponse({"status": "ignored"})
        
        user_id = msg_data.get("key", {}).get("remoteJid", "")
        user_text = msg_data.get("message", {}).get("conversation") or msg_data.get("message", {}).get("extendedTextMessage", {}).get("text")
        
        logging.info(f"[WEBHOOK] Mensaje de {user_id}: {user_text}")
        
        # --- FILTRO MODO PRUEBAS ---
        conn = get_db_settings(); cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = 'test_mode_enabled'")
        test_mode = cursor.fetchone()[0] == '1'
        
        if test_mode:
            cursor.execute("SELECT value FROM config WHERE key = 'test_numbers'")
            whitelist_raw = cursor.fetchone()[0]
            whitelist = [n.strip() for n in whitelist_raw.split(",") if n.strip()]
            clean_id = user_id.split("@")[0]
            
            logging.info(f"[TEST MODE] Activo. Whitelist: {whitelist}. Remitente: {clean_id}")
            
            if clean_id not in whitelist and user_id not in whitelist:
                logging.warning(f"[TEST MODE] Ignorando mensaje de {user_id} (No en whitelist)")
                conn.close()
                return JSONResponse({"status": "test_mode_ignored"})
        
        conn.close()
        if not user_text: return JSONResponse({"status": "no_text"})
        
        logging.info(f"[WEBHOOK] Procesando respuesta para {user_id}...")
        background_tasks.add_task(process_bot_response, user_id, user_text, "whatsapp")
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logging.error(f"[WEBHOOK] Error: {e}")
        return JSONResponse({"status": "error"})

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        message = data.get("message")
        if not message: return JSONResponse({"status": "no_message"})
        chat_id = str(message.get("chat", {}).get("id"))
        user_text = message.get("text")
        if not user_text: return JSONResponse({"status": "no_text"})
        background_tasks.add_task(process_bot_response, chat_id, user_text, "telegram")
        return JSONResponse({"status": "ok"})
    except: return JSONResponse({"status": "error"})

async def process_bot_response(user_id: str, user_text: str, platform: str):
    print(f"\n[DEBUG] process_bot_response: user={user_id}, platform={platform}")
    if not chatbot_app:
        print("[DEBUG] chatbot_app is NONE. IA will not respond.")
        return
    try:
        from src.database.analytics_engine import log_token_usage, log_message
        print(f"[DEBUG] Logging message to analytics...")
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
                
        # Pasamos el thread_id tanto en la config como en el estado inicial para mayor robustez
        print(f"[DEBUG] Invocando LangGraph para {user_id}...")
        result = await run_in_threadpool(
            chatbot_app.invoke,
            {"messages": [HumanMessage(content=user_text)], "thread_id": user_id}, 
            config={"configurable": {"thread_id": user_id}}
        )
        print(f"[DEBUG] LangGraph completado para {user_id}.")
        last_msg = result["messages"][-1]
        bot_response = extract_text(last_msg.content)
        log_message(user_id, "bot", bot_response)
        
        # Detección de Knowledge Gap más robusta e inteligente
        lower_res = bot_response.lower()
        print(f"[DEBUG] Analizando respuesta para Gap: {lower_res[:100]}...")
        trigger_phrases = [
            "actualmente no tengo información",
            "no tengo información sobre",
            "no tengo información actualizada",
            "no tengo acceso a información",
            "no cuento con información",
            "no sé nada sobre",
            "no sabría decirte",
            "no tengo los detalles",
            "no puedo darte esa información",
            "no tengo datos",
            "no hay información",
            "en tiempo real sobre"
        ]
        
        has_phrases = any(p in lower_res for p in trigger_phrases)
        has_proximity = ("no tengo" in lower_res and ("información" in lower_res or "info" in lower_res))
        
        print(f"[DEBUG] has_phrases: {has_phrases}, has_proximity: {has_proximity}")
        
        if has_phrases or has_proximity:
            print(f"[DEBUG] Knowledge Gap detectado para query: {user_text}")
            try:
                conn_g = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
                conn_g.execute("INSERT INTO knowledge_gaps (topic, frequency, status) VALUES (?, 1, 'pending') ON CONFLICT(topic) DO UPDATE SET frequency = frequency + 1, status = 'pending'", (user_text,))
                conn_g.commit()
                conn_g.close()
                print(f"[DEBUG] Gap registrado exitosamente en DB.")
            except Exception as e:
                logging.error(f"Error registrando gap: {e}")
                
        if platform == "whatsapp": await send_whatsapp_message(user_id, bot_response)
        else: await send_telegram_message(user_id, bot_response)
        usage = getattr(last_msg, "usage_metadata", None)
        if usage:
            log_token_usage(user_id, getattr(last_msg, "response_metadata", {}).get("model_name", "unknown"), usage.get("input_tokens", 0), usage.get("output_tokens", 0))
    except Exception as e: print(f"Error bot: {e}")

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
        cursor_s.execute("SELECT client_name FROM proceedings WHERE tracking_number LIKE ?", (f"%{t_id[-4:]}%",))
        row = cursor_s.fetchone()
        if row and row['client_name']: name = row['client_name']
    
    if t_id == "playground": platform = "Playground"
    elif t_id.startswith("usuario_nuevo_"): platform = "Web"
    elif "@" in t_id: platform = "WhatsApp"
    elif len(t_id) == 36 and "-" in t_id: platform = "Consola"
    elif t_id.isdigit(): platform = "Telegram"
    else: platform = "Local"
    
    timestamp = get_time_from_uuid6(checkpoint_id)
    time_ago = format_time_ago(timestamp)
    
    is_active = False
    if timestamp:
        from datetime import datetime
        if (datetime.now().timestamp() - timestamp) < 900: is_active = True
            
    return {"id": t_id, "name": name, "platform": platform, "time_ago": time_ago, "is_active": is_active}

# --- RUTAS DE ADMINISTRACIÓN ---
@app.get("/")
async def root(): return RedirectResponse(url="/admin")

@app.get("/admin", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def admin_dashboard(request: Request):
    threads, stats, notifications = [], {"total_chats": 0, "total_alerts": 0}, []
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
            
            stats["total_chats"] = len(threads)
        notif_path = os.path.join(ROOT_DIR, "notifications.sqlite")
        if os.path.exists(notif_path):
            conn = sqlite3.connect(notif_path); conn.row_factory = sqlite3.Row
            cursor = conn.cursor(); cursor.execute("SELECT motivo, fecha FROM alerts ORDER BY id DESC LIMIT 5")
            notifications = [dict(row) for row in cursor.fetchall()]
            stats["total_alerts"] = len(notifications); conn.close()
    except Exception as e:
        logging.error(f"Error silenciado previamente: {e}")
    return templates.TemplateResponse(request=request, name="admin/index.html", context={"threads": threads, "stats": stats, "notifications": notifications})

@app.get("/admin/channels", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def view_channels(request: Request):
    conn = get_db_settings(); cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM config WHERE key IN ('whatsapp_enabled', 'telegram_enabled', 'telegram_token', 'webhook_base_url')")
    config = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    external_env = {"EVOLUTION_API_URL": EVOLUTION_API_URL, "INSTANCE_NAME": INSTANCE_NAME}
    return templates.TemplateResponse(request=request, name="admin/channels.html", context={"config": config, "external_env": external_env})

@app.post("/admin/channels/save", dependencies=[Depends(verify_admin)])
async def save_channels_config(request: Request, whatsapp_enabled: str = Form("0"), telegram_enabled: str = Form("0"), telegram_token: str = Form(""), webhook_base_url: str = Form("")):
    # Limpiamos la URL para evitar que incluyan rutas como /admin/channels
    if webhook_base_url:
        parsed_url = re.match(r"(https?://[^/]+)", webhook_base_url)
        if parsed_url:
            webhook_base_url = parsed_url.group(1)

    conn = get_db_settings()
    updates = [('whatsapp_enabled', whatsapp_enabled), ('telegram_enabled', telegram_enabled), ('telegram_token', telegram_token), ('webhook_base_url', webhook_base_url)]
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
            
            # Conexión a settings para buscar nombres
            conn_s = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
            conn_s.row_factory = sqlite3.Row
            cursor_s = conn_s.cursor()
            
            for r in raw_threads:
                threads.append(get_thread_metadata(str(r[0]), str(r[1]), cursor_s))
            conn_s.close()
    except Exception as e:
        logging.error(f"Error silenciado previamente: {e}")
    return templates.TemplateResponse(request=request, name="admin/history.html", context={"threads": threads})

@app.get("/admin/chat/{thread_id}", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def view_chat_session(request: Request, thread_id: str):
    messages = []
    metadata = {"name": "Usuario", "platform": "Desconocido", "is_active": False}
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        db_path = os.path.join(ROOT_DIR, "checkpoints.sqlite")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path, check_same_thread=False); memory = SqliteSaver(conn)
            
            # Fetch metadata
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(checkpoint_id) FROM checkpoints WHERE thread_id = ?", (thread_id,))
            row_cp = cursor.fetchone()
            last_cp = row_cp[0] if row_cp else None
            
            conn_s = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
            conn_s.row_factory = sqlite3.Row
            cursor_s = conn_s.cursor()
            metadata = get_thread_metadata(thread_id, last_cp, cursor_s)
            
            # Cargar notas
            cursor_s.execute("SELECT notes FROM chat_notes WHERE thread_id = ?", (thread_id,))
            note_row = cursor_s.fetchone()
            metadata["notes"] = note_row[0] if note_row else ""
            
            # Chequear estado real de pausa
            cursor_s.execute("SELECT paused_until FROM bot_pauses WHERE user_id = ?", (thread_id,))
            pause_row = cursor_s.fetchone()
            metadata["is_paused"] = False
            if pause_row:
                from datetime import datetime
                try:
                    paused_until = datetime.strptime(pause_row[0], "%Y-%m-%d %H:%M:%S")
                    if datetime.now() < paused_until: metadata["is_paused"] = True
                except: pass
                
            conn_s.close()
            
            # Cargar historial de analytics en lugar de state (así vemos todo, incluso las pausas)
            conn_a = sqlite3.connect(os.path.join(ROOT_DIR, "analytics.sqlite"))
            cursor_a = conn_a.cursor()
            cursor_a.execute("SELECT role, content FROM messages WHERE thread_id = ? ORDER BY timestamp ASC", (thread_id,))
            for row in cursor_a.fetchall():
                role, content = row
                messages.append({"type": "human" if role == "user" else "ai", "content": content})
            conn_a.close()
            conn.close() # CRITICAL: Release the lock on checkpoints.sqlite
    except Exception as e:
        logging.error(f"Error silenciado previamente: {e}")
    return templates.TemplateResponse(request=request, name="admin/chat.html", context={"thread_id": thread_id, "messages": messages, "metadata": metadata})

@app.post("/admin/chat/{thread_id}/send", dependencies=[Depends(verify_admin)])
async def send_chat_message(thread_id: str, message: str = Form(...), background_tasks: BackgroundTasks = None):
    print(f"[DEBUG] Admin sending message to {thread_id}")
    # Detectamos plataforma
    platform = "whatsapp" if "@" in thread_id else "telegram"
    print(f"[DEBUG] Detected platform for {thread_id}: {platform}")
    
    # Enviar directo
    if platform == "whatsapp": await send_whatsapp_message(thread_id, message)
    else: await send_telegram_message(thread_id, message)
    
    # Registrar en analytics y en la memoria del bot
    try:
        from src.database.analytics_engine import log_message
        log_message(thread_id, "admin", message)
    except Exception as e: print(f"Error update state admin: {e}")
    
    # Pausar
    from datetime import datetime, timedelta
    paused_until = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_settings()
    conn.execute("INSERT OR REPLACE INTO bot_pauses (user_id, paused_until) VALUES (?, ?)", (thread_id, paused_until))
    conn.commit()
    conn.close()
    
    return RedirectResponse(url=f"/admin/chat/{thread_id}", status_code=303)

@app.get("/admin/chat/resume/{thread_id}", dependencies=[Depends(verify_admin)])
async def resume_bot(thread_id: str):
    conn = get_db_settings()
    conn.execute("DELETE FROM bot_pauses WHERE user_id = ?", (thread_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/admin/chat/{thread_id}", status_code=303)

@app.post("/admin/chat/{thread_id}/notes", dependencies=[Depends(verify_admin)])
async def save_chat_notes(thread_id: str, notes: str = Form(""), background_tasks: BackgroundTasks = None):
    conn = get_db_settings()
    conn.execute("INSERT OR REPLACE INTO chat_notes (thread_id, notes) VALUES (?, ?)", (thread_id, notes))
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/admin/chat/{thread_id}", status_code=303)

@app.get("/admin/kanban", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def view_kanban(request: Request):
    grouped = {"Pendiente": [], "En_Proceso": [], "Listo_para_Firmar": [], "Finalizado": []}
    try:
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite")); conn.row_factory = sqlite3.Row
        cursor = conn.cursor(); cursor.execute("SELECT * FROM proceedings ORDER BY updated_at DESC")
        items = [dict(row) for row in cursor.fetchall()]; conn.close()
        for item in items:
            status = item['status']
            # Normalización para que coincida con las claves del diccionario 'grouped' (reemplazando espacios por guiones bajos)
            key = status.replace(" ", "_")
            if key in grouped: grouped[key].append(item)
    except Exception as e:
        logging.error(f"Error silenciado previamente: {e}")
    return templates.TemplateResponse(request=request, name="admin/kanban.html", context={"grouped": grouped})

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
async def view_appointments(request: Request):
    appointments = []
    try:
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite")); conn.row_factory = sqlite3.Row
        cursor = conn.cursor(); cursor.execute("SELECT * FROM appointments ORDER BY date DESC, time DESC")
        appointments = [dict(row) for row in cursor.fetchall()]; conn.close()
    except Exception as e:
        logging.error(f"Error silenciado previamente: {e}")
    return templates.TemplateResponse(request=request, name="admin/appointments.html", context={"appointments": appointments})

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
    return templates.TemplateResponse(request=request, name="admin/proceedings.html", context={"proceedings": proceedings})

@app.get("/admin/submissions", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def view_submissions(request: Request):
    submissions = []
    try:
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite")); conn.row_factory = sqlite3.Row
        cursor = conn.cursor(); cursor.execute("SELECT * FROM form_submissions ORDER BY created_at DESC")
        submissions = [dict(row) for row in cursor.fetchall()]; conn.close()
    except Exception as e:
        logging.error(f"Error silenciado previamente: {e}")
    return templates.TemplateResponse(request=request, name="admin/submissions.html", context={"submissions": submissions})

@app.get("/admin/config", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def config_panel(request: Request, sync_needed: bool = False):
    conn = get_db_settings(); cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM config"); config = {row[0]: row[1] for row in cursor.fetchall()}
    cursor.execute("SELECT key, value FROM external_services"); external = {row[0]: row[1] for row in cursor.fetchall()}
    cursor.execute("SELECT id, topic, content, category, has_form, form_fields, storage_dest FROM knowledge ORDER BY category ASC")
    knowledge_items = [{"id": r[0], "topic": r[1], "content": r[2], "category": r[3], "has_form": r[4], "form_fields": r[5], "storage_dest": r[6]} for r in cursor.fetchall()]
    conn.close(); data_files = []
    if os.path.exists(os.path.join(ROOT_DIR, "data")):
        for f in os.listdir(os.path.join(ROOT_DIR, "data")):
            if f.endswith((".pdf", ".txt")): data_files.append({"name": f})
    
    external_env = {"EVOLUTION_API_URL": EVOLUTION_API_URL, "INSTANCE_NAME": INSTANCE_NAME}
    return templates.TemplateResponse(request=request, name="admin/config.html", context={"config": config, "external": external, "knowledge_items": knowledge_items, "data_files": data_files, "sync_needed": sync_needed, "external_env": external_env})

# --- RUTAS DE VINCULACIÓN WHATSAPP ---
@app.get("/admin/whatsapp/status", dependencies=[Depends(verify_admin)])
async def whatsapp_status_route():
    return await get_whatsapp_status()

@app.get("/admin/whatsapp/connect", dependencies=[Depends(verify_admin)])
async def whatsapp_connect_route():
    return await get_whatsapp_qr()

@app.post("/admin/whatsapp/logout", dependencies=[Depends(verify_admin)])
async def whatsapp_logout_route():
    success = await whatsapp_logout()
    return {"status": "ok" if success else "error"}

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

# --- RUTAS PLAYGROUND ---
@app.get("/admin/playground", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
async def ia_playground(request: Request):
    return templates.TemplateResponse(request=request, name="admin/playground.html", context={})

@app.post("/admin/playground/send", dependencies=[Depends(verify_admin)])
async def playground_send(request: Request):
    try:
        data = await request.json()
        user_text = data.get("message")
        thread_id = data.get("thread_id", "playground")
        
        if not chatbot_app: return JSONResponse({"status": "error", "message": "Bot no cargado"})
        
        result = await run_in_threadpool(
            chatbot_app.invoke,
            {"messages": [HumanMessage(content=user_text)], "thread_id": thread_id}, 
            config={"configurable": {"thread_id": thread_id}}
        )
        
        last_msg = result["messages"][-1]
        bot_response = extract_text(last_msg.content)
        return {"status": "ok", "response": bot_response}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.post("/admin/config/save-all", dependencies=[Depends(verify_admin)])
async def save_all_config(
    bot_name: str = Form(...), bot_tone: str = Form(...), system_prompt: str = Form(...),
    company_name: str = Form(""), company_phone: str = Form(""), company_email: str = Form(""), company_website: str = Form(""), company_address: str = Form(""),
    whatsapp_enabled: str = Form("0"), telegram_enabled: str = Form("0"), telegram_token: str = Form(""), webhook_base_url: str = Form(""),
    test_mode_enabled: str = Form("0"), test_numbers: str = Form(""),
    scheduling_enabled: str = Form("0"), scheduling_provider: str = Form("local"), appointment_duration: str = Form("30"), working_hours: str = Form("")
):
    conn = get_db_settings()
    
    # 1. Limpiar Webhook URL
    if webhook_base_url:
        parsed_url = re.match(r"(https?://[^/]+)", webhook_base_url)
        if parsed_url: webhook_base_url = parsed_url.group(1)

    # 2. Configuración General (Tabla 'config')
    config_updates = [
        ('bot_name', bot_name), ('bot_tone', bot_tone), ('system_prompt', system_prompt),
        ('company_name', company_name), ('company_phone', company_phone), ('company_email', company_email),
        ('company_website', company_website), ('company_address', company_address),
        ('whatsapp_enabled', whatsapp_enabled), ('telegram_enabled', telegram_enabled),
        ('telegram_token', telegram_token), ('webhook_base_url', webhook_base_url),
        ('test_mode_enabled', test_mode_enabled), ('test_numbers', test_numbers)
    ]
    for k, v in config_updates:
        conn.execute("UPDATE config SET value = ? WHERE key = ?", (v, k))
    
    # 3. Servicios Externos (Tabla 'external_services')
    external_updates = [
        ('scheduling_enabled', scheduling_enabled),
        ('scheduling_provider', scheduling_provider),
        ('appointment_duration', appointment_duration),
        ('working_hours', working_hours)
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

    return RedirectResponse(url="/admin/config?success=1", status_code=303)

@app.get("/admin/knowledge/delete/{item_id}", dependencies=[Depends(verify_admin)])
async def delete_knowledge(item_id: int):
    conn = get_db_settings(); conn.execute("DELETE FROM knowledge WHERE id = ?", (item_id,))
    conn.commit(); conn.close()
    return RedirectResponse(url="/admin/config?sync_needed=1", status_code=303)

@app.post("/admin/system/reset-total", dependencies=[Depends(verify_admin)])
async def reset_total_system():
    try:
        conn = get_db_settings(); cursor = conn.cursor()
        cursor.execute("DELETE FROM knowledge")
        cursor.execute("DELETE FROM appointments")
        cursor.execute("DELETE FROM proceedings")
        cursor.execute("DELETE FROM form_submissions")
        cursor.execute("DELETE FROM bot_pauses")
        cursor.execute("DELETE FROM external_services")
        cursor.execute("SELECT key, value FROM config WHERE key IN ('whatsapp_enabled', 'telegram_enabled', 'telegram_token')")
        channels_config = cursor.fetchall()
        cursor.execute("DELETE FROM config")
        defaults = [('bot_name', 'Zárate IA'), ('bot_tone', 'argentino'), ('system_prompt', MASTER_PROMPT), ('company_name', 'Nueva Empresa'), ('company_phone', ''), ('company_email', ''), ('company_website', ''), ('company_address', '')]
        cursor.executemany("INSERT INTO config VALUES (?, ?)", defaults)
        for k, v in channels_config: cursor.execute("INSERT OR REPLACE INTO config VALUES (?, ?)", (k, v))
        conn.commit(); conn.close()
        conn_an = sqlite3.connect(os.path.join(ROOT_DIR, "analytics.sqlite"))
        conn_an.execute("DELETE FROM messages"); conn_an.execute("DELETE FROM token_usage"); conn_an.execute("DELETE FROM session_analytics")
        conn_an.commit(); conn_an.close()
        cp_path = os.path.join(ROOT_DIR, "checkpoints.sqlite")
        if os.path.exists(cp_path):
            conn_cp = sqlite3.connect(cp_path); cursor_cp = conn_cp.cursor()
            cursor_cp.execute("SELECT name FROM sqlite_master WHERE type='table'")
            for table in cursor_cp.fetchall(): cursor_cp.execute(f"DELETE FROM {table[0]}")
            conn_cp.commit(); conn_cp.close()
        data_dir = os.path.join(ROOT_DIR, "data")
        if os.path.exists(data_dir):
            for f in os.listdir(data_dir):
                try: os.remove(os.path.join(data_dir, f))
                except Exception as e:
                    logging.error(f"Error silenciado previamente: {e}")
        chroma_dir = os.path.join(ROOT_DIR, "chroma_db")
        if os.path.exists(chroma_dir): shutil.rmtree(chroma_dir, ignore_errors=True)
        return RedirectResponse(url="/admin/config?success_reset=1", status_code=303)
    except: return RedirectResponse(url="/admin/config", status_code=303)

@app.get("/admin/knowledge/get/{item_id}", dependencies=[Depends(verify_admin)])
async def get_knowledge_item(item_id: int):
    conn = get_db_settings(); cursor = conn.cursor()
    cursor.execute("SELECT id, topic, content, category, has_form, form_fields, storage_dest FROM knowledge WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "topic": row[1], "content": row[2], "category": row[3], "has_form": row[4], "form_fields": row[5], "storage_dest": row[6]}
    return JSONResponse({"status": "error", "message": "No encontrado"}, status_code=404)

@app.post("/admin/knowledge/update", dependencies=[Depends(verify_admin)])
async def update_knowledge(item_id: int = Form(...), topic: str = Form(...), content: str = Form(...), category: str = Form(...), has_form: int = Form(0), form_fields: str = Form(None), storage_dest: str = Form("database")):
    conn = get_db_settings()
    conn.execute("UPDATE knowledge SET topic = ?, content = ?, category = ?, has_form = ?, form_fields = ?, storage_dest = ? WHERE id = ?", (topic, content, category, has_form, form_fields, storage_dest, item_id))
    conn.commit(); conn.close()
    return RedirectResponse(url="/admin/config?sync_needed=1", status_code=303)

@app.post("/admin/knowledge/add", dependencies=[Depends(verify_admin)])
async def add_knowledge(topic: str = Form(...), content: str = Form(...), category: str = Form(...), has_form: int = Form(0), form_fields: str = Form(None), storage_dest: str = Form("database")):
    conn = get_db_settings(); conn.execute("INSERT INTO knowledge (topic, content, category, has_form, form_fields, storage_dest) VALUES (?, ?, ?, ?, ?, ?)", (topic, content, category, has_form, form_fields, storage_dest))
    conn.commit(); conn.close()
    return RedirectResponse(url="/admin/config?sync_needed=1", status_code=303)

@app.post("/admin/files/upload", dependencies=[Depends(verify_admin)])
async def upload_file(file: UploadFile = File(...)):
    data_dir = os.path.join(ROOT_DIR, "data")
    if not os.path.exists(data_dir): os.makedirs(data_dir)
    with open(os.path.join(data_dir, file.filename), "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    return RedirectResponse(url="/admin/config?sync_needed=1", status_code=303)

@app.get("/admin/files/delete/{filename}", dependencies=[Depends(verify_admin)])
async def delete_file(filename: str):
    file_path = os.path.join(ROOT_DIR, "data", filename)
    if os.path.exists(file_path): os.remove(file_path)
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
    return templates.TemplateResponse(request=request, name="admin/gaps.html", context={"gaps": gaps})

@app.get("/admin/gaps/resolve/{gap_id}", dependencies=[Depends(verify_admin)])
async def resolve_gap(gap_id: int):
    try:
        conn = sqlite3.connect(os.path.join(ROOT_DIR, "settings.sqlite"))
        conn.execute("UPDATE knowledge_gaps SET status = 'resolved' WHERE id = ?", (gap_id,))
        conn.commit()
        conn.close()
    except: pass
    return RedirectResponse(url="/admin/gaps", status_code=303)

if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
