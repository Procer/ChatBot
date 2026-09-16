from src.database.session import SessionLocal
from src.database.models import SystemConfig
from src.database.gdrive_sync import encrypt_token, decrypt_token

OPENAI_ADMIN_KEY_CONFIG_KEY = "openai_admin_api_key"


def get_system_config(key: str) -> str | None:
    """Devuelve el valor desencriptado guardado bajo `key`, o None si no está cargado."""
    db = SessionLocal()
    try:
        row = db.query(SystemConfig).filter_by(key=key).first()
        if not row or not row.value_encrypted:
            return None
        try:
            return decrypt_token(row.value_encrypted)
        except Exception:
            return None
    finally:
        db.close()


def set_system_config(key: str, raw_value: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(SystemConfig).filter_by(key=key).first()
        encrypted = encrypt_token(raw_value)
        if row:
            row.value_encrypted = encrypted
        else:
            row = SystemConfig(key=key, value_encrypted=encrypted)
            db.add(row)
        db.commit()
    finally:
        db.close()


def clear_system_config(key: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(SystemConfig).filter_by(key=key).first()
        if row:
            db.delete(row)
            db.commit()
    finally:
        db.close()
