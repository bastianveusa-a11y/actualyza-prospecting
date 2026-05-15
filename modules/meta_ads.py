"""
Módulo Meta Ad Library
Cuenta anuncios activos de una clínica en Meta Ad Library.

Flujo:
1. Si se provee website_url, extrae el slug de Facebook/Instagram del sitio web.
2. Con el slug exacto busca en Ad Library con search_type=page (mucho más preciso).
3. Si no hay slug, busca por nombre de clínica con keyword_unordered.
4. Si hay user_token activo, intenta la API oficial primero.
"""

import re
import time
import requests
from urllib.parse import urlparse


GRAPH_URL   = "https://graph.facebook.com/v21.0/ads_archive"
LIBRARY_URL = "https://www.facebook.com/ads/library/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

_FB_URL_RE = re.compile(r'https?://(?:www\.)?facebook\.com/([a-zA-Z0-9._-]{3,})', re.IGNORECASE)
_IG_URL_RE = re.compile(r'https?://(?:www\.)?instagram\.com/([a-zA-Z0-9._-]{3,})', re.IGNORECASE)

# Slugs de Facebook que no son páginas de negocio
_FB_SKIP = {
    'sharer', 'sharer.php', 'login', 'login.php', 'dialog', 'share',
    'groups', 'events', 'pages', 'marketplace', 'help', 'policies',
    'legal', 'ads', 'business', 'watch', 'gaming', 'fundraisers',
    'profile.php', 'permalink.php', 'hashtag', 'plugins', 'photo',
    'video', 'note', 'notes', 'messages', 'notifications', 'settings',
    'bookmarks', 'friends', 'find-friends', 'jobs', 'news', 'stories',
    'your_information', 'privacy', 'terms', 'cookies', 'about',
}

# Slugs de Instagram que no son perfiles
_IG_SKIP = {
    'explore', 'p', 'reel', 'reels', 'stories', 'tv', 'accounts',
    'web', 'about', 'legal', 'privacy', 'help', 'press', 'api',
    'developer', 'directory', 'lite', 'download', 'invite',
}


