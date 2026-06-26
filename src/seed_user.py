import os
import sqlite3
import hashlib
from sqlalchemy.orm import Session
from src.database.session import SessionLocal
from src.database.models import User, Client

def seed_user():
    print("Creando usuario de prueba para el Dashboard SaaS...")
    db: Session = SessionLocal()
    
    try:
        # Buscar cliente Rondan
        client = db.query(Client).filter_by(slug="rondan").first()
        if not client:
            print("Error: El cliente 'rondan' no existe. Ejecuta seed_saas.py primero.")
            return

        # Crear hash simple (md5 igual que el legacy para no complicar ahora)
        raw_password = "admin"
        password_hash = hashlib.md5(raw_password.encode()).hexdigest()

        # Verificar si existe el usuario
        user = db.query(User).filter_by(email="admin").first()
        if not user:
            user = User(
                client_id=client.id,
                email="admin", # Usamos "admin" como email/username para la prueba
                password_hash=password_hash,
                role_name="client_admin"
            )
            db.add(user)
            db.commit()
            print("✅ Usuario 'admin' creado correctamente. (Pass: admin)")
        else:
            print("ℹ️ El usuario 'admin' ya existe.")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_user()
