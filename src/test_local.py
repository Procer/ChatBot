import os
import sys
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

# Añadir la carpeta raíz al path para que las importaciones de 'src.' funcionen
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # carpeta 'src'
ROOT_DIR = os.path.dirname(BASE_DIR) # carpeta raíz

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.agents.graph import app

load_dotenv()

def start_local_chat():
    """Simulador de chat local con persistencia."""
    # Leemos el thread_id de los argumentos de la consola, o usamos uno por defecto
    thread_id = sys.argv[1] if len(sys.argv) > 1 else "usuario_default"
    
    print("\n" + "="*50)
    print(f"🧠 CHATBOT ACTIVO | SESIÓN: {thread_id.upper()}")
    if "nuevo" in thread_id:
        print("✨ MODO: CONVERSACIÓN VIRGEN (SIN MEMORIA PREVIA)")
    else:
        print("💾 MODO: CONVERSACIÓN PERSISTENTE (CON MEMORIA)")
    print("="*50)
    print("Escribe 'salir' para terminar.\n")

    config = {"configurable": {"thread_id": thread_id}}

    while True:
        user_input = input("Tú: ")
        
        if user_input.lower() in ["salir", "exit", "quit"]:
            print("\nChat finalizado. ¡Hasta luego!")
            break

        user_msg = HumanMessage(content=user_input)

        try:
            print("(El bot está procesando...)")
            result = app.invoke({"messages": [user_msg]}, config=config)
            last_msg = result["messages"][-1]
            
            bot_text = ""
            if isinstance(last_msg.content, str):
                bot_text = last_msg.content
            elif isinstance(last_msg.content, list):
                for part in last_msg.content:
                    if isinstance(part, dict) and "text" in part:
                        bot_text += part["text"]
            
            print(f"Bot: {bot_text}\n")

        except Exception as e:
            print(f"[ERROR]: {str(e)}")

if __name__ == "__main__":
    start_local_chat()
