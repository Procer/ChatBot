import logging
import os
import sqlite3
import json
import sys
from typing import TypedDict, Annotated, List, Union
from datetime import datetime
from dotenv import load_dotenv

# CONFIGURACIÓN DE RUTAS PARA IMPORTACIONES
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
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import ToolNode

# Cargar variables de entorno
load_dotenv()

# --- CONFIGURACIÓN DE MODELOS ---
AI_PROVIDER = os.getenv("AI_PROVIDER", "google").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if AI_PROVIDER == "openai" and OPENAI_API_KEY:
    embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
else:
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=GOOGLE_API_KEY)

# --- UTILIDADES ---

def extract_text(content: Union[str, list]) -> str:
    if isinstance(content, str): return content
    if isinstance(content, list):
        text = ""
        for part in content:
            if isinstance(part, str): text += part
            elif isinstance(part, dict) and "text" in part: text += part["text"]
        return text
    return str(content)

def get_setting(key: str):
    try:
        db_path = "settings.sqlite"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        val = cursor.fetchone()[0]
        conn.close()
        return val
    except Exception as e:
        logging.error(f"Error en tool: {e}")
        return None

from src.database.forms import process_form_completion

# --- CONFIGURACIÓN DE ESTADO ---
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    thread_id: str
    onboarding_active: bool
    form_topic: str
    fields_to_collect: List[str]
    collected_data: dict
    storage_dest: str

# --- HERRAMIENTAS (TOOLS) ---

@tool
def obtener_precio_servicio(servicio: str):
    """Consulta el precio de un servicio."""
    try:
        services_json = get_setting("services_json")
        if not services_json: return "No hay servicios configurados."
        precios = json.loads(services_json)
        for k, v in precios.items():
            if servicio.lower() in k.lower(): return f"El precio para {k} es: {v}"
        return f"No tengo precio exacto para {servicio}."
    except Exception as e:
        logging.error(f"Error en tool: {e}")
        return "Error al consultar precios."

def registrar_vacio_conocimiento(query: str):
    """Registra una pregunta que el bot no pudo responder para análisis administrativo."""
    try:
        # Usamos settings.sqlite para centralizar los gaps
        db_path = os.path.join(ROOT_DIR, "settings.sqlite")
        conn = sqlite3.connect(db_path)
        # Usamos topic como nombre de columna para consistencia con el panel admin
        conn.execute("INSERT INTO knowledge_gaps (topic, frequency, status) VALUES (?, 1, 'pending') ON CONFLICT(topic) DO UPDATE SET frequency = frequency + 1, status = 'pending'", (query.strip(),))
        conn.commit(); conn.close()
    except Exception as e:
        logging.warning(f"Error registrando gap en DB: {e}")

@tool
def buscar_info_empresa(query: str):
    """Busca información oficial en el RAG. Devuelve JSON con contenido y fuentes para depuración."""
    try:
        vector_db = Chroma(persist_directory="chroma_db", embedding_function=embeddings)
        results = vector_db.similarity_search(query, k=3)
        if not results: 
            registrar_vacio_conocimiento(query)
            return json.dumps({"error": "No results found", "content": "No encontré información."})
        
        chunks = []
        for doc in results:
            chunks.append({
                "content": doc.page_content,
                "metadata": doc.metadata
            })
            
        return json.dumps({
            "status": "success",
            "full_context": "\n---\n".join([d.page_content for d in results]),
            "debug_chunks": chunks
        })
    except Exception as e: 
        return json.dumps({"error": str(e)})

@tool
def solicitar_asistencia_humana(motivo: str):
    """Notifica a un humano."""
    try:
        conn = sqlite3.connect("notifications.sqlite")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO alerts (motivo, fecha) VALUES (?, ?)", (motivo, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        return "Asesor notificado."
    except Exception as e:
        logging.error(f"Error en tool: {e}")
        return "Error al notificar."

@tool
def iniciar_onboarding_tramite(topic: str, storage_dest: str = "database"):
    """
    Activa la recolección de datos para un trámite específico. 
    Busca automáticamente los campos requeridos en la base de conocimiento.
    """
    try:
        conn = sqlite3.connect("settings.sqlite")
        cursor = conn.cursor()
        # Buscamos el trámite por coincidencia de texto
        cursor.execute("SELECT topic, form_fields FROM knowledge WHERE topic LIKE ?", (f"%{topic}%",))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            real_topic = row[0]
            fields_str = row[1]
            # Limpiamos y convertimos a lista, incluyendo SIEMPRE el nombre del cliente
            clean_fields = ["Nombre del Cliente"] + [f.strip(" .*") for f in fields_str.split(",")]
            # Eliminar duplicados manteniendo orden
            seen = set()
            final_fields = [x for x in clean_fields if not (x in seen or seen.add(x))]
            
            return json.dumps({
                "status": "activated",
                "topic": real_topic,
                "fields": final_fields,
                "storage": storage_dest
            })
        return json.dumps({"status": "error", "message": f"No encontré el trámite '{topic}' en mi base de datos."})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@tool
