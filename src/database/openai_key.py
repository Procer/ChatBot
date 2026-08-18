import logging

from src.database.session import SessionLocal
from src.database.models import ClientSettings
from src.database.gdrive_sync import encrypt_token, decrypt_token


def save_client_openai_key(client_id: int, raw_key: str) -> None:
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings:
            raise RuntimeError(f"No existe ClientSettings para client_id={client_id}")
        settings.openai_api_key_encrypted = encrypt_token(raw_key)
        db.commit()
    finally:
        db.close()


def clear_client_openai_key(client_id: int) -> None:
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if settings:
            settings.openai_api_key_encrypted = None
            db.commit()
    finally:
        db.close()


def resolve_client_openai_key(settings) -> str | None:
    """Desencripta la API key de OpenAI propia del cliente, si configuró una.
    None = el cliente no tiene key propia: el llamador debe usar la key global del .env
    (comportamiento previo, sin aislamiento de billing por cliente)."""
    if not settings or not settings.openai_api_key_encrypted:
        return None
    try:
        return decrypt_token(settings.openai_api_key_encrypted)
    except Exception as e:
        client_id = getattr(settings, "client_id", "?")
        logging.error(f"[OpenAI Key] No se pudo desencriptar la key propia del cliente {client_id}: {e}")
        return None


def get_client_embeddings(client_id: int, default_embeddings):
    """Devuelve un OpenAIEmbeddings propio del cliente si configuró su key, o `default_embeddings`
    (la instancia global armada con la key del .env) si no configuró una."""
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        client_key = resolve_client_openai_key(settings)
    finally:
        db.close()
    if client_key:
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(api_key=client_key)
    return default_embeddings
