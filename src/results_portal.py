"""Portal público "Mis Resultados": el paciente escribe su DNI y baja sus análisis sin pasar por WhatsApp.

Búsqueda en vivo contra la carpeta de Drive del cliente (no usa la Biblioteca de Documentos ni
Chroma). Los archivos se llaman "<PROTOCOLO> <DNI con ceros adelante>.pdf", ej:
"A300044 004593922.pdf" -> protocolo A300044, DNI 4593922.

Protecciones: tope de búsquedas por IP, links de descarga firmados (HMAC, stateless, con
vencimiento) que solo abren archivos de la carpeta configurada, y log de cada búsqueda.
"""
import base64
import hashlib
import hmac
import logging
import os
import re
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from src.database.gdrive_sync import get_drive_service, parse_folder_id_from_input, _FOLDER_MIME
from src.database.models import ClientSettings, ResultsSearchLog
from src.database.session import SessionLocal

DEFAULT_DAYS = 30
DEFAULT_FOLDER_NAME = "PROTOCOLOS"
TOKEN_TTL_SECONDS = 2 * 3600

# Argentina no tiene horario de verano: offset fijo evita depender de tzdata en Windows.
_AR_TZ = timezone(timedelta(hours=-3))
_WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre"]

_RATE_PER_IP = 10          # búsquedas por IP...
_RATE_PER_CLIENT = 400     # ...y tope global por cliente...
_RATE_WINDOW = 600         # ...en esta ventana (segundos)
_ip_hits = {}              # (client_id, ip) -> deque[timestamps]
_client_hits = {}          # client_id -> deque[timestamps]


# --- DNI ---

def normalize_dni(raw: str):
    """'4.593.922' / '04593922' / ' 4593922 ' -> '4593922'. None si no parece un DNI."""
    digits = re.sub(r"\D", "", raw or "").lstrip("0")
    if not (6 <= len(digits) <= 9):
        return None
    return digits


def parse_result_filename(name: str):
    """Devuelve (protocolo, dni) o None. El DNI es el token de solo dígitos; el protocolo, el otro."""
    stem = os.path.splitext(name or "")[0]
    tokens = [t for t in re.split(r"[\s_]+", stem.strip()) if t]
    dni = None
    others = []
    for t in tokens:
        if dni is None and re.fullmatch(r"\d{6,12}", t):
            dni = t.lstrip("0")
        else:
            others.append(t)
    if not dni:
        return None
    return (" ".join(others) or "-"), dni


def _dni_name_variants(dni: str):
    # En Drive, "name contains" busca por prefijo de palabra: hay que probar con los ceros de relleno.
    return sorted({dni, dni.zfill(8), dni.zfill(9), dni.zfill(10)})


def format_date_label(iso_ts: str) -> str:
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).astimezone(_AR_TZ)
    return f"{_WEEKDAYS[dt.weekday()]} {dt.day} de {_MONTHS[dt.month - 1]}"


# --- RATE LIMIT (en memoria, un solo worker de uvicorn) ---

def _hit(bucket: dict, key, limit: int) -> bool:
    now = time.time()
    q = bucket.setdefault(key, deque())
    while q and q[0] < now - _RATE_WINDOW:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def check_rate_limit(client_id: int, ip: str) -> bool:
    if len(_ip_hits) > 5000:
        _ip_hits.clear()
    return _hit(_client_hits, client_id, _RATE_PER_CLIENT) and _hit(_ip_hits, (client_id, ip), _RATE_PER_IP)


# --- TOKENS DE DESCARGA (firmados, sin estado en memoria: sobreviven a un restart) ---

def _secret() -> bytes:
    base = os.getenv("RESULTS_PORTAL_SECRET") or os.getenv("GDRIVE_TOKEN_ENCRYPTION_KEY") or ""
    if not base:
        raise RuntimeError("Falta RESULTS_PORTAL_SECRET / GDRIVE_TOKEN_ENCRYPTION_KEY en el entorno")
    return hmac.new(base.encode(), b"results-portal-v1", hashlib.sha256).digest()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(client_id: int, file_id: str) -> str:
    payload = f"{client_id}.{file_id}.{int(time.time()) + TOKEN_TTL_SECONDS}".encode()
    sig = hmac.new(_secret(), payload, hashlib.sha256).digest()[:18]
    return f"{_b64(payload)}.{_b64(sig)}"


def read_token(token: str):
    """(client_id, file_id) si la firma es válida y no venció; si no, None."""
    try:
        p, s = token.split(".", 1)
        payload = _unb64(p)
        expected = hmac.new(_secret(), payload, hashlib.sha256).digest()[:18]
        if not hmac.compare_digest(expected, _unb64(s)):
            return None
        client_id, file_id, exp = payload.decode().split(".")
        if int(exp) < time.time():
            return None
        return int(client_id), file_id
    except Exception:
        return None


# --- CONFIG ---

def get_portal_settings(settings: ClientSettings) -> dict:
    return {
        "enabled": bool(settings and settings.results_portal_enabled),
        "folder_id": (settings.results_portal_folder_id if settings else None) or "",
        "folder_name": (settings.results_portal_folder_name if settings else None) or "",
        "days": (settings.results_portal_days if settings and settings.results_portal_days else DEFAULT_DAYS),
        "phone": (settings.results_portal_phone if settings and settings.results_portal_phone else None)
                 or (settings.company_phone if settings else "") or "",
        "welcome": (settings.results_portal_welcome if settings else None) or "",
    }


