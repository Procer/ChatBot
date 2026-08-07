import logging
import os
import json
import sys
from typing import TypedDict, Annotated, List, Union
from datetime import datetime, timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # src/agents
SRC_DIR = os.path.dirname(BASE_DIR) # src
ROOT_DIR = os.path.dirname(SRC_DIR) # raíz del proyecto

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings, HarmBlockThreshold, HarmCategory
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage, AIMessage
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import ToolNode

# --- SQLAlchemy ---
from sqlalchemy.orm import Session
from src.database.session import SessionLocal
from src.database.models import Client, ClientSettings, UserProfile, KnowledgeGap, Alert, Knowledge, Submission, Appointment, Proceeding
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
    pending_pdf_path: str
    form_just_completed: bool

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

def registrar_vacio_conocimiento(client_id: int, query: str, thread_id: str = None):
    try:
        db = SessionLocal()
        gap = db.query(KnowledgeGap).filter_by(client_id=client_id, topic=query.strip()).first()
        if gap:
            gap.frequency += 1
            gap.status = 'pending'
        else:
            db.add(KnowledgeGap(client_id=client_id, topic=query.strip()))
        db.commit()
        
        if thread_id:
            from src.database.tagging_manager import assign_tag_by_name
            assign_tag_by_name(client_id, thread_id, "⚠️ Sin Responder")
    except Exception as e:
        logging.warning(f"Error registrando gap en SaaS: {e}")
    finally:
        db.close()

# --- HERRAMIENTAS SAAS ---

@tool
def buscar_info_empresa(query: str, config: RunnableConfig):
    """Busca información oficial detallada en el RAG / base de datos vectorial.
    Úsala para responder preguntas del usuario sobre requisitos de trámites, detalles de PDF/archivos adjuntos,
    información corporativa detallada, informes de sostenibilidad y cualquier duda técnica sobre la que no tengas información completa en tu contexto."""
    client_id = config.get("configurable", {}).get("client_id")
    if not client_id: return json.dumps({"error": "No client ID in config"})
    thread_id = config.get("configurable", {}).get("thread_id")
    
    try:
        from src.database.tagging_manager import get_user_role, assign_tag_by_name
        user_role = get_user_role(client_id, thread_id)
        
        vector_db = Chroma(persist_directory="chroma_db", embedding_function=embeddings)
        results = vector_db.similarity_search(query, k=3, filter={"client_id": client_id})
        
        def user_has_permission(u_role: str, req_role: str) -> bool:
            if not req_role or req_role.lower() in ["general", "publico", "público"]:
                return True
            if u_role.lower() == "gerente":
                return True
            return u_role.lower() == req_role.lower()
            
        filtered_results = []
        for doc in results:
            req_role = doc.metadata.get("required_role", "General")
            if user_has_permission(user_role, req_role):
                filtered_results.append(doc)
                tags_str = doc.metadata.get("tags_to_apply", "")
                if tags_str and thread_id:
                    for tag_name in [t.strip() for t in tags_str.split(",") if t.strip()]:
                        try:
                            assign_tag_by_name(client_id, thread_id, tag_name, assigned_by="knowledge_trigger")
                        except Exception as te:
                            logging.error(f"[Tagging] Error applying knowledge tag '{tag_name}': {te}")
                            
        if not filtered_results: 
            registrar_vacio_conocimiento(client_id, query, thread_id=thread_id)
            return json.dumps({"error": "No results found", "content": "No encontré información."})
            
        chunks = [{"content": doc.page_content, "metadata": doc.metadata} for doc in filtered_results]
        return json.dumps({
            "status": "success",
            "full_context": "\n---\n".join([d.page_content for d in filtered_results]),
            "debug_chunks": chunks
        })
    except Exception as e: 
        return json.dumps({"error": str(e)})

@tool
def solicitar_asistencia_humana(motivo: str, config: RunnableConfig):
    """Notifica a un humano."""
    client_id = config.get("configurable", {}).get("client_id")
    thread_id = config.get("configurable", {}).get("thread_id")
    try:
        db = SessionLocal()
        db.add(Alert(client_id=client_id, motivo=motivo))
        db.commit()
        
        if thread_id:
            try:
                from src.database.tagging_manager import assign_tag_by_name
                assign_tag_by_name(client_id, thread_id, "👤 Humano Requerido")
            except Exception as te:
                logging.error(f"[Tagging] Error applying tag in solicitar_asistencia_humana: {te}")
                
        return "Asesor notificado."
    except Exception as e:
        return "Error al notificar."
    finally:
        db.close()

@tool
def iniciar_onboarding_tramite(topic: str, config: RunnableConfig):
    """Activa la recolección de datos para un trámite. Debe usarse si el usuario quiere iniciar un tema con [TIENE_FORMULARIO]."""
    client_id = config.get("configurable", {}).get("client_id")
    thread_id = config.get("configurable", {}).get("thread_id")
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
            
        # --- Aplicar etiqueta ---
        if thread_id:
            try:
                from src.database.tagging_manager import assign_tag_by_name, remove_tag_by_name
                assign_tag_by_name(client_id, thread_id, "📝 Trámite Iniciado")
                remove_tag_by_name(client_id, thread_id, "🎓 Trámite Completado")
            except Exception as te:
                logging.error(f"[Tagging] Error applying tag in iniciar_onboarding_tramite: {te}")
            
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
def registrar_nombre_usuario(nombre_completo: str, config: RunnableConfig = None):
    """Registra el nombre y apellido real del usuario."""
    client_id = config.get("configurable", {}).get("client_id") if config else None
    thread_id = config.get("configurable", {}).get("thread_id") if config else None
    if client_id and thread_id:
        save_user_profile(client_id, thread_id, nombre_completo)
    return json.dumps({"status": "profile_update", "full_name": nombre_completo})

# --- Lógica de Negocio de Turnos y Expedientes (SaaS SQL Server) ---

def get_slots_disponibles_saas(client_id: int, date_str: str, tramite_nombre: str = None):
    from datetime import datetime, timedelta
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings:
            return []
            
        working_hours = None
        duration = None
        
        if tramite_nombre:
            from src.database.models import Knowledge
            search_topic = tramite_nombre.lower().strip()
            all_kb = db.query(Knowledge).filter_by(client_id=client_id, allow_scheduling=True).all()
            match = None
            for k in all_kb:
                kb_topic = k.topic.lower()
                if search_topic in kb_topic or kb_topic in search_topic:
                    match = k
                    break
            if match and match.scheduling_hours:
                working_hours = match.scheduling_hours
                duration = match.appointment_duration or settings.appointment_duration or 30
        
        if not working_hours:
            if settings and settings.enable_working_hours_for_scheduling:
                working_hours = settings.working_hours or "09:00-13:00, 16:00-20:00"
                duration = settings.appointment_duration or 30
            else:
                return []
                
        provider = settings.scheduling_provider or "local"
        calendar_id = settings.google_calendar_id or "primary"
        capacity = settings.scheduling_capacity or 1
        if tramite_nombre and match and hasattr(match, "scheduling_capacity") and match.scheduling_capacity is not None:
            capacity = match.scheduling_capacity
        enabled_days = (settings.scheduling_days or "mon,tue,wed,thu,fri").split(",")
        
        try:
            requested_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return []
            
        # weekday() -> 0: mon, 1: tue, 2: wed, 3: thu, 4: fri, 5: sat, 6: sun
        weekday_map = {
            0: "mon",
            1: "tue",
            2: "wed",
            3: "thu",
            4: "fri",
            5: "sat",
            6: "sun"
        }
        day_mapped = weekday_map[requested_date.weekday()]
        if day_mapped not in enabled_days:
            return []
            
        # Filtrar excepciones y bloqueos detallados
        from src.database.models import SchedulingException
        exceptions = db.query(SchedulingException).filter(
            SchedulingException.client_id == client_id,
            SchedulingException.date == date_str
        ).all()
        
        blocked_ranges = []
        for exc in exceptions:
            if not exc.start_time and not exc.end_time:
                # Bloqueo total de día completo (feriado, vacaciones, etc.)
                return []
            if exc.start_time and exc.end_time:
                blocked_ranges.append((exc.start_time.strip(), exc.end_time.strip()))
            
        import re
        ranges = []
        try:
            # Reemplazar " a " por "-" para soportar formatos como "de 08 a 13"
            normalized_str = re.sub(r'\s+a\s+', '-', working_hours)
            
            # Buscar patrones tipo "HH:MM-HH:MM"
            matches_hm = re.findall(r'(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})', normalized_str)
            if matches_hm:
                for start, end in matches_hm:
                    ranges.append((start.strip(), end.strip()))
            else:
                # Buscar patrones tipo "HH-HH" (ej: "de 08 a 13" -> "08-13")
                matches_h = re.findall(r'(\d{1,2})\s*-\s*(\d{1,2})', normalized_str)
                for start_h, end_h in matches_h:
                    ranges.append((f"{start_h.zfill(2)}:00", f"{end_h.zfill(2)}:00"))
        except Exception as parse_err:
            logging.error(f"Error parseando working_hours con regex: {parse_err}")
            
        if not ranges:
            try:
                for range_part in working_hours.split(","):
                    start_str, end_str = range_part.strip().split("-")
                    ranges.append((start_str.strip(), end_str.strip()))
            except Exception:
                return []
                
        all_slots = []
        for start_str, end_str in ranges:
            try:
                start_time = datetime.strptime(start_str, "%H:%M")
                end_time = datetime.strptime(end_str, "%H:%M")
                
                # Manejar rangos que cruzan o terminan en la medianoche (ej: 14:00-00:00)
                if end_time <= start_time:
                    end_time += timedelta(days=1)
                    
                current = start_time
                while current + timedelta(minutes=duration) <= end_time:
                    all_slots.append(current.strftime("%H:%M"))
                    current += timedelta(minutes=duration)
            except Exception as e:
                logging.error(f"Error generando slots para rango {start_str}-{end_str}: {e}")
                return []
            
        occupied = []
        if provider == "google":
            from src.agents.scheduling import get_calendar_service
            service = get_calendar_service()
            if service:
                time_min = f"{date_str}T00:00:00Z"
                time_max = f"{date_str}T23:59:59Z"
                try:
                    events_result = service.events().list(
                        calendarId=calendar_id, timeMin=time_min, timeMax=time_max,
                        singleEvents=True, orderBy='startTime'
                    ).execute()
                    events = events_result.get('items', [])
                    for event in events:
                        start = event['start'].get('dateTime', event['start'].get('date'))
                        if 'T' in start:
                            occupied_time = start.split('T')[1][:5]
                            occupied.append(occupied_time)
                except Exception as e:
                    logging.error(f"Error consultando Google Calendar: {e}")
        
        local_apps = db.query(Appointment).filter(
            Appointment.client_id == client_id,
            Appointment.date == date_str,
            Appointment.status != 'cancelled'
        ).all()
        for ap in local_apps:
            t = ap.time.strip() if ap.time else "00:00"
            if ":" in t:
                parts = t.split(":")
                t = f"{parts[0].zfill(2)}:{parts[1].zfill(2)}"
            else:
                try:
                    val = int(t)
                    t = f"{str(val).zfill(2)}:00"
                except ValueError:
                    pass
            occupied.append(t)
            
        # Argentina timezone (UTC-3)
        now_utc = datetime.utcnow()
        now = now_utc - timedelta(hours=3)
        is_today = date_str == now.strftime("%Y-%m-%d")
        current_time_str = now.strftime("%H:%M")
        
        available = []
        for s in all_slots:
            if is_today and s <= current_time_str:
                continue
            is_blocked = False
            for start, end in blocked_ranges:
                if start <= s < end:
                    is_blocked = True
                    break
            if is_blocked:
                continue
            if occupied.count(s) < capacity:
                available.append(s)
                
        return available
    finally:
        db.close()


