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
        db_path = os.path.join(ROOT_DIR, "settings.sqlite")
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        val = cursor.fetchone()[0]
        conn.close()
        return val
    except Exception as e:
        return None

def get_user_profile(user_id: str):
    try:
        db_path = os.path.join(ROOT_DIR, "settings.sqlite")
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT full_name FROM user_profiles WHERE user_id = ? OR CAST(user_id AS TEXT) = ?", (user_id, str(user_id)))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logging.error(f"Error recuperando perfil: {e}")
        return None

def save_user_profile(user_id: str, full_name: str):
    try:
        db_path = os.path.join(ROOT_DIR, "settings.sqlite")
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute("INSERT INTO user_profiles (user_id, full_name) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET full_name = excluded.full_name", (user_id, full_name))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"Error guardando perfil: {e}")
        return False

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
        conn = sqlite3.connect(db_path, timeout=30)
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
        db_path = os.path.join(ROOT_DIR, "notifications.sqlite")
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO alerts (motivo, fecha) VALUES (?, ?)", (motivo, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        return "Asesor notificado."
    except Exception as e:
        logging.error(f"Error en tool: {e}")
        return "Error al notificar."

@tool
def iniciar_onboarding_tramite(topic: str, thread_id: str = "unknown"):
    """
    Activa la recolección de datos para un trámite específico. 
    Verifica si el usuario ya tiene datos previos para este trámite.
    """
    try:
        db_path = os.path.join(ROOT_DIR, "settings.sqlite")
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()
        
        # 1. Buscar el trámite en conocimiento
        search_topic = topic.lower().strip()
        cursor.execute("SELECT topic, form_fields, has_form, storage_dest FROM knowledge")
        rows = cursor.fetchall()
        
        match = None
        for r in rows:
            kb_topic = r[0].lower()
            if search_topic in kb_topic or kb_topic in search_topic:
                match = r
                break
        
        if not match:
            conn.close()
            return json.dumps({"status": "error", "message": f"No encontré el trámite '{topic}'."})

        real_topic = match[0]
        fields_str = match[1]
        has_form = match[2]
        storage_dest = match[3] or "database"

        # 2. Verificar si ya tiene una sumisión previa
        cursor.execute("SELECT data FROM form_submissions WHERE thread_id = ? AND topic = ? ORDER BY created_at DESC LIMIT 1", (thread_id, real_topic))
        prev_sub = cursor.fetchone()
        conn.close()

        if not fields_str or fields_str.lower() == 'none' or has_form == 0:
            return json.dumps({"status": "info_only", "message": f"El tema '{real_topic}' no requiere formulario."})

        clean_fields = ["Nombre del Cliente"] + [f.strip(" .*") for f in fields_str.split(",") if f.strip()]
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
            response_data["previous_data_summary"] = str(list(json.loads(prev_sub[0]).keys()))
            response_data["message"] = f"ATENCIÓN: El usuario YA TIENE un trámite de '{real_topic}' registrado. Preguntale si quiere USAR LOS DATOS ANTERIORES para el nuevo turno o si prefiere cargarlos de nuevo."

        return json.dumps(response_data)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


@tool
def registrar_dato_tramite(campo: str, valor: str):
    """Registra un dato específico de un trámite (DNI, Dirección, etc.). 
    Úsala de forma PROACTIVA en cuanto detectes el dato en el mensaje del usuario, 
    incluso si no lo habías pedido todavía."""
    return json.dumps({"status": "recorded", "campo": campo.strip(" .*"), "valor": valor})

