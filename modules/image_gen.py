"""
Generación y composición de imágenes para creativos de email.

Flujo:
  1. Flux 1.1 Pro genera imagen de fondo fotorrealista de la clínica
  2. Pillow agrega overlay oscuro + headline + subtext + wordmark AMY AI
  3. El PNG compuesto se sube a Canva como asset (URL estable)
  4. Esa URL se guarda en Notion y se usa en emails 2b y 3
"""

import io
import os
import time
import urllib.request
from pathlib import Path

import requests

# Fuente: Inter descargada una vez en data/fonts/
_FONT_DIR  = Path(__file__).parent.parent / "data" / "fonts"
_FONT_BOLD = _FONT_DIR / "Inter-Bold.ttf"
_FONT_REG  = _FONT_DIR / "Inter-Regular.ttf"
_FONT_URL_BOLD = "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Bold.ttf"
_FONT_URL_REG  = "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Regular.ttf"

# Copy por categoría y email_num para la composición
_COPY = {
    ("dental", 2): {
        "headline": "Your next implant case called\n3 offices today.",
        "subtext":  "The first to call back wins.\nAMY responds in under 30 seconds — 24/7.",
    },
    ("estetica", 2): {
        "headline": "She booked with your competitor\n4 minutes after filling the form.",
        "subtext":  "Esthetic leads decide fast.\nAMY calls back in 28 seconds.",
    },
    ("medspa", 2): {
        "headline": "You're spending $3k/month on ads\nto lose leads in the first hour.",
        "subtext":  "AMY converts leads while you treat patients.\n24/7, bilingual, zero extra headcount.",
    },
    ("wellness", 2): {
        "headline": "Every uncontacted lead is a\nrecurring client you'll never have.",
        "subtext":  "AMY reaches out in under 30 seconds.\nBooks, qualifies, and follows up — always.",
    },
    ("dental", 3): {
        "headline": "A dental practice in Miami:\nbefore and after AMY AI.",
        "subtext":  "Before: 47 min callback · 21% conversion\nAfter:    28 sec callback · 64% conversion",
    },
    ("estetica", 3): {
        "headline": "An esthetic clinic in Dallas:\nbefore and after AMY AI.",
        "subtext":  "Before: 52 min callback · 18% bookings\nAfter:    24 sec callback · 57% bookings",
    },
    ("medspa", 3): {
        "headline": "A med spa in Houston stopped\nlosing after-hours leads.",
        "subtext":  "61% of leads came after 6pm — all uncontacted.\nWith AMY: 100% handled · +39% monthly bookings",
    },
    ("wellness", 3): {
        "headline": "A wellness clinic in Orlando\nconverted leads it used to lose.",
        "subtext":  "Before: 18–22 lost leads/month\nAfter (AMY AI): 2–3 lost leads/month",
    },
}

REPLICATE_API_URL = "https://api.replicate.com/v1/models/black-forest-labs/flux-1.1-pro/predictions"

# Prompts base por categoría — Flux genera el fondo visual, Canva añade el texto
_BASE_PROMPTS = {
    "dental": (
        "Minimalist professional photograph of a modern dental clinic interior. "
        "Clean white walls, soft natural light from large windows, sleek dental chair, "
        "no people, no text. High-end aesthetic, editorial photography style. "
        "Muted palette: white, warm gray, soft cream. Shot on Sony A7R, 35mm lens."
    ),
    "estetica": (
        "Minimalist professional photograph of a luxury esthetic clinic treatment room. "
        "Soft warm lighting, white marble surfaces, elegant minimal decor, no people, no text. "
        "High-end beauty industry aesthetic, editorial photography. "
        "Pale beige and white tones, ultra-clean composition. Shot on Sony A7R, 35mm lens."
    ),
    "medspa": (
        "Minimalist professional photograph of a high-end medical spa reception area. "
        "Soft ambient lighting, natural stone accents, lush minimal greenery, no people, no text. "
        "Luxury wellness aesthetic, editorial photography style. "
        "White and sage green palette, calm and premium feel. Shot on Sony A7R, 35mm lens."
    ),
    "wellness": (
        "Minimalist professional photograph of a modern wellness clinic lobby. "
        "Warm natural light, wooden accents, clean lines, indoor plants, no people, no text. "
        "Calm, trustworthy, health-focused aesthetic. Editorial photography. "
        "Warm whites, natural wood, soft greens. Shot on Sony A7R, 35mm lens."
    ),
}