def registrar_turno_saas(client_id: int, thread_id: str, date_str: str, time_str: str, reason: str, tramite_nombre: str = None):
    from datetime import datetime, timedelta
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings:
            return False
            
        provider = settings.scheduling_provider or "local"
        calendar_id = settings.google_calendar_id or "primary"
        
        duration = None
        if tramite_nombre:
            from src.database.models import Knowledge
            search_topic = tramite_nombre.lower().strip()
            all_kb = db.query(Knowledge).filter_by(client_id=client_id, allow_scheduling=True).all()
            match = None
            for k in all_kb:
                kb_topic = k.topic.lower()
                if search_topic in kb_topic or kb_topic in search_topic:
                    match = k
                    break
            if match and match.appointment_duration:
                duration = match.appointment_duration

        if not duration:
            duration = settings.appointment_duration or 30
            
        prof = db.query(UserProfile).filter_by(client_id=client_id, user_phone=thread_id).first()
        client_name = prof.full_name if (prof and prof.full_name) else "Cliente"
        
        google_success = True
        if provider == "google":
            from src.agents.scheduling import get_calendar_service
            service = get_calendar_service()
            if service:
                start_dt = f"{date_str}T{time_str}:00"
                try:
                    end_dt = (datetime.strptime(start_dt, "%Y-%m-%dT%H:%M:%S") + timedelta(minutes=duration)).isoformat()
                    event = {
                        'summary': f'Turno: {client_name}',
                        'description': f'Motivo: {reason}\nID Chat: {thread_id}',
                        'start': {'dateTime': start_dt, 'timeZone': 'America/Argentina/Buenos_Aires'},
                        'end': {'dateTime': end_dt, 'timeZone': 'America/Argentina/Buenos_Aires'},
                    }
                    service.events().insert(calendarId=calendar_id, body=event).execute()
                except Exception as e:
                    logging.error(f"Error registrando en Google Calendar: {e}")
                    google_success = False
            else:
                google_success = False
                
        new_app = Appointment(
            client_id=client_id,
            thread_id=thread_id,
            client_name=client_name,
            date=date_str,
            time=time_str,
            reason=reason,
            service=reason,
            status="confirmed"
        )
        db.add(new_app)
        db.commit()
        
        try:
            from src.database.tagging_manager import assign_tag_by_name, remove_tag_by_name
            assign_tag_by_name(client_id, thread_id, "🗓️ Turno Agendado")
            remove_tag_by_name(client_id, thread_id, "❌ Turno Cancelado")
        except Exception as te:
            logging.error(f"Error updating tagging in registrar_turno: {te}")
            
        return google_success
    except Exception as e:
        logging.error(f"Error reservando turno SaaS: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def cancelar_turno_saas(client_id: int, thread_id: str):
    db = SessionLocal()
    try:
        app = db.query(Appointment).filter(
            Appointment.client_id == client_id,
            Appointment.thread_id == thread_id,
            Appointment.status == 'confirmed'
        ).order_by(Appointment.date.asc(), Appointment.time.asc()).first()
        
        if app:
            app.status = 'cancelled'
            db.commit()
            
            try:
                from src.database.tagging_manager import assign_tag_by_name, remove_tag_by_name
                assign_tag_by_name(client_id, thread_id, "❌ Turno Cancelado")
                remove_tag_by_name(client_id, thread_id, "🗓️ Turno Agendado")
            except Exception as te:
                logging.error(f"Error updating tagging in cancelar_turno: {te}")
                
            return True
        return False
    except Exception as e:
        logging.error(f"Error cancelando turno SaaS: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def consultar_estado_proceedings_saas(client_id: int, numero_seguimiento: str):
    db = SessionLocal()
    try:
        proc = db.query(Proceeding).filter_by(client_id=client_id, tracking_number=numero_seguimiento).first()
        if proc:
            return {
                "cliente": proc.client_name,
                "asunto": proc.topic,
                "estado": proc.status,
                "notas": proc.notes,
                "actualizado": proc.updated_at.strftime("%Y-%m-%d %H:%M:%S") if proc.updated_at else ""
            }
        return None
    except Exception as e:
        logging.error(f"Error consultando expediente: {e}")
        return None
    finally:
        db.close()


@tool
def consultar_estado_tramite(numero_seguimiento: str, config: RunnableConfig):
    """Consulta el estado de un trámite o expediente usando su número de seguimiento."""
    client_id = config.get("configurable", {}).get("client_id")
    if not client_id:
        return "No se especificó un client_id válido."
        
    resultado = consultar_estado_proceedings_saas(client_id, numero_seguimiento)
    if resultado:
        return json.dumps({
            "status": "success",
            "asunto": resultado["asunto"],
            "estado": resultado["estado"],
            "notas": resultado["notas"],
            "actualizado": resultado["actualizado"]
        })
    return f"No se encontró ningún trámite con el número de seguimiento '{numero_seguimiento}'."


@tool
def cancelar_mi_turno(config: RunnableConfig):
    """Cancela el turno activo más próximo del usuario."""
    client_id = config.get("configurable", {}).get("client_id")
    thread_id = config.get("configurable", {}).get("thread_id")
    if not client_id or not thread_id:
        return "No se especificó la sesión del usuario."
        
    exito = cancelar_turno_saas(client_id, thread_id)
    if exito:
        return "Tu turno ha sido cancelado con éxito."
    return "No tenés ningún turno activo para cancelar."


@tool
def reprogramar_mi_turno(nueva_fecha: str, nueva_hora: str, config: RunnableConfig = None):
    """Reprograma el turno activo más próximo del usuario a una nueva fecha (YYYY-MM-DD) y hora (HH:MM)."""
    client_id = config.get("configurable", {}).get("client_id") if config else None
    thread_id = config.get("configurable", {}).get("thread_id") if config else None
    if not client_id or not thread_id:
        return "No se especificó la sesión de usuario."
        
    db = SessionLocal()
    try:
        app_obj = db.query(Appointment).filter(
            Appointment.client_id == client_id,
            Appointment.thread_id == thread_id,
            Appointment.status == 'confirmed'
        ).order_by(Appointment.date.asc(), Appointment.time.asc()).first()
        
        if not app_obj:
            return "No tenés ningún turno activo para reprogramar."
            
        tramite_original = None
        if app_obj.reason:
            if " - " in app_obj.reason:
                tramite_original = app_obj.reason.split(" - ")[0]
            else:
                tramite_original = app_obj.reason
                
        formatted_time = nueva_hora.strip()
        if ":" in formatted_time:
            parts = formatted_time.split(":")
            formatted_time = f"{parts[0].zfill(2)}:{parts[1].zfill(2)}"
        else:
            try:
                val = int(formatted_time)
                formatted_time = f"{str(val).zfill(2)}:00"
            except ValueError:
                pass
                
        slots = get_slots_disponibles_saas(client_id, nueva_fecha, tramite_original)
        if formatted_time not in slots:
            return f"El horario {formatted_time} no está disponible para la fecha {nueva_fecha}. Por favor, sugerile opciones disponibles al usuario de la siguiente lista: {', '.join(slots[:3])}."
            
        vieja_fecha = app_obj.date
        vieja_hora = app_obj.time
        app_obj.date = nueva_fecha
        app_obj.time = formatted_time
        db.commit()
        return f"Tu turno ha sido reprogramado con éxito. Anterior: {vieja_fecha} a las {vieja_hora} hs. Nuevo: {nueva_fecha} a las {formatted_time} hs."
    except Exception as e:
        logging.error(f"Error al reprogramar turno: {e}")
        db.rollback()
        return "Hubo un error al intentar reprogramar tu turno."
    finally:
        db.close()


def deducir_tramite_nombre(client_id: int, config: RunnableConfig) -> str:
    if not config:
        return None
    try:
        root_config = {
            "configurable": {
                "thread_id": config.get("configurable", {}).get("thread_id"),
                "client_id": client_id,
                "checkpoint_ns": ""
            }
        }
        state_snapshot = app.get_state(root_config)
        if not state_snapshot or not state_snapshot.values:
            return None
            
        msgs = state_snapshot.values.get("messages", [])
        
        # 1. Intentar obtenerlo del estado de la conversación (form_topic)
        form_topic = state_snapshot.values.get("form_topic")
        if form_topic:
            return form_topic
            
        # 2. Intentar buscar en ToolMessage recientes
        for m in reversed(msgs):
            if type(m).__name__ == "ToolMessage" and m.content:
                try:
                    data = json.loads(m.content)
                    if isinstance(data, dict):
                        if data.get("tramite"):
                            return data.get("tramite")
                        if data.get("tramite_nombre"):
                            return data.get("tramite_nombre")
                except:
                    pass
                    
        # 3. Intentar buscar en mensajes del historial usando normalización de números/ceros a la izquierda y palabras clave
        db_conn = SessionLocal()
        try:
            from src.database.models import Knowledge
            kb_topics = [k.topic for k in db_conn.query(Knowledge).filter_by(client_id=client_id, allow_scheduling=True).all()]
            
            def normalize_number_string(s: str) -> str:
                import re
                cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', s).lower()
                words = []
                for word in cleaned.split():
                    if word.isdigit():
                        words.append(str(int(word)))
                    else:
                        words.append(word)
                return " ".join(words)
                
            for m in reversed(msgs):
                if not m.content:
                    continue
                m_normalized = normalize_number_string(m.content)
                for topic in kb_topics:
                    topic_normalized = normalize_number_string(topic)
                    # Check substring match
                    if topic_normalized in m_normalized or m_normalized in topic_normalized:
                        return topic
                    # Word-level split match
                    topic_words = topic_normalized.split()
                    if len(topic_words) > 1 and all(w in m_normalized.split() for w in topic_words):
                        return topic
        finally:
            db_conn.close()
    except Exception as e:
        logging.error(f"Error en deducir_tramite_nombre: {e}")
    return None


@tool
def consultar_disponibilidad(fecha: str, tramite_nombre: str = None, config: RunnableConfig = None):
    """Consulta los horarios de turnos disponibles para una fecha específica (formato YYYY-MM-DD). Si el usuario solicita turno para un trámite o servicio específico, incluir tramite_nombre."""
    client_id = config.get("configurable", {}).get("client_id") if config else None
    if not client_id:
        return "No se especificó un client_id válido."
        
    # Deducir trámite de forma robusta si no viene
    if not tramite_nombre:
        tramite_nombre = deducir_tramite_nombre(client_id, config)
            
    slots = get_slots_disponibles_saas(client_id, fecha, tramite_nombre)
    
    # Obtener los turnos ya reservados por otros
    horarios_ocupados = []
    db_session = SessionLocal()
    try:
        from src.database.models import Appointment
        local_apps = db_session.query(Appointment).filter(
            Appointment.client_id == client_id,
            Appointment.date == fecha,
            Appointment.status != 'cancelled'
        ).all()
        for ap in local_apps:
            t = ap.time.strip() if ap.time else "00:00"
            if ":" in t:
                parts = t.split(":")
                t = f"{parts[0].zfill(2)}:{parts[1].zfill(2)}"
            horarios_ocupados.append(t)
    except Exception as err:
        logging.error(f"Error querying occupied slots in tool: {err}")
    finally:
        db_session.close()

    if slots:
        return json.dumps({
            "status": "success",
            "fecha": fecha,
            "tramite": tramite_nombre,
            "horarios_disponibles": slots,
            "horarios_ya_reservados_por_otros": horarios_ocupados
        })
    if tramite_nombre:
        return f"No hay turnos disponibles para el trámite '{tramite_nombre}' en la fecha {fecha}. Sugerir otra fecha."
    return f"No hay turnos disponibles para la fecha {fecha}. Por favor, sugerile al cliente que intente con otra fecha."


@tool
def agendar_turno(fecha: str, hora: str, motivo: str, tramite_nombre: str = None, nombre_usuario: str = None, config: RunnableConfig = None):
    """Registra y agenda un nuevo turno para el usuario en una fecha (YYYY-MM-DD) y hora (HH:MM) específicas. Si el usuario agenda para un trámite o servicio específico, incluir tramite_nombre. Si conoces el nombre y apellido del usuario, pasalo en nombre_usuario."""
    client_id = config.get("configurable", {}).get("client_id") if config else None
    thread_id = config.get("configurable", {}).get("thread_id") if config else None
    if not client_id or not thread_id:
        return "No se especificó la sesión de usuario."
        
    # Si se pasó el nombre del usuario directamente en la llamada, lo guardamos
    if nombre_usuario and nombre_usuario.strip():
        name_clean = nombre_usuario.strip()
        if name_clean.lower() not in ["cliente", "desconocido", "unknown", "sin nombre", "usuario"]:
            try:
                save_user_profile(client_id, thread_id, name_clean)
            except Exception as e:
                logging.error(f"Error al registrar nombre de usuario desde agendar_turno: {e}")
    # Si se está ejecutando registrar_nombre_usuario en paralelo en el mismo paso
    if config:
        try:
            root_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "client_id": client_id,
                    "checkpoint_ns": ""
                }
            }
            state_snapshot = app.get_state(root_config)
            if state_snapshot and state_snapshot.values:
                msgs = state_snapshot.values.get("messages", [])
                if msgs:
                    last_msg = msgs[-1]
                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        for tc in last_msg.tool_calls:
                            if tc.get("name") == "registrar_nombre_usuario":
                                parallel_name = tc.get("args", {}).get("nombre_completo")
                                if parallel_name and parallel_name.strip():
                                    name_clean = parallel_name.strip()
                                    if name_clean.lower() not in ["cliente", "desconocido", "unknown", "sin nombre", "usuario"]:
                                        save_user_profile(client_id, thread_id, name_clean)
        except Exception as e:
            logging.error(f"Error detectando registro de nombre en paralelo: {e}")

    # Verificar que el usuario tenga un perfil de nombre registrado antes de agendar
    db = SessionLocal()
    try:
        prof = db.query(UserProfile).filter_by(client_id=client_id, user_phone=thread_id).first()
        name_lower = prof.full_name.strip().lower() if prof and prof.full_name else ""
        if not prof or not prof.full_name or not prof.full_name.strip() or name_lower in ["cliente", "desconocido", "unknown", "sin nombre", "usuario"]:
            return "No se pudo agendar el turno. Para poder registrar el turno, por favor decile al usuario que primero te indique su nombre y apellido (mínimamente nombre) para agendarlo a su nombre."
    except Exception as e:
        logging.error(f"Error al verificar perfil de usuario en agendar_turno: {e}")
    finally:
        db.close()

    # Deducir tramite_nombre de forma robusta si no viene
    if not tramite_nombre:
        tramite_nombre = deducir_tramite_nombre(client_id, config)
            
    # Verificar si el slot todavía está disponible
    slots = get_slots_disponibles_saas(client_id, fecha, tramite_nombre)
    if hora not in slots:
        return f"El horario {hora} ya no está disponible para la fecha {fecha}. Por favor, consultá la disponibilidad nuevamente y sugerí otra hora."
        
    real_reason = motivo
    if tramite_nombre and tramite_nombre not in motivo:
        real_reason = f"{tramite_nombre} - {motivo}"
        
    exito = registrar_turno_saas(client_id, thread_id, fecha, hora, real_reason, tramite_nombre)
    if exito:
        return json.dumps({
            "status": "success",
            "message": f"Turno agendado con éxito para el {fecha} a las {hora} hs.",
            "detalle": real_reason
        })
    return "No se pudo agendar el turno. Por favor, intentá nuevamente."

