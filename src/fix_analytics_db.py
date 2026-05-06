import sqlite3
import os

db_path = 'analytics.sqlite'

# Si la base de datos es muy vieja y pequeña, es más seguro recrear las tablas críticas
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("Actualizando esquemas de analíticas...")

# 1. Tabla token_usage (Gastos detallados)
cursor.execute("DROP TABLE IF EXISTS token_usage")
cursor.execute("""
    CREATE TABLE token_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT,
        model TEXT,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        cost_usd REAL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")

# 2. Tabla session_analytics (Resumen para el Dashboard)
cursor.execute("DROP TABLE IF EXISTS session_analytics")
cursor.execute("""
    CREATE TABLE session_analytics (
        thread_id TEXT PRIMARY KEY,
        total_tokens INTEGER DEFAULT 0,
        total_cost_usd REAL DEFAULT 0.0,
        intent TEXT,
        is_deflected INTEGER DEFAULT 1,
        last_activity DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")

# 3. La tabla messages ya está bien, pero nos aseguramos
cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT,
        role TEXT,
        content TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")

conn.commit()
conn.close()
print("Base de datos analytics.sqlite normalizada con éxito.")
