import io
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Frame

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "pdf")
LOGO_COLOR = os.path.join(ASSETS_DIR, "zsg_logo_color.jpg")
LOGO_BLACK = os.path.join(ASSETS_DIR, "zsg_logo_black.png")

BLUE_ACCENT = colors.HexColor("#2f78b7")
TEXT_DARK = colors.HexColor("#1a1a1a")

PAGE_W, PAGE_H = A4

ABONO_INCLUYE = [
    "Actualización de la información.",
    "Pedidos de nuevas funciones, opciones, modificaciones.",
    "Mantenimiento.",
]


def _dotted_line(c: canvas.Canvas, x1, y, x2):
    c.saveState()
    c.setDash(1, 2)
    c.setStrokeColor(colors.grey)
    c.line(x1, y, x2, y)
    c.restoreState()


def generar_pdf_propuesta_chatbot(client_name: str, precio_ars: float) -> bytes:
    """Genera un presupuesto simple (una página) del servicio de Chatbot con IA:
    logo, precio mensual a cobrar y qué incluye el abono.
    Devuelve los bytes del PDF."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Presupuesto Chatbot con IA - {client_name}")

    left = 2.2 * cm
    right = PAGE_W - 2.2 * cm
    top = PAGE_H - 2 * cm

    logo_size = 2.4 * cm
    c.drawImage(
        LOGO_COLOR, left, top - logo_size, logo_size, logo_size,
        preserveAspectRatio=True, mask="auto",
    )
    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(TEXT_DARK)
    c.drawString(left + logo_size + 0.5 * cm, top - 0.9 * cm, "Zárate System Group")
    c.setFont("Helvetica", 11)
    c.setFillColor(BLUE_ACCENT)
    c.drawString(left + logo_size + 0.5 * cm, top - 1.5 * cm, "Chatbot con IA")

    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawRightString(right, top, datetime.now().strftime("%d/%m/%Y"))
    _dotted_line(c, left, top - logo_size - 0.4 * cm, right)

    body_style = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=10.5, leading=15,
        textColor=TEXT_DARK,
    )
    bullet_style = ParagraphStyle("bullet", parent=body_style, leftIndent=14, bulletIndent=2)

    content_top = top - logo_size - 1.1 * cm
    story = [
        Paragraph(f"Presupuesto para <b>{client_name}</b>", body_style),
        Paragraph(
            "Chatbot con IA: un asistente conversacional propio, entrenado con la "
            "información de su negocio, que funciona en WhatsApp, Instagram, "
            "Messenger y chat en sitio web las 24 horas.",
            body_style,
        ),
    ]
    frame_top = Frame(left, content_top - 3.2 * cm, right - left, 3.2 * cm, showBoundary=0)
    frame_top.addFromList(story, c)

    box_top = content_top - 3.6 * cm
    box_h = 2.2 * cm
    c.setFillColor(colors.HexColor("#eef5fb"))
    c.roundRect(left, box_top - box_h, right - left, box_h, 6, fill=1, stroke=0)
    c.setFillColor(BLUE_ACCENT)
    c.setFont("Helvetica", 10)
    c.drawString(left + 0.5 * cm, box_top - 0.85 * cm, "PRECIO A COBRAR")
    c.setFont("Helvetica-Bold", 20)
    precio_fmt = f"{precio_ars:,.0f}".replace(",", ".")
    c.drawString(left + 0.5 * cm, box_top - 1.7 * cm, f"$ {precio_fmt} / mes")

    incluye_top = box_top - box_h - 0.9 * cm
    heading_style = ParagraphStyle(
        "heading", fontName="Helvetica-Bold", fontSize=11.5, leading=14,
        textColor=TEXT_DARK, spaceAfter=4,
    )
    story2 = [Paragraph("El abono incluye:", heading_style)]
    for item in ABONO_INCLUYE:
        story2.append(Paragraph(f"•&nbsp;&nbsp;{item}", bullet_style))
    frame2 = Frame(left, incluye_top - 3.5 * cm, right - left, 3.5 * cm, showBoundary=0)
    frame2.addFromList(story2, c)

    footer_y = 2.6 * cm
    _dotted_line(c, left, footer_y, right)
    c.drawImage(
        LOGO_BLACK, left, footer_y - 1.7 * cm, 1.4 * cm, 1.4 * cm,
        preserveAspectRatio=True, mask="auto",
    )
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#333333"))
    text_x = left + 1.7 * cm
    c.drawString(text_x, footer_y - 0.6 * cm, "Juan Manuel de Rosas — Analista de sistemas")
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawString(text_x, footer_y - 1.05 * cm, "jmderosas@zaratesystemgroup.com.ar · 03487 15 587913")
    c.drawString(text_x, footer_y - 1.4 * cm, "www.zaratesystemgroup.com.ar")

    c.showPage()
    c.save()
    return buf.getvalue()