CATALOG_LEAD_TOPIC = "Datos de Contacto - Catálogo"
DEFAULT_CATALOG_LEAD_FIELDS = ["Nombre del Cliente", "Email", "Teléfono"]

# Palabras de relleno gramatical o cantidades ("precios PARA 1500 boligrafos") que casi
# nunca están en el nombre de un producto. OJO: NO metemos acá jerga de personalización
# como "logo"/"full"/"color" -en este catálogo esa jerga SÍ puede ser información real
# del producto (el atributo "Impresion Logo" distingue productos "Un color" de "Full
# color"), así que filtrarla de la búsqueda hacía que el bot no pudiera encontrar ni
# distinguir el único bolígrafo que sí imprime a full color.
CATALOG_STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "con", "sin",
    "por", "para", "que", "cuanto", "cuánto", "cuanta", "cuesta", "cuestan", "precio", "precios",
    "quiero", "quisiera", "necesito", "dame", "hay", "tenes", "tenés", "tienen", "unidades",
    "unidad", "cantidad", "y", "o", "en", "me", "sale", "salen", "vale", "valen", "costaria",
    "costaría", "costo", "costos", "sobre", "info", "informacion", "información",
}


def _catalog_search_query(db, client_id: int, query: str, searchable_fields):
    """Arma un query de CatalogProduct ordenado por relevancia, en vez de exigir que
    TODAS las palabras coincidan (AND). El usuario suele describir lo que quiere con
    palabras que nunca van a estar literalmente en el catálogo (cantidades como "1500",
    plurales como "boligrafos" vs. el "Boligrafo" singular cargado en el nombre).

    Ranking: cualquier producto cuyo NOMBRE matchee al menos una palabra de la consulta
    recibe un bonus grande y fijo (no acumulativo por palabra), porque eso es lo que
    realmente identifica DE QUÉ TIPO de producto se trata. El resto de las palabras que
    matcheen (en cualquier campo, incluida descripción/atributos) solo suman como
    desempate menor. Esto evita que productos de OTRA categoría ganen por pura casualidad
    de tener mucho texto genérico de marketing repetido en el nombre (ej. varios llaveros
    de este catálogo tienen literalmente "impresa con logo full color" en el nombre, lo
    que antes los hacía ganarle a los bolígrafos reales en una búsqueda de "bolígrafo full
    color"). `searchable_fields` debe empezar con el campo `name`."""
    from sqlalchemy import or_, case
    from src.database.models import CatalogProduct

    name_field = searchable_fields[0]

    raw_words = [w.strip(".,;:()\"'").lower() for w in query.strip().split() if w.strip(".,;:()\"'")]
    words = [w for w in raw_words if w not in CATALOG_STOPWORDS]
    if not words:
        words = raw_words or [query.strip()]

    alpha_words = [w for w in words if not w.isdigit()]
    # Los números sueltos (cantidad pedida) casi nunca están en el nombre del producto;
    # si hay otras palabras que sí pueden identificarlo, no las usamos para el filtro/score
    # (así no le restan relevancia a productos que sí coinciden en todo lo demás).
    match_words = alpha_words if alpha_words else words

    or_conditions = []
    name_match_conditions = []
    word_match_terms = []
    for w in match_words:
        variants = {w}
        if w.endswith("s") and len(w) > 3:
            variants.add(w[:-1])
        else:
            variants.add(w + "s")
        name_match = or_(*[name_field.ilike(f"%{v}%") for v in variants])
        any_match = or_(*[field.ilike(f"%{v}%") for field in searchable_fields for v in variants])
        name_match_conditions.append(name_match)
        or_conditions.append(any_match)
        word_match_terms.append(case((any_match, 1), else_=0))

    name_bonus = case((or_(*name_match_conditions), 100), else_=0)
    word_match_count = sum(word_match_terms[1:], word_match_terms[0])
    relevance = name_bonus + word_match_count

    return db.query(CatalogProduct).filter(
        CatalogProduct.client_id == client_id,
        CatalogProduct.is_active == True,
        or_(*or_conditions)
    ).order_by(relevance.desc())

