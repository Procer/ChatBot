import sqlite3
import os
from langgraph.checkpoint.sqlite import SqliteSaver

# Aseguramos que el path sea absoluto desde la raíz
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(ROOT_DIR, "checkpoints.sqlite")

# La simple instanciación de SqliteSaver con una conexión debería crear las tablas necesarias
conn = sqlite3.connect(db_path, check_same_thread=False)
memory = SqliteSaver(conn)
# No necesitamos hacer nada más, la librería crea las tablas al conectarse
conn.close()
print(f"Base de datos de checkpoints inicializada correctamente en {db_path}")
