import sqlite3
conn = sqlite3.connect('settings.sqlite')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
for table in cursor.fetchall():
    print(f"Tabla: {table[0]}")
conn.close()