@tool
def registrar_nombre_usuario(nombre_completo: str):
    """Registra el nombre y apellido real del usuario. Úsala inmediatamente cuando el usuario se identifique."""
    return json.dumps({"status": "profile_update", "full_name": nombre_completo})

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
    IMPORTANTE: Esta herramienta ya devuelve los horarios agrupados por MAÑANA y TARDE con sugerencias.
    NO los listes todos uno por uno en una lista de viñetas. Usa la estructura que te da la herramienta.
    fecha: Formato YYYY-MM-DD.
    """
    try:
        slots = get_available_slots(fecha)
        if not slots: return f"No hay turnos disponibles para el {fecha}."
        
        # Agrupar por Mañana (antes de las 13:00) y Tarde (después)
        manana = [s for s in slots if int(s.split(':')[0]) < 13]
        tarde = [s for s in slots if int(s.split(':')[0]) >= 13]
        
        res = f"### 🗓️ DISPONIBILIDAD PARA EL {fecha}:\n"
        if manana:
            res += f"✅ **MAÑANA:** {', '.join(manana)} (Hay {len(manana)} turnos disponibles)\n"
        else:
            res += f"❌ **MAÑANA:** No quedan turnos disponibles hoy por la mañana.\n"
            
        if tarde:
            res += f"✅ **TARDE:** {', '.join(tarde[:10])}{' y más horarios' if len(tarde) > 10 else ''} (Hay {len(tarde)} turnos disponibles)\n"
        else:
            res += f"❌ **TARDE:** No hay turnos disponibles para la tarde.\n"
            
        # Sugerencia proactiva (los 3 más cercanos)
        sugerencias = slots[:3]
        res += f"\n💡 **SUGERENCIA:** ¿Te vendría bien alguno de estos: {', '.join(sugerencias)}?"
        
        return res
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

tools = [obtener_precio_servicio, buscar_info_empresa, solicitar_asistencia_humana, iniciar_onboarding_tramite, registrar_dato_tramite, consultar_disponibilidad, agendar_turno, registrar_nombre_usuario]
tool_node = ToolNode(tools)

# --- INICIALIZACIÓN DEL LLM ---
if AI_PROVIDER == "openai" and OPENAI_API_KEY:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2).bind_tools(tools)
    llm_with_tools = llm
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
    
    # BUSQUEDA DE NOMBRE: Primero en estado local, luego en base de datos.
    db_name = get_user_profile(t_id)
    if db_name and "Nombre del Cliente" not in collected_data:
        collected_data["Nombre del Cliente"] = db_name
    
    user_name = collected_data.get("Nombre del Cliente")
    
    # 1. GENERACIÓN DEL PROMPT
    system_prompt = get_setting("system_prompt")
    if not system_prompt:
        bot_name = get_setting("bot_name") or "Zárate IA"
        company_name = get_setting("company_name") or "Rondan Escribanía"
        system_prompt = f"Sos {bot_name}, el asistente de {company_name}. Tu objetivo es ayudar a los clientes de forma CÁLIDA, AMABLE y 100% HUMANA."

    # Inyectar thread_id para uso de herramientas
    system_prompt += f"\n- Tu ID de chat actual es: {t_id}. Siempre pasá este ID al usar la herramienta 'iniciar_onboarding_tramite'.\n"

    # Inyectar Datos de la Empresa (Ficha)
    try:
        db_path = os.path.join(ROOT_DIR, "settings.sqlite")
        conn_e = sqlite3.connect(db_path, timeout=30)
        c_e = conn_e.cursor()
        c_e.execute("SELECT key, value FROM config WHERE key IN ('company_name', 'company_address', 'company_phone', 'company_email', 'company_website')")
        c_data = dict(c_e.fetchall())
        c_e.execute("SELECT value FROM external_services WHERE key = 'working_hours'")
        w_hours = c_e.fetchone()
        conn_e.close()
        
        company_info = f"""
### 🏢 DATOS OFICIALES DE LA EMPRESA:
- Nombre: {c_data.get('company_name', 'Rondan Escribanía')}
- Dirección: {c_data.get('company_address', 'No especificada')}
- Teléfono: {c_data.get('company_phone', 'No especificado')}
- Email: {c_data.get('company_email', 'No especificado')}
- Web: {c_data.get('company_website', 'No especificada')}
- Horarios de Atención: {w_hours[0] if w_hours else 'No especificados'}
"""
        system_prompt = company_info + "\n\n" + system_prompt
    except: pass

    # Inyectar Fecha y Hora Actual
    now = datetime.now()
    date_context = f"""