def registrar_dato_tramite(campo: str, valor: str):
    """Registra un dato de forma silenciosa. NO lo anuncies al usuario."""
    return json.dumps({"status": "recorded", "campo": campo.strip(" .*"), "valor": valor})

from src.agents.scheduling import get_available_slots, book_appointment, cancel_appointment, get_proceeding_status, get_external_setting

# --- HERRAMIENTAS DE AGENDAMIENTO Y SEGUIMIENTO ---
# ... (rest of tools unchanged)

@tool
def consultar_estado_tramite(numero_seguimiento: str):
    """
    Consulta la situación actual de un trámite usando su número de seguimiento.
    """
    try:
        res = get_proceeding_status(numero_seguimiento)
        if not res: return f"No encontré ningún trámite con el número {numero_seguimiento}. Por favor, verificalo."
        
        info = f"Estado del trámite {numero_seguimiento} ({res['asunto']}):\n"
        info += f"- Situación: {res['estado']}\n"
        if res['notas']: info += f"- Detalle: {res['notas']}\n"
        info += f"- Última actualización: {res['actualizado']}"
        return info
    except Exception as e:
        return f"Error al consultar el trámite: {str(e)}"

@tool
def cancelar_mi_turno():
    """
    Cancela el turno que el usuario tiene agendado.
    """
    return "SOLICITUD_CANCELACION_TURNO"

@tool
def consultar_disponibilidad(fecha: str):
    """
    Consulta los horarios libres para una fecha. 
    fecha: Formato YYYY-MM-DD.
    """
    try:
        slots = get_available_slots(fecha)
        if not slots: return f"No hay turnos disponibles para el {fecha}."
        return f"Horarios libres para el {fecha}: " + ", ".join(slots)
    except Exception as e:
        return f"Error al consultar disponibilidad: {str(e)}"

@tool
def agendar_turno(fecha: str, hora: str, motivo: str):
    """
    Reserva un turno en una fecha y hora específica.
    fecha: YYYY-MM-DD, hora: HH:MM.
    """
    # En un entorno real, extraeríamos el nombre del cliente del historial o se lo pediríamos
    success = book_appointment("unknown_thread", fecha, hora, motivo)
    if success:
        return f"¡Listo! Turno agendado para el {fecha} a las {hora} por {motivo}."
    return "No pude agendar el turno. Es posible que ese horario ya se haya ocupado."

tools = [obtener_precio_servicio, buscar_info_empresa, solicitar_asistencia_humana, iniciar_onboarding_tramite, registrar_dato_tramite, consultar_disponibilidad, agendar_turno]
tool_node = ToolNode(tools)

