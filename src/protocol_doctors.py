"""Acceso de médicos a la página pública de verificación de protocolos (/verificar/<token>):
usuario + contraseña propios, sesión por cookie firmada e indicadores de uso (ingresos / comprobaciones)."""
import hashlib
import hmac
import secrets
import time
from collections import deque
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.database.models import ProtocolDoctor, ProtocolDoctorEvent
from src.results_portal import _secret

COOKIE = "pc_doc"
SESSION_DAYS = 30
_PBKDF2_ROUNDS = 200_000

_fails = {}  # ip -> deque de timestamps de logins fallidos
_FAIL_WINDOW, _FAIL_MAX = 600, 8


def hash_password(password: str) -> str:
    salt = secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ROUNDS).hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    cand = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ROUNDS).hex()
    return hmac.compare_digest(cand, digest)


def login_allowed(ip: str) -> bool:
    if len(_fails) > 5000:
        _fails.clear()
    q = _fails.setdefault(ip, deque())
    while q and q[0] < time.time() - _FAIL_WINDOW:
        q.popleft()
    return len(q) < _FAIL_MAX


def register_failure(ip: str):
    _fails.setdefault(ip, deque()).append(time.time())


def _sig(client_id: int, doctor_id: int, exp: int) -> str:
    return hmac.new(_secret(), f"pcdoc|{client_id}|{doctor_id}|{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def make_cookie(client_id: int, doctor_id: int) -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    return f"{doctor_id}.{exp}.{_sig(client_id, doctor_id, exp)}"


def doctor_from_cookie(db: Session, client_id: int, cookie: str):
    """ProtocolDoctor activo del cliente al que pertenece la cookie, o None."""
    try:
        did, exp, sig = (cookie or "").split(".")
        did, exp = int(did), int(exp)
    except ValueError:
        return None
    if exp < time.time() or not hmac.compare_digest(sig, _sig(client_id, did, exp)):
        return None
    d = db.query(ProtocolDoctor).filter_by(id=did, client_id=client_id).first()
    return d if d and d.active else None


def add_event(db: Session, client_id: int, doctor_id: int, kind: str, status: str = None):
    db.add(ProtocolDoctorEvent(client_id=client_id, doctor_id=doctor_id, kind=kind, status=status))
    db.commit()


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def stats(db: Session, client_id: int):
    """Indicadores por médico + totales. Fechas en UTC ISO (el navegador las pasa a hora local)."""
    week = datetime.utcnow() - timedelta(days=7)
    doctors = db.query(ProtocolDoctor).filter_by(client_id=client_id).order_by(ProtocolDoctor.created_at).all()
    E = ProtocolDoctorEvent
    rows = db.query(E.doctor_id, E.kind, E.status, func.count(), func.max(E.at)).filter(E.client_id == client_id) \
        .group_by(E.doctor_id, E.kind, E.status).all()
    rows7 = db.query(E.doctor_id, E.kind, func.count()).filter(E.client_id == client_id, E.at > week) \
        .group_by(E.doctor_id, E.kind).all()
    ev7 = {(d, k): c for d, k, c in rows7}
    blank = {"logins": 0, "views": 0, "checks": 0, "found": 0, "missing": 0, "last_login": None, "last_check": None}
    by = {}
    for did, kind, status, cnt, last in rows:
        r = by.setdefault(did, dict(blank))
        if kind == "login":
            r["logins"] += cnt
            r["last_login"] = max(r["last_login"] or last, last)
        elif kind == "view":
            r["views"] += cnt
        else:
            r["checks"] += cnt
            r["last_check"] = max(r["last_check"] or last, last)
            if status in ("ok", "old"):
                r["found"] += cnt
            elif status == "missing":
                r["missing"] += cnt
    out = []
    for d in doctors:
        r = by.get(d.id, blank)
        out.append({"id": d.id, "username": d.username, "name": d.name or "", "active": bool(d.active),
                    "logins": r["logins"], "views": r["views"], "checks": r["checks"], "found": r["found"], "missing": r["missing"],
                    "logins_7d": ev7.get((d.id, "login"), 0), "checks_7d": ev7.get((d.id, "check"), 0),
                    "last_login": _iso(r["last_login"]), "last_check": _iso(r["last_check"])})
    totals = {k: sum(x[k] for x in out) for k in ("logins", "views", "checks", "logins_7d", "checks_7d", "found", "missing")}
    totals["doctors"] = len(out)
    return {"doctors": out, "totals": totals}
