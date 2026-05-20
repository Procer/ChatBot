import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any

from fastapi import FastAPI, Request, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import uvicorn
from dotenv import load_dotenv

# Importaciones SaaS Módulo por Módulo
from src.database.session import get_db, SessionLocal
from src.database.models import Client, ClientSettings, Conversation
from src.database.analytics_engine_saas import log_message, log_token_usage, mark_human_intervention
from src.agents.graph_saas import app as chatbot_app

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

# Locks para evitar Race Conditions por Usuario
user_locks: Dict[str, asyncio.Lock] = {}

def get_user_lock(user_id: str) -> asyncio.Lock:
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()
    return user_locks[user_id]

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

async def send_whatsapp_message_saas(client_id: int, user_id: str, message: str):
    """Envía un mensaje de texto vía Green-API leyendo credenciales de SQL Server."""
    try:
        db = SessionLocal()
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings or not settings.whatsapp_instance_id: return None
        
        import httpx
        url = f"https://api.green-api.com/waInstance{settings.whatsapp_instance_id}/sendMessage/{settings.whatsapp_token}"
        payload = {"chatId": user_id, "message": message}
        
        async with httpx.AsyncClient() as http_client:
            res = await http_client.post(url, json=payload, timeout=20.0)
            data = res.json()
            return data.get('idMessage')
    except Exception as e:
        logging.error(f"[SaaS Envio] Error: {e}")
        return None
    finally:
        db.close()

async def process_bot_response(client_id: int, user_id: str, user_text: str, platform: str, attachment_data: dict = None):
    """Orquestador principal que conecta el Webhook con LangGraph."""
    async with get_user_lock(user_id):
        print(f"\n[SaaS Process] Iniciando respuesta para cliente {client_id}, usuario {user_id}...")
        
        try:
            # 1. Registrar Mensaje de Usuario
            log_message(client_id, user_id, "user", user_text)
            
            # 2. Configuración para LangGraph (El Muro Multi-Cliente)
            config = {"configurable": {"thread_id": user_id, "client_id": client_id}}
            
            from langchain_core.messages import HumanMessage
            inputs = {"messages": [HumanMessage(content=user_text)]}
            
            # 3. Invocar Inteligencia Artificial
            final_state = chatbot_app.invoke(inputs, config=config)
            
            # 4. Enviar Respuesta
            if "messages" in final_state and len(final_state["messages"]) > 0:
                bot_msg = final_state["messages"][-1].content
                if bot_msg:
                    wa_id = await send_whatsapp_message_saas(client_id, user_id, bot_msg)
                    log_message(client_id, user_id, "bot", bot_msg, wa_id=wa_id)
                    
            # 5. Calcular Tokens (Simulado para demostración)
            log_token_usage(client_id, user_id, "gpt-4o-mini", 100, 50)
            
        except Exception as e:
            logging.error(f"[SaaS Process] Falla Crítica: {e}")

# ==========================================
# INICIO DE SERVIDOR
# ==========================================

if __name__ == "__main__":
    print("🚀 Iniciando Servidor Multi-Tenant SaaS (ZSG-Bot-iA)")
    # Ejecutamos en el puerto 8001 para no pisar el servidor legacy (8000)
    uvicorn.run("src.main_saas:app", host="0.0.0.0", port=8001, reload=True)
