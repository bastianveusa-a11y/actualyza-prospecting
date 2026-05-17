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

# Fuentes descargadas una vez en data/fonts/
_FONT_DIR    = Path(__file__).parent.parent / "data" / "fonts"
_FONT_BOLD   = _FONT_DIR / "Inter-Bold.ttf"
_FONT_REG    = _FONT_DIR / "Inter-Regular.ttf"
_FONT_ITALIC = _FONT_DIR / "PlayfairDisplay-Italic.ttf"
_FONT_URL_BOLD   = "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Bold.ttf"
_FONT_URL_REG    = "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Regular.ttf"
_FONT_URL_ITALIC = "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/static/PlayfairDisplay-Italic.ttf"

# Copy por categoría y email_num — diseñado para generar FOMO y conversión
_COPY = {
    ("dental", 2): {
        "hook_num":   "28 sec",
        "hook_label": "AMY AI answers your leads",
        "hook_sub":   "Your office average: 47 minutes. First to call wins.",
        "headline":   "Your next implant case called\n3 offices today.",
        "bullets": [
            "First to respond wins the case — every single time",
            "AMY works 24/7, bilingual, zero extra headcount",
            "64% avg conversion rate vs. 21% industry average",
        ],
        "cta": "See AMY in action  →  actualyza.com",
    },
    ("estetica", 2): {
        "hook_num":   "4 min",
        "hook_label": "before she booked your competitor",
        "hook_sub":   "That's how fast esthetic leads decide. Not hours — minutes.",
        "headline":   "She filled out your form.\nThen chose someone else.",
        "bullets": [
            "Esthetic leads decide in minutes, not hours",
            "AMY calls back before they can call someone else",
            "57% booking rate — no extra staff needed",
        ],
        "cta": "See AMY in action  →  actualyza.com",
    },
    ("medspa", 2): {
        "hook_num":   "61%",
        "hook_label": "of your leads come after 6pm",
        "hook_sub":   "Right now, none of them get a callback. AMY fixes that.",
        "headline":   "You're spending $3k/month on ads\nto lose leads in the first hour.",
        "bullets": [
            "AMY handles every after-hours inquiry instantly",
            "24/7 bilingual coverage — zero extra headcount",
            "+39% monthly bookings for clinics using AMY",
        ],
        "cta": "See AMY in action  →  actualyza.com",
    },
    ("wellness", 2): {
        "hook_num":   "18–22",
        "hook_label": "leads lost per month without AMY",
        "hook_sub":   "Each one is a recurring client gone forever.",
        "headline":   "Every uncontacted lead is a\nrecurring client you'll never have.",
        "bullets": [
            "AMY reaches out in under 30 seconds — always",
            "Books, qualifies, and follows up automatically",
            "Clinics cut lost leads from 22/mo to just 2–3",
        ],
        "cta": "See AMY in action  →  actualyza.com",
    },
    ("dental", 3): {
        "hook_num":   "64%",
        "hook_label": "conversion rate — after AMY AI",
        "hook_sub":   "Before: 21% conversion. Callback time: 47 min → 28 sec.",
        "headline":   "A dental practice in Miami\ntransformed with AMY AI.",
        "bullets": [
            "Before: 47-min callbacks, 21% lead conversion",
            "After AMY: 28-sec response, 64% conversion",
            "Same staff. Same budget. Completely different results.",
        ],
        "cta": "Get the same results  →  actualyza.com",
    },
    ("estetica", 3): {
        "hook_num":   "57%",
        "hook_label": "booking rate — after AMY AI",
        "hook_sub":   "Before: 18% bookings. Callback time: 52 min → 24 sec.",
        "headline":   "An esthetic clinic in Dallas\nstopped losing leads overnight.",
        "bullets": [
            "Before: 52-min callbacks, 18% booking rate",
            "After AMY: 24-sec response, 57% bookings",
            "No new hires. No overtime. Just AMY.",
        ],
        "cta": "Get the same results  →  actualyza.com",
    },
    ("medspa", 3): {
        "hook_num":   "+39%",
        "hook_label": "monthly bookings — after AMY AI",
        "hook_sub":   "Before: 61% of leads arrived after hours, all uncontacted.",
        "headline":   "A med spa in Houston stopped\nlosing after-hours leads.",
        "bullets": [
            "Before: 61% of leads came after 6pm — all missed",
            "After AMY: 100% handled instantly, 24/7",
            "+39% monthly bookings with the exact same team",
        ],
        "cta": "Get the same results  →  actualyza.com",
    },
    ("wellness", 3): {
        "hook_num":   "–89%",
        "hook_label": "lost leads — after AMY AI",
        "hook_sub":   "Before: 18–22 lost leads/month. After: just 2–3.",
        "headline":   "A wellness clinic in Orlando\nconverted leads it used to lose.",
        "bullets": [
            "Before AMY: 18–22 lost leads every single month",
            "After AMY: just 2–3 — a near-complete turnaround",
            "Same staff. Same budget. Almost zero lost leads.",
        ],
        "cta": "Get the same results  →  actualyza.com",
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
    api_key = os.getenv("REPLICATE_API_TOKEN", "") or os.getenv("REPLICATE_API_KEY", "")
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


def compose_creative(flux_url: str, categoria: str, email_num: int, style: str = "a") -> bytes:
    """
    Composición de creativo de ventas sobre imagen Flux:
      - Overlay oscuro uniforme (backdrop atmosférico)
      - Número de impacto grande (hook stat)
      - Headline en Playfair Italic
      - Bullets con beneficios concretos
      - CTA strip en la base
      - Wordmark AMY AI top-left
    """
    from PIL import Image, ImageDraw, ImageFont

    _ensure_fonts()

    resp = requests.get(flux_url, timeout=30)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
    W, H = img.size  # 1200 x 630

    # Overlay oscuro uniforme — la clínica queda como atmósfera de fondo
    overlay = Image.new("RGBA", (W, H), overlay_color)
    img = Image.alpha_composite(img, overlay)

    draw = ImageDraw.Draw(img)
    copy = _COPY.get((categoria, email_num), _COPY.get(("dental", email_num), _COPY[("dental", 2)]))

    # Style A: gold/warm — Style B: teal/cool
    if style == "b":
        ACCENT = (64, 200, 152, 255)   # teal
        overlay_color = (6, 10, 22, 208)  # cooler dark
    else:
        ACCENT = (201, 169, 110, 255)  # gold
        overlay_color = (8, 9, 19, 208)   # warm dark

    GOLD  = (201, 169, 110, 255)
    WHITE = (238, 238, 248, 255)
    GRAY  = (155, 155, 180, 255)
    GREEN = (64, 200, 152, 255)
    RED_M = (210,  90,  90, 210)

    def _tf(path, size, fallback=None):
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            if fallback:
                try:
                    return ImageFont.truetype(str(fallback), size)
                except Exception:
                    pass
            return ImageFont.load_default()

    font_wm     = _tf(_FONT_BOLD,   18)
    font_hook   = _tf(_FONT_BOLD,   70)
    font_lbl    = _tf(_FONT_REG,    16)
    font_sub_lb = _tf(_FONT_REG,    15)
    font_hl     = _tf(_FONT_ITALIC, 48, _FONT_BOLD)
    font_bullet = _tf(_FONT_REG,    21)
    font_cta    = _tf(_FONT_BOLD,   20)

    px = 60   # left margin
    cy = 38   # current y

    # ── Wordmark ────────────────────────────────────────────────────
    draw.text((px, cy), "AMY AI", font=font_wm, fill=GOLD)
    cy += 22
    draw.line([(px, cy + 3), (px + 88, cy + 3)], fill=(201, 169, 110, 110), width=1)
    cy += 18

    # ── Hook stat ───────────────────────────────────────────────────
    hook_num   = copy.get("hook_num", "")
    hook_label = copy.get("hook_label", "")
    hook_sub   = copy.get("hook_sub", "")

    hook_color = ACCENT
    draw.text((px, cy), hook_num, font=font_hook, fill=hook_color)
    bb = draw.textbbox((0, 0), hook_num, font=font_hook)
    cy += (bb[3] - bb[1]) + 4

    draw.text((px, cy), hook_label.upper(), font=font_lbl, fill=GRAY)
    cy += 20
    if hook_sub:
        draw.text((px, cy), hook_sub, font=font_sub_lb, fill=RED_M)
        cy += 20

    cy += 16
    draw.line([(px, cy), (px + 380, cy)], fill=(255, 255, 255, 25), width=1)
    cy += 18

    # ── Headline en Playfair Italic ─────────────────────────────────
    for line in copy.get("headline", "").split("\n"):
        draw.text((px, cy), line, font=font_hl, fill=WHITE)
        bb = draw.textbbox((0, 0), line, font=font_hl)
        cy += (bb[3] - bb[1]) + 5
    cy += 10

    # ── Bullets ─────────────────────────────────────────────────────
    for b in copy.get("bullets", []):
        draw.text((px, cy), f"→  {b}", font=font_bullet, fill=GRAY)
        bb = draw.textbbox((0, 0), f"→  {b}", font=font_bullet)
        cy += (bb[3] - bb[1]) + 7

    # ── CTA strip ───────────────────────────────────────────────────
    cta = copy.get("cta", "")
    if cta:
        strip_h = 50
        strip_y = H - strip_h
        ar, ag, ab, _ = ACCENT
        draw.rectangle([(0, strip_y), (W, H)], fill=(ar, ag, ab, 22))
        draw.line([(0, strip_y), (W, strip_y)], fill=(ar, ag, ab, 75), width=1)
        cta_bb = draw.textbbox((0, 0), cta, font=font_cta)
        cta_ty = strip_y + (strip_h - (cta_bb[3] - cta_bb[1])) // 2
        draw.text((px, cta_ty), cta, font=font_cta, fill=ACCENT)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


def _ensure_fonts():
    """Descarga Inter Bold/Regular + Playfair Display Italic si no están presentes."""
    _FONT_DIR.mkdir(parents=True, exist_ok=True)
    for path, url in [
        (_FONT_BOLD,   _FONT_URL_BOLD),
        (_FONT_REG,    _FONT_URL_REG),
        (_FONT_ITALIC, _FONT_URL_ITALIC),
    ]:
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
