import sqlite3
import os

db_path = "settings.sqlite"

def update_scheduling_db():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Tabla de Turnos Locales
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT,
        client_name TEXT,
        date TEXT,
        time TEXT,
        reason TEXT,
        status TEXT DEFAULT 'confirmed',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 2. Configuración de Proveedor y Horarios
    # Guardaremos esto en external_services
    configs = [
        ("scheduling_provider", "local"), # 'local' o 'google'
        ("working_hours", "09:00-13:00, 16:00-20:00"),
        ("appointment_duration", "30"), # duración en minutos
        ("google_calendar_id", "primary")
    ]
    for key, val in configs:
        cursor.execute("INSERT OR IGNORE INTO external_services (key, value) VALUES (?, ?)", (key, val))
    
    conn.commit()
    conn.close()
    print("Base de datos de agendamiento lista.")

if __name__ == "__main__":
    update_scheduling_db()
