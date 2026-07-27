import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def generar_pdf_presupuesto(client_id: int, client_settings, productos: list) -> str:
    """Genera un PDF de presupuesto para los productos dados.
    Devuelve la ruta relativa (con / inicial) donde quedó guardado, servida por /uploads."""
    client_dir = os.path.join("uploads", f"client_{client_id}", "quotes")
    os.makedirs(client_dir, exist_ok=True)

    filename = f"quote_{int(datetime.now().timestamp())}.pdf"
    file_path = os.path.join(client_dir, filename).replace("\\", "/")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleQuote", parent=styles["Heading1"], fontSize=16)
    normal = styles["Normal"]

    doc = SimpleDocTemplate(file_path, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    story = []

    bot_name = getattr(client_settings, "bot_name", None) or "Presupuesto"
    company_address = getattr(client_settings, "company_address", None) or ""
    company_phone = getattr(client_settings, "company_phone", None) or ""

    story.append(Paragraph(bot_name, title_style))
    if company_address:
        story.append(Paragraph(company_address, normal))
    if company_phone:
        story.append(Paragraph(f"Tel: {company_phone}", normal))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(f"Presupuesto - {datetime.now().strftime('%d/%m/%Y')}", styles["Heading2"]))
    story.append(Spacer(1, 0.5 * cm))

    for p in productos:
        story.append(Paragraph(p.get("nombre", ""), styles["Heading3"]))
        data = [["SKU", p.get("sku", "") or "-"]]
        if p.get("precio_unitario"):
            data.append(["Precio unitario", f"$ {p['precio_unitario']}"])
        if p.get("atributos_extra"):
            data.append(["Atributos", p["atributos_extra"]])
        if p.get("cantidad"):
            data.append(["Cantidad", str(p["cantidad"])])
        if p.get("subtotal"):
            data.append(["Subtotal", f"$ {p['subtotal']}"])

        table = Table(data, colWidths=[4 * cm, 11 * cm])
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.4 * cm))

    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Presupuesto sujeto a disponibilidad de stock. Precios expresados en pesos argentinos.", normal))

    doc.build(story)
    return f"/{file_path}"
