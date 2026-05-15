#!/usr/bin/env python3
"""
Diagnóstico de conexiones — Actualyza Prospecting System
Corre este script para verificar qué servicios están activos y cuáles faltan.
Uso: python check_connections.py
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("ERROR: python-dotenv no instalado. Corre: pip install -r requirements.txt")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: requests no instalado. Corre: pip install -r requirements.txt")
    sys.exit(1)

# ── Colores ANSI ──────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def status_ok(detail):   return f"{GREEN}✓ CONECTADO{RESET}    {DIM}{detail}{RESET}"
def status_fail(detail): return f"{RED}✗ FALTA{RESET}        {DIM}{detail}{RESET}"
def status_warn(detail): return f"{YELLOW}~ OPCIONAL{RESET}     {DIM}{detail}{RESET}"


# ── Checks individuales ───────────────────────────────────────

def check_google_places():
    key = os.getenv("GOOGLE_PLACES_API_KEY")
    if not key:
        return False, status_fail("GOOGLE_PLACES_API_KEY no está en .env")

    # Places API (New) — endpoint y headers correctos
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress",
        "Content-Type": "application/json",
    }
    body = {"textQuery": "dental clinic miami", "maxResultCount": 1}
    try:
        r = requests.post(url, headers=headers, json=body, timeout=10)
        data = r.json()
        if r.status_code == 200:
            count = len(data.get("places", []))
            return True, status_ok(f"Places API (New) activa — resultados de prueba: {count}")
        else:
            msg = data.get("error", {}).get("message", r.text[:120])
            return False, status_fail(f"API respondió {r.status_code}: {msg}")
    except Exception as e:
        return False, status_fail(f"No se pudo conectar: {e}")


def check_meta_ads():
    # User Token tiene prioridad (funciona en apps sin verificación)
    token      = os.getenv("META_USER_TOKEN")
    token_type = "User Token"
    if not token:
        token      = os.getenv("META_APP_TOKEN")
        token_type = "App Token"
    if not token:
        app_id     = os.getenv("META_APP_ID")
        app_secret = os.getenv("META_APP_SECRET")
        if not app_id or not app_secret:
            return False, status_fail("META_USER_TOKEN no está en .env (ver instrucciones)")
        token      = f"{app_id}|{app_secret}"
        token_type = "App Token (construido)"
    url = "https://graph.facebook.com/v21.0/ads_archive"
    params = {
        "access_token": token,
        "ad_reached_countries": '["US"]',
        "search_terms": "clinic",
        "ad_active_status": "ACTIVE",
        "limit": 1,
        "fields": "id",
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if "error" in data:
            code = data["error"].get("code", "?")
            msg  = data["error"].get("message", "error desconocido")
            return False, status_fail(f"Error {code}: {msg}")
        return True, status_ok(f"Meta Ad Library activa ({token_type})")
    except Exception as e:
        return False, status_fail(f"No se pudo conectar: {e}")


def check_notion():
    token = os.getenv("NOTION_TOKEN")
    if not token:
        return False, status_fail("NOTION_TOKEN no está en .env")

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
    }
    try:
        r = requests.get("https://api.notion.com/v1/users/me", headers=headers, timeout=10)
        data = r.json()
        if r.status_code == 200:
            name = data.get("name") or data.get("bot", {}).get("owner", {}).get("user", {}).get("name", "bot")
            return True, status_ok(f"Notion API activa — integración: {name}")
        else:
            return False, status_fail(f"Notion respondió {r.status_code}: {data.get('message', '')}")
    except Exception as e:
        return False, status_fail(f"No se pudo conectar: {e}")


def check_notion_database():
    token = os.getenv("NOTION_TOKEN")
    db_id = os.getenv("NOTION_DATABASE_ID")

    if not db_id:
        return None, status_warn("NOTION_DATABASE_ID vacío — se configurará en Etapa 3")
    if not token:
        return False, status_fail("NOTION_TOKEN requerido para verificar la base de datos")

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
    }
    try:
        r = requests.get(
            f"https://api.notion.com/v1/databases/{db_id}",
            headers=headers,
            timeout=10,
        )
        data = r.json()
        if r.status_code == 200:
            titles = data.get("title", [])
            name = titles[0].get("plain_text", "Sin título") if titles else "Sin título"
            return True, status_ok(f"Database accesible — '{name}'")
        else:
            return False, status_fail(f"No se pudo acceder: {data.get('message', r.status_code)}")
    except Exception as e:
        return False, status_fail(f"Error al verificar database: {e}")


def check_smtp():
    import smtplib
    host     = os.getenv("SMTP_HOST", "smtp.hostinger.com")
    port     = int(os.getenv("SMTP_PORT", "465"))
    user     = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")

    if not user or not password:
        missing = []
        if not user:     missing.append("SMTP_USER")
        if not password: missing.append("SMTP_PASSWORD")
        return None, status_warn(f"{' y '.join(missing)} vacíos — necesario para Etapa 5 (email outreach)")

    try:
        # Puerto 465 usa SSL directo; puerto 587 usa STARTTLS
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=10) as server:
                server.login(user, password)
        else:
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.starttls()
                server.login(user, password)
        return True, status_ok(f"Hostinger SMTP activo — {user} (puerto {port} SSL)")
    except smtplib.SMTPAuthenticationError:
        return False, status_fail(f"Credenciales incorrectas para {user}")
    except Exception as e:
        return False, status_fail(f"No se pudo conectar a {host}:{port} — {e}")


def check_sunbiz():
    """Sunbiz no tiene API — solo verificamos que el sitio es accesible."""
    url = "https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults"
    try:
        r = requests.get(
            url,
            params={
                "searchNameOrder": "HEALTHTEST",
                "inquiryType": "EntityName",
                "inquiryDirectionType": "ForwardList",
            },
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
        )
        if r.status_code == 200:
            return True, status_ok("Sunbiz.org accesible (scraping — no requiere API key)")
        else:
            return None, status_warn(f"Sunbiz respondió {r.status_code} — puede ser temporal")
    except Exception as e:
        return False, status_fail(f"No se pudo conectar con Sunbiz: {e}")


def check_hunter():
    key = os.getenv("HUNTER_API_KEY")
    if not key:
        return None, status_warn("HUNTER_API_KEY vacío — opcional para enriquecimiento de emails")

    try:
        r = requests.get(
            "https://api.hunter.io/v2/account",
            params={"api_key": key},
            timeout=10,
        )
        data = r.json()
        if "data" in data:
            plan     = data["data"].get("plan_name", "desconocido")
            searches = data["data"].get("requests", {}).get("searches", {}).get("available", "?")
            return True, status_ok(f"Hunter.io activo — plan: {plan}, búsquedas disponibles: {searches}")
        else:
            errors = data.get("errors", [{}])
            detail = errors[0].get("details", "error desconocido") if errors else "error desconocido"
            return False, status_fail(f"Hunter.io error: {detail}")
    except Exception as e:
        return False, status_fail(f"No se pudo conectar: {e}")


# ── Runner principal ──────────────────────────────────────────

CHECKS = [
    {
        "name":  "Google Places API",
        "stage": "Etapa 1 — búsqueda de clínicas por ciudad y categoría",
        "fn":    check_google_places,
        "url":   "https://console.cloud.google.com/apis/credentials",
    },
    {
        "name":  "Meta Ad Library API",
        "stage": "Etapa 2 — conteo de anuncios activos (filtro central)",
        "fn":    check_meta_ads,
        "url":   "https://developers.facebook.com/apps/",
    },
    {
        "name":  "Notion API",
        "stage": "Todas las etapas — almacenamiento y dashboard",
        "fn":    check_notion,
        "url":   "https://www.notion.so/my-integrations",
    },
    {
        "name":  "Notion Database",
        "stage": "Etapa 3 — base de datos específica de prospectos",
        "fn":    check_notion_database,
        "url":   "(ID de la URL de tu base de datos en Notion)",
    },
    {
        "name":  "Sunbiz (scraping)",
        "stage": "Etapa 4 — datos legales y registro de propietario",
        "fn":    check_sunbiz,
        "url":   "https://search.sunbiz.org",
    },
    {
        "name":  "Email Hostinger SMTP",
        "stage": "Etapa 5 — envío de correos de prospección",
        "fn":    check_smtp,
        "url":   "Usa tu correo y contraseña de Hostinger (SMTP_USER / SMTP_PASSWORD)",
    },
    {
        "name":  "Hunter.io",
        "stage": "Opcional — enriquecimiento: emails de contacto por dominio",
        "fn":    check_hunter,
        "url":   "https://hunter.io/api-keys",
    },
]


def main():
    print()
    print(f"{BOLD}{'━' * 58}{RESET}")
    print(f"{BOLD}  DIAGNÓSTICO DE CONEXIONES{RESET}")
    print(f"{BOLD}  Actualyza Prospecting System{RESET}")
    print(f"{BOLD}{'━' * 58}{RESET}")
    print()

    connected = []
    missing   = []
    optional  = []

    for check in CHECKS:
        print(f"  {BOLD}{check['name']}{RESET}")
        print(f"  {CYAN}{check['stage']}{RESET}")
        status, message = check["fn"]()
        print(f"  {message}")
        print()

        if status is True:
            connected.append(check["name"])
        elif status is False:
            missing.append((check["name"], check["url"]))
        else:
            optional.append(check["name"])

    print(f"{BOLD}{'━' * 58}{RESET}")
    print(f"{BOLD}  RESUMEN{RESET}")
    print(f"{BOLD}{'━' * 58}{RESET}")
    print(f"  {GREEN}Conectados:{RESET}  {len(connected)}  —  {', '.join(connected) or 'ninguno'}")
    print(f"  {RED}Faltantes:{RESET}   {len(missing)}  —  {', '.join(n for n, _ in missing) or 'ninguno'}")
    print(f"  {YELLOW}Opcionales:{RESET}  {len(optional)}  —  {', '.join(optional) or 'ninguno'}")
    print()

    if missing:
        print(f"{BOLD}  PRÓXIMOS PASOS (orden recomendado):{RESET}")
        priority = ["Notion API", "Google Places API", "Meta Ad Library API", "Email Hostinger SMTP", "Hunter.io"]
        step = 1
        for name in priority:
            for mname, url in missing:
                if mname == name:
                    print(f"  {step}. {mname}")
                    print(f"     {DIM}{url}{RESET}")
                    step += 1
        print()

    print(f"  {DIM}Copia .env.example → .env y completa las variables faltantes.")
    print(f"  Vuelve a correr este script para ver tu progreso.{RESET}")
    print()


if __name__ == "__main__":
    main()