def resolve_folder(client_id: int, raw_input: str):
    """Valida la carpeta pegada (link o ID). Si viene vacío, busca una subcarpeta 'PROTOCOLOS'
    dentro de la carpeta raíz de la Biblioteca. Devuelve (folder_id, folder_name) o (None, error)."""
    service = get_drive_service(client_id)
    if not service:
        return None, "El cliente no tiene cuenta de servicio de Google Drive configurada."
    raw_input = (raw_input or "").strip()
    try:
        if raw_input:
            folder_id = parse_folder_id_from_input(raw_input)
            meta = service.files().get(fileId=folder_id, fields="id, name, mimeType", supportsAllDrives=True).execute()
            if meta.get("mimeType") != _FOLDER_MIME:
                return None, "Eso no es una carpeta de Drive."
            return meta["id"], meta["name"]

        db = SessionLocal()
        try:
            s = db.query(ClientSettings).filter_by(client_id=client_id).first()
            root = s.gdrive_root_folder_id if s else None
        finally:
            db.close()
        q = f"name = '{DEFAULT_FOLDER_NAME}' and mimeType = '{_FOLDER_MIME}' and trashed = false"
        if root:
            q += f" and '{root}' in parents"
        found = service.files().list(q=q, fields="files(id, name)", pageSize=5,
                                     supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get("files", [])
        if not found:
            return None, f"No encontré una carpeta '{DEFAULT_FOLDER_NAME}' compartida con la cuenta de servicio. Pegá el link de la carpeta."
        return found[0]["id"], found[0]["name"]
    except Exception as e:
        logging.error(f"[Resultados] Error resolviendo carpeta (client_id={client_id}): {e}")
        return None, "No se pudo acceder a la carpeta. Verificá que esté compartida con la cuenta de servicio."


# --- BÚSQUEDA ---

def search_results(client_id: int, folder_id: str, dni: str, days: int):
    """Lista de {protocolo, fecha, token}, más nuevo primero. Lanza excepción si Drive falla."""
    return [{
        "protocolo": f["protocolo"],
        "fecha": format_date_label(f["created"]),
        "token": make_token(client_id, f["file_id"]),
    } for f in search_result_files(client_id, folder_id, dni, days)]


def search_result_files(client_id: int, folder_id: str, dni: str, days: int):
    """Archivos de ese DNI (exacto) subidos en los últimos `days` días, más nuevo primero:
    [{file_id, name, protocolo, created}]. `created` es el createdTime ISO de Drive. Lanza si Drive falla."""
    service = get_drive_service(client_id)
    if not service:
        raise RuntimeError("Drive no configurado para el cliente")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    names = " or ".join(f"name contains '{v}'" for v in _dni_name_variants(dni))
    q = f"'{folder_id}' in parents and trashed = false and createdTime > '{since}' and ({names})"

    files, page_token = [], None
    while True:
        resp = service.files().list(
            q=q, fields="nextPageToken, files(id, name, createdTime, mimeType)", orderBy="createdTime desc",
            pageSize=100, pageToken=page_token, supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token or len(files) >= 200:
            break

    results = []
    for f in files:
        parsed = parse_result_filename(f.get("name"))
        if not parsed or parsed[1] != dni:  # "contains" es laxo: se confirma el DNI exacto acá
            continue
        results.append({"file_id": f["id"], "name": f.get("name") or "", "protocolo": parsed[0], "created": f["createdTime"]})
    return results


def list_recent_dnis(client_id: int, folder_id: str, since_dt, max_files: int = 500):
    """DNI (sin ceros) de los archivos creados en la carpeta después de `since_dt` (UTC naive).
    Lo usa el vigía del chat web. Lanza excepción si Drive falla."""
    service = get_drive_service(client_id)
    if not service:
        raise RuntimeError("Drive no configurado para el cliente")
    q = f"'{folder_id}' in parents and trashed = false and createdTime > '{since_dt.strftime('%Y-%m-%dT%H:%M:%S')}'"
    dnis, page_token, seen = set(), None, 0
    while True:
        resp = service.files().list(
            q=q, fields="nextPageToken, files(id, name)", pageSize=100, pageToken=page_token,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        for f in resp.get("files", []):
            parsed = parse_result_filename(f.get("name"))
            if parsed:
                dnis.add(parsed[1])
        seen += len(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token or seen >= max_files:
            break
    return dnis


def fetch_result_file(client_id: int, folder_id: str, file_id: str):
    """(bytes, filename, mimetype) solo si el archivo sigue en la carpeta del portal."""
    from src.database.gdrive_sync import resolve_file_download
    service = get_drive_service(client_id)
    if not service:
        return None
    meta = service.files().get(fileId=file_id, fields="parents, trashed", supportsAllDrives=True).execute()
    if meta.get("trashed") or folder_id not in (meta.get("parents") or []):
        return None
    return resolve_file_download(client_id, file_id)


def log_search(client_id: int, dni: str, ip: str, found: int, error: bool = False):
    db = SessionLocal()
    try:
        db.add(ResultsSearchLog(client_id=client_id, dni=dni[:20], ip=(ip or "")[:64], results_count=found, error=error))
        db.commit()
    except Exception as e:
        logging.error(f"[Resultados] No se pudo guardar el log de búsqueda: {e}")
    finally:
        db.close()
