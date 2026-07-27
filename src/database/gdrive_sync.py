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
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

load_dotenv()

from src.database.session import SessionLocal
from src.database.models import ClientSettings, Document, DocumentSegmentLink

GOOGLE_OAUTH_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")  # opcional; si falta, se deriva de request.base_url
GDRIVE_TOKEN_ENCRYPTION_KEY = os.getenv("GDRIVE_TOKEN_ENCRYPTION_KEY")

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_FOLDER_MIME = "application/vnd.google-apps.folder"
_GOOGLE_NATIVE_MIME_PREFIX = "application/vnd.google-apps."
_GOOGLE_NATIVE_EXPORT_MIME = "application/pdf"

_STATE_TTL = 600
_DOWNLOAD_TOKEN_TTL = 600
_oauth_states = {}    # state -> {"client_id": int, "expires_at": float}
_download_tokens = {}  # token -> {"client_id", "thread_id", "document_id", "expires_at"}


# --- TÍTULO AUTOMÁTICO (misma regla que cleanTitleFromFilename en document_library.html) ---

def clean_filename_to_title(filename: str) -> str:
    name = os.path.splitext(filename)[0]
    name = re.sub(r"[-_]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return " ".join(w.capitalize() for w in name.split(" "))


# --- ENCRIPTACIÓN DEL REFRESH TOKEN ---
# A diferencia de whatsapp_token/telegram_token (texto plano en ClientSettings), un refresh_token
# de Drive da acceso de lectura permanente a todo el Drive de la cuenta que lo autorizó: amerita
# encriptación en reposo aunque el resto del proyecto no la use.

def _fernet() -> Fernet:
    if not GDRIVE_TOKEN_ENCRYPTION_KEY:
        raise RuntimeError("GDRIVE_TOKEN_ENCRYPTION_KEY no está configurada en el entorno")
    key = GDRIVE_TOKEN_ENCRYPTION_KEY.encode("utf-8") if isinstance(GDRIVE_TOKEN_ENCRYPTION_KEY, str) else GDRIVE_TOKEN_ENCRYPTION_KEY
    return Fernet(key)


def encrypt_token(raw: str) -> str:
    return _fernet().encrypt(raw.encode("utf-8")).decode("utf-8")


def decrypt_token(enc: str) -> str:
    return _fernet().decrypt(enc.encode("utf-8")).decode("utf-8")


# --- CREDENCIALES DE LA APP OAUTH (propias de cada cliente/tenant) ---
# Cada cliente registra su propio proyecto/app en Google Cloud y carga acá su Client ID/Secret
# (panel Super Admin → Configuración del Cliente). Esto es DISTINTO de la cuenta de Drive que
# el cliente conecta después (ClientSettings.gdrive_refresh_token_encrypted) — una cosa es
# "qué app pide permiso" y otra "a qué cuenta de Drive se le pide permiso".

def get_google_oauth_credentials(tenant_client_id: int):
    """Devuelve (oauth_client_id, oauth_client_secret) del cliente/tenant, o (None, None) si no configuró la app."""
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=tenant_client_id).first()
        if not settings or not settings.google_oauth_client_id or not settings.google_oauth_client_secret_encrypted:
            return None, None
        try:
            return settings.google_oauth_client_id, decrypt_token(settings.google_oauth_client_secret_encrypted)
        except Exception as e:
            logging.error(f"[GDrive] Error desencriptando google_oauth_client_secret (client_id={tenant_client_id}): {e}")
            return None, None
    finally:
        db.close()


def save_google_oauth_credentials(tenant_client_id: int, oauth_client_id: str, oauth_client_secret: str = None) -> None:
    """oauth_client_secret=None deja el secreto ya guardado sin cambios (para poder actualizar solo el client_id)."""
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=tenant_client_id).first()
        if not settings:
            raise RuntimeError(f"No existe ClientSettings para client_id={tenant_client_id}")
        settings.google_oauth_client_id = oauth_client_id
        if oauth_client_secret:
            settings.google_oauth_client_secret_encrypted = encrypt_token(oauth_client_secret)
        db.commit()
    finally:
        db.close()


def get_google_oauth_status(tenant_client_id: int) -> dict:
    oauth_client_id, oauth_client_secret = get_google_oauth_credentials(tenant_client_id)
    return {"client_id": oauth_client_id or "", "configured": bool(oauth_client_id and oauth_client_secret)}


# --- OAUTH ---

