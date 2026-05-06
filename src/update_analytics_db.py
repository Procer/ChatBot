import sqlite3
import os

db_path = "analytics.sqlite"

def setup_analytics_db():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Registro de uso de tokens por mensaje
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS token_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        model TEXT,
        cost_usd REAL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Resumen de sesiones para Tasa de Deflexión e Intenciones
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS session_analytics (
        thread_id TEXT PRIMARY KEY,
        intent TEXT DEFAULT 'Otros',
        is_deflected INTEGER DEFAULT 1, -- 1 = Resuelto por IA, 0 = Intervenido por humano
        total_tokens INTEGER DEFAULT 0,
        total_cost_usd REAL DEFAULT 0.0,
        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    conn.commit()
    conn.close()
    print("Base de datos de analítica lista.")

if __name__ == "__main__":
    setup_analytics_db()