### 🕒 CONTEXTO TEMPORAL:
- Fecha y hora actual: {now.strftime("%A, %d de %B de %Y %H:%M")}
- Día de la semana: {now.strftime("%A")}
- IMPORTANTE: Si el usuario pide un turno para "hoy" o "mañana", usá esta fecha como referencia.
"""
    system_prompt = date_context + "\n\n" + system_prompt

    # Inyectar Regla de Identidad obligatoria
    identity_rule = f"""
### 🎭 REGLA DE IDENTIDAD:
- Usuario actual: {user_name or 'DESCONOCIDO'}.
- SI EL USUARIO ES 'DESCONOCIDO': Respondé a su duda técnica primero. Después, de forma muy natural y tranqui, pedile el nombre.
  Ejemplo: "¡Dale! Los requisitos son X e Y. Por cierto, ¿cómo es tu nombre? Así ya te agendo acá en la escribanía."
- SI YA CONOCÉS AL USUARIO ({user_name}): Saludalo por su nombre de entrada. Ej: "¡Hola {user_name}! ¿Cómo va todo?".
- PROHIBICIÓN: No uses frases como "con quién tengo el gusto", "registrar consulta", "tengo tu nombre registrado" ni nada que suene a call center. Hablá como un escribano/secretario amable."
"""
    
    system_prompt = identity_rule + "\n\n" + system_prompt
    
    if onboarding_active:
        # Aseguramos que 'Nombre del Cliente' esté en la lista si no lo está
        if "Nombre del Cliente" not in fields_to_collect:
            fields_to_collect.insert(0, "Nombre del Cliente")

        missing = [f for f in fields_to_collect if f not in collected_data]
        if missing:
            current_field = missing[0]
            system_prompt += f"\n### 📝 GESTIÓN DE TRÁMITE: {state.get('form_topic')}\n"
            system_prompt += f"**CAMPOS REQUERIDOS:** {', '.join(fields_to_collect)}\n"
            system_prompt += f"**FALTAN ESTOS DATOS:** {', '.join(missing)}\n"
            system_prompt += f"**SIGUIENTE DATO A PEDIR:** '{current_field}'.\n"
            
            system_prompt += f"""
### 🧠 REGLAS CRÍTICAS DE EXTRACCIÓN (MAPEADO INTELIGENTE):
1. **EXTRACCIÓN INDIVIDUALIZADA (OBLIGATORIO):** Si detectás varios datos del mismo tipo (ej: dos DNIs o dos nombres), NO los guardes juntos en un solo campo. Guardalos en sus campos correspondientes (DNI del Padre, DNI de la Madre, etc.).
2. **PROHIBICIÓN DE NOMBRES DE ARCHIVO:** NUNCA guardes el nombre técnico del archivo (ej: "tg_...pdf" o "image.jpg") como valor de un campo. El hecho de que se recibió un archivo ya queda registrado por el sistema. Los campos solo deben contener datos de texto legibles (nombres, documentos, estados, etc.).
3. **PROHIBICIÓN DE AGRUPAR:** Nunca uses comas o la palabra "y" para guardar dos valores en un solo campo si existen campos separados para cada uno. 
3. **EXTRACCIÓN PROACTIVA:** Si el usuario envía información que corresponde a CUALQUIERA de los campos requeridos (incluso si no es el que pediste), usá 'registrar_dato_tramite' inmediatamente.
4. **DETECCIÓN MÚLTIPLE:** Si en un solo mensaje el usuario da varios datos, llamá a 'registrar_dato_tramite' varias veces.
5. **INFERENCIA INTELIGENTE:** Mapeá el lenguaje natural a los campos técnicos.
   - "mi documento es..." -> DNI.
   - "vivo en..." -> Dirección.
   - "me llamo..." -> Nombre.
