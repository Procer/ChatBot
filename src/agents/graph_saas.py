import logging
import os
import json
import sys
from typing import TypedDict, Annotated, List, Union
from datetime import datetime
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # src/agents
SRC_DIR = os.path.dirname(BASE_DIR) # src
ROOT_DIR = os.path.dirname(SRC_DIR) # raíz del proyecto

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings, HarmBlockThreshold, HarmCategory
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import ToolNode

# --- SQLAlchemy ---
from sqlalchemy.orm import Session
from src.database.session import SessionLocal
from src.database.models import Client, ClientSettings, UserProfile, KnowledgeGap, Alert, Knowledge, Submission
from src.database.forms_saas import process_form_completion

load_dotenv()
AI_PROVIDER = os.getenv("AI_PROVIDER", "google").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if AI_PROVIDER == "openai" and OPENAI_API_KEY:
    embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
else:
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=GOOGLE_API_KEY)

# --- NUEVO: AgentState SaaS ---
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    thread_id: str
    client_id: int  # <-- MURO MULTI-CLIENTE
    onboarding_active: bool
    form_topic: str
    fields_to_collect: List[str]
    collected_data: dict
    storage_dest: str

# --- Helpers SaaS ---
def get_user_profile(client_id: int, user_id: str):
    try:
        db = SessionLocal()
        profile = db.query(UserProfile).filter_by(client_id=client_id, user_phone=str(user_id)).first()
        return profile.full_name if profile else None
    except Exception as e:
        logging.error(f"Error recuperando perfil SaaS: {e}")
        return None
    finally:
        db.close()

def save_user_profile(client_id: int, user_id: str, full_name: str):
    try:
        db = SessionLocal()
        profile = db.query(UserProfile).filter_by(client_id=client_id, user_phone=str(user_id)).first()
        if profile:
            profile.full_name = full_name
        else:
            profile = UserProfile(client_id=client_id, user_phone=str(user_id), full_name=full_name)
            db.add(profile)
        db.commit()
        return True
    except Exception as e:
        logging.error(f"Error guardando perfil SaaS: {e}")
        return False
    finally:
        db.close()

def registrar_vacio_conocimiento(client_id: int, query: str):
    try:
        db = SessionLocal()
        gap = db.query(KnowledgeGap).filter_by(client_id=client_id, topic=query.strip()).first()
        if gap:
            gap.frequency += 1
            gap.status = 'pending'
        else:
            db.add(KnowledgeGap(client_id=client_id, topic=query.strip()))
        db.commit()
    except Exception as e:
        logging.warning(f"Error registrando gap en SaaS: {e}")
    finally:
        db.close()

# --- HERRAMIENTAS SAAS ---

@tool
def buscar_info_empresa(query: str, config: RunnableConfig):
    """Busca información oficial en el RAG."""
    client_id = config.get("configurable", {}).get("client_id")
    if not client_id: return json.dumps({"error": "No client ID in config"})
    
    try:
        vector_db = Chroma(persist_directory="chroma_db", embedding_function=embeddings)
        # ⚠️ CRITICO: Chroma no es SQL, requiere que filtremos por metadata
        results = vector_db.similarity_search(query, k=3, filter={"client_id": client_id})
        if not results: 
            registrar_vacio_conocimiento(client_id, query)
            return json.dumps({"error": "No results found", "content": "No encontré información."})
        
        chunks = [{"content": doc.page_content, "metadata": doc.metadata} for doc in results]
        return json.dumps({
            "status": "success",
            "full_context": "\n---\n".join([d.page_content for d in results]),
            "debug_chunks": chunks
        })
    except Exception as e: 
        return json.dumps({"error": str(e)})

@tool
def solicitar_asistencia_humana(motivo: str, config: RunnableConfig):
    """Notifica a un humano."""
    client_id = config.get("configurable", {}).get("client_id")
    try:
        db = SessionLocal()
        db.add(Alert(client_id=client_id, motivo=motivo))
        db.commit()
        return "Asesor notificado."
    except Exception as e:
        return "Error al notificar."
    finally:
        db.close()

