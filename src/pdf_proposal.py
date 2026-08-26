import io
import os
from datetime import datetime

import reportlab
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "pdf")
LOGO_COLOR = os.path.join(ASSETS_DIR, "zsg_logo_color.jpg")

REPORTLAB_FONTS_DIR = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
FONT_REGULAR_TTF = os.path.join(REPORTLAB_FONTS_DIR, "Vera.ttf")
FONT_BOLD_TTF = os.path.join(REPORTLAB_FONTS_DIR, "VeraBd.ttf")

BLUE_ACCENT = colors.HexColor("#2f78b7")
BLUE_ACCENT_RGB = (47, 120, 183)
GRAY_TEXT_RGB = (90, 90, 90)
DARK_TEXT_RGB = (26, 26, 26)

DEFAULT_MENSAJE = "Incluye actualización de la información, pedidos de nuevas funciones y mantenimiento."

# Tarjeta horizontal tipo talonario/ticket
CARD_W_CM = 18.0
CARD_H_CM = 6.2
MARGIN_CM = 0.8
IMAGE_DPI = 200


def _wrap_text_pillow(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def generar_pdf_voucher(client_name: str, precio_ars: float, mensaje: str | None = None) -> bytes:
    """Genera la tarjeta de cobro (rectángulo tipo talonario, una sola página del
    tamaño de la tarjeta) en PDF. Devuelve los bytes del PDF."""
    mensaje = (mensaje or DEFAULT_MENSAJE).strip() or DEFAULT_MENSAJE
    precio_fmt = f"{precio_ars:,.0f}".replace(",", ".")

    w, h = CARD_W_CM * cm, CARD_H_CM * cm
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h))
    c.setTitle(f"Cobro Chatbot con IA - {client_name}")

    c.setFillColor(colors.white)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#d0d0d0"))
    c.setLineWidth(1)
    c.rect(0.15 * cm, 0.15 * cm, w - 0.3 * cm, h - 0.3 * cm, fill=0, stroke=1)
    c.setFillColor(BLUE_ACCENT)
    c.rect(0, 0, 0.35 * cm, h, fill=1, stroke=0)

    left = MARGIN_CM * cm + 0.2 * cm
    right = w - MARGIN_CM * cm
    top = h - MARGIN_CM * cm

    logo_size = 1.7 * cm
    c.drawImage(LOGO_COLOR, left, top - logo_size, logo_size, logo_size, preserveAspectRatio=True, mask="auto")

    text_x = left + logo_size + 0.4 * cm
    c.setFillColor(colors.HexColor("#1a1a1a"))
    c.setFont("Helvetica-Bold", 15)
    c.drawString(text_x, top - 0.65 * cm, "Chatbot con IA")
    c.setFillColor(colors.grey)
    c.setFont("Helvetica", 10)
    c.drawString(text_x, top - 1.25 * cm, client_name)

    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.grey)
    c.drawRightString(right, top - 0.15 * cm, datetime.now().strftime("%d/%m/%Y"))

    sep_y = top - logo_size - 0.35 * cm
    c.saveState()
    c.setDash(1, 2)
    c.setStrokeColor(colors.HexColor("#c0c0c0"))
    c.line(left, sep_y, right, sep_y)
    c.restoreState()

    price_y = sep_y - 1.0 * cm
    c.setFont("Helvetica", 12)
    c.setFillColor(colors.HexColor("#1a1a1a"))
    c.drawString(left, price_y, "Cobro mensual:")
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(BLUE_ACCENT)
    c.drawRightString(right, price_y - 0.05 * cm, f"$ {precio_fmt}")

    from reportlab.platypus import Paragraph, Frame
    from reportlab.lib.styles import ParagraphStyle
    msg_style = ParagraphStyle("msg", fontName="Helvetica", fontSize=10, leading=13.5, textColor=colors.HexColor("#333333"))
    msg_top = price_y - 0.6 * cm
    frame = Frame(left, 0.5 * cm, right - left, msg_top - 0.5 * cm, showBoundary=0, topPadding=0, leftPadding=0, rightPadding=0, bottomPadding=0)
    frame.addFromList([Paragraph(mensaje, msg_style)], c)

    c.showPage()
    c.save()
    return buf.getvalue()