def generate_background(categoria: str, email_num: int) -> str:
    """
    Genera una imagen de fondo con Flux 1.1 Pro para la categoría y email dados.
    Retorna la URL pública de la imagen generada.
    email_num: 2 (banner de impacto) o 3 (social proof — tono más cálido)
    """
    api_key = os.getenv("REPLICATE_API_KEY", "")
    if not api_key:
        raise RuntimeError("REPLICATE_API_KEY no configurada")

    base = _BASE_PROMPTS.get(categoria, _BASE_PROMPTS["dental"])

    # Email 3 (social proof) — tono ligeramente más cálido y cercano
    if email_num == 3:
        base = base.replace("Minimalist professional photograph", "Warm professional photograph")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Prefer": "wait",  # espera respuesta síncrona (hasta 60s)
    }
    payload = {
        "input": {
            "prompt":           base,
            "width":            1200,
            "height":           630,
            "output_format":    "jpg",
            "output_quality":   90,
            "safety_tolerance": 2,
        }
    }

    resp = requests.post(REPLICATE_API_URL, json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    # Con Prefer: wait la respuesta puede ser síncrona o async
    if data.get("status") in ("starting", "processing"):
        return _poll(data["urls"]["get"], api_key)

    output = data.get("output")
    if isinstance(output, list):
        return output[0]
    if isinstance(output, str):
        return output

    raise RuntimeError(f"Respuesta inesperada de Replicate: {data}")


def compose_creative(flux_url: str, categoria: str, email_num: int) -> bytes:
    """
    Descarga la imagen Flux y le agrega con Pillow:
      - Gradiente oscuro en la mitad inferior
      - Headline en blanco (bold)
      - Subtext en gris claro
      - Wordmark "AMY AI" en dorado (top-right)
    Retorna los bytes del PNG final.
    """
    from PIL import Image, ImageDraw, ImageFont
    import textwrap

    _ensure_fonts()

    # Descargar imagen Flux
    resp = requests.get(flux_url, timeout=30)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
    W, H = img.size  # 1200 x 630

    # Gradiente oscuro bottom 55%
    grad_h    = int(H * 0.55)
    grad_top  = H - grad_h
    overlay   = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_ov   = ImageDraw.Draw(overlay)
    for y in range(grad_h):
        alpha = int(200 * (y / grad_h) ** 1.4)
        draw_ov.line([(0, grad_top + y), (W, grad_top + y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, overlay)

    draw = ImageDraw.Draw(img)
    copy = _COPY.get((categoria, email_num), _COPY.get(("dental", email_num), _COPY[("dental", 2)]))

    # Fuentes
    try:
        font_hl  = ImageFont.truetype(str(_FONT_BOLD), 52)
        font_sub = ImageFont.truetype(str(_FONT_REG),  28)
        font_wm  = ImageFont.truetype(str(_FONT_BOLD), 22)
    except Exception:
        font_hl = font_sub = font_wm = ImageFont.load_default()

    pad_x, pad_y = 64, 52

    # Wordmark AMY AI — top right
    wm_text = "AMY AI"
    wm_bbox = draw.textbbox((0, 0), wm_text, font=font_wm)
    wm_w    = wm_bbox[2] - wm_bbox[0]
    draw.text((W - wm_w - pad_x, pad_y), wm_text, font=font_wm, fill="#c9a96e")

    # Subtext — above bottom edge
    sub_lines = copy["subtext"].split("\n")
    sub_y     = H - pad_y
    for line in reversed(sub_lines):
        bbox  = draw.textbbox((0, 0), line, font=font_sub)
        sub_y -= (bbox[3] - bbox[1]) + 6
        draw.text((pad_x, sub_y), line, font=font_sub, fill=(220, 220, 220, 255))
    sub_y -= 18

    # Headline — above subtext
    hl_lines = copy["headline"].split("\n")
    hl_y     = sub_y
    for line in reversed(hl_lines):
        bbox  = draw.textbbox((0, 0), line, font=font_hl)
        hl_y -= (bbox[3] - bbox[1]) + 8
        draw.text((pad_x, hl_y), line, font=font_hl, fill=(255, 255, 255, 255))

    # Exportar como PNG
    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


def _ensure_fonts():
    """Descarga Inter Bold + Regular si no están presentes."""
    _FONT_DIR.mkdir(parents=True, exist_ok=True)
    for path, url in [(_FONT_BOLD, _FONT_URL_BOLD), (_FONT_REG, _FONT_URL_REG)]:
        if not path.exists():
            try:
                urllib.request.urlretrieve(url, path)
            except Exception:
                pass  # usará default font de Pillow


def _poll(get_url: str, api_key: str, max_wait: int = 120) -> str:
    headers = {"Authorization": f"Bearer {api_key}"}
    deadline = time.time() + max_wait
    while time.time() < deadline:
        r = requests.get(get_url, headers=headers, timeout=30)
        r.raise_for_status()
        d = r.json()
        status = d.get("status")
        if status == "succeeded":
            out = d.get("output")
            return out[0] if isinstance(out, list) else out
        if status == "failed":
            raise RuntimeError(f"Replicate falló: {d.get('error')}")
        time.sleep(3)
    raise TimeoutError("Replicate no respondió en tiempo")
