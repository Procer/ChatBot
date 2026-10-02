"""Genera el cartel A4 con QR del portal "Mis Resultados" y el snippet para la web del laboratorio.

Uso (desde la raíz del repo):
    python deploy/make_results_qr.py [slug] [base_url] [texto_del_titulo]
Ejemplo:
    python deploy/make_results_qr.py laboratorio-micucci https://anka.ar "Bajá tus análisis"

Salida en deploy/out/: qr_resultados_<slug>.pdf (cartel A4), qr_resultados_<slug>.png (solo el QR) y
snippet_resultados_<slug>.html (botón + iframe para pegar en la web del laboratorio).
"""
import os
import sys

import qrcode
from qrcode.constants import ERROR_CORRECT_Q
from PIL import Image, ImageDraw, ImageFont

slug = sys.argv[1] if len(sys.argv) > 1 else "laboratorio-micucci"
base = (sys.argv[2] if len(sys.argv) > 2 else "https://anka.ar").rstrip("/")
title = sys.argv[3] if len(sys.argv) > 3 else "Bajá tus análisis"
url = f"{base}/resultados/{slug}"
out = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(out, exist_ok=True)

NAVY, MUTED, BG = (21, 32, 57), (90, 100, 120), (255, 255, 255)


def font(size, bold=False):
    for p in (("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
              ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def centered(d, y, text, f, fill, W):
    w = d.textlength(text, font=f)
    d.text(((W - w) / 2, y), text, font=f, fill=fill)


# QR alto (corrección Q): se lee bien aunque se imprima chico o con un poco de suciedad
qr = qrcode.QRCode(error_correction=ERROR_CORRECT_Q, box_size=20, border=2)
qr.add_data(url)
qr.make(fit=True)
qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
qr_img.save(os.path.join(out, f"qr_resultados_{slug}.png"))

W, H = 1654, 2339  # A4 a 200 dpi
page = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(page)
centered(d, 190, title, font(150, True), NAVY, W)
centered(d, 400, "Con tu celular, sin esperar y sin papel", font(58), MUTED, W)
size = 1000
page.paste(qr_img.resize((size, size), Image.NEAREST), ((W - size) // 2, 560))
steps = ["1. Abrí la cámara del celular", "2. Apuntá al cuadrado", "3. Escribí tu DNI y listo"]
for i, s in enumerate(steps):
    centered(d, 1690 + i * 95, s, font(66, True), NAVY, W)
centered(d, 2050, f"o entrá a {base.replace('https://', '')}/resultados/{slug}", font(46), MUTED, W)
page.save(os.path.join(out, f"qr_resultados_{slug}.pdf"), "PDF", resolution=200.0)

snippet = f"""<!-- Opción 1: botón (abre el portal en una pestaña nueva) -->
<a href="{url}" target="_blank" rel="noopener"
   style="display:inline-block;background:#1A5FA8;color:#fff;font:700 20px/1.2 system-ui,sans-serif;
          padding:16px 28px;border-radius:14px;text-decoration:none">
  Bajá tus análisis
</a>

<!-- Opción 2: el portal embebido en la página (iframe) -->
<iframe src="{url}?embed=1" title="Mis resultados" loading="lazy"
        style="width:100%;max-width:520px;height:640px;border:0;border-radius:16px"></iframe>
"""
with open(os.path.join(out, f"snippet_resultados_{slug}.html"), "w", encoding="utf-8") as f:
    f.write(snippet)

print("URL del QR:", url)
print("Archivos en", out)
