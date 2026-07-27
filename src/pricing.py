import re


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
