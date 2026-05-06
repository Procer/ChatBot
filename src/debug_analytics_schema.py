import sqlite3
conn = sqlite3.connect('analytics.sqlite')
cursor = conn.cursor()

def get_schema(table):
    cursor.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]

tables = ['token_usage', 'session_analytics', 'messages']
for t in tables:
    print(f"Tabla {t}: {get_schema(t)}")

conn.close()
