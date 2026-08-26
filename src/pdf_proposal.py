import io
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Frame

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "pdf")
LOGO_COLOR = os.path.join(ASSETS_DIR, "zsg_logo_color.jpg")
LOGO_BLACK = os.path.join(ASSETS_DIR, "zsg_logo_black.png")

GRAY_DARK = colors.HexColor("#6e6e6e")
GRAY_LIGHT = colors.HexColor("#b9bcbe")
BLUE_ACCENT = colors.HexColor("#7bb3e0")
BLUE_LOGO = colors.HexColor("#2f78b7")

SERVICES = [
    "SOPORTE TÉCNICO",
    "SITIOS Y SISTEMAS WEB",
    "SOLUCIONES GRÁFICAS",
    "DOMÓTICA (CASA INTELIGENTE)",
    "REALIDAD AUMENTADA",
    "CHATBOTS CON IA",
]

PAGE_W, PAGE_H = A4


def _draw_cover(c: canvas.Canvas):
    c.setFillColor(GRAY_DARK)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    sidebar_w = 6.2 * cm
    logo_box = 4.6 * cm
    top_margin = 1.3 * cm

    c.setFillColor(colors.white)
    c.rect(top_margin, PAGE_H - top_margin - logo_box, logo_box, logo_box, fill=1, stroke=0)
    pad = 0.25 * cm
    c.drawImage(
        LOGO_COLOR,
        top_margin + pad, PAGE_H - top_margin - logo_box + pad,
        logo_box - 2 * pad, logo_box - 2 * pad,
        preserveAspectRatio=True, mask="auto",
    )

    rows_top = PAGE_H - top_margin - logo_box - 0.6 * cm
    row_h = 3.1 * cm
    checker = [(GRAY_LIGHT, BLUE_ACCENT), (BLUE_ACCENT, GRAY_LIGHT), (GRAY_LIGHT, BLUE_ACCENT)]
    y = rows_top - row_h
    c.setFillColor(GRAY_LIGHT)
    c.rect(0, y, sidebar_w, row_h, fill=1, stroke=0)
    y -= row_h
    for left_c, right_c in checker:
        half = sidebar_w / 2
        c.setFillColor(left_c)
        c.rect(0, y, half, row_h, fill=1, stroke=0)
        c.setFillColor(right_c)
        c.rect(half, y, half, row_h, fill=1, stroke=0)
        y -= row_h
    c.setFillColor(GRAY_LIGHT)
    c.rect(0, 0, sidebar_w, max(y, 0), fill=1, stroke=0)

    mark = 0.55 * cm
    mx = PAGE_W - top_margin - 2 * mark
    my = top_margin
    c.setFillColor(BLUE_ACCENT)
    c.rect(mx, my + mark, mark, mark, fill=1, stroke=0)
    c.setFillColor(GRAY_LIGHT)
    c.rect(mx + mark, my + mark, mark, mark, fill=1, stroke=0)
    c.rect(mx, my, mark, mark, fill=1, stroke=0)
    c.setFillColor(BLUE_ACCENT)
    c.rect(mx + mark, my, mark, mark, fill=1, stroke=0)

    text_x = sidebar_w + 0.9 * cm
    c.setFillColor(colors.white)
    c.setFont("Helvetica", 30)
    c.drawString(text_x, PAGE_H - 6.2 * cm, "Zárate System Group")
    c.setFont("Helvetica", 15)
    c.drawString(text_x, PAGE_H - 7.1 * cm, "SOLUCIONES INFORMÁTICAS")
    c.setFont("Helvetica", 9)
    c.drawString(text_x, PAGE_H - 7.7 * cm, "Remotas y presenciales")

    c.setFont("Helvetica-Bold", 11)
    item_y = PAGE_H - 10.5 * cm
    for service in SERVICES:
        if service == "CHATBOTS CON IA":
            c.setFillColor(BLUE_ACCENT)
        else:
            c.setFillColor(colors.white)
        c.drawString(text_x, item_y, service)
        item_y -= 1.05 * cm

    c.showPage()


def _dotted_line(c: canvas.Canvas, x1, y, x2):
    c.saveState()
    c.setDash(1, 2)
    c.setStrokeColor(colors.grey)
    c.line(x1, y, x2, y)
    c.restoreState()