@tool
def consultar_catalogo(query: str, config: RunnableConfig):
    """Busca productos, precios y disponibilidad en el catálogo comercial.
    Úsala cuando el usuario pregunte por precios, stock, características o imágenes de productos en venta.
    IMPORTANTE sobre el parámetro 'query': incluí TODAS las palabras relevantes que dijo el usuario
    sobre qué producto quiere, no solo el nombre genérico. Si mencionó color, material, tipo de
    impresión del logo (ej. "full color" vs "un color") u otra característica distintiva, esas
    palabras van también en el query: son las que permiten encontrar el producto exacto entre
    varias variantes similares (ej. "bolígrafo full color" en vez de solo "bolígrafo").
    Si encuentras un producto con 'ruta_imagen', incluye exactamente la etiqueta [SEND_PRODUCT_IMAGE: <ruta_imagen>] en tu respuesta para enviarle la foto al usuario.
    Si la respuesta trae 'ruta_pdf', incluye exactamente la etiqueta [SEND_PRODUCT_PDF: <ruta_pdf>] para enviarle el presupuesto en PDF.
    Si el producto tiene 'reglas_precio' (precio por cantidad), calcula o deduce el precio correcto según la cantidad que pida el usuario.
    Cada resultado trae 'atributos_extra' con datos reales del producto (ej. tipo de impresión del logo):
    respondé SIEMPRE en base a ese valor real, nunca asumas ni repitas literalmente lo que pidió el
    usuario si el atributo dice otra cosa (ej. si pidió "full color" pero el atributo dice "Un color",
    tenés que aclararle que ESE producto es de un color, no ofrecerlo como si fuera full color)."""
    client_id = config.get("configurable", {}).get("client_id")
    thread_id = config.get("configurable", {}).get("thread_id")
    if not client_id: return json.dumps({"error": "No client ID"})

    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()

        # Modo "pedir datos antes de informar": si está activo y este contacto todavía
        # no completó el formulario de datos, activamos el mismo mecanismo de onboarding
        # genérico que usan los trámites (ver state_manager), en vez de responder la consulta.
        if settings and settings.catalog_require_lead_before_price:
            from src.database.models import CatalogRequest
            # Los datos de contacto del catálogo se guardan en CatalogRequest
            # (ver process_catalog_completion), NO en Submission -esa tabla es para
            # los trámites administrativos genéricos-. Antes esta verificación
            # consultaba Submission, así que nunca encontraba nada y el bot volvía a
            # pedir los datos de contacto en cada consulta, sin llegar nunca a
            # responder con el precio.
            prev_lead = db.query(CatalogRequest).filter_by(
                client_id=client_id, thread_id=thread_id
            ).first()
            if not prev_lead:
                try:
                    fields = json.loads(settings.catalog_lead_fields) if settings.catalog_lead_fields else None
                except Exception:
                    fields = None
                if not fields:
                    fields = DEFAULT_CATALOG_LEAD_FIELDS

                return json.dumps({
                    "status": "activated",
                    "topic": CATALOG_LEAD_TOPIC,
                    "fields": fields,
                    "storage": "database",
                    "producto_consulta": query,
                    "message": (
                        f"Antes de responder sobre precios o productos del catálogo, pedile amablemente al "
                        f"usuario estos datos (uno por vez o todos juntos): {', '.join(fields)}. Usá "
                        f"'registrar_dato_tramite' para cada dato que te dé. La consulta original del usuario "
                        f"era: '{query}'. Una vez completados los datos, continuá respondiendo esa consulta."
                    )
                })

        from src.database.models import CatalogProduct

        # Buscamos por palabras clave y ordenamos por relevancia (cuántas coinciden),
        # así "Boligrafo con mi logo full color" encuentra los bolígrafos aunque "logo"
        # o "full color" no estén literales en ningún producto (ver _catalog_search_query).
        searchable_fields = [
            CatalogProduct.name,
            CatalogProduct.description,
            CatalogProduct.sku,
            CatalogProduct.custom_attributes,
        ]
        products = _catalog_search_query(db, client_id, query, searchable_fields).limit(5).all()

        if not products:
            from src.database.catalog_requests import log_catalog_search
            log_catalog_search(client_id, thread_id, query, found=False)
            return json.dumps({"status": "no_results", "message": f"No se encontraron productos para '{query}'."})

        results = []
        for p in products:
            res = {
                "nombre": p.name,
                "sku": p.sku,
                "precio_base": p.price,
                "cantidad_minima": p.min_quantity,
                "stock": p.stock,
                "descripcion": p.description or ""
            }
            if p.price_rules:
                res["reglas_precio"] = p.price_rules
            if p.custom_attributes:
                res["atributos_extra"] = p.custom_attributes
            include_images = not settings or settings.catalog_include_images is not False
            if p.image_path and include_images:
                res["ruta_imagen"] = p.image_path
            results.append(res)

        from src.database.catalog_requests import log_catalog_search
        top = results[0]
        log_catalog_search(client_id, thread_id, query, found=True, results_count=len(results),
                            producto_nombre=top.get("nombre"), producto_sku=top.get("sku"))

        response_payload = {"status": "success", "resultados": results}

        # El presupuesto en PDF ya NO se manda en cada búsqueda: se genera y envía
        # automáticamente recién cuando el cliente confirma el pedido de un producto
        # puntual (ver iniciar_pedido_catalogo / process_form_completion).
        if settings and settings.catalog_response_style:
            instruccion = (
                "Usa la información para responder SIGUIENDO ESTRICTAMENTE las 'ESTILO DE RESPUESTA DEL CATÁLOGO' "
                "indicadas en tu configuración (cuántos productos mostrar, qué campos incluir, cuándo mandar imagen, etc.). "
                "Si según esas instrucciones corresponde enviar una imagen, escribí literalmente [SEND_PRODUCT_IMAGE: <ruta_imagen>]."
            )
        else:
            instruccion = "Usa la información para responder. Si el producto tiene 'ruta_imagen', DEBES escribir literalmente [SEND_PRODUCT_IMAGE: <ruta_imagen>] en tu texto."
        response_payload["instruccion"] = instruccion

        return json.dumps(response_payload)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})
    finally:
        db.close()

DEFAULT_CATALOG_ORDER_FIELDS = ["Cantidad", "Fecha de Entrega"]

def _buscar_producto_catalogo(db, client_id: int, query: str):
    """Busca un único producto por SKU exacto o por palabras (mismo motor que consultar_catalogo)."""
    from src.database.models import CatalogProduct

    exact = db.query(CatalogProduct).filter(
        CatalogProduct.client_id == client_id,
        CatalogProduct.is_active == True,
        CatalogProduct.sku == query.strip()
    ).first()
    if exact:
        return exact

    searchable_fields = [CatalogProduct.name, CatalogProduct.description, CatalogProduct.sku, CatalogProduct.custom_attributes]
    return _catalog_search_query(db, client_id, query, searchable_fields).first()

@tool
def iniciar_pedido_catalogo(producto: str, config: RunnableConfig):
    """Activa la toma de pedido de un producto del catálogo (cantidad, fecha de entrega, etc.).
    Úsala cuando el usuario exprese intención real de compra sobre un producto ya identificado
    (ej. "quiero comprar X", "hacéme el pedido", "dame 200 unidades"), no para una simple consulta de precio.
    IMPORTANTE sobre el parámetro 'producto': incluí TODAS las características relevantes que dijo
    el usuario (color, tipo de impresión del logo, material, etc.), no solo el nombre genérico -
    si hay varias variantes similares, esas palabras son las que permiten identificar la correcta
    (ej. "bolígrafo full color" en vez de solo "bolígrafo")."""
    client_id = config.get("configurable", {}).get("client_id")
    if not client_id: return json.dumps({"error": "No client ID"})

    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        prod = _buscar_producto_catalogo(db, client_id, producto)
        if not prod:
            return json.dumps({"status": "error", "message": f"No encontré el producto '{producto}' en el catálogo."})

        try:
            fields = json.loads(settings.catalog_order_fields) if settings and settings.catalog_order_fields else None
        except Exception:
            fields = None
        if not fields:
            fields = DEFAULT_CATALOG_ORDER_FIELDS

        message = (
            f"Estás tomando el pedido de '{prod.name}' (SKU: {prod.sku}). Pedile al usuario, uno por vez o "
            f"todos juntos, estos datos: {', '.join(fields)}. Para 'Cantidad' usá SIEMPRE la herramienta "
            f"'registrar_cantidad_pedido' (pasándole el sku '{prod.sku}'), y para 'Fecha de Entrega' usá SIEMPRE "
            f"'registrar_fecha_entrega_pedido'. Para cualquier otro dato usá 'registrar_dato_tramite'. "
            f"IMPORTANTE: ANTES de pedir esos datos, decile al usuario el precio de este producto (ver "
            f"'reglas_precio' de esta respuesta) calculando el tramo que corresponda si ya mencionó una "
            f"cantidad, o el rango completo si todavía no la dijo. Nunca sigas con el pedido sin haber "
            f"comunicado el precio."
        )
        if settings and settings.catalog_confirm_attributes and prod.custom_attributes:
            message += (
                f" IMPORTANTE: el atributo REAL de este producto es '{prod.custom_attributes}'. Comunicáselo "
                f"tal cual es, sin suponer ni afirmar otra cosa. Si algo que el usuario pidió antes (color, "
                f"tipo de impresión, etc.) NO coincide con este atributo real, decíselo explícitamente "
                f"(ej. 'este modelo imprime el logo a un solo color, no a full color') en vez de confirmar "
                f"como si coincidiera, y preguntale si igual lo quiere o prefiere otra opción. Solo si "
                f"coincide, confirmale explícitamente que este es el que quiere antes de cerrar el pedido."
            )

        response_payload = {
            "status": "activated",
            "topic": f"Pedido: {prod.name}",
            "fields": fields,
            "storage": "database",
            "producto_sku": prod.sku,
            "producto_nombre": prod.name,
            "message": message
        }
        if prod.price_rules:
            response_payload["reglas_precio"] = prod.price_rules
        elif prod.price:
            response_payload["precio_base"] = prod.price

        return json.dumps(response_payload)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})
    finally:
        db.close()

@tool
def registrar_cantidad_pedido(producto_sku: str, cantidad: int, config: RunnableConfig):
    """Registra la cantidad de un pedido de catálogo, validando la cantidad mínima del producto."""
    client_id = config.get("configurable", {}).get("client_id")
    if not client_id: return json.dumps({"error": "No client ID"})

    db = SessionLocal()
    try:
        from src.database.models import CatalogProduct
        prod = db.query(CatalogProduct).filter_by(client_id=client_id, sku=producto_sku).first()
        min_qty = prod.min_quantity if prod and prod.min_quantity else 1

        if cantidad < min_qty:
            return json.dumps({
                "status": "error",
                "message": f"La cantidad mínima para este producto es {min_qty}. Pedile al usuario que confirme una cantidad de al menos {min_qty} unidades."
            })

        response = {"status": "recorded", "campo": "Cantidad", "valor": str(cantidad)}
        if prod:
            from src.pricing import resolve_unit_price
            precio_unitario = resolve_unit_price(prod.price, prod.price_rules, cantidad)
            if precio_unitario:
                response["precio_unitario_calculado"] = precio_unitario
                response["subtotal_calculado"] = round(precio_unitario * cantidad, 2)
                response["instruccion"] = (
                    f"Comunicale al usuario EXACTAMENTE este precio unitario y subtotal (ya calculados, "
                    f"NO los recalcules vos): $ {precio_unitario} por unidad, subtotal $ {round(precio_unitario * cantidad, 2)} "
                    f"para {cantidad} unidades."
                )
        return json.dumps(response)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})
    finally:
        db.close()

@tool
def registrar_fecha_entrega_pedido(fecha: str, config: RunnableConfig):
    """Registra la fecha de entrega deseada de un pedido de catálogo (formato YYYY-MM-DD),
    validando el mínimo de días de anticipación configurado por el negocio."""
    client_id = config.get("configurable", {}).get("client_id")
    if not client_id: return json.dumps({"error": "No client ID"})

    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        min_lead_days = (settings.catalog_min_lead_days or 0) if settings else 0

        try:
            fecha_pedida = datetime.strptime(fecha.strip(), "%Y-%m-%d")
        except ValueError:
            return json.dumps({"status": "error", "message": f"La fecha '{fecha}' no tiene el formato YYYY-MM-DD. Volvé a calcularla usando el CONTEXTO TEMPORAL."})

        hoy = datetime.utcnow() - timedelta(hours=3)
        fecha_minima = hoy + timedelta(days=min_lead_days)

        if min_lead_days > 0 and fecha_pedida.date() < fecha_minima.date():
            return json.dumps({
                "status": "error",
                "message": (
                    f"Ese producto requiere un mínimo de {min_lead_days} días de anticipación. "
                    f"La fecha más próxima posible es {fecha_minima.strftime('%Y-%m-%d')}. Pedile al usuario que elija esa fecha u otra posterior."
                )
            })

        return json.dumps({"status": "recorded", "campo": "Fecha de Entrega", "valor": fecha.strip()})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})
    finally:
        db.close()

DOC_LOGIN_TOPIC_PREFIX = "Login Documento: "
DOC_SEARCH_TOPIC_PREFIX = "Búsqueda Documento: "

