import sqlite3
import os

db_path = "settings.sqlite"

def update_bot_status_db():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Tabla para pausar el bot por usuario
    # expires_at: TIMESTAMP hasta cuando el bot debe estar callado
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bot_pauses (
        user_id TEXT PRIMARY KEY,
        paused_until TIMESTAMP
    )
    """)
    
    conn.commit()
    conn.close()
    print("Base de datos de estados de bot lista.")

if __name__ == "__main__":
    update_bot_status_db()