# --- INICIALIZACIÓN DEL LLM ---
if AI_PROVIDER == "openai" and OPENAI_API_KEY:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2).bind_tools(tools)
else:
    llm = ChatGoogleGenerativeAI(
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

# --- NODOS ---

def call_model(state: AgentState):
    onboarding_active = state.get("onboarding_active", False)
    collected_data = state.get("collected_data", {})
    fields_to_collect = state.get("fields_to_collect", [])
    t_id = state.get("thread_id", "unknown_user")
    
    # BUSQUEDA DE NOMBRE: Si ya lo tenemos, lo usamos.
    user_name = collected_data.get("Nombre del Cliente")
    
    # 1. GENERACIÓN DEL PROMPT
    # Leemos el MASTER_PROMPT directamente desde la base de datos en TIEMPO REAL.
    # Así cualquier cambio en configuración o reglas aplica instantáneamente sin reiniciar consolas.
    system_prompt = get_setting("system_prompt")
    
    if not system_prompt:
        bot_name = get_setting("bot_name") or "Zárate IA"
        company_name = get_setting("company_name") or "Rondan Escribanía"
        system_prompt = f"""Sos {bot_name}, el asistente de {company_name}. 
Tu objetivo es ayudar a los clientes de forma CÁLIDA, AMABLE y 100% HUMANA.

### 🚫 REGLAS DE ORO (INCUMPLIMIENTO = ERROR CRÍTICO):
- PROHIBIDO decir "He registrado...", "He activado...", "Dato guardado", "Modo activo".
- PROHIBIDO usar lenguaje de sistema. Respondé como un secretario/a real por WhatsApp o Telegram.
- Si el usuario te da un dato, decí: "Dale", "Buenísimo", "Anotado", o simplemente hacé la siguiente pregunta.
- Si no sabés el nombre del cliente, PREGUNTALO antes de cualquier otra cosa: "¿Con quién tengo el gusto de hablar?".

### 📋 MODO TRÁMITE:"""
    
    if onboarding_active:
        # Aseguramos que 'Nombre del Cliente' esté en la lista si no lo está
        if "Nombre del Cliente" not in fields_to_collect:
            fields_to_collect.insert(0, "Nombre del Cliente")

        missing = [f for f in fields_to_collect if f not in collected_data]
        if missing:
            system_prompt += f"\nEstás gestionando el trámite: {state.get('form_topic')}\n"
            system_prompt += f"Datos que te faltan: {', '.join(missing)}\n"
            system_prompt += f"Instrucción: Pedí el próximo dato ('{missing[0]}') de forma natural."
            if user_name: system_prompt += f" Estás hablando con {user_name}."
        else:
            system_prompt += "\n¡Trámite terminado! Avisale al cliente que ya pasaste todo al equipo."
    else:
        system_prompt += "\nAtendé la consulta del usuario. Si es un trámite, buscalo con 'buscar_info_empresa' y activá el trámite con 'iniciar_onboarding_tramite' (pasá SOLO el nombre del trámite)."

    # Inyección de Conocimiento
    try:
        conn = sqlite3.connect("settings.sqlite")
        cursor = conn.cursor()
        cursor.execute("SELECT topic, content, form_fields FROM knowledge")
        kb = cursor.fetchall()
        kb_text = "\n".join([f"- {r[0]}: {r[1]} (Campos: {r[2]})" for r in kb])
        system_prompt += f"\n\n### CONOCIMIENTO OFICIAL:\n{kb_text}"
        conn.close()
    except Exception as e:
        logging.warning(f"Error silenciado: {e}")

    # 2. LLAMADA AL MODELO
    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    response = llm.invoke(messages)
    
    return {
        "messages": [response], 
        "thread_id": t_id,
        "onboarding_active": onboarding_active,
        "fields_to_collect": fields_to_collect,
        "collected_data": collected_data
    }

def state_manager(state: AgentState):
    print(f"\n[DEBUG] Ejecutando state_manager")
    new_state = {}
    collected_data = state.get("collected_data", {}).copy()
    
    # Intentamos recuperar el thread_id de diversas fuentes para evitar el "unknown_user"
    # LangGraph guarda la configuración en el contexto, pero aquí tratamos de obtenerlo del estado inicial
    t_id = state.get("thread_id")
    
    # Buscamos en los últimos mensajes si hubo llamadas a herramientas exitosas
    for msg in reversed(state["messages"]):
        if isinstance(msg, ToolMessage):
            try:
                data = json.loads(msg.content)
                if data.get("status") == "activated":
                    print(f" - Onboarding Activado: {data.get('topic')}")
                    new_state["onboarding_active"] = True
                    new_state["form_topic"] = data["topic"]
                    new_state["fields_to_collect"] = data["fields"]
                    new_state["collected_data"] = {}
                    new_state["storage_dest"] = data["storage"]
                elif data.get("status") == "recorded":
                    campo = data.get("campo").strip(" .*")
                    valor = data.get("valor")
                    print(f" - Dato Registrado: {campo} = {valor}")
                    
                    # MEJORA: Si el campo ya tiene un valor, acumulamos en lugar de sobrescribir
                    # Esto permite guardar múltiples DNIs o nombres en un solo campo si el bot los envía por separado
                    if campo in collected_data:
                        existente = str(collected_data[campo])
                        if valor not in existente: # Evitar duplicados por re-ejecución
                            collected_data[campo] = f"{existente}, {valor}"
                    else:
                        collected_data[campo] = valor
                        
                    new_state["collected_data"] = collected_data
            except Exception as e:
                logging.warning(f"Error parseando tool output: {e}")
                continue
        if isinstance(msg, HumanMessage): break

    # Verificación de cierre: ¿Tenemos todos los campos?
    is_active = new_state.get("onboarding_active", state.get("onboarding_active", False))
    if is_active:
        fields = new_state.get("fields_to_collect", state.get("fields_to_collect", []))
        data = collected_data
        
        missing = [f for f in fields if f not in data]
        if fields and not missing:
            print(f" - ¡TODOS LOS CAMPOS COMPLETOS! Disparando guardado...")
            
            # Si t_id sigue siendo None, es un problema de flujo. 
            # Como último recurso, no debería ser unknown si main.py lo pasa.
            final_thread_id = t_id or "unknown_user"
            
            process_form_completion(
                final_thread_id,
                new_state.get("form_topic", state.get("form_topic")),
                data,
                new_state.get("storage_dest", state.get("storage_dest", "database"))
            )
            new_state["onboarding_active"] = False
            new_state["collected_data"] = {} 
            collected_data = {} 
            
    return new_state

def should_continue(state: AgentState):
    last_msg = state["messages"][-1]
    if last_msg.tool_calls: return "tools"
    return "manager"

def manager_should_continue(state: AgentState):
    # Si el último mensaje es de una herramienta, volvemos al agente para que responda
    if isinstance(state["messages"][-1], ToolMessage):
        return "agent"
    return END

# --- GRAFO ---
workflow = StateGraph(AgentState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", tool_node)
workflow.add_node("manager", state_manager)

workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "manager": "manager"})
workflow.add_edge("tools", "manager")
workflow.add_conditional_edges("manager", manager_should_continue, {"agent": "agent", END: END})

conn = sqlite3.connect("checkpoints.sqlite", check_same_thread=False)
memory = SqliteSaver(conn)
app = workflow.compile(checkpointer=memory)
