import asyncio
import json
import os
import sys

# Ajustar path para encontrar el módulo 'src'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from langchain_core.messages import HumanMessage
from src.agents.graph import app as chatbot_app, extract_text
from src.database.analytics_engine import log_token_usage, log_message

async def test_full_logging():
    user_id = "user_test_admin"
    user_text = "¿Cuáles son los horarios de atención?"
    
    print(f"Usuario dice: {user_text}")
    
    # 1. Registrar mensaje usuario
    log_message(user_id, "user", user_text)
    
    # 2. Obtener respuesta del bot
    config = {"configurable": {"thread_id": user_id}}
    result = chatbot_app.invoke({"messages": [HumanMessage(content=user_text)]}, config=config)
    
    last_msg = result["messages"][-1]
    bot_response = extract_text(last_msg.content)
    print(f"Bot responde: {bot_response}")
    
    # 3. Registrar mensaje bot
    log_message(user_id, "bot", bot_response)
    
    # 4. Registrar tokens
    usage = getattr(last_msg, "usage_metadata", None)
    if usage:
        log_token_usage(
            user_id,
            getattr(last_msg, "response_metadata", {}).get("model_name", "unknown"),
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0)
        )
    
    print("\n--- Verificando Base de Datos ---")
    import sqlite3
    conn = sqlite3.connect('analytics.sqlite')
    cursor = conn.cursor()
    cursor.execute("SELECT role, content FROM messages WHERE thread_id = ?", (user_id,))
    rows = cursor.fetchall()
    for row in rows:
        print(f"DB -> {row[0]}: {row[1][:50]}...")
    conn.close()

if __name__ == "__main__":
    asyncio.run(test_full_logging())