@tool
def iniciar_onboarding_tramite(topic: str, thread_id: str, config: RunnableConfig):
    """Activa la recolección de datos para un trámite."""
    client_id = config.get("configurable", {}).get("client_id")
    try:
        db = SessionLocal()
        search_topic = topic.lower().strip()
        
        # 1. Buscar el trámite en SQL Server
        all_kb = db.query(Knowledge).filter_by(client_id=client_id).all()
        match = None
        for k in all_kb:
            kb_topic = k.topic.lower()
            if search_topic in kb_topic or kb_topic in search_topic:
                match = k
                break
                
        if not match:
            return json.dumps({"status": "error", "message": f"No encontré el trámite '{topic}'."})
            
        real_topic = match.topic
        fields_str = match.form_fields
        has_form = match.has_form
        storage_dest = match.storage_dest or "database"

        # 2. Verificar si ya tiene sumisión previa
        prev_sub = db.query(Submission).filter_by(client_id=client_id, thread_id=thread_id, topic=real_topic).order_by(Submission.created_at.desc()).first()
        
        if not fields_str or fields_str.lower() == 'none' or not has_form:
            return json.dumps({"status": "info_only", "message": f"El tema '{real_topic}' no requiere formulario."})

        import re as _re
        raw_fields = [f.strip(" .*") for f in _re.split(r',(?![^(]*\))', fields_str) if f.strip()]
        clean_fields = ["Nombre del Cliente"] + raw_fields
        seen = set()
        final_fields = [x for x in clean_fields if not (x in seen or seen.add(x))]
        
        response_data = {
            "status": "activated",
            "topic": real_topic,
            "fields": final_fields,
            "storage": storage_dest
        }

        if prev_sub:
            response_data["has_previous_data"] = True
            try:
                data = json.loads(prev_sub.payload_json)
                response_data["previous_data_summary"] = str(list(data.keys()))
            except: pass
            response_data["message"] = f"ATENCIÓN: El usuario YA TIENE un trámite registrado. Preguntale si quiere USAR LOS DATOS ANTERIORES para el nuevo turno o si prefiere cargarlos de nuevo."

        return json.dumps(response_data)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})
    finally:
        db.close()

@tool
def registrar_dato_tramite(campo: str, valor: str):
    """Registra un dato específico de un trámite."""
    return json.dumps({"status": "recorded", "campo": campo.strip(" .*"), "valor": valor})

@tool
def registrar_nombre_usuario(nombre_completo: str):
    """Registra el nombre y apellido real del usuario."""
    return json.dumps({"status": "profile_update", "full_name": nombre_completo})

# (Tools temporales para scheduling hasta migrar scheduling.py)
@tool
def consultar_estado_tramite(numero_seguimiento: str):
    """Consulta estado del trámite."""
    return "Módulo de turnos en migración."

@tool
def cancelar_mi_turno():
    """Cancela el turno."""
    return "SOLICITUD_CANCELACION_TURNO"

@tool
def consultar_disponibilidad(fecha: str):
    """Consulta horarios."""
    return "Módulo de turnos en migración."

@tool
def agendar_turno(fecha: str, hora: str, motivo: str, thread_id: str):
    """Reserva un turno."""
    return "Módulo de turnos en migración."

tools = [buscar_info_empresa, solicitar_asistencia_humana, iniciar_onboarding_tramite, registrar_dato_tramite, consultar_disponibilidad, agendar_turno, registrar_nombre_usuario, consultar_estado_tramite, cancelar_mi_turno]
tool_node = ToolNode(tools)

if AI_PROVIDER == "openai" and OPENAI_API_KEY:
    llm_with_tools = ChatOpenAI(model="gpt-4o-mini", temperature=0.2).bind_tools(tools)
else:
    llm_with_tools = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash", 
        temperature=0.1,
        google_api_key=GOOGLE_API_KEY,
        safety_settings={
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        }
    ).bind_tools(tools)


def call_model(state: AgentState):
    t_id = state.get("thread_id", "unknown")
    client_id = state.get("client_id")
    onboarding_active = state.get("onboarding_active", False)
    collected_data = state.get("collected_data", {})
    fields_to_collect = state.get("fields_to_collect", [])
    
    if not client_id:
        return {"messages": [SystemMessage(content="Error Interno: client_id no proporcionado al LLM.")]}
        
    db = SessionLocal()
    try:
        client = db.query(Client).filter_by(id=client_id).first()
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        
        db_name = get_user_profile(client_id, t_id)
        if db_name and "Nombre del Cliente" not in collected_data:
            collected_data["Nombre del Cliente"] = db_name
            
        user_name = collected_data.get("Nombre del Cliente")
        
        bot_name = "Bot"
        company_name = client.business_name if client else "La Empresa"
        system_prompt = settings.bot_system_prompt if settings and settings.bot_system_prompt else f"Sos {bot_name}, el asistente de {company_name}."
        
        system_prompt += f"\n- Tu ID de chat actual es: {t_id}.\n"
        
        company_info = f"""
### 🏢 DATOS OFICIALES DE LA EMPRESA:
- Nombre: {company_name}
- Horarios de Atención: {settings.working_hours if settings else 'No especificados'}
"""
        system_prompt = company_info + "\n\n" + system_prompt
        
        now = datetime.now()
        date_context = f"""
### 🕒 CONTEXTO TEMPORAL:
- Fecha y hora actual: {now.strftime("%A, %d de %B de %Y %H:%M")}
"""
        system_prompt = date_context + "\n\n" + system_prompt
        
        identity_rule = f"""
### 🎭 REGLA DE IDENTIDAD:
- Usuario actual: {user_name or 'DESCONOCIDO'}.
"""
        system_prompt = identity_rule + "\n\n" + system_prompt
        
        # Onboarding Logic
        if onboarding_active:
            if "Nombre del Cliente" not in fields_to_collect:
                fields_to_collect.insert(0, "Nombre del Cliente")

            missing = [f for f in fields_to_collect if f not in collected_data]
            if missing:
                current_field = missing[0]
                system_prompt += f"\n### 📝 GESTIÓN DE TRÁMITE: {state.get('form_topic')}\n"
                system_prompt += f"**FALTAN ESTOS DATOS:** {', '.join(missing)}\n"
                system_prompt += f"**SIGUIENTE DATO A PEDIR:** '{current_field}'.\n"
                system_prompt += f"""
### 🧠 REGLAS CRÍTICAS DE EXTRACCIÓN (MAPEADO INTELIGENTE):
1. **EXTRACCIÓN INMEDIATA (OBLIGATORIO):** En cuanto detectes un dato en el mensaje, usá 'registrar_dato_tramite'.
2. **SIEMPRE USA HERRAMIENTAS:** No confirmes los datos solo con texto.
"""
            else:
                system_prompt += "\n### ✅ TRÁMITE COMPLETADO\n"
        else:
            system_prompt += """
### ℹ️ REGLAS DE INFORMACIÓN Y TRÁMITES:
1. **INFORMACIÓN PRIMERO:** Brindá la info.
2. **INICIO DE TRÁMITE:** Solo ofrécelo si tiene la etiqueta `[TIENE_FORMULARIO]`.
"""

        # Inyección de Conocimiento Multi-Cliente
        kb = db.query(Knowledge).filter_by(client_id=client_id).all()
        kb_text = ""
        for r in kb:
            has_media = " [CON_ARCHIVO]" if r.media_path else ""
            has_form_tag = " [TIENE_FORMULARIO]" if r.has_form else " [SOLO_INFORMACION]"
            kb_text += f"- {r.topic}{has_media}{has_form_tag}: {r.content} (Campos: {r.form_fields})\n"
        
        system_prompt += f"\n\n### CONOCIMIENTO OFICIAL:\n{kb_text}"
        
    finally:
        db.close()

    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    response = llm_with_tools.invoke(messages)
    
    return {
        "messages": [response], 
        "thread_id": t_id,
        "client_id": client_id,
        "onboarding_active": onboarding_active,
        "fields_to_collect": fields_to_collect,
        "collected_data": collected_data
    }

