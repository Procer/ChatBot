import sqlite3
import os

db_path = "notifications.sqlite"

def update_gaps_db():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Tabla para registrar preguntas que el bot no supo responder
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_gaps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT,
        frequency INTEGER DEFAULT 1,
        last_asked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'pending' -- pending, resolved
    )
    """)
    
    conn.commit()
    conn.close()
    print("Base de datos de vacíos de conocimiento lista.")

if __name__ == "__main__":
    update_gaps_db()
