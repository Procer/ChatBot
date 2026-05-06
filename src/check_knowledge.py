import sqlite3
import os

DB_PATH = "settings.sqlite"

def check_knowledge():
    if not os.path.exists(DB_PATH):
        print("DB no existe")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT topic, form_fields FROM knowledge WHERE topic LIKE '%Autorización%'")
    rows = cursor.fetchall()
    for row in rows:
        print(f"Topic: {row[0]}")
        print(f"Fields: {row[1]}")
    conn.close()

if __name__ == "__main__":
    check_knowledge()
