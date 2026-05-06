import os
import sqlite3
import sys

# Configurar rutas
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
sys.path.append(ROOT_DIR)

def check_brain():
    print("=== DIAGNÓSTICO DEL CEREBRO (VPS) ===")
    db_path = os.path.join(ROOT_DIR, "settings.sqlite")
    
    if not os.path.exists(db_path):
        print(f"❌ ERROR: No se encuentra {db_path}")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 1. Verificar Prompt
        cursor.execute("SELECT value FROM config WHERE key = 'system_prompt'")
        prompt = cursor.fetchone()
        if prompt:
            print(f"✅ Prompt cargado (Primeros 100 carácteres): {prompt[0][:100]}...")
        else:
            print("❌ ERROR: No hay 'system_prompt' en la base de datos.")

        # 2. Verificar Conocimiento (Trámites)
        cursor.execute("SELECT COUNT(*) FROM knowledge")
        count = cursor.fetchone()[0]
        print(f"✅ Conocimiento: {count} trámites/temas cargados en la tabla 'knowledge'.")

        # 3. Verificar Webhook
        cursor.execute("SELECT value FROM config WHERE key = 'webhook_base_url'")
        webhook = cursor.fetchone()
        if webhook and webhook[0]:
            print(f"✅ Webhook Base URL: {webhook[0]}")
            if "localhost" in webhook[0]:
                print("⚠️ ADVERTENCIA: La URL tiene 'localhost'. En el VPS debería ser tu IP o Dominio.")
        else:
            print("❌ ERROR: Webhook Base URL no configurada.")

        # 4. Verificar Vector DB
        chroma_path = os.path.join(ROOT_DIR, "chroma_db")
        if os.path.exists(chroma_path):
            print(f"✅ Carpeta chroma_db encontrada.")
        else:
            print("⚠️ ADVERTENCIA: Carpeta chroma_db no encontrada. El RAG (PDFs) no funcionará.")

        conn.close()
    except Exception as e:
        print(f"❌ ERROR inesperado: {e}")

if __name__ == "__main__":
    check_brain()
