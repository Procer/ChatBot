import sqlite3
import os

def check_db(db_name, query, label):
    if not os.path.exists(db_name):
        print(f"Base de datos {db_name} no existe.")
        return
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        print(f"--- {label} ---")
        for row in rows:
            print(row)
        conn.close()
    except Exception as e:
        print(f"Error en {db_name}: {e}")

# 1. Ver hilos en checkpoints
check_db('checkpoints.sqlite', "SELECT DISTINCT thread_id FROM checkpoints LIMIT 5", "Hilos en Checkpoints")

# 2. Ver mensajes en analytics (si existe la tabla)
# Primero listamos tablas de analytics.sqlite
check_db('analytics.sqlite', "SELECT name FROM sqlite_master WHERE type='table'", "Tablas en Analytics")

# 3. Ver mensajes reales (ajustar según nombre de tabla si es diferente)
check_db('analytics.sqlite', "SELECT thread_id, role, content FROM messages ORDER BY id DESC LIMIT 5", "Últimos Mensajes en Historial")
