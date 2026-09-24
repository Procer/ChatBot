"""Métricas y controles del piloto del chat web (Fase 5): embudo, serie diaria, costo de IA,
checklist de puesta en marcha y estado del servidor."""
import os
from datetime import datetime, timedelta

from sqlalchemy import func

from src.database.models import (ClientSettings, TokenUsage, WebBroadcast, WebDelivery, WebDevice, WebEvent, WebLink,
                                 WebPushSub)

_AR = timedelta(hours=3)


def _day(dt: datetime) -> str:
    return (dt - _AR).strftime("%Y-%m-%d")


def _bucket(rows, days: list) -> list:
    """rows: iterable de datetimes (UTC) -> cantidad por dia local, alineada con `days`."""
    counts = {d: 0 for d in days}
    for (dt,) in rows:
        if dt is not None:
            k = _day(dt)
            if k in counts:
                counts[k] += 1
    return [counts[d] for d in days]


def compute(db, client_id: int, days: int = 14) -> dict:
    days = max(1, min(90, days))
    now = datetime.utcnow()
    today_local = (now - _AR).replace(hour=0, minute=0, second=0, microsecond=0)
    labels = [(today_local - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    since = (today_local - timedelta(days=days - 1)) + _AR      # inicio del primer dia, en UTC
    q = lambda col, *flt: db.query(col).filter(*flt)

    new_devices = _bucket(q(WebDevice.created_at, WebDevice.client_id == client_id, WebDevice.created_at >= since).all(), labels)
    messages = _bucket(q(WebEvent.created_at, WebEvent.client_id == client_id, WebEvent.kind == "user", WebEvent.created_at >= since).all(), labels)
    links_new = _bucket(q(WebLink.created_at, WebLink.client_id == client_id, WebLink.created_at >= since).all(), labels)
    links_ok = _bucket(q(WebLink.verified_at, WebLink.client_id == client_id, WebLink.verified_at >= since).all(), labels)
    delivered = _bucket(q(WebDelivery.created_at, WebDelivery.client_id == client_id, WebDelivery.created_at >= since).all(), labels)
    subs_new = _bucket(q(WebPushSub.created_at, WebPushSub.client_id == client_id, WebPushSub.created_at >= since).all(), labels)

    # Embudo (histórico del cliente): escaneó -> vinculó -> verificó -> activó avisos
    devices_total = db.query(WebDevice).filter_by(client_id=client_id).count()
    linked = db.query(func.count(func.distinct(WebLink.device_id))).filter(WebLink.client_id == client_id).scalar() or 0
    verified = db.query(func.count(func.distinct(WebLink.device_id))).filter(WebLink.client_id == client_id, WebLink.status == "verificado").scalar() or 0
    with_push = db.query(func.count(func.distinct(WebPushSub.device_id))).filter(WebPushSub.client_id == client_id).scalar() or 0
    with_news = db.query(func.count(func.distinct(WebPushSub.device_id))).filter(WebPushSub.client_id == client_id, WebPushSub.topic_news == True).scalar() or 0  # noqa: E712
    chatted = db.query(func.count(func.distinct(WebEvent.device_id))).filter(WebEvent.client_id == client_id, WebEvent.kind == "user").scalar() or 0
    status = dict(db.query(WebLink.status, func.count(WebLink.id)).filter(WebLink.client_id == client_id).group_by(WebLink.status).all())

    # Costo de IA de las conversaciones web en el periodo
    tu = db.query(func.coalesce(func.sum(TokenUsage.cost_usd), 0.0), func.coalesce(func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens), 0)) \
        .filter(TokenUsage.client_id == client_id, TokenUsage.thread_id.like("web:%"), TokenUsage.timestamp >= since).one()
    msgs_period = sum(messages)
    active_7d = db.query(WebDevice).filter(WebDevice.client_id == client_id, WebDevice.last_seen_at >= now - timedelta(days=7)).count()
    bcs = db.query(WebBroadcast).filter(WebBroadcast.client_id == client_id, WebBroadcast.status == "enviado", WebBroadcast.sent_at >= since).count()

    pct = lambda a, b: round(100.0 * a / b) if b else 0
    return {
        "days": labels,
        "series": {"new_devices": new_devices, "messages": messages, "links_new": links_new, "links_verified": links_ok,
                   "deliveries": delivered, "push_subs": subs_new},
        "funnel": [
            {"key": "scanned", "label": "Abrieron el chat", "n": devices_total, "pct": 100 if devices_total else 0},
            {"key": "chatted", "label": "Le escribieron al bot", "n": chatted, "pct": pct(chatted, devices_total)},
            {"key": "linked", "label": "Vincularon su DNI", "n": linked, "pct": pct(linked, devices_total)},
            {"key": "verified", "label": "Verificados (vieron su análisis)", "n": verified, "pct": pct(verified, devices_total)},
            {"key": "push", "label": "Activaron los avisos", "n": with_push, "pct": pct(with_push, devices_total)},
            {"key": "news", "label": "Aceptaron novedades", "n": with_news, "pct": pct(with_news, devices_total)},
        ],
        "totals": {"devices": devices_total, "active_7d": active_7d, "messages": msgs_period,
                   "deliveries": sum(delivered), "links_by_status": status, "broadcasts": bcs,
                   "ai_cost_usd": round(float(tu[0]), 4), "ai_tokens": int(tu[1]),
                   "ai_cost_per_msg_usd": round(float(tu[0]) / msgs_period, 5) if msgs_period else 0.0},
    }


def to_csv(m: dict) -> str:
    cols = [("new_devices", "celulares_nuevos"), ("messages", "mensajes_al_bot"), ("links_new", "vinculaciones"),
            ("links_verified", "verificadas"), ("deliveries", "analisis_entregados"), ("push_subs", "avisos_activados")]
    lines = ["fecha," + ",".join(n for _, n in cols)]
    for i, day in enumerate(m["days"]):
        lines.append(day + "," + ",".join(str(m["series"][k][i]) for k, _ in cols))
    return "\n".join(lines) + "\n"


def checklist(db, client_id: int, settings: ClientSettings) -> list:
    """Puntos para arrancar el piloto. status: ok | warn | todo. `manual` = lo confirma una persona."""
    from src.web_chat import DEFAULT_WELCOME
    push_devices = db.query(WebPushSub.device_id).filter(WebPushSub.client_id == client_id).distinct().count()
    items = [
        ("chat_on", "El chat está encendido", "ok" if settings.web_chat_enabled else "todo", "Activá “Chat encendido” y guardá."),
        ("folder", "Carpeta de PROTOCOLOS conectada", "ok" if (settings.results_portal_folder_id and settings.gdrive_service_account_json_encrypted) else "todo",
         "Configurala en Biblioteca de Documentos → Portal “Mis Resultados”."),
        ("results_on", "Resultados dentro del chat activados", "ok" if settings.web_chat_results_enabled else "todo", "Activá “Entregar resultados en el chat”."),
        ("logo", "Logo propio del chat cargado", "ok" if (settings.web_chat_logo or settings.logo_path) else "warn", "Subí un logo cuadrado con solo el símbolo."),
        ("welcome", "Mensaje de bienvenida personalizado", "ok" if (settings.web_chat_welcome or "").strip() and (settings.web_chat_welcome or "").strip() != DEFAULT_WELCOME else "warn",
         "Escribí el saludo definitivo del laboratorio."),
        ("consent", "Texto de consentimiento definido", "ok" if (settings.web_chat_consent or "").strip() else "warn",
         "Hoy se usa el texto por defecto: conviene que lo revise el asesor legal del laboratorio."),
        ("push_tested", "Al menos un celular con avisos activados (prueba hecha)", "ok" if push_devices else "todo",
         "Abrí el chat en un celular, vinculá un DNI de prueba y tocá “Sí, avisame”."),
        ("kb", "El bot responde con la información del laboratorio cargada", "manual", "Probá horarios, preparación y turnos desde el chat."),
        ("poster", "Cartel con el QR impreso y puesto en recepción", "manual", "Imprimilo desde este panel (botón “Imprimir cartel A4”)."),
        ("staff", "Recepción leyó el instructivo", "manual", "Imprimí el instructivo para recepción desde este panel."),
    ]
    return [{"key": k, "label": l, "status": s, "hint": h} for k, l, s, h in items]


def server_health(db) -> dict:
    """Consumo del servidor relevante para el chat web (solo lo ve el super admin)."""
    rss = None
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss = round(int(line.split()[1]) / 1024, 1)    # kB -> MB
    except Exception:
        pass
    ck = None
    try:
        ck = round(os.path.getsize("checkpoints.sqlite") / 1048576, 1)
    except Exception:
        pass
    return {"process_rss_mb": rss, "checkpoints_mb": ck,
            "web_devices": db.query(WebDevice).count(), "web_events": db.query(WebEvent).count(),
            "web_links": db.query(WebLink).count(), "push_subs": db.query(WebPushSub).count(),
            "web_threads_with_messages": db.query(func.count(func.distinct(WebEvent.device_id))).scalar() or 0}