6. **VALORES COMPUESTOS:** Si el campo es inherentemente múltiple (ej: "DNI de los padres") y NO hay campos individuales, guardalos indicando a quién pertenece cada uno (ej: "Padre: 123, Madre: 456").
7. **NO TE TRABES:** Si el usuario no tiene un dato, decile: "No hay problema, seguimos con lo demás". Pasá al siguiente campo faltante de forma natural.
8. **ARCHIVOS:** Si falta un documento, aclará que puede enviarlo por este chat.
"""
            if user_name: system_prompt += f" Estás hablando con {user_name}."
        else:
            system_prompt += "\n### ✅ TRÁMITE COMPLETADO\n"
            system_prompt += "Ya tenés todos los datos necesarios. Avisale al cliente de forma muy amable que ya registraste todo y que el equipo se pondrá en contacto o, si corresponde, ofrecé agendar un turno ahora mismo."
    else:
        system_prompt += """
### ℹ️ REGLAS DE INFORMACIÓN Y TRÁMITES:
1. **INFORMACIÓN PRIMERO:** Si el usuario pregunta por un trámite (ej: "requisitos para X"), NO inicies la recolección de datos inmediatamente. Primero, brindá TODA la información y requisitos que tengas en tu conocimiento de forma clara y amable.
2. **INICIO DE TRÁMITE:** Solo después de dar la información, preguntá si quiere comenzar con el trámite ahora. Si dice que sí, usá 'iniciar_onboarding_tramite'.
3. **RECONOCIMIENTO DE DATOS:** Si el usuario te da un dato suelto (como su nombre) sin estar en un trámite, usá 'registrar_nombre_usuario'.

### 📂 ENVÍO DE DOCUMENTACIÓN:
- Si un tema del "CONOCIMIENTO OFICIAL" indica que tiene un archivo adjunto (marcado como [CON_ARCHIVO]), y considerás que es útil para el usuario, agregá la etiqueta `[SEND_FILE: nombre_del_tema]` exactamente así al final de tu mensaje. 
- Ejemplo: "Aquí tenés los requisitos. [SEND_FILE: Requisitos Carnet]"
- El sistema se encargará de enviar el archivo real. Vos solo poné la etiqueta.
"""

    # Inyección de Conocimiento
    try:
        db_path = os.path.join(ROOT_DIR, "settings.sqlite")
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()
        cursor.execute("SELECT topic, content, form_fields, media_path FROM knowledge")
        kb = cursor.fetchall()
        kb_text = ""
        for r in kb:
            has_media = " [CON_ARCHIVO]" if r[3] else ""
            kb_text += f"- {r[0]}{has_media}: {r[1]} (Campos: {r[2]})\n"
        
        system_prompt += f"\n\n### CONOCIMIENTO OFICIAL:\n{kb_text}"
        conn.close()
    except Exception as e:
        logging.warning(f"Error silenciado: {e}")

    # 2. LLAMADA AL MODELO
    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    response = llm_with_tools.invoke(messages)
    
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
                elif data.get("status") == "profile_update":
                    name = data.get("full_name")
                    print(f" - Actualizando perfil de usuario: {name} para thread {t_id}")
                    save_user_profile(t_id, name)
                    collected_data["Nombre del Cliente"] = name
                    new_state["collected_data"] = collected_data
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
        
        # Normalización para comparación insensible a mayúsculas/espacios
        data_keys_norm = {k.lower().strip(): k for k in collected_data.keys()}
        
        missing = []
        for f in fields:
            f_norm = f.lower().strip()
            # Si no está en las llaves normalizadas o el valor es vacío
            if f_norm not in data_keys_norm or not str(collected_data[data_keys_norm[f_norm]]).strip():
                missing.append(f)

        if fields and not missing:
            print(f" - ¡TODOS LOS CAMPOS COMPLETOS! Disparando guardado...")
            from src.database.forms import process_form_completion
            final_thread_id = t_id or "unknown_user"
            
            process_form_completion(
                final_thread_id,
                new_state.get("form_topic", state.get("form_topic")),
                collected_data,
                new_state.get("storage_dest", state.get("storage_dest", "database"))
            )
            new_state["onboarding_active"] = False
            new_state["fields_to_collect"] = []
            new_state["form_topic"] = None
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

db_path_checkpoints = os.path.join(ROOT_DIR, "checkpoints.sqlite")
conn = sqlite3.connect(db_path_checkpoints, check_same_thread=False, timeout=30)
memory = SqliteSaver(conn)
app = workflow.compile(checkpointer=memory)
