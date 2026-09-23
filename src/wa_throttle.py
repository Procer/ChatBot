"""Proteccion anti-bloqueo para el canal de WhatsApp (Green-API).

Green-API automatiza WhatsApp Web, asi que WhatsApp puede bloquear el numero si el patron de
envio parece no humano (rafagas, volumen alto, mensajes a quien no espera nada). Este modulo
agrega, de forma configurable por cliente (ClientSettings.wa_*):
  - pausa aleatoria (y opcionalmente el indicador "escribiendo...") antes de cada envio,
  - tope de mensajes por minuto (los mensajes esperan, no se pierden),
  - tope de mensajes proactivos por hora (recordatorios/avisos que el bot inicia solo).
Los contadores viven en memoria del proceso: alcanzan para el objetivo (evitar rafagas) y se
reinician con el servicio.
"""
import asyncio
import random
import time
from collections import defaultdict, deque

import httpx

DEFAULT_DELAY_MIN = 2
DEFAULT_DELAY_MAX = 5
DEFAULT_PER_MINUTE = 20
DEFAULT_PROACTIVE_PER_HOUR = 40

_sent_last_minute = defaultdict(deque)     # client_id -> timestamps de todos los envios
_proactive_last_hour = defaultdict(deque)  # client_id -> timestamps de envios proactivos
_locks = defaultdict(asyncio.Lock)


def _val(settings, name, default):
    v = getattr(settings, name, None)
    return default if v is None else v


def _purge(dq: deque, window: float, now: float):
    while dq and now - dq[0] >= window:
        dq.popleft()


def proactive_budget_ok(client_id: int, settings) -> bool:
    """True si todavia se pueden mandar mensajes proactivos esta hora (0 = sin tope)."""
    cap = int(_val(settings, "wa_proactive_per_hour", DEFAULT_PROACTIVE_PER_HOUR))
    if cap <= 0:
        return True
    dq = _proactive_last_hour[client_id]
    _purge(dq, 3600, time.monotonic())
    return len(dq) < cap


async def _wait_for_minute_slot(client_id: int, cap: int):
    """Espera hasta que haya lugar en la ventana de 60 s y reserva el lugar."""
    if cap <= 0:
        return
    while True:
        async with _locks[client_id]:
            now = time.monotonic()
            dq = _sent_last_minute[client_id]
            _purge(dq, 60, now)
            if len(dq) < cap:
                dq.append(now)
                return
            wait = 60 - (now - dq[0]) + 0.05
        await asyncio.sleep(max(wait, 0.1))


async def before_send(client_id: int, chat_id: str, settings, proactive: bool, api_base: str = None):
    """Aplica tope por minuto + pausa humana antes de mandar. api_base es
    https://api.green-api.com/waInstance<id> (sin metodo ni token), usado solo para el
    indicador 'escribiendo'."""
    await _wait_for_minute_slot(client_id, int(_val(settings, "wa_rate_per_minute", DEFAULT_PER_MINUTE)))

    if proactive:
        _proactive_last_hour[client_id].append(time.monotonic())

    if not _val(settings, "wa_humanize_enabled", True):
        return

    lo = max(0, int(_val(settings, "wa_delay_min_seconds", DEFAULT_DELAY_MIN)))
    hi = max(lo, int(_val(settings, "wa_delay_max_seconds", DEFAULT_DELAY_MAX)))
    delay = random.uniform(lo, hi) if hi > 0 else 0
    if delay <= 0:
        return

    if _val(settings, "wa_typing_indicator", True) and api_base and delay >= 1:
        try:
            typing_ms = int(min(max(delay, 1), 20) * 1000)
            async with httpx.AsyncClient() as http_client:
                await http_client.post(f"{api_base}/sendTyping/{settings.whatsapp_token}",
                                       json={"chatId": chat_id, "typingTime": typing_ms}, timeout=5.0)
        except Exception:
            pass  # el indicador es cosmetico: si falla igual se hace la pausa

    await asyncio.sleep(delay)