@tool
def buscar_documento(query: str, config: RunnableConfig):
    """Busca documentos (manuales, reglamentos, formularios, instructivos) por título o
    palabras clave, para enviárselos al usuario. NO analiza el contenido de los archivos,
    solo el título y las palabras clave configuradas. Solo debe usarse cuando el usuario
    pide explícitamente un documento/manual/reglamento (o cuando el sistema te indique
    con un 'REFUERZO DE BIBLIOTECA DE DOCUMENTOS' que corresponde buscar).
    Si el resultado trae 'status':'multiple', mostrale al usuario una lista NUMERADA solo
    con los títulos y esperá que elija uno antes de escribir cualquier etiqueta [SEND_DOC: ...].
    Si trae 'status':'success', y el documento responde lo que pidió el usuario, incluí
    literalmente la etiqueta [SEND_DOC: <id>] al final de tu respuesta.
    Si trae 'status':'activated', seguí el flujo de login indicado en 'message'."""
    client_id = config.get("configurable", {}).get("client_id")
    thread_id = config.get("configurable", {}).get("thread_id")
    if not client_id: return json.dumps({"error": "No client ID"})

    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings or not settings.feat_document_library:
            return json.dumps({"status": "error", "message": "La biblioteca de documentos no está habilitada para este cliente."})
    finally:
        db.close()

    from src.database.document_library import search_documents_candidates, log_document_search

    candidates = search_documents_candidates(client_id, thread_id, query, k=5)

    if not candidates:
        log_document_search(client_id, thread_id, query, found=False)
        return json.dumps({"status": "no_results", "message": f"No encontré ningún documento para '{query}'."})

    accessible = [c for c in candidates if c["accessible"]]
    log_document_search(client_id, thread_id, query, found=True, results_count=len(candidates),
                         document_title=candidates[0]["title"])

    if not accessible:
        blocked = candidates[0]
        segment_name = blocked["blocking_segment_name"]
        auth_mode = blocked["blocking_segment_auth_mode"]
        fields = ["Usuario", "Contraseña"] if auth_mode == "individual" else ["Contraseña"]
        return json.dumps({
            "status": "activated",
            "topic": f"{DOC_LOGIN_TOPIC_PREFIX}{segment_name}",
            "fields": fields,
            "storage": "database",
            "documento_consulta": query,
            "message": (
                f"El documento que busca el usuario pertenece a un segmento protegido ('{segment_name}'). "
                f"Pedile amablemente estos datos, uno por vez o todos juntos: {', '.join(fields)}. "
                f"Para 'Usuario' (si corresponde) usá 'registrar_dato_tramite', y para 'Contraseña' usá "
                f"SIEMPRE la herramienta 'registrar_clave_documento' (pasándole segmento='{segment_name}'). "
                f"La consulta original del usuario era: '{query}'. Una vez validado el acceso, volvé a "
                f"llamar a 'buscar_documento' con esa misma consulta."
            )
        })

    if len(accessible) == 1:
        doc = accessible[0]
        return json.dumps({
            "status": "success",
            "documento": {"id": doc["id"], "titulo": doc["title"], "descripcion": doc["description"]},
            "instruccion": "Si esto responde lo que pidió el usuario, incluí la etiqueta [SEND_DOC: <id>] al final de tu respuesta."
        })

    return json.dumps({
        "status": "multiple",
        "candidatos": [{"id": c["id"], "titulo": c["title"]} for c in accessible],
        "instruccion": "Mostrale al usuario una lista numerada SOLO con los títulos y esperá a que elija uno antes de escribir cualquier etiqueta [SEND_DOC: ...]."
    })

@tool
def registrar_clave_documento(segmento: str, clave: str, config: RunnableConfig, usuario: str = None):
    """Valida la contraseña (y usuario, si el segmento lo requiere) para acceder a un
    segmento protegido de la biblioteca de documentos. Se debe llamar con el nombre exacto
    del segmento indicado en el flujo de login."""
    client_id = config.get("configurable", {}).get("client_id")
    thread_id = config.get("configurable", {}).get("thread_id")
    if not client_id: return json.dumps({"error": "No client ID"})

    from src.database.document_library import validate_segment_credentials
    result = validate_segment_credentials(client_id, thread_id, segmento, clave, usuario=usuario)

    if result.get("status") != "success":
        return json.dumps({"status": "error", "message": result.get("message", "No se pudo validar el acceso.")})

    return json.dumps({"status": "recorded", "campo": "Contraseña", "valor": "••••••"})

@tool
def iniciar_busqueda_documento_segmento(query: str, segmento: str, config: RunnableConfig):
    """Activa la recolección de los datos configurados para buscar documentos de un segmento
    específico. Usala SOLO cuando el sistema te lo indique con un 'REFUERZO DE BÚSQUEDA POR
    SEGMENTO'. NO llames a 'buscar_documento' en ese mismo turno: una vez recolectados todos los
    datos, el sistema te va a pedir que la llames con la consulta combinada."""
    client_id = config.get("configurable", {}).get("client_id")
    if not client_id: return json.dumps({"error": "No client ID"})

    from src.database.document_library import get_segment_by_name
    db = SessionLocal()
    try:
        segment = get_segment_by_name(db, client_id, segmento)
        if not segment:
            return json.dumps({"status": "error", "message": f"No encontré el segmento '{segmento}'."})
        try:
            fields = [f.strip() for f in json.loads(segment.search_fields) if f and f.strip()] if segment.search_fields else []
        except Exception:
            fields = []
        if not fields:
            return json.dumps({"status": "error", "message": f"El segmento '{segmento}' no tiene datos configurados para pedir."})
        segment_name = segment.name
    finally:
        db.close()

    return json.dumps({
        "status": "activated",
        "topic": f"{DOC_SEARCH_TOPIC_PREFIX}{segment_name}",
        "fields": fields,
        "storage": "database",
        "documento_consulta": query,
        "message": (
            f"Para buscar el documento del segmento '{segment_name}' pedile estos datos al usuario, uno "
            f"por vez o todos juntos: {', '.join(fields)}. Usá 'registrar_dato_tramite' para cada uno. "
            f"La consulta original era: '{query}'."
        )
    })

@tool
def buscar_documento_en_segmento(query: str, segmento: str, config: RunnableConfig):
    """Busca UN ÚNICO documento dentro de un segmento específico, usando solo los datos puntuales
    ya recolectados (no la consulta/frase original que disparó el flujo). Se debe llamar SOLO al
    completar la recolección de datos activada por 'iniciar_busqueda_documento_segmento', con el
    texto EXACTO indicado por el sistema como 'query'. Nunca devuelve una lista: si hay resultado,
    es el documento puntual que corresponde a esos datos.
    Si trae 'status':'not_found', avisale al usuario que no encontraste un documento con esos datos.
    Si trae 'status':'activated', seguí el mismo flujo de login que con 'buscar_documento':
    'registrar_dato_tramite' para 'Usuario' y 'registrar_clave_documento' para 'Contraseña'.
    Si trae 'status':'success', incluí literalmente la etiqueta [SEND_DOC: <id>] al final de tu
    respuesta si el documento responde lo que pidió el usuario."""
    client_id = config.get("configurable", {}).get("client_id")
    thread_id = config.get("configurable", {}).get("thread_id")
    if not client_id: return json.dumps({"error": "No client ID"})

    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings or not settings.feat_document_library:
            return json.dumps({"status": "error", "message": "La biblioteca de documentos no está habilitada para este cliente."})
    finally:
        db.close()

    from src.database.document_library import get_segment_by_name, search_segment_document

    db2 = SessionLocal()
    try:
        segment = get_segment_by_name(db2, client_id, segmento)
    finally:
        db2.close()
    if not segment:
        return json.dumps({"status": "error", "message": f"No encontré el segmento '{segmento}'."})

    result = search_segment_document(client_id, thread_id, segment.id, query)

    if not result:
        return json.dumps({"status": "not_found", "message": f"No encontré ningún documento del segmento '{segmento}' con esos datos."})

    if result["status"] == "blocked":
        auth_mode = result["auth_mode"]
        fields = ["Usuario", "Contraseña"] if auth_mode == "individual" else ["Contraseña"]
        return json.dumps({
            "status": "activated",
            "topic": f"{DOC_LOGIN_TOPIC_PREFIX}{result['segment_name']}",
            "fields": fields,
            "storage": "database",
            "documento_consulta": query,
            "segmento_busqueda": result["segment_name"],
            "message": (
                f"El documento del segmento '{result['segment_name']}' está protegido. "
                f"Pedile amablemente estos datos, uno por vez o todos juntos: {', '.join(fields)}. "
                f"Para 'Usuario' (si corresponde) usá 'registrar_dato_tramite', y para 'Contraseña' usá "
                f"SIEMPRE la herramienta 'registrar_clave_documento' (pasándole segmento='{result['segment_name']}'). "
                f"Una vez validado el acceso, volvé a llamar a 'buscar_documento_en_segmento' con "
                f"segmento='{result['segment_name']}' y esta misma query: '{query}'."
            )
        })

    return json.dumps({
        "status": "success",
        "documento": {"id": result["id"], "titulo": result["title"], "descripcion": result["description"]},
        "instruccion": "Si esto responde lo que pidió el usuario, incluí la etiqueta [SEND_DOC: <id>] al final de tu respuesta."
    })

tools = [buscar_info_empresa, solicitar_asistencia_humana, iniciar_onboarding_tramite, registrar_dato_tramite, consultar_disponibilidad, agendar_turno, registrar_nombre_usuario, consultar_estado_tramite, cancelar_mi_turno, reprogramar_mi_turno, consultar_catalogo, iniciar_pedido_catalogo, registrar_cantidad_pedido, registrar_fecha_entrega_pedido, buscar_documento, registrar_clave_documento, iniciar_busqueda_documento_segmento, buscar_documento_en_segmento]
tool_node = ToolNode(tools)

# Herramientas de gestión de turnos: solo deben ofrecerse al LLM si el cliente tiene la
# funcionalidad de turnos habilitada (feat_appointments). Sin esto, el bot intenta agendar
# turnos aunque el cliente nunca haya configurado el módulo.
APPOINTMENT_TOOL_NAMES = {"consultar_disponibilidad", "agendar_turno", "cancelar_mi_turno", "reprogramar_mi_turno"}
tools_no_appointments = [t for t in tools if t.name not in APPOINTMENT_TOOL_NAMES]

