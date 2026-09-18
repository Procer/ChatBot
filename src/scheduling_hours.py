"""Horario semanal estructurado del negocio (Config -> Empresa -> Horarios de Atención).

Reemplaza el parseo por regex de un texto libre ("Lunes a Viernes 09:00-18:00" o
"09:00-13:00, 16:00-20:00") por un JSON por día de la semana, con turnos múltiples por día
(ej. mañana/tarde) y habilitación independiente por día (ej. sábado con otro horario, domingo
cerrado) - pedido real de un usuario probando en vivo (2026-09-17): "muchos atienden en dos
horarios (a la mañana, cierran al mediodía, y abren a la tarde), y lo mismo en otro horario
el finde". Los clientes que todavía no migraron a este formato (working_hours_json vacío)
siguen usando el texto libre legacy (ver is_within_working_hours en main_saas.py y el fallback
en get_slots_disponibles_saas de graph_saas.py).
"""
import json
from datetime import datetime

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_LABELS = {
    "mon": "Lunes", "tue": "Martes", "wed": "Miércoles", "thu": "Jueves",
    "fri": "Viernes", "sat": "Sábado", "sun": "Domingo",
}
WEEKDAY_TO_KEY = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}


def default_schedule():
    """Lunes a viernes con dos turnos (mañana/tarde), fin de semana cerrado - el caso más
    común de comercio, para no arrancar con el editor completamente vacío."""
    schedule = {}
    for d in DAYS:
        if d in ("sat", "sun"):
            schedule[d] = {"enabled": False, "ranges": []}
        else:
            schedule[d] = {"enabled": True, "ranges": [["09:00", "13:00"], ["16:00", "20:00"]]}
    return schedule


def parse_schedule(json_str):
    """Devuelve el dict de horario semanal a partir del JSON guardado, o None si no hay JSON
    válido (cliente que todavía no migró a este formato, o texto legacy)."""
    if not json_str:
        return None
    try:
        data = json.loads(json_str)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    schedule = {}
    for d in DAYS:
        entry = data.get(d) or {}
        clean_ranges = []
        for r in (entry.get("ranges") or []):
            if isinstance(r, (list, tuple)) and len(r) == 2 and r[0] and r[1]:
                clean_ranges.append((str(r[0]).strip(), str(r[1]).strip()))
        schedule[d] = {"enabled": bool(entry.get("enabled")) and bool(clean_ranges), "ranges": clean_ranges}
    return schedule


def get_ranges_for_date(schedule, date_str):
    """Lista de (start, end) para esa fecha (YYYY-MM-DD), o [] si el negocio está cerrado ese día."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return []
    entry = schedule.get(WEEKDAY_TO_KEY[d.weekday()]) or {}
    if not entry.get("enabled"):
        return []
    return entry.get("ranges") or []


def is_open_now(schedule, now=None):
    now = now or datetime.now()
    entry = schedule.get(WEEKDAY_TO_KEY[now.weekday()]) or {}
    if not entry.get("enabled"):
        return False
    for start_str, end_str in (entry.get("ranges") or []):
        try:
            start_t = datetime.strptime(start_str, "%H:%M").time()
            end_t = datetime.strptime(end_str, "%H:%M").time()
        except ValueError:
            continue
        if start_t <= end_t:
            if start_t <= now.time() <= end_t:
                return True
        else:
            # Rango que cruza la medianoche (ej. 22:00-02:00).
            if now.time() >= start_t or now.time() <= end_t:
                return True
    return False


def format_schedule_text(schedule):
    """Texto legible en español (para el prompt del bot y como respaldo del campo de texto
    legacy), agrupando días consecutivos con el mismo horario: 'Lunes a viernes: 09:00-13:00
    y 16:00-20:00. Sábado: 09:00-13:00. Domingo: cerrado.'"""
    def ranges_key(entry):
        if not entry.get("enabled") or not entry.get("ranges"):
            return None
        return tuple(tuple(r) for r in entry["ranges"])

    groups = []
    current_key, current_days = "unset", []
    for d in DAYS:
        k = ranges_key(schedule.get(d) or {})
        if current_days and k == current_key:
            current_days.append(d)
        else:
            if current_days:
                groups.append((current_days, current_key))
            current_days, current_key = [d], k
    if current_days:
        groups.append((current_days, current_key))

    parts = []
    for days, key in groups:
        label = DAY_LABELS[days[0]] if len(days) == 1 else f"{DAY_LABELS[days[0]]} a {DAY_LABELS[days[-1]]}"
        if key is None:
            parts.append(f"{label}: cerrado")
        else:
            parts.append(f"{label}: " + " y ".join(f"{s}-{e}" for s, e in key))
    return (". ".join(parts) + ".") if parts else "No especificados"
