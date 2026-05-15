"""
Módulo Meta Ad Library
Cuenta anuncios activos de una página de Facebook.
Usa la API oficial si META_USER_TOKEN está activo,
o scraping web como fallback automático.
"""

import os
import re
import time
import requests


GRAPH_URL    = "https://graph.facebook.com/v21.0/ads_archive"
LIBRARY_URL  = "https://www.facebook.com/ads/library/"
SEARCH_URL   = "https://www.facebook.com/ads/library/async/search_ads/"


def count_ads_for_page(
    page_name: str,
    facebook_page_id: str = None,
    user_token: str = None,
    delay: float = 2.0,
) -> dict:
    """
    Cuenta anuncios activos de una clínica en Meta Ad Library.
    Intenta API primero; si falla, usa scraping web.
    Retorna: {"count": int, "level": str, "method": str, "error": str|None}
    """
    time.sleep(delay)

    if user_token:
        result = _count_via_api(page_name, facebook_page_id, user_token)
        if result["error"] is None:
            return result
        # API falló — fallback a scraping
        print(f"    API Meta falló ({result['error']}), usando scraping web...")

    return _count_via_scraping(page_name, delay)


def _count_via_api(
    page_name: str,
    page_id: str,
    token: str,
) -> dict:
    """Consulta la API oficial de Ad Library."""
    params = {
        "access_token":        token,
        "ad_reached_countries": '["US"]',
        "ad_active_status":    "ACTIVE",
        "limit":               50,
        "fields":              "id",
    }
    if page_id:
        params["search_page_ids"] = f'[{page_id}]'
    else:
        params["search_terms"] = page_name

    try:
        r = requests.get(GRAPH_URL, params=params, timeout=15)
        data = r.json()
        if "error" in data:
            return {
                "count": 0, "level": "Sin anuncios", "method": "api",
                "error": f"Error {data['error'].get('code')}: {data['error'].get('message', '')}",
            }
        count = len(data.get("data", []))
        return {
            "count": count,
            "level": _classify_level(count),
            "method": "api",
            "error": None,
        }
    except Exception as e:
        return {"count": 0, "level": "Sin anuncios", "method": "api", "error": str(e)}


def _count_via_scraping(page_name: str, delay: float = 2.0) -> dict:
    """
    Scraping de facebook.com/ads/library como fallback.
    Solo cuenta si hay resultados visibles — no es perfecto pero es funcional.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    params = {
        "active_status": "active",
        "ad_type":       "all",
        "country":       "US",
        "q":             page_name,
        "search_type":   "keyword_unordered",
    }
    try:
        time.sleep(delay)
        r = requests.get(LIBRARY_URL, params=params, headers=headers, timeout=15)

        # Busca indicadores de cantidad en el HTML
        text = r.text
        patterns = [
            r'"total_count":(\d+)',
            r'(\d+)\s+result',
            r'Showing\s+.*?(\d+)\s+ad',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                count = int(m.group(1))
                return {
                    "count":  count,
                    "level":  _classify_level(count),
                    "method": "scraping",
                    "error":  None,
                }

        # No se pudo extraer número exacto — indicamos si hay anuncios o no
        has_ads = (
            '"ad_archive_id"' in text
            or "sponsored" in text.lower()
            or "active ads" in text.lower()
        )
        count = 1 if has_ads else 0
        return {
            "count":  count,
            "level":  "Baja" if has_ads else "Sin anuncios",
            "method": "scraping_approximate",
            "error":  None,
        }

    except Exception as e:
        return {
            "count": 0, "level": "Sin anuncios",
            "method": "scraping", "error": str(e),
        }


def _classify_level(count: int) -> str:
    """Clasifica el nivel de inversión estimada según cantidad de anuncios."""
    if count == 0:  return "Sin anuncios"
    if count <= 3:  return "Baja"
    if count <= 10: return "Media"
    return "Alta"


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    token = os.getenv("META_USER_TOKEN")

    test_cases = [
        {"page_name": "Aspen Dental", "page_id": None},
        {"page_name": "Ideal Image",  "page_id": None},
    ]

    for tc in test_cases:
        print(f"Buscando anuncios de '{tc['page_name']}'...")
        result = count_ads_for_page(
            page_name=tc["page_name"],
            user_token=token,
            delay=2.0,
        )
        print(f"  Anuncios: {result['count']} | Nivel: {result['level']} | Método: {result['method']}")
        if result["error"]:
            print(f"  Error: {result['error']}")
