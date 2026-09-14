import logging

from src.database.session import SessionLocal
from src.database.models import ClientSettings
from src.database.gdrive_sync import encrypt_token, decrypt_token


def save_client_mp_token(client_id: int, raw_token: str) -> None:
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings:
            raise RuntimeError(f"No existe ClientSettings para client_id={client_id}")
        settings.mp_access_token_encrypted = encrypt_token(raw_token)
        db.commit()
    finally:
        db.close()


def clear_client_mp_token(client_id: int) -> None:
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if settings:
            settings.mp_access_token_encrypted = None
            db.commit()
    finally:
        db.close()


def resolve_client_mp_token(settings) -> str | None:
    """Desencripta el Access Token de Mercado Pago propio del cliente. None = no configuró uno."""
    if not settings or not settings.mp_access_token_encrypted:
        return None
    try:
        return decrypt_token(settings.mp_access_token_encrypted)
    except Exception as e:
        client_id = getattr(settings, "client_id", "?")
        logging.error(f"[MP Token] No se pudo desencriptar el access token del cliente {client_id}: {e}")
        return None
