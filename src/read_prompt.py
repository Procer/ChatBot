import sqlite3
conn = sqlite3.connect('settings.sqlite')
cursor = conn.cursor()
cursor.execute("SELECT value FROM settings WHERE key = 'system_prompt'")
row = cursor.fetchone()
print(f"System Prompt: {row[0] if row else 'No definido'}")
conn.close()
