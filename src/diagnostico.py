import os
import sys
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

# Asegurar que 'src' esté en el path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from agents.graph import app

load_dotenv()

def test_bot():
    print("\n--- INICIANDO PRUEBA DE DIAGNÓSTICO (MODO SILENCIOSO) ---")
    
    # ID de prueba para la memoria
    config = {"configurable": {"thread_id": "test_diagnostico_123"}}

    pruebas = [
        "¿Quién es Rondan Soluciones?",  # Probar RAG (buscar_info_empresa)
        "¿Qué precio tiene el mantenimiento?", # Probar Tool (obtener_precio_servicio)
        "¿Recuerdas quién soy?" # Probar Persistencia (memoria)
    ]

    for consulta in pruebas:
        print(f"\nConsulta: {consulta}")
        try:
            # Invocar al bot
            result = app.invoke({"messages": [HumanMessage(content=consulta)]}, config=config)
            
            # Obtener respuesta final
            last_msg = result["messages"][-1]
            print(f"Bot: {last_msg.content}")
        except Exception as e:
            print(f"Error en consulta '{consulta}': {e}")

if __name__ == "__main__":
    test_bot()
