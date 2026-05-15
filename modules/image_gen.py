"""
Generación de imágenes con Flux 1.1 Pro via Replicate.

Flujo para creativos de email:
  1. Flux genera imagen de fondo (fotorrealista, clínica/profesional)
  2. La URL resultante se sube a Canva como asset
  3. Canva compone el diseño final con texto y stats encima
  4. Se exporta como PNG y se almacena para uso en emails
"""

import os
import time
import requests

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
