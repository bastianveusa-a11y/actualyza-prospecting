"""
Registros mercantiles estatales de EE.UU.
Interfaz unificada: lookup(state, clinic_name, ...) → dict con mismos campos que Sunbiz.

Soportados:
  FL → Sunbiz (existente)
  CA → California SOS JSON API
  AZ → Arizona Corporation Commission JSON API
  TX → Texas SOS form search
  NV → Nevada SOS form search
  Resto → skip (retorna dict vacío sin error bloqueante)
"""

import time
import re
import requests
from difflib import SequenceMatcher

TIMEOUT = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
}


def _score(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _best_match(name: str, candidates: list, name_key: str, min_score: float = 0.55):
    """Retorna el candidato con mejor score de nombre, o None si no pasa el mínimo."""
    scored = sorted(
        [{"item": c, "score": _score(name, c.get(name_key, ""))} for c in candidates],
        key=lambda x: x["score"], reverse=True,
    )
    if scored and scored[0]["score"] >= min_score:
        return scored[0]["item"], scored[0]["score"]
    return None, 0.0


# ─────────────────────────────────────────────────────────────────────────────
# California — SOS JSON API (pública, sin auth)
# ─────────────────────────────────────────────────────────────────────────────
def _lookup_ca(clinic_name: str, delay: float = 1.5) -> dict:
    try:
        time.sleep(delay)
        resp = requests.get(
            "https://bizfileonline.sos.ca.gov/api/Records/businesses/search",
            params={"query": clinic_name, "page": 0, "status": ""},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", {}).get("hits", []) or data.get("results", []) or []

        # Normalizar campos del JSON de CA SOS
        candidates = []
        for h in hits[:10]:
            src = h.get("_source", h)
            candidates.append({
                "name":  src.get("CORP_NM", src.get("name", "")),
                "agent": src.get("AGENT_NM", src.get("agent_name", "")),
                "status": src.get("CORP_STATUS_CDDESCR", ""),
                "id":    src.get("CORP_ID", src.get("entity_number", "")),
            })

        match, score = _best_match(clinic_name, candidates, "name")
        if not match:
            return {"error": f"CA SOS: sin match para '{clinic_name}'"}

        entity_id = match.get("id", "")
        return {
            "nombre_legal":      match.get("name", ""),
            "dueno":             match.get("agent", ""),
            "agente_registrado": match.get("agent", ""),
            "estado_registro":   match.get("status", ""),
            "sunbiz_url":        f"https://bizfileonline.sos.ca.gov/search/business/{entity_id}",
            "match_score":       round(score, 2),
        }
    except Exception as e:
        return {"error": f"CA SOS: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# Arizona — Arizona Corporation Commission JSON API
# ─────────────────────────────────────────────────────────────────────────────
def _lookup_az(clinic_name: str, delay: float = 1.5) -> dict:
    try:
        time.sleep(delay)
        resp = requests.get(
            "https://ecorp.azcc.gov/CommonHelper/GetEntityByName",
            params={"name": clinic_name},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        hits = resp.json() or []
        if not isinstance(hits, list):
            hits = hits.get("results", []) or []

        candidates = [
            {
                "name":   h.get("EntityName", ""),
                "agent":  h.get("AgentName", ""),
                "status": h.get("EntityStatus", ""),
                "id":     h.get("EntityId", ""),
            }
            for h in hits[:10]
        ]

        match, score = _best_match(clinic_name, candidates, "name")
        if not match:
            return {"error": f"AZ ACC: sin match para '{clinic_name}'"}

        entity_id = match.get("id", "")
        return {
            "nombre_legal":      match.get("name", ""),
            "dueno":             match.get("agent", ""),
            "agente_registrado": match.get("agent", ""),
            "estado_registro":   match.get("status", ""),
            "sunbiz_url":        f"https://ecorp.azcc.gov/EntitySearch/Index?entityNumber={entity_id}",
            "match_score":       round(score, 2),
        }
    except Exception as e:
        return {"error": f"AZ ACC: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# Texas — Texas SOS form search (HTML scraping)
# ─────────────────────────────────────────────────────────────────────────────
def _lookup_tx(clinic_name: str, delay: float = 2.0) -> dict:
    try:
        from bs4 import BeautifulSoup
        time.sleep(delay)
        session = requests.Session()
        session.headers.update(HEADERS)

        # Texas SOS busqueda pública
        resp = session.get(
            "https://mycpa.cpa.state.tx.us/coa/",
            timeout=TIMEOUT,
        )
        resp.raise_for_status()

        # POST con el nombre
        search = session.post(
            "https://mycpa.cpa.state.tx.us/coa/",
            data={
                "firmnme": clinic_name,
                "taxpayernumber": "",
                "Submit": "Search",
            },
            timeout=TIMEOUT,
        )
        soup = BeautifulSoup(search.text, "lxml")

        rows = soup.select("table tr")[1:11]  # skip header
        candidates = []
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) >= 2:
                candidates.append({"name": cells[0], "agent": cells[1] if len(cells) > 1 else ""})

        match, score = _best_match(clinic_name, candidates, "name")
        if not match:
            return {"error": f"TX SOS: sin match para '{clinic_name}'"}

        return {
            "nombre_legal":      match.get("name", ""),
            "dueno":             match.get("agent", ""),
            "agente_registrado": match.get("agent", ""),
            "estado_registro":   "Active",
            "sunbiz_url":        f"https://mycpa.cpa.state.tx.us/coa/?firmnme={requests.utils.quote(clinic_name)}",
            "match_score":       round(score, 2),
        }
    except Exception as e:
        return {"error": f"TX SOS: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# Nevada — Nevada SOS search
# ─────────────────────────────────────────────────────────────────────────────
def _lookup_nv(clinic_name: str, delay: float = 2.0) -> dict:
    try:
        from bs4 import BeautifulSoup
        time.sleep(delay)
        resp = requests.post(
            "https://esos.nv.gov/EntitySearch/OnlineEntitySearch",
            data={
                "entityName":      clinic_name,
                "entityType":      "",
                "entityStatus":    "Active",
                "searchType":      "NonProfitCorporation,ProfessionalCorporation,Corporation,LLC",
                "listSize":        "10",
                "startIndex":      "0",
            },
            headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        rows = soup.select("table.grid tr")[1:11]
        candidates = []
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if cells:
                link = row.find("a")
                href = link["href"] if link and link.get("href") else ""
                candidates.append({"name": cells[0], "agent": cells[2] if len(cells) > 2 else "", "href": href})

        match, score = _best_match(clinic_name, candidates, "name")
        if not match:
            return {"error": f"NV SOS: sin match para '{clinic_name}'"}

        return {
            "nombre_legal":      match.get("name", ""),
            "dueno":             match.get("agent", ""),
            "agente_registrado": match.get("agent", ""),
            "estado_registro":   "Active",
            "sunbiz_url":        f"https://esos.nv.gov{match.get('href', '')}",
            "match_score":       round(score, 2),
        }
    except Exception as e:
        return {"error": f"NV SOS: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# Router principal
# ─────────────────────────────────────────────────────────────────────────────
_SUPPORTED = {"FL", "CA", "AZ", "TX", "NV"}


def lookup(
    state: str,
    clinic_name: str,
    clinic_address: str = "",
    clinic_zip: str = "",
    clinic_phone: str = "",
    delay: float = 1.5,
) -> dict:
    """
    Busca datos del registro mercantil estatal para una clínica.
    Retorna dict con: nombre_legal, dueno, agente_registrado, sunbiz_url, match_score.
    Si el estado no está soportado o no hay match, retorna {"error": "..."}.
    """
    if state == "FL":
        from modules.sunbiz import lookup_clinic as sunbiz_lookup
        return sunbiz_lookup(
            clinic_name=clinic_name,
            clinic_address=clinic_address,
            clinic_zip=clinic_zip,
            clinic_phone=clinic_phone,
            delay=delay,
        )
    if state == "CA":
        return _lookup_ca(clinic_name, delay)
    if state == "AZ":
        return _lookup_az(clinic_name, delay)
    if state == "TX":
        return _lookup_tx(clinic_name, delay)
    if state == "NV":
        return _lookup_nv(clinic_name, delay)

    # Estado no soportado — skip silencioso
    return {"error": f"Registro mercantil para {state} no implementado aún"}