def build_oauth_flow(redirect_uri: str, tenant_client_id: int) -> Flow:
    oauth_client_id, oauth_client_secret = get_google_oauth_credentials(tenant_client_id)
    if not oauth_client_id or not oauth_client_secret:
        raise RuntimeError("Este cliente todavía no cargó las credenciales de su app OAuth de Google")
    client_config = {
        "web": {
            "client_id": oauth_client_id,
            "client_secret": oauth_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    return Flow.from_client_config(client_config, scopes=DRIVE_SCOPES, redirect_uri=redirect_uri)


def get_oauth_redirect_uri(request_base_url: str) -> str:
    if GOOGLE_OAUTH_REDIRECT_URI:
        return GOOGLE_OAUTH_REDIRECT_URI
    return f"{str(request_base_url).rstrip('/')}/api/admin/gdrive/oauth/callback"


def _sweep_expired(cache: dict):
    now = time.time()
    for k in [k for k, v in cache.items() if v.get("expires_at", 0) < now]:
        cache.pop(k, None)


def generate_oauth_state(client_id: int) -> str:
    _sweep_expired(_oauth_states)
    state = secrets.token_urlsafe(24)
    _oauth_states[state] = {"client_id": client_id, "expires_at": time.time() + _STATE_TTL}
    return state


def pop_oauth_state(state: str):
    entry = _oauth_states.pop(state, None)
    if not entry or entry["expires_at"] < time.time():
        return None
    return entry["client_id"]


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


def save_oauth_tokens(client_id: int, credentials) -> None:
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings:
            return
        if not credentials.refresh_token:
            logging.warning(f"[GDrive] No se recibió refresh_token para client_id={client_id} (¿ya estaba autorizado sin revocar?)")
            return

        settings.gdrive_refresh_token_encrypted = encrypt_token(credentials.refresh_token)
        settings.gdrive_connected_at = datetime.utcnow()
        settings.gdrive_needs_reconnect = False

        try:
            service = build("drive", "v3", credentials=credentials)
            about = service.about().get(fields="user").execute()
            settings.gdrive_connected_email = about.get("user", {}).get("emailAddress")
        except Exception as e:
            logging.error(f"[GDrive] Error obteniendo email de la cuenta conectada (client_id={client_id}): {e}")

        db.commit()
    finally:
        db.close()


def disconnect_drive(client_id: int) -> None:
    db = SessionLocal()
    refresh_token = None
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings:
            return
        if settings.gdrive_refresh_token_encrypted:
            try:
                refresh_token = decrypt_token(settings.gdrive_refresh_token_encrypted)
            except Exception:
                pass
        settings.gdrive_refresh_token_encrypted = None
        settings.gdrive_connected_email = None
        settings.gdrive_connected_at = None
        settings.gdrive_root_folder_id = None
        settings.gdrive_root_folder_name = None
        settings.gdrive_needs_reconnect = False
        db.commit()
    finally:
        db.close()

    if refresh_token:
        try:
            import requests
            requests.post("https://oauth2.googleapis.com/revoke", params={"token": refresh_token}, timeout=5)
        except Exception as e:
            logging.warning(f"[GDrive] No se pudo revocar el token en Google (client_id={client_id}): {e}")


def get_drive_service(client_id: int):
    db = SessionLocal()
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings or not settings.gdrive_refresh_token_encrypted:
            return None
        try:
            refresh_token = decrypt_token(settings.gdrive_refresh_token_encrypted)
        except Exception as e:
            logging.error(f"[GDrive] Error desencriptando refresh_token (client_id={client_id}): {e}")
            return None

        oauth_client_id, oauth_client_secret = get_google_oauth_credentials(client_id)
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=oauth_client_id,
            client_secret=oauth_client_secret,
            scopes=DRIVE_SCOPES,
        )
        try:
            creds.refresh(GoogleAuthRequest())
        except RefreshError as e:
            logging.error(f"[GDrive] Refresh token inválido/revocado (client_id={client_id}): {e}")
            settings.gdrive_needs_reconnect = True
            db.commit()
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

    summary = {"created": 0, "unmapped_folders": [], "root_files_skipped": 0, "missing_in_drive": 0, "needs_reconnect": False}

    service = get_drive_service(client_id)
    if not service:
        summary["needs_reconnect"] = True
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
        except Exception as e:
            logging.error(f"[GDrive] Error listando la carpeta raíz (client_id={client_id}): {e}")
            summary["error"] = str(e)
            return summary

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
        return not meta.get("trashed", False)
    except Exception:
        return False


def resolve_file_download(client_id: int, external_file_id: str):
    """Devuelve (bytes, filename, mimetype). El mimeType se resuelve acá, nunca se persiste en DB."""
    service = get_drive_service(client_id)
    if not service:
        raise RuntimeError("No se pudo obtener el servicio de Drive (revisar conexión del cliente)")

    meta = service.files().get(fileId=external_file_id, fields="name, mimeType, trashed").execute()
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
