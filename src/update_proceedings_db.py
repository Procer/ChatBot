import sqlite3
import os

db_path = "settings.sqlite"

def update_proceedings_db():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Tabla de Seguimiento de Trámites (Expedientes)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS proceedings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tracking_number TEXT UNIQUE,
        client_name TEXT,
        topic TEXT,
        status TEXT,
        notes TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    conn.commit()
    conn.close()
    print("Base de datos de trámites actualizada.")

if __name__ == "__main__":
    update_proceedings_db()
