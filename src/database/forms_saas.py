import logging
import json
import os
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy.orm import Session

from src.database.session import SessionLocal
from src.database.models import Submission, Proceeding, Attachment, ClientSettings

def get_external_setting(client_id: int, key: str):
    """Obtiene configuraciones específicas de un cliente en formato SaaS."""
    try:
        db: Session = SessionLocal()
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings: return None
        
        # En el modelo SaaS mapeamos las antiguas keys a las nuevas columnas
        if key == "google_sheet_id":
            return settings.google_sheet_id
        elif key == "working_hours":
            return settings.working_hours
        
        return None
    except Exception as e:
        logging.error(f"Error get_external_setting SaaS: {e}")
        return None
    finally:
        db.close()

def save_submission_local(client_id: int, thread_id: str, topic: str, data: dict):
    """Guarda los datos recolectados en la base de datos SaaS."""
    try:
        db: Session = SessionLocal()
        data_json = json.dumps(data)
        
        new_sub = Submission(
            client_id=client_id,
            thread_id=thread_id,
            topic=topic,
            payload_json=data_json
        )
        db.add(new_sub)
        db.commit()
        db.refresh(new_sub)
        new_id = new_sub.id
        db.close()
        return new_id
    except Exception as e:
        logging.error(f"Error al guardar sumisión SaaS: {e}")
        return None

def save_to_google_sheets(client_id: int, thread_id: str, topic: str, data: dict):
    """Envía los datos a Google Sheets usando la hoja configurada del cliente."""
    try:
        # 1. Obtener ID de la hoja desde la DB del cliente
        sheet_id = get_external_setting(client_id, "google_sheet_id")
        if not sheet_id:
            logging.warning(f"[SaaS] Cliente {client_id} no tiene configurado 'google_sheet_id'")
            return False

        # 2. Configurar Autenticación
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "credentials.json")
        
        if not os.path.exists(creds_path):
            logging.error(f"No se encontró el archivo de credenciales en {creds_path}")
            return False

        creds = Credentials.from_service_account_file(creds_path, scopes=scope)
        client = gspread.authorize(creds)

        # 3. Abrir la hoja y seleccionar (o crear) la pestaña según el trámite
        sheet = client.open_by_key(sheet_id)
        
        try:
            worksheet = sheet.worksheet(topic)
        except gspread.exceptions.WorksheetNotFound:
            # Si no existe la pestaña para este trámite, la creamos y añadimos cabeceras
            worksheet = sheet.add_worksheet(title=topic, rows="100", cols="20")
            headers = ["Fecha", "WhatsApp ID"] + list(data.keys())
            worksheet.append_row(headers)

        # 4. Preparar fila de datos
        row = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(thread_id)]
        for key in list(data.keys()):
            row.append(str(data[key]))

        worksheet.append_row(row)
        logging.info(f"[SaaS] Datos guardados en Google Sheets para cliente {client_id}: {topic}")
        return True
    except Exception as e:
        logging.error(f"Google Sheets SaaS error: {e}")
        return False

def process_form_completion(client_id: int, thread_id: str, topic: str, data: dict, storage_dest: str = 'database'):
    """Gestiona el fin de un formulario vinculándolo al cliente SaaS correspondiente."""
    logging.info(f"\n[SaaS] FINALIZANDO FORMULARIO")
    logging.info(f" - Cliente ID: {client_id}")
    logging.info(f" - Thread ID: {thread_id}")
    logging.info(f" - Topic: {topic}")
    logging.info(f" - Destino: {storage_dest}")
    
    try:
        from src.database.tagging_manager import assign_tag_by_name, remove_tag_by_name
        assign_tag_by_name(client_id, thread_id, "🎓 Trámite Completado")
        remove_tag_by_name(client_id, thread_id, "📝 Trámite Iniciado")
    except Exception as te:
        logging.error(f"[Tagging] Error applying tag in process_form_completion: {te}")
        
    success_local = False
    if storage_dest in ['database', 'both']:
        # 1. Guardar en DB local y obtener ID
        submission_id = save_submission_local(client_id, thread_id, topic, data)
        success_local = submission_id is not None
        logging.info(f" - Resultado guardado local: {success_local} (ID: {submission_id})")
        
        if success_local:
            try:
                db: Session = SessionLocal()
                # 1.1 VINCULAR ADJUNTOS: Buscamos adjuntos pendientes de este usuario y cliente y los asociamos a esta sumisión
                db.query(Attachment).filter(
                    Attachment.client_id == client_id,
                    Attachment.thread_id == thread_id,
                    Attachment.form_id == None
                ).update({"form_id": submission_id})
                
                # 2. Crear entrada en el CRM (proceedings) para el tablero Kanban
                now_str = datetime.now().strftime("%M%S")
                suffix = str(thread_id)[-4:] if thread_id and len(str(thread_id)) >= 4 else "0000"
                tracking = f"TR-{suffix}-{now_str}"
                
                client_name = data.get("Nombre del Cliente", data.get("Nombre", data.get("nombre", data.get("Cliente", "Cliente Nuevo"))))
                
                new_proc = Proceeding(
                    client_id=client_id,
                    tracking_number=tracking,
                    client_name=client_name,
                    topic=topic,
                    status='Pendiente',
                    notes=f"Datos recolectados vía Bot: {json.dumps(data)}"
                )
                db.add(new_proc)
                db.commit()
                logging.info(f" - Expediente CRM creado SaaS: {tracking}")
            except Exception as e:
                logging.error(f"Error procesando CRM o Adjuntos SaaS: {e}")
            finally:
                db.close()
        
    success_sheets = True
    if storage_dest in ['sheets', 'both']:
        success_sheets = save_to_google_sheets(client_id, thread_id, topic, data)
        
    return success_local or success_sheets
