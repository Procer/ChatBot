import math
import re


# --- Tarifa SaaS (precio de lista público) ------------------------------------
# Réplica EXACTA de calcular() en templates/admin/super_admin_calculadora.html.
# Si tocás la fórmula acá, tocala también en ese JS (y viceversa): hoy la
# calculadora es client-side y no hay forma limpia de compartir el cálculo.
SAAS_LIST_PRICE_DEFAULTS = {
    "clientes": 1,                 # peor caso: el VPS entero cae sobre 1 cliente
    "whatsapp_usd": 12.0,
    "openai_usd": 10.0,
    "adicional_usd": 100.0,        # ganancia por cliente
    "server_tramo1_ars": 22000.0,  # 1 a 2 clientes
    "server_tramo2_ars": 40000.0,  # 3 a 6 clientes
    "server_tramo3_ars": 75000.0,  # 7 o más
}


def _ceil_mil(valor: float) -> float:
    """Redondeo hacia arriba al millar, igual que redondearArriba() del JS."""
    return math.ceil((valor or 0) / 1000) * 1000


def compute_saas_list_price_ars(dolar_venta: float, **overrides) -> dict:
    """Tarifa mensual de lista (ARS por cliente) con los supuestos del 'peor caso'
    (1 cliente, servidor Tramo 1, ganancia 100 USD). Espeja calcular() de la
    calculadora del super-admin. Devuelve el total a cobrar y su desglose."""
    p = {**SAAS_LIST_PRICE_DEFAULTS, **overrides}
    tc = float(dolar_venta or 0)
    clientes = int(p["clientes"]) or 0

    costo_wha_ars = _ceil_mil(clientes * p["whatsapp_usd"] * tc)
    costo_ia_ars = _ceil_mil(clientes * p["openai_usd"] * tc)

    if clientes <= 0:
        costo_server_ars = 0.0
    elif clientes <= 2:
        costo_server_ars = p["server_tramo1_ars"]
    elif clientes <= 6:
        costo_server_ars = p["server_tramo2_ars"]
    else:
        costo_server_ars = p["server_tramo3_ars"]
    costo_server_ars = _ceil_mil(costo_server_ars)

    total_costos_ars = _ceil_mil(costo_wha_ars + costo_ia_ars + costo_server_ars)
    adicional_total_ars = _ceil_mil(clientes * p["adicional_usd"] * tc)
    total_cobrar_ars = total_costos_ars + adicional_total_ars
    abono_por_cliente_ars = _ceil_mil(total_cobrar_ars / clientes) if clientes > 0 else 0.0

    return {
        "price_ars": int(abono_por_cliente_ars),
        "infra_ars": int(total_costos_ars),
        "ganancia_ars": int(adicional_total_ars),
        "dolar_oficial": tc,
    }


def _parse_price_number(text: str):
    """Convierte un número en formato argentino ('757,50', '1.234,56', '8000') a float."""
    t = text.strip().replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _parse_range_bounds(prefix_text: str):
    """Extrae (low, high) de la parte del texto anterior al precio.
    high=None significa 'sin tope superior' (ej. 'Más de 50', 'MAS DE 10000')."""
    nums = [int(n.replace(".", "")) for n in re.findall(r"\d[\d.]*", prefix_text)]
    if not nums:
        return None, None
    is_upper_only = bool(re.search(r"menos de|inferior a|hasta", prefix_text, re.I))
    if len(nums) >= 2:
        return nums[0], nums[1]
    if is_upper_only:
        return 0, nums[0]
    # Un solo número sin pista de tope superior (ej. "Más de 50", o un solo valor suelto):
    # se asume "desde esta cantidad en adelante", el caso más común en descuentos por volumen.
    return nums[0], None


def resolve_unit_price(base_price, price_rules_text: str, cantidad: int) -> float:
    """Devuelve el precio unitario que corresponde a 'cantidad', según los tramos libres
    de 'price_rules_text' (ej. 'ENTRE 200 Y 499: $ 757,50 | MAS DE 10000: $ 361,92').
    Si ningún tramo cubre la cantidad pedida, usa el precio base (convención documentada
    en el panel de catálogo: el precio base es para las cantidades no cubiertas por ningún rango)."""
    base_price = base_price or 0
    if not price_rules_text or not cantidad:
        return base_price

    best = None  # (low, price)
    for segment in price_rules_text.split("|"):
        seg = segment.strip()
        if not seg:
            continue
        match = re.search(r"\$\s*([\d.,]+)", seg)
        if not match:
            continue
        price = _parse_price_number(match.group(1))
        if price is None:
            continue
        low, high = _parse_range_bounds(seg[:match.start()])
        if low is None:
            continue
        if cantidad >= low and (high is None or cantidad <= high):
            if best is None or low > best[0]:
                best = (low, price)

    return best[1] if best is not None else base_price
