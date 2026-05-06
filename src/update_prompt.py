import sqlite3

db_path = "settings.sqlite"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

new_prompt = """Eres el asistente de Rondan Soluciones. 
Tu única fuente de verdad es la información que encuentras en tus documentos (RAG). 
Si el usuario pregunta algo y encuentras la respuesta en tus documentos, responde exactamente lo que dicen, sin filtros de formalidad. 
Si no encuentras información específica, di que no lo sabes."""

cursor.execute("UPDATE config SET value = ? WHERE key = 'system_prompt'", (new_prompt,))
conn.commit()
conn.close()
print("System Prompt actualizado para máxima fidelidad.")
