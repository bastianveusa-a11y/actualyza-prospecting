"""
Módulo Google Places (New API)
Busca clínicas por categoría y ciudad, extrae datos básicos.
"""

import os
import time
import requests


SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.addressComponents",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.websiteUri",
    "places.rating",
    "places.userRatingCount",
    "places.regularOpeningHours",
    "places.types",
    "places.googleMapsUri",
])

CATEGORIES = {
    "dental":    "dental clinic",
    "estetica":  "cosmetic surgery clinic",
    "medspa":    "med spa",
    "wellness":  "wellness clinic",
}


def _build_headers(api_key: str) -> dict:
    return {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
        "Content-Type": "application/json",
    }


def _extract_zip(address_components: list) -> str:
    for comp in address_components:
        if "postal_code" in comp.get("types", []):
            return comp.get("shortText", "")
    return ""


def _parse_place(place: dict) -> dict:
    address_components = place.get("addressComponents", [])
    return {
        "google_place_id":  place.get("id", ""),
        "nombre":           place.get("displayName", {}).get("text", ""),
        "direccion":        place.get("formattedAddress", ""),
        "zip":              _extract_zip(address_components),
        "telefono":         place.get("nationalPhoneNumber", ""),
        "telefono_intl":    place.get("internationalPhoneNumber", ""),
        "web":              place.get("websiteUri", ""),
        "rating":           place.get("rating", ""),
        "reviews":          place.get("userRatingCount", 0),
        "google_maps_url":  place.get("googleMapsUri", ""),
        "tipos":            place.get("types", []),
    }


def search_clinics(
    city: str,
    state: str,
    category_key: str,
    api_key: str,
    max_results: int = 20,
    page_token: str = None,
    delay: float = 1.0,
) -> dict:
    """
    Busca clínicas de una categoría en una ciudad.
    Retorna: {"clinics": [...], "next_page_token": str|None, "error": str|None}
    """
    category_term = CATEGORIES.get(category_key, category_key)
    query = f"{category_term} in {city}, {state}"

    body = {
        "textQuery": query,
        "maxResultCount": min(max_results, 20),
        "locationBias": {
            "circle": {
                "center": _get_city_center(city),
                "radius": 40000.0,
            }
        },
    }
    if page_token:
        body["pageToken"] = page_token

    try:
        time.sleep(delay)
        r = requests.post(
            SEARCH_URL,
            headers=_build_headers(api_key),
            json=body,
            timeout=15,
        )
        data = r.json()

        if r.status_code != 200:
            msg = data.get("error", {}).get("message", r.text[:200])
            return {"clinics": [], "next_page_token": None, "error": msg}

        clinics = [_parse_place(p) for p in data.get("places", [])]
        return {
            "clinics":         clinics,
            "next_page_token": data.get("nextPageToken"),
            "error":           None,
        }

    except Exception as e:
        return {"clinics": [], "next_page_token": None, "error": str(e)}


def search_all_categories(
    city: str,
    state: str,
    api_key: str,
    max_per_category: int = 20,
    delay: float = 1.0,
) -> list[dict]:
    """
    Busca todas las categorías para una ciudad.
    Retorna lista de clínicas deduplicadas por google_place_id.
    """
    seen = set()
    all_clinics = []

    for key in CATEGORIES:
        print(f"  Buscando {key} en {city}...")
        result = search_clinics(city, state, key, api_key, max_per_category, delay=delay)

        if result["error"]:
            print(f"    Error en {key}: {result['error']}")
            continue

        for clinic in result["clinics"]:
            pid = clinic["google_place_id"]
            if pid not in seen:
                seen.add(pid)
                clinic["categoria"] = key
                clinic["ciudad"] = city
                clinic["estado"] = state
                all_clinics.append(clinic)

        print(f"    {len(result['clinics'])} encontradas ({len(all_clinics)} únicas acumuladas)")
        time.sleep(delay)

    return all_clinics


# Coordenadas centrales por ciudad
_CITY_CENTERS = {
    "Miami":   {"latitude": 25.7617, "longitude": -80.1918},
    "Orlando": {"latitude": 28.5383, "longitude": -81.3792},
    "Dallas":  {"latitude": 32.7767, "longitude": -96.7970},
}

def _get_city_center(city: str) -> dict:
    return _CITY_CENTERS.get(city, {"latitude": 25.7617, "longitude": -80.1918})


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("GOOGLE_PLACES_API_KEY")
    city    = os.getenv("TARGET_CITY", "Miami")
    state   = os.getenv("TARGET_STATE", "FL")

    print(f"Buscando clínicas en {city}, {state}...\n")
    clinics = search_all_categories(city, state, api_key, max_per_category=5)

    print(f"\nTotal encontradas: {len(clinics)}")
    for c in clinics[:3]:
        print(f"  - {c['nombre']} | {c['rating']}★ ({c['reviews']} reviews) | {c['telefono']}")