if AI_PROVIDER == "openai" and OPENAI_API_KEY:
    llm_with_tools = ChatOpenAI(model="gpt-4o-mini", temperature=0.2).bind_tools(tools)
    llm_with_tools_no_appointments = ChatOpenAI(model="gpt-4o-mini", temperature=0.2).bind_tools(tools_no_appointments)
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
    llm_with_tools_no_appointments = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        temperature=0.1,
        google_api_key=GOOGLE_API_KEY,
        safety_settings={
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        }
    ).bind_tools(tools_no_appointments)


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
        # feat_appointments es nullable en la DB (columnas viejas sin migrar quedan en NULL);
        # tratamos NULL/True como habilitado y solo False lo desactiva explícitamente.
        appointments_enabled = bool(settings is None or settings.feat_appointments is not False)

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
        now_utc = datetime.utcnow()
        now = now_utc - timedelta(hours=3)
        days_es = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        months_es = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        
        day_name_es = days_es[now.weekday()]
        month_name_es = months_es[now.month]
        
        # Generar mapeo de los próximos 10 días para evitar errores de cálculo del LLM
        proximos_dias_lines = []
        for i in range(10):
            futuro = now + timedelta(days=i)
            futuro_day_name = days_es[futuro.weekday()]
            relativo = ""
            if i == 0: relativo = " (hoy)"
            elif i == 1: relativo = " (mañana)"
            
            proximos_dias_lines.append(f"  * {futuro_day_name}{relativo}: {futuro.strftime('%Y-%m-%d')}")
            
        proximos_dias_str = "\n".join(proximos_dias_lines)
        
        date_context = f"""
### 🕒 CONTEXTO TEMPORAL (ARGENTINA):
- Día de la semana: {day_name_es}
- Fecha y hora actual: {day_name_es}, {now.day} de {month_name_es} de {now.year} {now.strftime("%H:%M")}
- Mapeo de fechas para los próximos días (¡Usar exactamente estas fechas al llamar a las herramientas!):
{proximos_dias_str}
"""
        
        prohibition_rule = ""
        if appointments_enabled:
            prohibition_rule = """
### 🚫 PROHIBICIÓN ABSOLUTA DE MOSTRAR LISTAS DE HORARIOS:
- Está TERMINANTEMENTE PROHIBIDO enviarle al usuario listas verticales o largas de horarios (usando guiones, viñetas, listas numeradas o texto separado por saltos de línea).
- Si el usuario te pide un horario ocupado (ej. las 15:30), NUNCA listes toda la disponibilidad. Debes guiarlo conversacionalmente ofreciéndole únicamente las opciones inmediatamente anteriores o posteriores disponibles (ej: "El horario de las 15:30 ya está ocupado para ese día, pero te puedo ofrecer un turno antes a las 15:00 o después a las 16:00. ¿Te sirve alguno de estos?").
- Si el usuario pregunta disponibilidad general, sólo menciónale 2 o 3 opciones representativas en una sola frase amigable en un renglón continuo, sin hacer listas.
- CONFIANZA ABSOLUTA EN LAS HERRAMIENTAS: Si la herramienta 'consultar_disponibilidad' o 'agendar_turno' indica que un horario solicitado está disponible (está en la lista de horarios_disponibles), significa que está LIBRE. NUNCA digas que está ocupado si la herramienta te dice que está disponible.
"""

        system_prompt = company_info + "\n\n" + date_context + "\n\n" + prohibition_rule + "\n\n" + system_prompt
        
        if not user_name:
            identity_rule = """
### 🎭 REGLA DE IDENTIDAD:
- Usuario actual: DESCONOCIDO.
- REGLA CRÍTICA DE NOMBRE: El nombre del usuario actual es DESCONOCIDO. Debes preguntarle amigable y discretamente su nombre y apellido (mínimamente nombre) en tu primera respuesta (por ejemplo, "¿Con quién tengo el gusto de hablar para agendar tu consulta?"), pero de manera que NO impida continuar con la conversación si el usuario prefiere responder sobre otro tema. En cuanto el usuario te mencione su nombre, debes llamar de inmediato a la herramienta 'registrar_nombre_usuario' para registrarlo.
"""
        else:
            identity_rule = f"""
### 🎭 REGLA DE IDENTIDAD:
- Usuario actual: {user_name}.
"""
        system_prompt = identity_rule + "\n\n" + system_prompt
        
        # --- Contexto de Rol y Etiquetas de Usuario ---
        try:
            from src.database.tagging_manager import get_user_role, get_user_tags
            user_role = get_user_role(client_id, t_id)
            user_tags = get_user_tags(client_id, t_id)
            tags_str = ", ".join(t.get("name", "") for t in user_tags) if user_tags else "Ninguna"
            
            tagging_context = f"""
### 🏷️ PERFIL Y PERMISOS DEL USUARIO:
- Rol del Usuario: {user_role}
- Etiquetas del Usuario: {tags_str}
- Regla de Acceso: El usuario tiene el rol '{user_role}'. Solo tiene permitido consultar información autorizada para este rol. El buscador de información ya filtra las respuestas según este rol, pero tú debes comportarte de acuerdo a este rol.
"""
            system_prompt = tagging_context + "\n\n" + system_prompt
        except Exception as te:
            logging.error(f"[Prompt Tagging] Error adding tagging context: {te}")
        
        # Onboarding Logic
        if onboarding_active:
            if "Nombre del Cliente" not in fields_to_collect:
                fields_to_collect.insert(0, "Nombre del Cliente")
 
            missing = [f for f in fields_to_collect if f not in collected_data]
            is_pedido_topic = str(state.get('form_topic') or '').startswith("Pedido: ")
            is_doc_login_topic = str(state.get('form_topic') or '').startswith(DOC_LOGIN_TOPIC_PREFIX)
            is_doc_search_topic = str(state.get('form_topic') or '').startswith(DOC_SEARCH_TOPIC_PREFIX)
            if missing:
                current_field = missing[0]
                system_prompt += f"\n### 📝 GESTIÓN DE TRÁMITE: {state.get('form_topic')}\n"
                system_prompt += f"**FALTAN ESTOS DATOS:** {', '.join(missing)}\n"
                system_prompt += f"**SIGUIENTE DATO A PEDIR:** '{current_field}'.\n"
                system_prompt += f"""
### 🧠 REGLAS CRÍTICAS DE EXTRACCIÓN (MAPEADO INTELIGENTE):
1. **EXTRACCIÓN INMEDIATA (OBLIGATORIO):** En cuanto detectes un dato en el mensaje, usá 'registrar_dato_tramite'.
2. **SIEMPRE USA HERRAMIENTAS:** No confirmes los datos solo con texto.
3. **CONVERSACIÓN, NO FORMULARIO:** No lo conviertas en un cuestionario. Pedí el próximo dato como parte natural de la charla (por ejemplo, después de comentar algo sobre el producto o responder algo que dijo el cliente), nunca como una lista fría de campos pendientes.
"""
                if is_pedido_topic:
                    system_prompt += "4. **CAMPOS ESPECIALES DEL PEDIDO:** Para 'Cantidad' usá SIEMPRE 'registrar_cantidad_pedido' (nunca 'registrar_dato_tramite'). Para 'Fecha de Entrega' usá SIEMPRE 'registrar_fecha_entrega_pedido'. Si alguna de esas herramientas devuelve un error (cantidad o fecha inválida), NO uses 'registrar_dato_tramite' como respaldo: explicale el motivo al usuario y pedile un valor válido.\n"
                elif is_doc_login_topic:
                    system_prompt += "4. **CAMPO ESPECIAL DE LOGIN:** Para 'Contraseña' usá SIEMPRE 'registrar_clave_documento' (nunca 'registrar_dato_tramite'), pasándole el nombre del segmento. Si devuelve un error (usuario/clave incorrectos), NO la registres como si fuera válida: explicale el motivo al usuario y pedile que la vuelva a escribir.\n"
                elif is_doc_search_topic:
                    system_prompt += "4. **ESTOS DATOS SON PARA MEJORAR LA BÚSQUEDA, NO SON UN REQUISITO ESTRICTO:** si el usuario no tiene o no sabe alguno de estos datos (por ejemplo dice 'no tengo ese número' o te da información distinta a la pedida), NO insistas más de una vez ni lo bloquees. Registrá ese campo igual con 'registrar_dato_tramite' usando el texto que sí te haya dado (aunque no tenga el formato exacto pedido), o con el valor 'N/A' si no dio nada útil, y seguí con el próximo dato. Si ya no quedan más datos por pedir, avisale amablemente que vas a buscar con lo que tenés.\n"
            else:
                if state.get('form_topic') == CATALOG_LEAD_TOPIC:
                    system_prompt += (
                        "\n### ✅ DATOS DE CONTACTO COMPLETADOS\n"
                        "Ya tenés todos los datos de contacto del usuario. Ahora DEBÉS continuar respondiendo "
                        "su consulta original sobre el catálogo (precio/producto que había preguntado antes), "
                        "volviendo a llamar a la herramienta 'consultar_catalogo' con esa misma consulta.\n"
                    )
                elif is_pedido_topic:
                    system_prompt += (
                        f"\n### ✅ PEDIDO REGISTRADO: {state.get('form_topic')}\n"
                        f"Ya tenés todos los datos del pedido ({', '.join(f'{k}: {v}' for k, v in collected_data.items())}). "
                        "Confirmale al usuario un resumen claro del pedido (producto, cantidad, fecha de entrega) y "
                        "avisale que fue registrado y que se va a procesar.\n"
                    )
                elif is_doc_login_topic:
                    segmento_busqueda = collected_data.get("Segmento de Búsqueda")
                    if segmento_busqueda:
                        consulta = collected_data.get("Consulta de Documento", "")
                        system_prompt += (
                            "\n### ✅ ACCESO A DOCUMENTOS VALIDADO\n"
                            "El usuario ya se autenticó correctamente. Ahora DEBÉS llamar a la herramienta "
                            f"'buscar_documento_en_segmento' con segmento='{segmento_busqueda}' y este texto "
                            f"EXACTO como parámetro 'query' (no lo reformules ni lo resumas): '{consulta}'.\n"
                        )
                    else:
                        system_prompt += (
                            "\n### ✅ ACCESO A DOCUMENTOS VALIDADO\n"
                            "El usuario ya se autenticó correctamente. Ahora DEBÉS continuar respondiendo su consulta "
                            "original sobre el documento que había pedido, volviendo a llamar a la herramienta "
                            "'buscar_documento' con esa misma consulta.\n"
                        )
                elif is_doc_search_topic:
                    from src.database.document_library import build_segment_search_query
                    segment_fields = [f for f in fields_to_collect if f != "Nombre del Cliente"]
                    combined_query = build_segment_search_query(collected_data, segment_fields)
                    segment_name = str(state.get('form_topic') or '')[len(DOC_SEARCH_TOPIC_PREFIX):]
                    system_prompt += (
                        "\n### ✅ DATOS DE BÚSQUEDA COMPLETADOS\n"
                        "Ya tenés los datos para buscar el documento. Ahora DEBÉS llamar a la herramienta "
                        f"'buscar_documento_en_segmento' con segmento='{segment_name}' y este texto EXACTO "
                        f"como parámetro 'query' (no lo reformules ni lo resumas): '{combined_query}'.\n"
                    )
                else:
                    system_prompt += "\n### ✅ TRÁMITE COMPLETADO\n"
        else:
            rag_enabled = settings.feat_rag_enabled if settings else False
            rag_rule = ""
            if rag_enabled:
                rag_rule = "\n5. **BÚSQUEDA EN EL RAG / DOCUMENTOS ADJUNTOS (HABILITADO):** Si el usuario hace preguntas técnicas, detalladas, solicita aclaraciones o te pregunta sobre la información contenida en documentos adjuntos/PDFs (como el \"informe de sostenibilidad\" u otros archivos en el CONOCIMIENTO OFICIAL marcado como [CON_ARCHIVO]), DEBES usar obligatoriamente la herramienta `buscar_info_empresa` para buscar los detalles en la base de datos vectorial/RAG. No inventes respuestas ni ofrezcas contacto humano sin antes realizar la búsqueda."

            system_prompt += f"""
### ℹ️ REGLAS DE INFORMACIÓN Y TRÁMITES:
1. **INFORMACIÓN PRIMERO:** Brindá la info.
2. **INICIO DE TRÁMITE:** Si el usuario consulta sobre un tema del CONOCIMIENTO OFICIAL que tiene la etiqueta `[TIENE_FORMULARIO]`, ES OBLIGATORIO Y ESTRICTO que EJECUTES la herramienta `iniciar_onboarding_tramite` (pasándole el nombre del topic) para comenzar a pedirle los datos. ¡No hagas preguntas manualmente sin usar la herramienta!
3. **ARCHIVOS ADJUNTOS:** Si el conocimiento consultado tiene la etiqueta `[CON_ARCHIVO]`, DEBES incluir OBLIGATORIAMENTE la etiqueta `[SEND_FILE: nombre_del_tema]` al final de tu respuesta de texto. El sistema se encargará de enviarlo.
4. **OPCIONES INTERACTIVAS:** Si el tema tiene la etiqueta `[OPCIONES: opc1 | opc2]`, DEBES agregar al final de tu respuesta una pregunta invitando a la acción y una lista numerada con esas opciones exactas (ej: "¿Qué deseas hacer?\n1. opc1\n2. opc2").
6. **INICIO DE PEDIDO DE CATÁLOGO:** Si el usuario expresa intención real de comprar un producto del catálogo ya identificado (ej. "quiero comprarlo", "hacéme el pedido", "dame 200 unidades"), y no solo consulta el precio, ES OBLIGATORIO que EJECUTES la herramienta `iniciar_pedido_catalogo` (pasándole el nombre o SKU del producto) para empezar a tomar el pedido. No lo hagas manualmente por texto.
7. **ROL DE VENDEDOR EXPERTO:** Cuando hables de productos del catálogo, actuá como un vendedor experto: destacá beneficios concretos, resolvé objeciones, sugerí la opción que mejor resuelve lo que pidió el cliente y, cuando tenga sentido, ofrecé un producto complementario o de mayor valor. Guiá activamente hacia el cierre (ej. "¿Querés que te lo reserve?") en vez de solo listar información.
8. **BÚSQUEDA OBLIGATORIA ANTES DE RESPONDER SOBRE PRODUCTOS:** Ante CUALQUIER mensaje que pregunte, aunque sea de forma informal o ambigua, si vendés o tenés determinado producto, ES OBLIGATORIO ejecutar la herramienta `consultar_catalogo` con esa consulta ANTES de responder, incluso si estás seguro de que no lo tenés. Nunca respondas de memoria ni digas que no tenés/vendés algo sin haber ejecutado la herramienta primero: si no lo hacés, esa consulta no queda registrada para detectar demanda de productos faltantes.{rag_rule}
9. **BIBLIOTECA DE DOCUMENTOS:** Si el usuario pide un manual/reglamento/documento (o el sistema te indica con un "REFUERZO DE BIBLIOTECA DE DOCUMENTOS" que corresponde), ES OBLIGATORIO llamar a `buscar_documento`. Si devuelve `status: multiple`, mostrale al usuario una lista NUMERADA solo con los títulos y esperá su elección antes de escribir cualquier etiqueta. Cuando identifiques cuál documento quiere (por número o nombre) y tengas su `id`, incluí literalmente la etiqueta `[SEND_DOC: <id>]` al final de tu respuesta. Si devuelve `status: activated`, seguí el mismo flujo de recolección de datos que para trámites: usá `registrar_dato_tramite` para 'Usuario' (si corresponde) y `registrar_clave_documento` para 'Contraseña', pasándole el nombre del segmento indicado.
"""

            if settings and settings.catalog_response_style:
                system_prompt += f"\n### 🎨 ESTILO DE RESPUESTA DEL CATÁLOGO:\n{settings.catalog_response_style}\n"

        # Las reglas de turnos deben estar siempre presentes, aun durante el onboarding,
        # pero solo si el cliente tiene el módulo de turnos habilitado (feat_appointments).
        if appointments_enabled:
            system_prompt += """
### 📅 REGLAS ESTRICTAS PARA LA GESTIÓN DE TURNOS:
1. **FLUJO DE SELECCIÓN:** Para reservar un turno, debés guiar al usuario paso a paso en la elección de la fecha y hora:
   - **Paso 1: Fecha:** Si el usuario solicita un turno pero no indica fecha, pregúñtale qué día le gustaría asistir. Calcula la fecha exacta (formato YYYY-MM-DD) usando el 'CONTEXTO TEMPORAL'. Por ejemplo, si hoy es viernes 29 de mayo de 2026, el próximo lunes es 1 de junio de 2026. ¡Calculá bien los días y los meses de 30/31 días!
   - **Paso 2: Hora (OBLIGATORIEDAD DE CONSULTA):** En cuanto identifiques la fecha solicitada por el usuario (o si el usuario cambia el día solicitado, por ejemplo, de "mañana" a "hoy"), DEBES llamar obligatoria y de inmediato a la herramienta `consultar_disponibilidad` para esa fecha. Está TERMINANTEMENTE PROHIBIDO responderle al usuario si el horario está ocupado o libre sin antes haber llamado a `consultar_disponibilidad` para esa fecha específica. Tampoco podés asumir horarios basándote en la consulta de otra fecha o en tu memoria.
     * **Si hay turnos:** NUNCA muestres un listado de todos los horarios disponibles. En su lugar, guíalo en la elección mencionando solo 2 o 3 opciones representativas (ej: "Tengo libre a las 09:00, 11:30 o 12:30. ¿Te sirve alguno?").
     * **Si el horario exacto solicitado por el usuario no está en la lista de disponibles:**
       - Si figura en `horarios_ya_reservados_por_otros`, dile que ya está reservado/ocupado por otra persona.
       - Si no figura en `horarios_ya_reservados_por_otros`, dile amigablemente que ese horario no es un slot de reserva válido, no está habilitado o está fuera de los turnos de atención para ese día (ya que los turnos son cada 30 minutos).
       - En cualquier caso, nunca listes toda la disponibilidad. Ofrécele amigablemente 2 opciones libres cercanas en un único renglón corrido de texto (ej: *"El horario de las 23:45 no está habilitado para hoy, pero te puedo ofrecer a las 23:30 o 23:00. ¿Te sirve alguno?"*). Guíalo conversacionalmente.
   - **Paso 3: Confirmación:** Cuando el usuario elija un horario válido, procedé a agendar el turno usando la herramienta `agendar_turno`.
2. **RESOLUCIÓN DE FECHAS:** Sé extremadamente preciso al calcular la fecha del día que te pida (ej: "lunes", "mañana", "el próximo jueves"). Si la fecha cae en un día en el que no hay disponibilidad o está fuera de los horarios de atención, infórmalo y proponé el día hábil más cercano de forma amigable (ej: "El lunes 1 de junio no tenemos turnos disponibles, pero te puedo ofrecer para el martes 2 de junio. ¿Te sirve?").
3. **REGLA DE HORARIOS GENERALES:** NUNCA menciones los "Horarios de Atención" generales de la empresa (por ejemplo: lunes a viernes de 08 a 13 hs) al usuario cuando estés guiando o informando sobre turnos. Los horarios de atención general del negocio son exclusivamente para visitas/consultas físicas generales y no representan los horarios específicos habilitados para turnos, los cuales pueden ser distintos o más cortos. Para responder sobre disponibilidad u horarios de turnos, debés consultar SIEMPRE la herramienta `consultar_disponibilidad`.
4. **INDEPENDENCIA DE TRÁMITES (ONBOARDING NO BLOQUEANTE):** El proceso de recolección de datos (onboarding) nunca debe bloquear o posponer la reserva de turnos. Si el usuario te indica una fecha y hora específica para su turno (ej: "miércoles a las 10"), debés llamar inmediatamente a la herramienta `agendar_turno` para confirmarlo, sin importar si aún faltan campos del formulario por completar (como DNI, marca, título, etc.). Asegura la reserva del turno primero y luego continúa solicitando la información pendiente.
"""
 
        # Inyección de Conocimiento Multi-Cliente
        kb = db.query(Knowledge).filter_by(client_id=client_id).all()
        kb_text = ""
        for r in kb:
            has_media = " [CON_ARCHIVO]" if (r.media_path and r.send_as_file is not False) else ""
            has_form_tag = " [TIENE_FORMULARIO]" if r.has_form else " [SOLO_INFORMACION]"
            has_options = f" [OPCIONES: {r.interactive_options}]" if r.interactive_options else ""
            kb_text += f"- {r.topic}{has_media}{has_form_tag}{has_options}: {r.content} (Campos: {r.form_fields})\n"
        
        system_prompt += f"\n\n### CONOCIMIENTO OFICIAL:\n{kb_text}"
        
        # Recordatorios de alta prioridad al final del system prompt (mayor relevancia para el LLM)
        system_prompt += "\n\n### 🚨 INSTRUCCIONES OPERATIVAS CRÍTICAS (DEBEN CUMPLIRSE EN ESTA RESPUESTA):"
        if not user_name:
            system_prompt += "\n1. EL CLIENTE ES DESCONOCIDO: Pregúntale amigable y discretamente su nombre y apellido (mínimamente nombre) dentro de tu respuesta (ej: '¿Con quién tengo el gusto de hablar para agendar tu consulta?'), sin bloquear el flujo si prefiere responder otra cosa, pero recuerda que NO PUEDES confirmar ni registrar el turno en la herramienta 'agendar_turno' sin que el usuario te haya indicado su nombre."
        
        if appointments_enabled:
            system_prompt += "\n2. PROHIBIDO ENVIAR LISTAS DE HORARIOS: Está terminantemente prohibido usar listas verticales para mostrar horas de turnos. Si el horario pedido por el usuario no está en la lista de disponibles, no listes los demás. Si figura en 'horarios_ya_reservados_por_otros', dile que ya está ocupado/reservado por otro cliente. Si no figura allí, dile amigablemente que no es un slot de reserva válido o no está habilitado para ese día. En cualquier caso, ofrécele 2 opciones libres cercanas en un único renglón corrido de texto (ej: 'El horario de las 23:45 no está habilitado para hoy, pero te puedo ofrecer a las 23:30 o 23:00. ¿Te sirve alguno?')."

        system_prompt += "\n3. ENVÍO DE ARCHIVOS ADJUNTOS: Si el tema del que habla el usuario tiene la etiqueta `[CON_ARCHIVO]` (ej. FORMULARIO 08) o has consultado información sobre un tema con archivo, DEBES agregar OBLIGATORIAMENTE la etiqueta `[SEND_FILE: nombre_del_tema]` al final de tu respuesta de texto. ¡No omitas esta etiqueta por ningún motivo!"

        if appointments_enabled:
            system_prompt += "\n4. VERIFICACIÓN Y ACCIÓN DE AGENDA INMEDIATA (Garantizar exactitud): NUNCA asumas ni le digas al usuario que un horario está libre u ocupado basándote en tu memoria o en los ejemplos del prompt. Si el usuario te pide un horario específico (ej: miércoles a las 10) y tras llamar a 'consultar_disponibilidad' compruebas que ese horario está en la lista de 'horarios_disponibles', DEBES llamar obligatoriamente a la herramienta 'agendar_turno' en esta misma respuesta para reservarlo. Está TERMINANTEMENTE PROHIBIDO decirle que está ocupado o pedirle más confirmaciones por chat si el horario devuelto por la herramienta está libre."
        
    finally:
        db.close()

    # Recortar el historial de mensajes para mantener el contexto limpio y evitar que ignore instrucciones
    raw_msgs = state["messages"]
    max_msgs = 15
    if len(raw_msgs) > max_msgs:
        pruned = raw_msgs[-max_msgs:]
        from langchain_core.messages import ToolMessage
        while len(pruned) < len(raw_msgs) and isinstance(pruned[0], ToolMessage):
            idx_to_add = len(raw_msgs) - len(pruned) - 1
            pruned.insert(0, raw_msgs[idx_to_add])
        messages = [SystemMessage(content=system_prompt)] + pruned
    else:
        messages = [SystemMessage(content=system_prompt)] + raw_msgs


    # ----------------- REFUERZO DINÁMICO DE REGLAS DE NEGOCIO -----------------
    recent_text = ""
    for m in messages:
        if hasattr(m, 'content') and m.content and not isinstance(m, SystemMessage):
            recent_text += " " + str(m.content).lower()
            
    current_form_topic = state.get("form_topic", "")
    
    # Deducir intenciones del usuario sobre adjuntos y agenda en su último mensaje
    user_asked_for_file = False
    user_scheduling_intent = False
    user_product_intent = False
    last_human_msg = ""
    for m in reversed(messages):
        if hasattr(m, 'content') and m.content and not isinstance(m, SystemMessage):
            if type(m).__name__ == "HumanMessage":
                last_human_msg = str(m.content).lower()
                break

    if last_human_msg:
        file_keywords = ["pdf", "archivo", "mandam", "envi", "descarg", "adjunt", "papel", "documento"]
        scheduling_keywords = ["turn", "agend", "reserv", "cit", "hor", "fech", "disponib", " hs", "lunes", "martes", "miercol", "jueves", "viernes", "sabad", "doming", "si, ", "sí, ", "confirm"]
        product_keywords = ["tene", "tien", "vend", "hay ", "consig", "necesit", "busco", "buscas", "quiero", "precio", "cuest", "cuant", "cuánt", "stock", "catalog", "catálog", "comprar", "producto", "modelo"]
        if any(kw in last_human_msg.lower() for kw in file_keywords):
            user_asked_for_file = True
        if any(skw in last_human_msg.lower() for skw in scheduling_keywords):
            user_scheduling_intent = True
        if any(pkw in last_human_msg.lower() for pkw in product_keywords):
            user_product_intent = True

    if user_scheduling_intent:
        messages.append(SystemMessage(content="REFUERZO DE AGENDA: El usuario está expresando intención de consultar o agendar un turno (ej: indicando día, hora, solicitando disponibilidad o diciendo que quiere reservar). DEBES llamar obligatoriamente a la herramienta `consultar_disponibilidad` en esta misma respuesta para la fecha correspondiente (usando el CONTEXTO TEMPORAL para calcularla). Está terminantemente prohibido inventar o adivinar si el horario está libre u ocupado sin usar la herramienta primero."))

    user_doc_intent = False
    matched_segment = None
    matched_segment_fields = None
    if last_human_msg and settings and settings.feat_document_library:
        try:
            db_kw = SessionLocal()
            from src.database.document_library import get_doc_trigger_keywords, get_segment_by_trigger
            seg_match = get_segment_by_trigger(db_kw, client_id, last_human_msg)
            if seg_match:
                matched_segment, matched_segment_fields = seg_match
            doc_keywords = get_doc_trigger_keywords(db_kw, client_id, settings)
            db_kw.close()
        except Exception as kw_err:
            logging.error(f"Error obteniendo frases gatillo de la biblioteca de documentos: {kw_err}")
            doc_keywords = []
        if not matched_segment and doc_keywords and any(dk in last_human_msg.lower() for dk in doc_keywords):
            user_doc_intent = True

    if matched_segment and not onboarding_active:
        messages.append(SystemMessage(content=(
            f"REFUERZO DE BÚSQUEDA POR SEGMENTO: El usuario está pidiendo un documento del segmento "
            f"'{matched_segment.name}', que requiere estos datos antes de buscar: "
            f"{', '.join(matched_segment_fields)}. DEBES llamar obligatoriamente a "
            f"`iniciar_busqueda_documento_segmento` en esta misma respuesta (query=la consulta del usuario, "
            f"segmento='{matched_segment.name}'). NO llames a `buscar_documento` en este turno."
        )))
    elif user_doc_intent and not onboarding_active:
        messages.append(SystemMessage(content="REFUERZO DE BIBLIOTECA DE DOCUMENTOS: El usuario está pidiendo un documento/manual/reglamento. DEBES llamar obligatoriamente a `buscar_documento` en esta misma respuesta con esa consulta antes de responder."))

    if user_product_intent and settings and settings.feat_catalog and not onboarding_active:
        messages.append(SystemMessage(content="REFUERZO DE CATÁLOGO: El usuario está preguntando por un producto, precio o disponibilidad. DEBES llamar obligatoriamente a la herramienta `consultar_catalogo` en esta misma respuesta con esa consulta, INCLUSO SI ESTÁS SEGURO de que ese producto no existe en el catálogo. Está terminantemente prohibido responder 'no tenemos/no vendemos eso' o cualquier respuesta similar sin haber ejecutado antes la herramienta: si no la ejecutás, esa consulta no queda registrada."))

    # Query database for knowledge items with media to reinforce [SEND_FILE] tag
    try:
        db = SessionLocal()
        kb_items = db.query(Knowledge).filter_by(client_id=client_id).all()
        for r in kb_items:
            topic_mentioned = r.topic.lower() in recent_text or (current_form_topic and current_form_topic.lower() == r.topic.lower())
            if topic_mentioned and r.media_path:
                # Regla: solo enviar archivo si el usuario lo pide explícitamente O si no está agendando ni en onboarding
                should_send_file = user_asked_for_file or (not user_scheduling_intent and not onboarding_active)
                if should_send_file:
                    messages.append(SystemMessage(content=f"IMPORTANTE: El tema '{r.topic}' tiene un archivo adjunto. DEBES incluir obligatoriamente la etiqueta `[SEND_FILE: {r.topic}]` al final de tu respuesta de texto (por ejemplo, al final del mensaje de explicación o de confirmación). No la omitas por ningún motivo."))
    except Exception as kb_err:
        logging.error(f"Error querying KB for reinforcement: {kb_err}")
    finally:
        db.close()

    # Reinforce prohibition of listing schedules if a tool response for availability is present
    has_availability_tool_output = False
    from langchain_core.messages import ToolMessage
    for m in messages[-3:]:
        if isinstance(m, ToolMessage) and (m.name == "consultar_disponibilidad" or "horarios_disponibles" in getattr(m, 'content', '')):
            has_availability_tool_output = True
            break
            
    if has_availability_tool_output:
        messages.append(SystemMessage(content="IMPORTANTE: Si el usuario solicitó un día y hora específicos (ej: 'miércoles a las 10') y esa hora está en la lista de 'horarios_disponibles' de la herramienta, DEBES llamar de inmediato a la herramienta 'agendar_turno' para reservarlo en esta misma respuesta. Si el usuario cambia de día o pide para una fecha distinta a la consultada, DEBES llamar primero a 'consultar_disponibilidad' con la nueva fecha. Está terminantemente prohibido asumir disponibilidad o no disponibilidad de una fecha sin haber llamado a la herramienta en este turno. Si no especificó un horario exacto libre, menciónale solo 2 o 3 opciones representativas en un único renglón corrido de texto."))
    # --------------------------------------------------------------------------

    try:
        with open(os.path.join(ROOT_DIR, "actual_prompt.txt"), "w", encoding="utf-8") as debug_file:
            for m in messages:
                debug_file.write(f"=== {type(m).__name__} ===\n{m.content}\n\n")
    except Exception as debug_err:
        pass

    active_llm = llm_with_tools if appointments_enabled else llm_with_tools_no_appointments
    response = active_llm.invoke(messages)
    
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
                    initial_data = {}
                    if data.get("producto_consulta"):
                        initial_data["Producto de Interés"] = data["producto_consulta"]
                    if data.get("producto_sku"):
                        initial_data["SKU"] = data["producto_sku"]
                    if data.get("documento_consulta"):
                        initial_data["Consulta de Documento"] = data["documento_consulta"]
                    if data.get("segmento_busqueda"):
                        initial_data["Segmento de Búsqueda"] = data["segmento_busqueda"]
                    new_state["collected_data"] = initial_data
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
                        # Si ya existe y es distinto, lo sobreescribimos en lugar de concatenarlo
                        # para evitar DNIs o modelos duplicados en el mismo string
                        collected_data[campo] = valor
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

        already_completed = state.get("form_just_completed", False)

        if fields and not missing and not already_completed:
            final_thread_id = t_id or "unknown_user"
            topic = new_state.get("form_topic", state.get("form_topic"))
            storage_dest = new_state.get("storage_dest", state.get("storage_dest", "database"))
            is_catalog_topic = topic == CATALOG_LEAD_TOPIC or str(topic or "").startswith("Pedido: ")
            is_doc_login_topic = str(topic or "").startswith(DOC_LOGIN_TOPIC_PREFIX)
            is_doc_search_topic = str(topic or "").startswith(DOC_SEARCH_TOPIC_PREFIX)

            pdf_path = None
            if is_catalog_topic:
                # El catálogo (consultas y pedidos) se guarda aparte de los trámites
                # administrativos: no va a data_submissions/data_proceedings.
                from src.database.catalog_requests import process_catalog_completion
                pdf_path = process_catalog_completion(
                    client_id=client_id,
                    thread_id=final_thread_id,
                    topic=topic,
                    data=collected_data,
                    storage_dest=storage_dest
                )
            elif is_doc_login_topic:
                # La sesión ya se creó en validate_segment_credentials; acá solo se
                # audita con un tag. A propósito NO se persiste collected_data (puede
                # contener rastros de usuario/clave) en data_submissions.
                from src.database.document_library import process_doc_login_completion
                process_doc_login_completion(
                    client_id=client_id,
                    thread_id=final_thread_id,
                    topic=topic
                )
            elif is_doc_search_topic:
                # Los valores de los campos son insumos efímeros para armar la query de búsqueda,
                # no un trámite: no hay nada que persistir acá. La búsqueda real (y su auditoría vía
                # log_document_search) ocurre cuando buscar_documento se vuelva a llamar con la
                # consulta combinada, en la próxima respuesta del agente.
                pass
            else:
                process_form_completion(
                    client_id=client_id,
                    thread_id=final_thread_id,
                    topic=topic,
                    data=collected_data,
                    storage_dest=storage_dest
                )
            # OJO: NO reseteamos onboarding_active/form_topic/collected_data todavía.
            # Si lo hiciéramos acá, el agente perdería el contexto (form_topic, datos
            # recolectados) justo antes de generar el mensaje de cierre (resumen del
            # pedido, o continuar la consulta de catálogo), porque LangGraph aplica
            # este cambio de estado ANTES de la próxima invocación del agente. Se
            # limpia recién en la pasada siguiente, una vez que el agente ya respondió.
            new_state["form_just_completed"] = True
            if pdf_path:
                new_state["pending_pdf_path"] = pdf_path
        elif already_completed:
            last_msg = state["messages"][-1]
            if isinstance(last_msg, AIMessage) and not getattr(last_msg, "tool_calls", None):
                new_state["onboarding_active"] = False
                new_state["fields_to_collect"] = []
                new_state["form_topic"] = None
                new_state["collected_data"] = {}
                new_state["form_just_completed"] = False

    return new_state

def should_continue(state: AgentState):
    last_msg = state["messages"][-1]
    if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls: return "tools"
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
