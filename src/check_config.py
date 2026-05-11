import sqlite3
import os

db_path = os.path.join("..", "settings.sqlite")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT key, value FROM config WHERE key IN ('webhook_base_url', 'whatsapp_enabled')")
for row in cursor.fetchall():
    print(f"{row[0]}: {row[1]}")
conn.close()
