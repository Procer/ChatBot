import sys
import os

# Ajustar path para que reconozca 'src'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, ROOT_DIR)

print(f"DEBUG: ROOT_DIR is {ROOT_DIR}")

try:
    from src.agents.graph import app
    print("SUCCESS: El cerebro se cargó correctamente.")
except Exception as e:
    print("FAILURE: Error al cargar el cerebro:")
    import traceback
    traceback.print_exc()
