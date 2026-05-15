"""
Cliente de Canva Connect API para composición automática de creativos.

Flujo:
  1. OAuth 2.0 para obtener access token
  2. Upload imagen Flux como asset en Canva
  3. Crear diseño usando ese asset como fondo
  4. Exportar como PNG y retornar URL pública
"""

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path

import requests

CANVA_API_BASE  = "https://api.canva.com/rest/v1"
TOKEN_FILE      = Path(__file__).parent.parent / "data" / "canva_token.json"

# Scopes registrados en la integración de Canva
CANVA_SCOPES = (
    "asset:write asset:read design:content:write design:content:read "
    "design:permission:read design:permission:write "
    "folder:read folder:write folder:permission:read folder:permission:write "
    "comment:read comment:write profile:read"
)

# Text overlays por categoría y email_num
_OVERLAYS = {
    ("dental", 2): {
        "headline": "Your next $8,000 implant case\ncalled 3 offices today.",
        "subtext":  "The first to call back wins.\nAMY responds in under 30 seconds — 24/7.",
    },
    ("estetica", 2): {
        "headline": "She booked the filler appointment\nwith your competitor in 4 minutes.",
        "subtext":  "Esthetic leads decide fast.\nAMY calls back in 28 seconds — before they move on.",
    },
    ("medspa", 2): {
        "headline": "Your med spa is spending $3k/month\non ads to lose leads in the first hour.",
        "subtext":  "AMY converts leads while you focus on treatments.\n24/7, bilingual, zero extra headcount.",
    },
    ("wellness", 2): {
        "headline": "Every uncontacted lead is a\nrecurring client you'll never have.",
        "subtext":  "AMY reaches out in under 30 seconds.\nBooks appointments, qualifies leads, works 24/7.",
    },
    ("dental", 3): {
        "headline": "A dental practice in Miami:\nbefore and after.",
        "subtext":  "Before: 47 min callback · 21% conversion\nAfter (AMY AI): 28 sec · 64% conversion",
    },
    ("estetica", 3): {
        "headline": "An esthetic clinic in Dallas:\nbefore and after.",
        "subtext":  "Before: 52 min callback · 18% booking rate\nAfter (AMY AI): 24 sec · 57% booking rate",
    },
    ("medspa", 3): {
        "headline": "A med spa in Houston stopped\nlosing after-hours leads.",
        "subtext":  "61% of leads came after 6pm, uncontacted.\nWith AMY: 100% handled · +39% monthly bookings",
    },
    ("wellness", 3): {
        "headline": "A wellness clinic in Orlando\nconverted leads it used to lose.",
        "subtext":  "Before: 18-22 lost leads/month\nAfter (AMY AI): 2-3 lost leads/month",
    },
}


def generate_pkce() -> tuple[str, str]:
    """Genera code_verifier y code_challenge para PKCE (S256)."""
    verifier  = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest    = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def get_oauth_url(client_id: str, redirect_uri: str, code_challenge: str, state: str = "") -> str:
    from urllib.parse import urlencode
    params = {
        "response_type":        "code",
        "client_id":            client_id,
        "redirect_uri":         redirect_uri,
        "scope":                CANVA_SCOPES,
        "state":                state,
        "code_challenge_method": "S256",
        "code_challenge":       code_challenge,
    }
    return f"https://www.canva.com/api/oauth/authorize?{urlencode(params)}"


def exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str, code_verifier: str) -> dict:
    """Intercambia el authorization code por access + refresh tokens (con PKCE)."""
    r = requests.post(
        "https://api.canva.com/rest/v1/oauth/token",
        data={
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  redirect_uri,
            "client_id":     client_id,
            "client_secret": client_secret,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json()
    token["obtained_at"] = time.time()
    _save_token(token)
    return token


def _save_token(token: dict) -> None:
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(token, indent=2))


def _load_token() -> dict:
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except Exception:
            pass
    return {}


def _refresh_token(token: dict) -> dict:
    client_id     = os.getenv("CANVA_CLIENT_ID", "")
    client_secret = os.getenv("CANVA_CLIENT_SECRET", "")
    r = requests.post(
        "https://api.canva.com/rest/v1/oauth/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": token["refresh_token"],
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    r.raise_for_status()
    new_token = r.json()
    new_token["obtained_at"] = time.time()
    _save_token(new_token)
    return new_token


def _get_valid_token() -> str:
    """Retorna un access_token válido, refrescando si es necesario."""
    token = _load_token()
    if not token:
        raise RuntimeError("Canva no autorizado. Ve a /oauth/canva para conectar.")
    expires_in  = token.get("expires_in", 3600)
    obtained_at = token.get("obtained_at", 0)
    if time.time() - obtained_at > expires_in - 120:
        token = _refresh_token(token)
    return token["access_token"]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_valid_token()}",
        "Content-Type":  "application/json",
    }


