import sqlite3
import os

db_path = "settings.sqlite"

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("\n--- [CONFIG] SYSTEM PROMPT ---")
    cursor.execute("SELECT value FROM config WHERE key = 'system_prompt'")
    row = cursor.fetchone()
    print(row[0] if row else "No configurado")
    
    print("\n--- [KNOWLEDGE] TABLA DE HECHOS ---")
    cursor.execute("SELECT id, topic, content, category FROM knowledge")
    rows = cursor.fetchall()
    for r in rows:
        print(f"ID: {r[0]} | TEMA: {r[1]} | CATEGORÍA: {r[3]}")
        print(f"INFO: {r[2]}\n")
    
    conn.close()
else:
    print("No se encontró settings.sqlite")