def state_manager(state: AgentState):
    new_state = {}
    collected_data = state.get("collected_data", {}).copy()
    t_id = state.get("thread_id")
    client_id = state.get("client_id")
    
    for msg in reversed(state["messages"]):
        if isinstance(msg, ToolMessage):
            try:
                data = json.loads(msg.content)
                if data.get("status") == "activated":
                    new_state["onboarding_active"] = True
                    new_state["form_topic"] = data["topic"]
                    new_state["fields_to_collect"] = data["fields"]
                    new_state["collected_data"] = {}
                    new_state["storage_dest"] = data["storage"]
                elif data.get("status") == "profile_update":
                    name = data.get("full_name")
                    save_user_profile(client_id, t_id, name)
                    collected_data["Nombre del Cliente"] = name
                    new_state["collected_data"] = collected_data
                elif data.get("status") == "recorded":
                    campo = data.get("campo").strip(" .*")
                    valor = data.get("valor")
                    
                    if campo in collected_data:
                        existente = str(collected_data[campo])
                        if valor not in existente:
                            collected_data[campo] = f"{existente}, {valor}"
                    else:
                        collected_data[campo] = valor
                    
                    new_state["collected_data"] = collected_data
            except Exception as e:
                continue
        if isinstance(msg, HumanMessage): break

    is_active = new_state.get("onboarding_active", state.get("onboarding_active", False))
    if is_active:
        fields = new_state.get("fields_to_collect", state.get("fields_to_collect", []))
        data_keys_norm = {k.lower().strip(): k for k in collected_data.keys()}
        
        missing = []
        for f in fields:
            f_norm = f.lower().strip()
            if f_norm not in data_keys_norm or not str(collected_data[data_keys_norm[f_norm]]).strip():
                missing.append(f)

        if fields and not missing:
            final_thread_id = t_id or "unknown_user"
            
            process_form_completion(
                client_id=client_id,
                thread_id=final_thread_id,
                topic=new_state.get("form_topic", state.get("form_topic")),
                data=collected_data,
                storage_dest=new_state.get("storage_dest", state.get("storage_dest", "database"))
            )
            new_state["onboarding_active"] = False
            new_state["fields_to_collect"] = []
            new_state["form_topic"] = None
            new_state["collected_data"] = {} 
            
    return new_state

def should_continue(state: AgentState):
    last_msg = state["messages"][-1]
    if last_msg.tool_calls: return "tools"
    return "manager"

def manager_should_continue(state: AgentState):
    if isinstance(state["messages"][-1], ToolMessage):
        return "agent"
    return END

workflow = StateGraph(AgentState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", tool_node)
workflow.add_node("manager", state_manager)

workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "manager": "manager"})
workflow.add_edge("tools", "manager")
workflow.add_conditional_edges("manager", manager_should_continue, {"agent": "agent", END: END})

import sqlite3
# El checkpointer MANTIENE SQLite para no quebrar la lógica nativa de LangGraph
db_path_checkpoints = os.path.join(ROOT_DIR, "checkpoints.sqlite")
conn = sqlite3.connect(db_path_checkpoints, check_same_thread=False, timeout=30)
memory = SqliteSaver(conn)
app = workflow.compile(checkpointer=memory)
