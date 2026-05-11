import sqlite3
import os
from datetime import datetime, timedelta
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "settings.sqlite")
SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "service_account.json")
SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_calendar_service():
    """Inicializa el servicio de Google Calendar usando Service Account."""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        return None
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return build('calendar', 'v3', credentials=creds)
    except Exception as e:
        print(f"Error Calendar Service: {e}")
        return None

def get_external_setting(key):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM external_services WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except: return None

def get_available_slots(date_str):
    """
    Calcula los huecos libres para una fecha específica (YYYY-MM-DD).
    """
    provider = get_external_setting("scheduling_provider")
    working_hours = get_external_setting("scheduling_hours") or "09:00-13:00, 16:00-20:00"
    duration = int(get_external_setting("appointment_duration") or 30)
    calendar_id = get_external_setting("google_calendar_id") or "primary"

    # 0. Verificar si el día está habilitado
    enabled_days = (get_external_setting("scheduling_days") or "mon,tue,wed,thu,fri").split(",")
    requested_date = datetime.strptime(date_str, "%Y-%m-%d")
    day_name = requested_date.strftime("%a").lower() # mon, tue, etc.
    
    # Mapeo por si acaso locale
    day_map = {"mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu", "fri": "fri", "sat": "sat", "sun": "sun"}
    if day_name not in enabled_days:
        return []

    # 1. Generar todos los slots posibles
    all_slots = []
    try:
        for range_part in working_hours.split(","):
            start_str, end_str = range_part.strip().split("-")
            start_time = datetime.strptime(start_str, "%H:%M")
            end_time = datetime.strptime(end_str, "%H:%M")
            
            current = start_time
            while current + timedelta(minutes=duration) <= end_time:
                all_slots.append(current.strftime("%H:%M"))
                current += timedelta(minutes=duration)
    except: return []

    # 2. Consultar slots ocupados
    occupied = []
    if provider == "google":
        service = get_calendar_service()
        if service:
            # Definir rango de búsqueda (todo el día)
            time_min = f"{date_str}T00:00:00Z"
            time_max = f"{date_str}T23:59:59Z"
            
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
    else:
        # Local
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT time FROM appointments WHERE date = ? AND status != 'cancelled'", (date_str,))
        occupied = [row[0] for row in cursor.fetchall()]
        conn.close()

    # 3. Filtrar por capacidad y por tiempo actual (si es hoy)
    capacity = int(get_external_setting("scheduling_capacity") or 1)
    now = datetime.now()
    is_today = date_str == now.strftime("%Y-%m-%d")
    current_time_str = now.strftime("%H:%M")
    
    available = []
    for s in all_slots:
        # Si es hoy, el slot debe ser posterior a la hora actual
        if is_today and s <= current_time_str:
            continue
            
        if occupied.count(s) < capacity:
            available.append(s)
            
    return available

def book_appointment(thread_id, date, time, reason, client_name="Cliente"):
    """Registra el turno en Local o Google Calendar."""
    provider = get_external_setting("scheduling_provider")
    calendar_id = get_external_setting("google_calendar_id") or "primary"
    
    if provider == "google":
        service = get_calendar_service()
        if not service: return False
        
        # Crear evento en Google
        duration = int(get_external_setting("appointment_duration") or 30)
        start_dt = f"{date}T{time}:00"
        end_dt = (datetime.strptime(start_dt, "%Y-%m-%dT%H:%M:%S") + timedelta(minutes=duration)).isoformat()
        
        event = {
            'summary': f'Turno: {client_name}',
            'description': f'Motivo: {reason}\nID Chat: {thread_id}',
            'start': {'dateTime': start_dt, 'timeZone': 'America/Argentina/Buenos_Aires'},
            'end': {'dateTime': end_dt, 'timeZone': 'America/Argentina/Buenos_Aires'},
        }
        
        try:
            service.events().insert(calendarId=calendar_id, body=event).execute()
            # También guardamos copia local para historial del panel
            save_local_copy(thread_id, client_name, date, time, reason)
            return True
        except Exception as e:
            print(f"Error booking Google: {e}")
            return False
    else:
        # Local
        return save_local_copy(thread_id, client_name, date, time, reason)

def save_local_copy(thread_id, client_name, date, time, reason):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO appointments (thread_id, client_name, date, time, reason)
            VALUES (?, ?, ?, ?, ?)
        """, (thread_id, client_name, date, time, reason))
        conn.commit(); conn.close()
        return True
    except: return False

def cancel_appointment(thread_id, date=None, time=None):
    """Cancela un turno."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if date and time:
            cursor.execute("UPDATE appointments SET status = 'cancelled' WHERE thread_id = ? AND date = ? AND time = ?", (thread_id, date, time))
        else:
            cursor.execute("UPDATE appointments SET status = 'cancelled' WHERE id = (SELECT id FROM appointments WHERE thread_id = ? AND status = 'confirmed' ORDER BY date ASC, time ASC LIMIT 1)", (thread_id,))
        
        success = cursor.rowcount > 0
        conn.commit(); conn.close()
        return success
    except: return False

def get_proceeding_status(tracking_number):
    """Busca el estado de un trámite."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM proceedings WHERE tracking_number = ?", (tracking_number,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "cliente": row["client_name"],
                "asunto": row["topic"],
                "estado": row["status"],
                "notas": row["notes"],
                "actualizado": row["updated_at"]
            }
        return None
    except: return None
