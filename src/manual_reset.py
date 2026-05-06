import sqlite3
import os
import shutil

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def reset_all():
    print("🧨 Iniciando detonación de datos (Reset Total)...")
    
    # 1. SETTINGS.SQLITE
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'settings.sqlite'))
    cursor = conn.cursor()
    tables_to_wipe = ['knowledge', 'appointments', 'proceedings', 'form_submissions', 'bot_pauses', 'external_services']
    for table in tables_to_wipe:
        cursor.execute(f"DELETE FROM {table}")
    
    # Preservar canales y resetear el resto
    cursor.execute("SELECT key, value FROM config WHERE key IN ('whatsapp_enabled', 'telegram_enabled', 'telegram_token')")
    channels = cursor.fetchall()
    cursor.execute("DELETE FROM config")
    defaults = [
        ('bot_name', 'Zárate IA'), ('bot_tone', 'argentino'),
        ('system_prompt', '### QUIEN SOS: Zárate IA, asistente profesional de Zárate System Group.'),
        ('company_name', 'Nueva Empresa'), ('company_phone', ''),
        ('company_email', ''), ('company_website', ''), ('company_address', '')
    ]
    cursor.executemany("INSERT INTO config VALUES (?, ?)", defaults)
    for k, v in channels:
        cursor.execute("INSERT OR REPLACE INTO config VALUES (?, ?)", (k, v))
    conn.commit(); conn.close()
    print("✅ Configuración y Operaciones reseteadas.")

    # 2. ANALYTICS.SQLITE
    conn = sqlite3.connect(os.path.join(ROOT_DIR, 'analytics.sqlite'))
    for table in ['messages', 'token_usage', 'session_analytics']:
        conn.execute(f"DELETE FROM {table}")
    conn.commit(); conn.close()
    print("✅ Historial y Métricas eliminadas.")

    # 3. CHECKPOINTS.SQLITE
    cp_path = os.path.join(ROOT_DIR, 'checkpoints.sqlite')
    if os.path.exists(cp_path):
        conn = sqlite3.connect(cp_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        for table in cursor.fetchall():
            cursor.execute(f"DELETE FROM {table[0]}")
        conn.commit(); conn.close()
    print("✅ Memoria de sesiones (IA) limpiada.")

    # 4. Archivos y Chroma
    data_dir = os.path.join(ROOT_DIR, "data")
    if os.path.exists(data_dir):
        for f in os.listdir(data_dir):
            try: os.remove(os.path.join(data_dir, f))
            except: pass
    
    chroma_dir = os.path.join(ROOT_DIR, "chroma_db")
    if os.path.exists(chroma_dir):
        shutil.rmtree(chroma_dir, ignore_errors=True)
    print("✅ Archivos y Base Vectorial eliminados.")

    print("\n🚀 RESET TOTAL COMPLETADO CON ÉXITO.")

if __name__ == "__main__":
    reset_all()