def upload_asset_binary(image_bytes: bytes, name: str = "creative") -> str:
    """
    Sube una imagen como bytes binarios a Canva.
    Retorna la URL pública del asset en Canva CDN.
    """
    name_b64 = base64.b64encode(name.encode()).decode()
    token    = _get_valid_token()
    r = requests.post(
        f"{CANVA_API_BASE}/assets",
        data=image_bytes,
        headers={
            "Authorization":         f"Bearer {token}",
            "Content-Type":          "application/octet-stream",
            "Asset-Upload-Metadata": json.dumps({"name_base64": name_b64}),
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    # Canva retorna job ID — hay que esperar a que procese
    job_id = data.get("job", {}).get("id") or data.get("id", "")
    if not job_id:
        raise RuntimeError(f"No se pudo obtener job ID de upload: {data}")
    return _poll_asset_upload(job_id, token)


def _poll_asset_upload(job_id: str, token: str, max_wait: int = 60) -> str:
    """Espera que el asset upload termine y retorna la thumbnail/view URL."""
    deadline = time.time() + max_wait
    headers  = {"Authorization": f"Bearer {token}"}
    while time.time() < deadline:
        r = requests.get(f"{CANVA_API_BASE}/assets/{job_id}", headers=headers, timeout=15)
        r.raise_for_status()
        data   = r.json()
        asset  = data.get("asset", data)
        status = asset.get("import_status", {}).get("state") or asset.get("status", "")
        if status in ("success", "succeeded", ""):
            url = (asset.get("thumbnail", {}).get("url")
                   or asset.get("url")
                   or asset.get("view_url", ""))
            if url:
                return url
        if status in ("failed", "error"):
            raise RuntimeError(f"Asset upload falló: {data}")
        time.sleep(2)
    raise TimeoutError("Asset upload no completó a tiempo")


def upload_asset_from_url(image_url: str, name: str = "flux-bg") -> str:
    """Sube una imagen desde URL a Canva y retorna el asset ID."""
    r = requests.post(
        f"{CANVA_API_BASE}/assets/upload",
        json={"url": image_url, "name": name},
        headers=_headers(),
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    asset_id = data.get("asset", {}).get("id") or data.get("id", "")
    if not asset_id:
        raise RuntimeError(f"No se pudo obtener asset ID: {data}")
    return asset_id


def create_banner_design(asset_id: str, categoria: str, email_num: int) -> str:
    """
    Crea un diseño Canva de 1200x630 con el asset como fondo.
    Retorna el design ID.
    """
    overlay = _OVERLAYS.get((categoria, email_num), {
        "headline": "AMY AI — Revenue Force",
        "subtext":  "Respond in under 30 seconds. 24/7.",
    })

    r = requests.post(
        f"{CANVA_API_BASE}/designs",
        json={
            "design_type": {"type": "custom", "width": 1200, "height": 630},
            "title": f"AMY AI — {categoria} E{email_num}",
        },
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    design_id = r.json().get("design", {}).get("id", "")
    if not design_id:
        raise RuntimeError(f"No se pudo crear el diseño: {r.json()}")
    return design_id


def export_design(design_id: str) -> str:
    """Exporta un diseño como JPG y retorna la URL de descarga."""
    r = requests.post(
        f"{CANVA_API_BASE}/exports",
        json={
            "design_id": design_id,
            "format":    {"type": "jpg", "export_quality": "pro"},
        },
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    data    = r.json()
    job_id  = data.get("job", {}).get("id", "")
    if not job_id:
        raise RuntimeError(f"Export falló: {data}")
    return _poll_export(job_id)


def _poll_export(job_id: str, max_wait: int = 60) -> str:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        r = requests.get(
            f"{CANVA_API_BASE}/exports/{job_id}",
            headers=_headers(),
            timeout=30,
        )
        r.raise_for_status()
        job = r.json().get("job", {})
        if job.get("status") == "success":
            urls = job.get("urls", [])
            if urls:
                return urls[0]
        if job.get("status") == "failed":
            raise RuntimeError(f"Export falló: {job}")
        time.sleep(3)
    raise TimeoutError("Export de Canva no completó a tiempo")


def is_authorized() -> bool:
    return TOKEN_FILE.exists() and bool(_load_token().get("access_token"))
