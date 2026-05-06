import os
import sys
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

# Asegurar que 'src' esté en el path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from agents.graph import app

load_dotenv()

def test_memory():
    print("\n--- PRUEBA ESPECÍFICA DE MEMORIA PERSISTENTE ---")
    config = {"configurable": {"thread_id": "test_memoria_real"}}

    pruebas = [
        "Hola, me llamo Juan y soy de Buenos Aires.", 
        "¿Recuerdas mi nombre y de dónde soy?"
    ]

    for consulta in pruebas:
        print(f"\nConsulta: {consulta}")
        try:
            result = app.invoke({"messages": [HumanMessage(content=consulta)]}, config=config)
            last_msg = result["messages"][-1]
            print(f"Bot: {last_msg.content}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    test_memory()
