"""Verificador de protocolos subidos: para que el personal del laboratorio confirme que los PDFs están en
la carpeta de Drive y que el paciente los va a encontrar en el portal / chat web. Sin IA.

Hace UNA lectura de la carpeta (últimos LOOKBACK_DAYS días, cacheada CACHE_SECONDS) y todo lo demás se resuelve
en memoria con las mismas reglas de nombre que usa el portal del paciente (results_portal.parse_result_filename),
así lo que ve el personal es lo que verá el paciente.
"""
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from src.database.gdrive_sync import get_drive_service
from src.results_portal import parse_result_filename, _AR_TZ, _WEEKDAYS, _MONTHS

LOOKBACK_DAYS = 120   # ventana de la lectura; el paciente solo ve los últimos `days` del portal
CACHE_SECONDS = 60
MAX_FILES = 30000
MAX_LINES = 500

_cache = {}           # (client_id, folder_id) -> (timestamp, files)
_lock = threading.Lock()


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def list_folder_files(client_id: int, folder_id: str, force: bool = False):
    """[{id, name, created(datetime UTC), protocolo, dni}] más nuevo primero. protocolo/dni = None si el
    nombre no sigue el formato (ese archivo el paciente NO lo encuentra). Lanza excepción si Drive falla."""
    key = (client_id, folder_id)
    with _lock:
        hit = _cache.get(key)
        if hit and not force and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    service = get_drive_service(client_id)
    if not service:
        raise RuntimeError("Drive no configurado para el cliente")
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    q = f"'{folder_id}' in parents and trashed = false and createdTime > '{since}'"
    out, page_token = [], None
    while True:
        resp = service.files().list(
            q=q, fields="nextPageToken, files(id, name, createdTime, mimeType)", orderBy="createdTime desc",
            pageSize=1000, pageToken=page_token, supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        for f in resp.get("files", []):
            if f.get("mimeType") == "application/vnd.google-apps.folder":
                continue
            parsed = parse_result_filename(f.get("name"))
            out.append({"id": f["id"], "name": f.get("name") or "", "created": _parse_iso(f["createdTime"]),
                        "protocolo": parsed[0] if parsed else None, "dni": parsed[1] if parsed else None})
        page_token = resp.get("nextPageToken")
        if not page_token or len(out) >= MAX_FILES:
            break
    with _lock:
        _cache[key] = (time.time(), out)
    return out


def _ar(dt: datetime) -> datetime:
    return dt.astimezone(_AR_TZ)


def _day_label(d) -> str:
    return f"{_WEEKDAYS[d.weekday()]} {d.day} de {_MONTHS[d.month - 1]}"


def summarize(files, days: int, now: datetime = None):
    """Resumen para tranquilidad: subidos por día (últimos 7 días), última subida y archivos con nombre raro."""
    now = now or datetime.now(timezone.utc)
    today = _ar(now).date()
    per_day = {today - timedelta(days=i): 0 for i in range(7)}
    for f in files:
        d = _ar(f["created"]).date()
        if d in per_day:
            per_day[d] += 1
    last = max((f["created"] for f in files), default=None)
    odd = [f for f in files if not f["dni"] and _ar(f["created"]) >= _ar(now) - timedelta(days=days)]
    return {
        "per_day": [{"date": d.isoformat(), "label": ("Hoy" if d == today else "Ayer" if d == today - timedelta(days=1) else _day_label(d)),
                     "count": c} for d, c in sorted(per_day.items(), reverse=True)],
        "last_upload": ({"at": last.strftime("%Y-%m-%dT%H:%M:%SZ"), "minutes_ago": int((now - last).total_seconds() // 60)} if last else None),
        "total_in_window": len(files),
        "odd_names": {"count": len(odd), "examples": [f["name"] for f in odd[:15]]},
    }


def _classify(line: str):
    """('file'|'dni'|'proto', valor normalizado) o None si la línea no sirve."""
    raw = (line or "").strip().strip(",;")
    if not raw:
        return None
    parsed = parse_result_filename(raw) if re.search(r"[\s_\-]", raw) or raw.lower().endswith(".pdf") else None
    if parsed and re.search(r"[A-Za-z]", raw):
        return "file", (parsed[0].upper(), parsed[1])
    digits = re.sub(r"[.\s]", "", raw)
    if re.fullmatch(r"\d{6,9}", digits):
        return "dni", digits.lstrip("0")
    token = re.sub(r"\.pdf$", "", raw, flags=re.I).strip()
    if re.fullmatch(r"[A-Za-z0-9]{3,20}", token):
        return "proto", token.upper()
    return None


def check_items(files, text: str, days: int, now: datetime = None):
    """Compara una lista pegada (un DNI, protocolo o nombre de archivo por línea) contra la carpeta.
    Devuelve (filas, resumen). Cada fila: {input, kind, status: 'ok'|'old'|'missing'|'invalid', matches:[...]}
    'old' = está en la carpeta pero con más de `days` días: el paciente ya no lo ve."""
    now = now or datetime.now(timezone.utc)
    limit = now - timedelta(days=days)
    by_dni, by_proto = {}, {}
    for f in files:
        if f["dni"]:
            by_dni.setdefault(f["dni"], []).append(f)
        if f["protocolo"]:
            by_proto.setdefault(f["protocolo"].upper(), []).append(f)

    rows, seen = [], set()
    for line in (text or "").splitlines()[:MAX_LINES]:
        if not line.strip():
            continue
        c = _classify(line)
        if not c:
            rows.append({"input": line.strip()[:60], "kind": "invalid", "status": "invalid", "matches": []})
            continue
        kind, val = c
        if (kind, val) in seen:
            continue
        seen.add((kind, val))
        if kind == "dni":
            found = by_dni.get(val, [])
        elif kind == "proto":
            found = by_proto.get(val, [])
        else:
            found = [f for f in by_dni.get(val[1], []) if (f["protocolo"] or "").upper() == val[0]]
        matches = [{"id": f["id"], "name": f["name"], "protocolo": f["protocolo"],
                    "at": f["created"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "visible_until": (f["created"] + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "visible": f["created"] > limit} for f in found]
        status = "missing" if not matches else ("ok" if any(m["visible"] for m in matches) else "old")
        rows.append({"input": line.strip()[:60], "kind": kind, "status": status, "matches": matches[:6]})

    summary = {s: sum(1 for r in rows if r["status"] == s) for s in ("ok", "old", "missing", "invalid")}
    summary["total"] = len(rows)
    return rows, summary


def _terms_for(line: str):
    """Textos a buscar en Drive (name contains) para una línea: DNI con ceros de relleno, o el protocolo."""
    c = _classify(line)
    if not c:
        return []
    kind, val = c
    if kind == "dni":
        return sorted({val, val.zfill(8), val.zfill(9), val.zfill(10)})
    if kind == "proto":
        return [val]
    return [val[0]]


def search_files(client_id: int, folder_id: str, terms, max_results: int = 200):
    """Búsqueda directa en Drive, SIN límite de antigüedad (la lectura cacheada sólo cubre LOOKBACK_DAYS).
    Mismo formato que list_folder_files."""
    terms = [t for t in terms if re.fullmatch(r"[A-Za-z0-9]{3,20}", t or "")]
    if not terms:
        return []
    service = get_drive_service(client_id)
    if not service:
        raise RuntimeError("Drive no configurado para el cliente")
    names = " or ".join(f"name contains '{t}'" for t in terms)
    q = f"'{folder_id}' in parents and trashed = false and ({names})"
    resp = service.files().list(
        q=q, fields="files(id, name, createdTime, mimeType)", orderBy="createdTime desc", pageSize=min(max_results, 1000),
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    out = []
    for f in resp.get("files", []):
        if f.get("mimeType") == "application/vnd.google-apps.folder":
            continue
        parsed = parse_result_filename(f.get("name"))
        out.append({"id": f["id"], "name": f.get("name") or "", "created": _parse_iso(f["createdTime"]),
                    "protocolo": parsed[0] if parsed else None, "dni": parsed[1] if parsed else None})
    return out


MAX_DIRECT_LOOKUPS = 40


def check_text(client_id: int, folder_id: str, files, text: str, days: int):
    """check_items + segunda pasada: lo que no aparece entre los archivos recientes se busca directo en
    Drive (protocolos de hace meses o años). Sólo después de eso se informa 'missing'."""
    rows, summary = check_items(files, text, days)
    missing = [r for r in rows if r["status"] == "missing"][:MAX_DIRECT_LOOKUPS]
    if not missing:
        return rows, summary
    known = {f["id"] for f in files}
    extra = []
    for r in missing:
        for f in search_files(client_id, folder_id, _terms_for(r["input"])):
            if f["id"] not in known:
                known.add(f["id"])
                extra.append(f)
    return check_items(list(files) + extra, text, days) if extra else (rows, summary)