def find_social_links(website_url: str, timeout: int = 8) -> dict:
    """
    Extrae slugs de Facebook/Instagram del sitio web de la clínica.
    Retorna: {"facebook": str, "instagram": str}
    """
    result = {"facebook": "", "instagram": ""}
    if not website_url:
        return result

    try:
        r = requests.get(website_url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code != 200:
            return result
        html = r.text
    except Exception:
        return result

    # Busca Facebook
    for m in _FB_URL_RE.finditer(html):
        slug = m.group(1).split('?')[0].split('#')[0].rstrip('/')
        if slug.lower() not in _FB_SKIP and len(slug) >= 3:
            result["facebook"] = slug
            break

    # Busca Instagram
    for m in _IG_URL_RE.finditer(html):
        slug = m.group(1).split('?')[0].split('#')[0].rstrip('/')
        if slug.lower() not in _IG_SKIP and len(slug) >= 3:
            result["instagram"] = slug
            break

    return result


def count_ads_for_page(
    page_name: str,
    facebook_page_id: str = None,
    user_token: str = None,
    delay: float = 2.0,
    website_url: str = None,
) -> dict:
    """
    Cuenta anuncios activos de una clínica en Meta Ad Library.
    Si website_url se provee, primero extrae el slug exacto de Facebook/Instagram.
    Retorna: {"count": int, "level": str, "method": str, "error": str|None, "fb_slug": str}
    """
    time.sleep(delay)

    # Paso 1: Extraer slug exacto desde el sitio web
    fb_slug = ""
    ig_slug = ""
    if website_url:
        social  = find_social_links(website_url)
        fb_slug = social["facebook"]
        ig_slug = social["instagram"]

    # El nombre más preciso disponible: slug FB > slug IG > nombre de clínica
    exact_name  = fb_slug or ig_slug or page_name
    search_type = "page" if (fb_slug or ig_slug) else "keyword_unordered"

    # Paso 2: Intentar API oficial si hay token
    if user_token:
        result = _count_via_api(exact_name, facebook_page_id, user_token)
        if result["error"] is None:
            result["fb_slug"] = fb_slug or ig_slug
            return result
        print(f"    API Meta falló ({result['error']}), usando scraping web...")

    # Paso 3: Scraping de Ad Library
    result = _count_via_scraping(exact_name, delay=0, search_type=search_type)
    result["fb_slug"] = fb_slug or ig_slug
    return result


def _count_via_api(page_name: str, page_id: str, token: str) -> dict:
    """Consulta la API oficial de Ad Library."""
    params = {
        "access_token":         token,
        "ad_reached_countries": '["US"]',
        "ad_active_status":     "ACTIVE",
        "limit":                50,
        "fields":               "id",
    }
    if page_id:
        params["search_page_ids"] = f'[{page_id}]'
    else:
        params["search_terms"] = page_name

    try:
        r    = requests.get(GRAPH_URL, params=params, timeout=15)
        data = r.json()
        if "error" in data:
            return {
                "count": 0, "level": "Sin anuncios", "method": "api",
                "error": f"Error {data['error'].get('code')}: {data['error'].get('message', '')}",
            }
        count = len(data.get("data", []))
        return {"count": count, "level": _classify_level(count), "method": "api", "error": None}
    except Exception as e:
        return {"count": 0, "level": "Sin anuncios", "method": "api", "error": str(e)}


def _count_via_scraping(
    page_name: str,
    delay: float = 0,
    search_type: str = "keyword_unordered",
) -> dict:
    """
    Scraping de facebook.com/ads/library.
    Con search_type='page' y un slug exacto, los resultados son mucho más precisos.
    """
    if delay > 0:
        time.sleep(delay)

    params = {
        "active_status": "active",
        "ad_type":       "all",
        "country":       "US",
        "q":             page_name,
        "search_type":   search_type,
    }
    try:
        r    = requests.get(LIBRARY_URL, params=params, headers=_HEADERS, timeout=15)
        text = r.text

        # Patrones para extraer cantidad
        patterns = [
            r'"total_count"\s*:\s*(\d+)',
            r'(\d[\d,]*)\s+result',
            r'Showing\s+.*?(\d+)\s+ad',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                count = int(m.group(1).replace(',', ''))
                return {
                    "count": count, "level": _classify_level(count),
                    "method": f"scraping_{search_type}", "error": None,
                }

        # Indicador binario si no se puede extraer número
        has_ads = '"ad_archive_id"' in text or "active ads" in text.lower()
        count   = 1 if has_ads else 0
        return {
            "count": count, "level": "Baja" if has_ads else "Sin anuncios",
            "method": f"scraping_{search_type}_approx", "error": None,
        }

    except Exception as e:
        return {"count": 0, "level": "Sin anuncios", "method": "scraping", "error": str(e)}


def _classify_level(count: int) -> str:
    if count == 0:  return "Sin anuncios"
    if count <= 3:  return "Baja"
    if count <= 10: return "Media"
    return "Alta"


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    token = os.getenv("META_USER_TOKEN")

    test_cases = [
        {"page_name": "Aspen Dental Miami",  "website": "https://www.aspendental.com"},
        {"page_name": "Ideal Image Orlando", "website": "https://www.idealimage.com"},
    ]

    for tc in test_cases:
        print(f"\nBuscando anuncios de '{tc['page_name']}'...")
        result = count_ads_for_page(
            page_name=tc["page_name"],
            user_token=token,
            delay=2.0,
            website_url=tc["website"],
        )
        print(f"  Slug FB: {result.get('fb_slug', '-')}")
        print(f"  Anuncios: {result['count']} | Nivel: {result['level']} | Método: {result['method']}")
        if result["error"]:
            print(f"  Error: {result['error']}")
