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
        cursor.execute("SELECT id, topic, media_path, has_form, form_fields FROM knowledge")
        rows = cursor.fetchall()
        print(f"✅ Conocimiento: {len(rows)} trámites/temas cargados en la tabla 'knowledge':")
        for r in rows:
            has_media = f"📎 Sí ({os.path.basename(r[2])})" if r[2] else "❌ No"
            has_form = "📝 Sí" if r[3] == 1 else "❌ No"
            print(f"   - [ID {r[0]}] '{r[1]}' | Formulario: {has_form} | Adjunto: {has_media}")

        # 3. Verificar Webhook
        cursor.execute("SELECT value FROM config WHERE key = 'webhook_base_url'")
        webhook = cursor.fetchone()
        if webhook and webhook[0]:
            print(f"✅ Webhook Base URL: {webhook[0]}")
            if "localhost" in webhook[0]:
                print("⚠️ ADVERTENCIA: La URL tiene 'localhost'. En el VPS debería ser tu IP o Dominio.")
        else:
            print("❌ ERROR: Webhook Base URL no configurada.")

        # 3.5 Verificar Mensaje de Bienvenida y Archivo
        cursor.execute("SELECT key, value FROM config WHERE key IN ('welcome_media_path', 'welcome_message_text')")
        w_cfg = dict(cursor.fetchall())
        w_media = w_cfg.get('welcome_media_path')
        print(f"✅ Mensaje de bienvenida: '{w_cfg.get('welcome_message_text', '')}'")
        if w_media:
            clean_media = w_media[1:] if w_media.startswith('/') else w_media
            phys_path = os.path.join(ROOT_DIR, clean_media)
            print(f"📎 Archivo de bienvenida en BD: '{w_media}'")
            if os.path.exists(phys_path):
                print(f"   ✅ Archivo físico ENCONTRADO en el servidor: {phys_path} ({os.path.getsize(phys_path)} bytes)")
            else:
                print(f"   ❌ ERROR: El archivo físico NO EXISTE en la ruta: {phys_path}")
        else:
            print("ℹ️ No hay imagen de bienvenida configurada.")

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