def _draw_letter(c: canvas.Canvas, client_name: str, precio_ars_fmt: str):
    left = 2.2 * cm
    right = PAGE_W - 2.2 * cm
    top = PAGE_H - 2 * cm

    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawRightString(right, top, "www.zaratesystemgroup.com.ar")
    _dotted_line(c, left, top - 0.35 * cm, right)

    body_style = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=10.5, leading=15.5,
        alignment=TA_JUSTIFY, textColor=colors.HexColor("#1a1a1a"),
    )
    bold_style = ParagraphStyle("bold", parent=body_style, fontName="Helvetica-Bold")
    heading_style = ParagraphStyle(
        "heading", fontName="Helvetica-Bold", fontSize=11.5, leading=14,
        textColor=colors.HexColor("#1a1a1a"), spaceBefore=6, spaceAfter=4,
    )
    bullet_style = ParagraphStyle("bullet", parent=body_style, leftIndent=14, bulletIndent=2)

    story = [
        Paragraph(f"Estimados de <b>{client_name}</b>:", body_style),
        Paragraph(
            "Por medio de la presente nos ponemos en contacto con ustedes para ofrecerles "
            "nuestros servicios.", body_style
        ),
        Paragraph(
            "<b>Zárate System Group</b> es un grupo de profesionales en sistemas que comenzamos "
            "en el año <b>2009</b> a trabajar en el ámbito informático y hoy podemos brindar un "
            "servicio de excelencia a nuestros clientes. Tenemos base en la ciudad de "
            "<b>Zárate</b> y ya hemos extendido nuestros servicios a <b>Campana</b>, "
            "<b>Escobar</b>, <b>Pilar</b> y <b>CABA</b>.", body_style
        ),
        Paragraph(
            "Nuestro objetivo es ofrecer una <b>solución integral, minimizar riesgos y ayudar "
            "en las tomas de decisiones.</b>", body_style
        ),
        Paragraph("PROPUESTA", heading_style),
        Paragraph(
            "Chatbot con IA: un asistente conversacional propio, entrenado con la información "
            "de su negocio, que responde consultas, deriva a un humano cuando hace falta y "
            "puede tomar pedidos, turnos y datos de contacto de forma automática, las 24 horas.",
            body_style,
        ),
        Paragraph(
            "El chatbot funciona en <b>WhatsApp, Instagram, Messenger y chat en sitio web.</b>",
            body_style,
        ),
        Paragraph("PRECIO", heading_style),
        Paragraph(f"Tiene un costo mensual de <b>$ {precio_ars_fmt}</b>.", body_style),
        Paragraph("El abono implica:", body_style),
        Paragraph("•&nbsp;&nbsp;Actualización de la información.", bullet_style),
        Paragraph("•&nbsp;&nbsp;Pedidos de nuevas funciones, opciones, modificaciones.", bullet_style),
        Paragraph("•&nbsp;&nbsp;Mantenimiento.", bullet_style),
        Paragraph(
            "<i>No deje de ingresar a nuestro sitio web para conocer nuestros otros servicios.</i>",
            body_style,
        ),
        Paragraph("Reciba un cordial saludo,", body_style),
        Paragraph(
            "<b>Juan Manuel de Rosas</b><br/><i>Analista de sistemas</i><br/>"
            "jmderosas@zaratesystemgroup.com.ar<br/>03487 15 587913<br/>"
            "www.zaratesystemgroup.com.ar",
            body_style,
        ),
    ]

    frame = Frame(left, 3.4 * cm, right - left, top - 1 * cm - 3.4 * cm, showBoundary=0)
    frame.addFromList(story, c)

    footer_y = 2.6 * cm
    _dotted_line(c, left, footer_y, right)
    c.drawImage(
        LOGO_BLACK, left, footer_y - 1.9 * cm, 1.6 * cm, 1.6 * cm,
        preserveAspectRatio=True, mask="auto",
    )
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawString(left + 1.9 * cm, footer_y - 1.15 * cm, "Página 2 | 03487-15-587913")

    c.showPage()


def generar_pdf_propuesta_chatbot(client_name: str, precio_ars: float) -> bytes:
    """Genera la propuesta comercial (portada + carta) del servicio de Chatbot con IA,
    con el nombre del cliente y el precio mensual sugerido ya completados.
    Devuelve los bytes del PDF."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Propuesta Chatbot con IA - {client_name}")

    _draw_cover(c)
    precio_fmt = f"{precio_ars:,.0f}".replace(",", ".")
    _draw_letter(c, client_name, precio_fmt)

    c.save()
    return buf.getvalue()
