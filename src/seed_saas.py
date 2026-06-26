import os
import sqlite3
from sqlalchemy.orm import Session
from src.database.session import SessionLocal
from src.database.models import Client, ClientSettings

def get_sqlite_setting(cursor, key):
    try:
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None
    except:
        return None

def seed_database():
    print("🔄 Iniciando migración de credenciales de SQLite a SQL Server (SaaS)...")
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'settings.sqlite')
    
    if not os.path.exists(db_path):
        print("⚠️ No se encontró settings.sqlite. Se cargarán datos vacíos.")
        sqlite_data = {"business_name": "Rondan Escribanía"}
    else:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        sqlite_data = {
            "business_name": get_sqlite_setting(cursor, "company_name") or "Rondan Escribanía",
            "bot_system_prompt": get_sqlite_setting(cursor, "system_prompt"),
            "whatsapp_instance_id": get_sqlite_setting(cursor, "whatsapp_instance_id"),
            "whatsapp_token": get_sqlite_setting(cursor, "whatsapp_api_token"),
        }
        
        try:
            cursor.execute("SELECT value FROM external_services WHERE key = 'working_hours'")
            w_row = cursor.fetchone()
            sqlite_data["working_hours"] = w_row[0] if w_row else ""
            
            cursor.execute("SELECT value FROM external_services WHERE key = 'google_sheet_id'")
            g_row = cursor.fetchone()
            sqlite_data["google_sheet_id"] = g_row[0] if g_row else ""
        except:
            sqlite_data["working_hours"] = ""
            sqlite_data["google_sheet_id"] = ""
            
        conn.close()

    db: Session = SessionLocal()
    
    try:
        # Verificar si el cliente ya existe
        client = db.query(Client).filter_by(slug="rondan").first()
        if not client:
            print("🏗️ Creando Cliente 'rondan' en SQL Server...")
            client = Client(business_name=sqlite_data["business_name"], slug="rondan", status="active")
            db.add(client)
            db.commit()
            db.refresh(client)
        else:
            print("📝 Cliente 'rondan' encontrado. Actualizando datos de negocio...")
            client.business_name = sqlite_data["business_name"]
            db.commit()

        # Insertar / Actualizar Settings
        settings = db.query(ClientSettings).filter_by(client_id=client.id).first()
        if not settings:
            settings = ClientSettings(
                client_id=client.id,
                whatsapp_instance_id=sqlite_data.get("whatsapp_instance_id"),
                whatsapp_token=sqlite_data.get("whatsapp_token"),
                bot_system_prompt=sqlite_data.get("bot_system_prompt"),
                google_sheet_id=sqlite_data.get("google_sheet_id"),
                working_hours=sqlite_data.get("working_hours"),
                feat_rag_enabled=True,
                feat_human_handoff=True
            )
            db.add(settings)
        else:
            settings.whatsapp_instance_id = sqlite_data.get("whatsapp_instance_id")
            settings.whatsapp_token = sqlite_data.get("whatsapp_token")
            settings.bot_system_prompt = sqlite_data.get("bot_system_prompt")
            settings.google_sheet_id = sqlite_data.get("google_sheet_id")
            settings.working_hours = sqlite_data.get("working_hours")
            
        db.commit()
        print(f"✅ Migración inicial exitosa. (Client ID: {client.id} - Slug: {client.slug})")
        print(f"🔑 Credenciales WA: Instance={settings.whatsapp_instance_id} | Token={settings.whatsapp_token[:5]}...")
    except Exception as e:
        print(f"❌ Error durante la migración: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()
