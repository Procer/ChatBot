import sqlite3
import os

db_path = "settings.sqlite"

def update_db():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Añadir nuevas columnas a la tabla knowledge (si no existen)
    try:
        cursor.execute("ALTER TABLE knowledge ADD COLUMN has_form INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE knowledge ADD COLUMN form_fields TEXT")
        cursor.execute("ALTER TABLE knowledge ADD COLUMN storage_dest TEXT DEFAULT 'database'")
        print("Columnas añadidas a 'knowledge'.")
    except sqlite3.OperationalError:
        print("Las columnas ya existen en 'knowledge' o hubo un error.")

    # 2. Crear tabla para los envíos de datos (Submissions)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS form_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT,
        form_topic TEXT,
        data TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 3. Crear tabla para configuraciones de servicios externos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS external_services (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    
    conn.commit()
    conn.close()
    print("Base de datos actualizada correctamente.")

if __name__ == "__main__":
    update_db()