def generar_imagen_voucher(client_name: str, precio_ars: float, mensaje: str | None = None) -> bytes:
    """Genera la misma tarjeta de cobro como imagen PNG (para copiar/pegar en WhatsApp).
    Devuelve los bytes del PNG."""
    mensaje = (mensaje or DEFAULT_MENSAJE).strip() or DEFAULT_MENSAJE
    precio_fmt = f"{precio_ars:,.0f}".replace(",", ".")

    px_per_cm = IMAGE_DPI / 2.54
    W = int(CARD_W_CM * px_per_cm)
    H = int(CARD_H_CM * px_per_cm)

    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    border_px = max(1, int(0.02 * px_per_cm * 10))
    border_margin = int(0.15 * px_per_cm)
    draw.rectangle(
        [border_margin, border_margin, W - border_margin, H - border_margin],
        outline=(208, 208, 208), width=border_px,
    )
    draw.rectangle([0, 0, int(0.35 * px_per_cm), H], fill=BLUE_ACCENT_RGB)

    margin_px = int(MARGIN_CM * px_per_cm) + int(0.2 * px_per_cm)
    right_px = W - int(MARGIN_CM * px_per_cm)
    top_px = int(MARGIN_CM * px_per_cm)

    logo_size_px = int(1.7 * px_per_cm)
    logo = Image.open(LOGO_COLOR).convert("RGB").resize((logo_size_px, logo_size_px))
    img.paste(logo, (margin_px, top_px))

    font_title = ImageFont.truetype(FONT_BOLD_TTF, int(0.55 * px_per_cm))
    font_client = ImageFont.truetype(FONT_REGULAR_TTF, int(0.4 * px_per_cm))
    font_small = ImageFont.truetype(FONT_REGULAR_TTF, int(0.32 * px_per_cm))
    font_label = ImageFont.truetype(FONT_REGULAR_TTF, int(0.42 * px_per_cm))
    font_price = ImageFont.truetype(FONT_BOLD_TTF, int(0.72 * px_per_cm))
    font_msg = ImageFont.truetype(FONT_REGULAR_TTF, int(0.36 * px_per_cm))

    text_x = margin_px + logo_size_px + int(0.4 * px_per_cm)
    draw.text((text_x, top_px), "Chatbot con IA", font=font_title, fill=DARK_TEXT_RGB)
    draw.text((text_x, top_px + int(0.65 * px_per_cm)), client_name, font=font_client, fill=GRAY_TEXT_RGB)

    date_txt = datetime.now().strftime("%d/%m/%Y")
    dw = draw.textlength(date_txt, font=font_small)
    draw.text((right_px - dw, top_px), date_txt, font=font_small, fill=GRAY_TEXT_RGB)

    sep_y = top_px + logo_size_px + int(0.35 * px_per_cm)
    dash_len, gap_len = int(0.08 * px_per_cm), int(0.06 * px_per_cm)
    x = margin_px
    while x < right_px:
        draw.line([(x, sep_y), (min(x + dash_len, right_px), sep_y)], fill=(192, 192, 192), width=2)
        x += dash_len + gap_len

    price_y = sep_y + int(0.45 * px_per_cm)
    draw.text((margin_px, price_y), "Cobro mensual:", font=font_label, fill=DARK_TEXT_RGB)
    price_txt = f"$ {precio_fmt}"
    pw = draw.textlength(price_txt, font=font_price)
    draw.text((right_px - pw, price_y - int(0.05 * px_per_cm)), price_txt, font=font_price, fill=BLUE_ACCENT_RGB)

    msg_top = price_y + int(0.95 * px_per_cm)
    max_width = right_px - margin_px
    line_h = int(0.5 * px_per_cm)
    for i, line in enumerate(_wrap_text_pillow(draw, mensaje, font_msg, max_width)):
        draw.text((margin_px, msg_top + i * line_h), line, font=font_msg, fill=(51, 51, 51))

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
