import io
import json
import logging
import os
import re
import secrets
import sys
import time
from datetime import datetime

# Add root directory to sys.path (mismo patrón que document_library.py)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
from cryptography.fernet import Fernet
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

load_dotenv()

from src.database.session import SessionLocal
from src.database.models import ClientSettings, Document, DocumentSegmentLink

GDRIVE_TOKEN_ENCRYPTION_KEY = os.getenv("GDRIVE_TOKEN_ENCRYPTION_KEY")

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_FOLDER_MIME = "application/vnd.google-apps.folder"
_GOOGLE_NATIVE_MIME_PREFIX = "application/vnd.google-apps."
_GOOGLE_NATIVE_EXPORT_MIME = "application/pdf"
_SHARE_DENIED_STATUSES = (403, 404)

_DOWNLOAD_TOKEN_TTL = 600
_download_tokens = {}  # token -> {"client_id", "thread_id", "document_id", "expires_at"}


# --- TÍTULO AUTOMÁTICO (misma regla que cleanTitleFromFilename en document_library.html) ---

def clean_filename_to_title(filename: str) -> str:
    name = os.path.splitext(filename)[0]
    name = re.sub(r"[-_]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return " ".join(w.capitalize() for w in name.split(" "))


# --- ENCRIPTACIÓN DE LA CLAVE DE LA CUENTA DE SERVICIO ---
# A diferencia de whatsapp_token/telegram_token (texto plano en ClientSettings), la clave JSON
# de una cuenta de servicio da acceso de lectura permanente a todo lo compartido con ella:
# amerita encriptación en reposo aunque el resto del proyecto no la use.

def _fernet() -> Fernet:
    if not GDRIVE_TOKEN_ENCRYPTION_KEY:
        raise RuntimeError("GDRIVE_TOKEN_ENCRYPTION_KEY no está configurada en el entorno")
    key = GDRIVE_TOKEN_ENCRYPTION_KEY.encode("utf-8") if isinstance(GDRIVE_TOKEN_ENCRYPTION_KEY, str) else GDRIVE_TOKEN_ENCRYPTION_KEY
    return Fernet(key)


def encrypt_token(raw: str) -> str:
    return _fernet().encrypt(raw.encode("utf-8")).decode("utf-8")


def decrypt_token(enc: str) -> str:
    return _fernet().decrypt(enc.encode("utf-8")).decode("utf-8")


# --- CUENTA DE SERVICIO (propia de cada cliente/tenant) ---
# Cada cliente tiene su propia cuenta de servicio (dentro de un único proyecto de Google Cloud
# nuestro) y comparte su carpeta de Drive con el email de esa cuenta, como se comparte con
# cualquier persona. No hay pantalla de consentimiento ni vencimiento de token: la clave solo
# deja de funcionar si se revoca a mano o se le saca el acceso a la carpeta.

def save_service_account_key(client_id: int, sa_json_raw: str) -> str:
    """Valida y guarda la clave JSON de la cuenta de servicio. Devuelve el client_email cacheado."""
    try:
        sa_info = json.loads(sa_json_raw)
    except json.JSONDecodeError:
        raise ValueError("El archivo pegado no es un JSON válido")
    if sa_info.get("type") != "service_account" or not sa_info.get("client_email"):
        raise ValueError("El JSON no corresponde a una clave de cuenta de servicio de Google")

    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings:
            raise RuntimeError(f"No existe ClientSettings para client_id={client_id}")
        settings.gdrive_service_account_json_encrypted = encrypt_token(sa_json_raw)
        settings.gdrive_service_account_email = sa_info["client_email"]
        settings.gdrive_share_revoked = False
        db.commit()
        return sa_info["client_email"]
    finally:
        db.close()


def clear_service_account_key(client_id: int) -> None:
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings:
            return
        settings.gdrive_service_account_json_encrypted = None
        settings.gdrive_service_account_email = None
        settings.gdrive_share_revoked = False
        settings.gdrive_root_folder_id = None
        settings.gdrive_root_folder_name = None
        db.commit()
    finally:
        db.close()


def get_service_account_status(client_id: int) -> dict:
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        configured = bool(settings and settings.gdrive_service_account_json_encrypted)
        return {
            "configured": configured,
            "email": settings.gdrive_service_account_email if settings else None,
            "share_revoked": bool(settings and settings.gdrive_share_revoked),
        }
    finally:
        db.close()


def clear_root_folder(client_id: int) -> None:
    """Acción del cliente sobre SU selección de carpeta (no borra la cuenta de servicio en sí)."""
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings:
            return
        settings.gdrive_root_folder_id = None
        settings.gdrive_root_folder_name = None
        db.commit()
    finally:
        db.close()


def _sweep_expired(cache: dict):
    now = time.time()
    for k in [k for k, v in cache.items() if v.get("expires_at", 0) < now]:
        cache.pop(k, None)


def create_download_token(client_id: int, thread_id: str, document_id: int, ttl_seconds: int = _DOWNLOAD_TOKEN_TTL) -> str:
    _sweep_expired(_download_tokens)
    token = secrets.token_urlsafe(24)
    _download_tokens[token] = {
        "client_id": client_id, "thread_id": thread_id, "document_id": document_id,
        "expires_at": time.time() + ttl_seconds,
    }
    return token


def peek_download_token(token: str):
    entry = _download_tokens.get(token)
    if not entry or entry["expires_at"] < time.time():
        _download_tokens.pop(token, None)
        return None
    return entry


def _mark_share_revoked(client_id: int, revoked: bool) -> None:
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if settings and settings.gdrive_share_revoked != revoked:
            settings.gdrive_share_revoked = revoked
            db.commit()
    finally:
        db.close()


def get_drive_service(client_id: int):
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings or not settings.gdrive_service_account_json_encrypted:
            return None
        try:
            sa_info = json.loads(decrypt_token(settings.gdrive_service_account_json_encrypted))
            creds = service_account.Credentials.from_service_account_info(sa_info, scopes=DRIVE_SCOPES)
        except Exception as e:
            logging.error(f"[GDrive] Error construyendo credenciales de cuenta de servicio (client_id={client_id}): {e}")
            return None
        return build("drive", "v3", credentials=creds)
    finally:
        db.close()


# --- NAVEGACIÓN DE CARPETAS ---

def parse_folder_id_from_input(raw: str) -> str:
    """Acepta tanto un fileId crudo como un link pegado de Drive."""
    raw = (raw or "").strip()
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", raw)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", raw)
    if m:
        return m.group(1)
    return raw


