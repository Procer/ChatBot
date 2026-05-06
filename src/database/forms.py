import logging
import sqlite3
import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "settings.sqlite"

def save_submission_local(thread_id, topic, data):
    """Guarda los datos recolectados en la base de datos local."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Convertimos el diccionario de datos a JSON para guardarlo en una columna TEXT
        data_json = json.dumps(data)
        
        cursor.execute("""
            INSERT INTO form_submissions (thread_id, form_topic, data, status)
            VALUES (?, ?, ?, ?)
        """, (thread_id, topic, data_json, 'completed'))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.info(f"Error al guardar sumisión local: {e}")
        return False

import gspread
from google.oauth2.service_account import Credentials

def save_to_google_sheets(topic, data):
    """
    Envía los datos a Google Sheets usando gspread.
    Requiere un archivo 'credentials.json' en la raíz.
    """
    try:
        # 1. Obtener ID de la hoja desde la base de datos
        sheet_id = get_external_setting("google_sheet_id")
        if not sheet_id:
            print("[ERROR] No se ha configurado 'google_sheet_id' en el panel.")
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
        row = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "User"] # TODO: Pasar thread_id real
        for key in list(data.keys()):
            row.append(str(data[key]))

        worksheet.append_row(row)
        logging.info(f"Datos guardados en Google Sheets: {topic}")
        return True
    except Exception as e:
        logging.error(f"Google Sheets: {e}")
        return False

def process_form_completion(thread_id, topic, data, storage_dest='database'):
    """Gestiona el fin de un formulario según el destino configurado."""
    logging.info(f"\n[DEBUG] FINALIZANDO FORMULARIO")
    logging.info(f" - Thread ID: {thread_id}")
    logging.info(f" - Topic: {topic}")
    logging.info(f" - Data: {data}")
    logging.info(f" - Destino: {storage_dest}")
    
    success = True
    if storage_dest in ['database', 'both']:
        logging.info(f" - Intentando guardar en DB local...")
        success = save_submission_local(thread_id, topic, data)
        logging.info(f" - Resultado guardado local: {success}")
        
        # 2. Crear entrada en el CRM (proceedings) para el tablero Kanban
        try:
            conn = sqlite3.connect(DB_PATH)
            # Generamos un tracking_number más robusto (TR + ultimos 4 id + MinutoSegundo)
            from datetime import datetime
            now_str = datetime.now().strftime("%M%S")
            suffix = str(thread_id)[-4:] if thread_id and len(str(thread_id)) >= 4 else "0000"
            tracking = f"TR-{suffix}-{now_str}"
            
            client = data.get("Nombre", data.get("nombre", data.get("Cliente", "Cliente Nuevo")))
            
            conn.execute("""
                INSERT INTO proceedings (tracking_number, client_name, topic, status, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (tracking, client, topic, 'Pendiente', f"Datos recolectados vía Bot: {json.dumps(data)}"))
            conn.commit(); conn.close()
            logging.info(f" - Expediente CRM creado: {tracking}")
        except Exception as e:
            logging.info(f"Error al crear expediente CRM: {e}")
        
    if storage_dest in ['sheets', 'both']:
        success = save_to_google_sheets(topic, data) and success
        
    return success

def get_external_setting(key):
    """Obtiene configuraciones de servicios externos (ej: Google Sheet ID)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM external_services WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except:
        return None
