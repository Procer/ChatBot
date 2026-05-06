import sqlite3
import os

def init_databases():
    print("🚀 Iniciando configuración de infraestructura para nuevo cliente...")
    
    # 1. SETTINGS.SQLITE (Configuración y Negocio)
    conn = sqlite3.connect('settings.sqlite')
    cursor = conn.cursor()
    
    # Tabla de Configuración General
    cursor.execute("""CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY, 
        value TEXT
    )""")
    
    # Tabla de Conocimiento (RAG + Formularios)
    cursor.execute("""CREATE TABLE IF NOT EXISTS knowledge (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        topic TEXT, 
        content TEXT, 
        category TEXT,
        has_form INTEGER DEFAULT 0,
        form_fields TEXT,
        storage_dest TEXT DEFAULT 'database'
    )""")
    
    # Servicios Externos (Turnos, Calendario)
    cursor.execute("""CREATE TABLE IF NOT EXISTS external_services (
        key TEXT PRIMARY KEY, 
        value TEXT
    )""")
    
    # Turnos / Citas
    cursor.execute("""CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        user_name TEXT,
        date TEXT,
        time TEXT,
        reason TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    # CRM / Expedientes
    cursor.execute("""CREATE TABLE IF NOT EXISTS proceedings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tracking_number TEXT UNIQUE,
        client_name TEXT,
        topic TEXT,
        status TEXT DEFAULT 'Pendiente',
        notes TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    # Pausas del Bot
    cursor.execute("""CREATE TABLE IF NOT EXISTS bot_pauses (
        user_id TEXT PRIMARY KEY, 
        paused_until DATETIME
    )""")

    # Envío de Formularios (Onboarding)
    cursor.execute("""CREATE TABLE IF NOT EXISTS form_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT,
        topic TEXT,
        data TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    # Insertar valores por defecto si no existen
    defaults = [
        ('bot_name', 'Asistente IA'),
        ('bot_tone', 'argentino'),
        ('system_prompt', '### QUIEN SOS: Un asistente profesional y amable.'),
        ('company_name', 'Nueva Empresa'),
        ('whatsapp_enabled', '0'),
        ('telegram_enabled', '0'),
        ('telegram_token', '')
    ]
    cursor.executemany("INSERT OR IGNORE INTO config VALUES (?, ?)", defaults)
    
    conn.commit()
    conn.close()
    print("✅ Base de datos SETTINGS lista.")

    # 2. ANALYTICS.SQLITE (Costos y Mensajes)
    conn = sqlite3.connect('analytics.sqlite')
    cursor = conn.cursor()
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS token_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT,
        model TEXT,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        cost_usd REAL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT,
        role TEXT,
        content TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS session_analytics (
        thread_id TEXT PRIMARY KEY,
        total_tokens INTEGER DEFAULT 0,
        total_cost_usd REAL DEFAULT 0.0,
        intent TEXT,
        is_deflected INTEGER DEFAULT 1,
        last_activity DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    
    conn.commit()
    conn.close()
    print("✅ Base de datos ANALYTICS lista.")

    # 3. NOTIFICATIONS.SQLITE (Alertas y Gaps)
    conn = sqlite3.connect('notifications.sqlite')
    cursor = conn.cursor()
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        motivo TEXT,
        fecha DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    
    cursor.execute("""CREATE TABLE IF NOT EXISTS knowledge_gaps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT,
        frequency INTEGER DEFAULT 1,
        status TEXT DEFAULT 'pending'
    )""")
    
    conn.commit()
    conn.close()
    print("✅ Base de datos NOTIFICATIONS lista.")

    print("\n🎉 SISTEMA INICIALIZADO CORRECTAMENTE.")
    print("Ahora podés configurar los canales desde el Panel Admin.")

if __name__ == "__main__":
    init_databases()
