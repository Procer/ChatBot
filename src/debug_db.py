import sqlite3
import os

db_path = r"c:\laragon\www\Rondan\Chatbot\analytics.sqlite"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM messages ORDER BY timestamp DESC LIMIT 10")
    rows = cursor.fetchall()
    for row in rows:
        print(dict(row))
    conn.close()
else:
    print("DB NOT FOUND")