def _list_children(service, parent_id: str, mime_filter: str):
    files = []
    page_token = None
    query = f"'{parent_id}' in parents and trashed = false and mimeType {mime_filter}"
    while True:
        resp = service.files().list(
            q=query, fields="nextPageToken, files(id, name, mimeType)",
            pageToken=page_token, pageSize=100,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def list_subfolders(service, parent_id: str):
    return _list_children(service, parent_id, f"= '{_FOLDER_MIME}'")


def list_files_in_folder(service, folder_id: str):
    return _list_children(service, folder_id, f"!= '{_FOLDER_MIME}'")


def list_folder_contents_for_picker(client_id: int, parent_id: str = None):
    """Picker server-side para el panel admin: subcarpetas de parent_id (o de la raíz del Drive)."""
    service = get_drive_service(client_id)
    if not service:
        return None
    return list_subfolders(service, parent_id or "root")


def get_folder_info(client_id: int, folder_id: str):
    service = get_drive_service(client_id)
    if not service:
        return None
    try:
        meta = service.files().get(fileId=folder_id, fields="id, name, mimeType").execute()
        if meta.get("mimeType") != _FOLDER_MIME:
            return None
        return meta
    except Exception as e:
        logging.error(f"[GDrive] Error validando carpeta {folder_id} (client_id={client_id}): {e}")
        return None


# --- SYNC (solo metadata: título/keywords a Chroma, nunca el contenido del archivo) ---

def sync_client_drive(client_id: int) -> dict:
    from src.database.document_library import get_segment_by_name, sync_document_to_chroma

    summary = {"created": 0, "unmapped_folders": [], "root_files_skipped": 0, "missing_in_drive": 0, "share_revoked": False}

    service = get_drive_service(client_id)
    if not service:
        summary["error"] = "No hay cuenta de servicio configurada para este cliente"
        return summary

    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings or not settings.gdrive_root_folder_id:
            summary["error"] = "No hay carpeta raíz configurada"
            return summary

        sync_started_at = datetime.utcnow()

        try:
            subfolders = list_subfolders(service, settings.gdrive_root_folder_id)
            root_files = list_files_in_folder(service, settings.gdrive_root_folder_id)
            summary["root_files_skipped"] = len(root_files)
        except HttpError as e:
            if e.resp is not None and e.resp.status in _SHARE_DENIED_STATUSES:
                settings.gdrive_share_revoked = True
                db.commit()
                summary["share_revoked"] = True
                summary["error"] = "La carpeta ya no está compartida con la cuenta de servicio"
            else:
                summary["error"] = str(e)
            logging.error(f"[GDrive] Error listando la carpeta raíz (client_id={client_id}): {e}")
            return summary
        except Exception as e:
            logging.error(f"[GDrive] Error listando la carpeta raíz (client_id={client_id}): {e}")
            summary["error"] = str(e)
            return summary

        settings.gdrive_share_revoked = False

        for folder in subfolders:
            segment = get_segment_by_name(db, client_id, folder["name"])
            if not segment:
                summary["unmapped_folders"].append(folder["name"])
                continue

            try:
                files = list_files_in_folder(service, folder["id"])
            except Exception as e:
                logging.error(f"[GDrive] Error listando archivos de '{folder['name']}' (client_id={client_id}): {e}")
                continue

            for f in files:
                doc = db.query(Document).filter_by(client_id=client_id, external_file_id=f["id"]).first()
                if doc:
                    doc.gdrive_last_seen_at = sync_started_at
                    db.commit()
                    continue

                doc = Document(
                    client_id=client_id,
                    title=clean_filename_to_title(f["name"]),
                    source_type="gdrive",
                    external_file_id=f["id"],
                    is_active=True,
                    gdrive_last_seen_at=sync_started_at,
                )
                db.add(doc)
                db.commit()
                db.refresh(doc)
                db.add(DocumentSegmentLink(client_id=client_id, document_id=doc.id, segment_id=segment.id))
                db.commit()
                sync_document_to_chroma(doc.id)
                summary["created"] += 1

        summary["missing_in_drive"] = db.query(Document).filter(
            Document.client_id == client_id,
            Document.source_type == "gdrive",
            Document.is_active == True,
            (Document.gdrive_last_seen_at == None) | (Document.gdrive_last_seen_at < sync_started_at)
        ).count()

        settings.gdrive_last_sync_at = datetime.utcnow()
        settings.gdrive_last_sync_summary = json.dumps(summary, ensure_ascii=False)
        db.commit()
        return summary
    except Exception as e:
        logging.error(f"[GDrive] Error sincronizando client_id={client_id}: {e}")
        summary["error"] = str(e)
        return summary
    finally:
        db.close()


# --- DESCARGA BAJO DEMANDA (solo al momento de enviar, nunca durante el sync) ---

def check_file_available(client_id: int, external_file_id: str) -> bool:
    service = get_drive_service(client_id)
    if not service:
        return False
    try:
        meta = service.files().get(fileId=external_file_id, fields="id, trashed").execute()
        _mark_share_revoked(client_id, False)
        return not meta.get("trashed", False)
    except HttpError as e:
        if e.resp is not None and e.resp.status in _SHARE_DENIED_STATUSES:
            _mark_share_revoked(client_id, True)
        return False
    except Exception:
        return False


def resolve_file_download(client_id: int, external_file_id: str):
    """Devuelve (bytes, filename, mimetype). El mimeType se resuelve acá, nunca se persiste en DB."""
    service = get_drive_service(client_id)
    if not service:
        raise RuntimeError("No se pudo obtener el servicio de Drive (revisar la cuenta de servicio del cliente)")

    try:
        meta = service.files().get(fileId=external_file_id, fields="name, mimeType, trashed").execute()
    except HttpError as e:
        if e.resp is not None and e.resp.status in _SHARE_DENIED_STATUSES:
            _mark_share_revoked(client_id, True)
        raise
    _mark_share_revoked(client_id, False)

    if meta.get("trashed"):
        raise RuntimeError("El archivo fue eliminado en Drive")

    mime_type = meta.get("mimeType", "")
    filename = meta.get("name", "documento")

    if mime_type.startswith(_GOOGLE_NATIVE_MIME_PREFIX):
        request = service.files().export_media(fileId=external_file_id, mimeType=_GOOGLE_NATIVE_EXPORT_MIME)
        out_mime = _GOOGLE_NATIVE_EXPORT_MIME
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"
    else:
        request = service.files().get_media(fileId=external_file_id)
        out_mime = mime_type or "application/octet-stream"

    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf.read(), filename, out_mime
