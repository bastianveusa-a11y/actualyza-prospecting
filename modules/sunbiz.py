"""
Módulo Sunbiz — Florida Division of Corporations
Busca datos legales y dueños de clínicas por nombre.
Usa cloudscraper para pasar Cloudflare. Pausas obligatorias entre requests.

Estrategias de búsqueda (en orden):
  1. Nombre de entidad exacto
  2. Officer/manager por keyword del nombre
  3. Variantes del nombre (subconjuntos de palabras distintivas)
  4. Nombre ficticio / DBA (negocio registrado bajo otro nombre legal)

Scoring: nombre (65%) + ZIP (20%) + dirección (15%) + teléfono (10% bonus)
"""

import re
import time
import unicodedata
from typing import Optional

import cloudscraper
from bs4 import BeautifulSoup


BASE               = "https://search.sunbiz.org"
SEARCH_URL         = f"{BASE}/Inquiry/CorporationSearch/SearchResults"
FICTITIOUS_URL     = f"{BASE}/Inquiry/FicticiousNameSearch/SearchResults"

_STOP_WORDS = {
    "the", "of", "and", "a", "an", "for", "by",
    "clinic", "dental", "center", "centre", "medical", "med", "spa",
    "wellness", "health", "care", "group", "studio", "aesthetics",
    "aesthetic", "beauty", "plastic", "surgery", "cosmetic", "institute",
    "associates", "llc", "inc", "pa", "pllc", "corp", "florida",
    "services", "solutions", "management", "practice",
}

_GEO_TERMS = {
    "miami", "brickell", "coral", "gables", "doral", "hialeah", "kendall",
    "aventura", "wynwood", "coconut", "grove", "homestead", "cutler",
    "bay", "north", "south", "east", "west", "downtown",
}

_ENTITY_SUFFIXES = {"llc", "inc", "corp", "pa", "pllc", "ltd", "co", "plc"}

# Sesión compartida (se crea una vez por proceso)
_scraper = None

def _get_scraper():
    global _scraper
    if _scraper is None:
        _scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "darwin", "mobile": False}
        )
    return _scraper


# ── Utilidades de matching ────────────────────────────────────

def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(w for w in text.split() if w not in _STOP_WORDS)


def _name_score(a: str, b: str) -> float:
    wa = set(_normalize(a).split())
    wb = set(_normalize(b).split())
    if not wa or not wb:
        return 0.0
    common = wa & wb
    if not common:
        return 0.0
    base = len(common) / max(len(wa), len(wb))
    if common.issubset(_GEO_TERMS):
        base *= 0.4
    return base


def _zip_match(address_block: str, target_zip: str) -> bool:
    if not target_zip:
        return False
    return target_zip.strip()[:5] in address_block


def _address_overlap(sunbiz_addr: str, clinic_addr: str) -> float:
    stop = {"st", "ave", "blvd", "dr", "rd", "ln", "suite", "ste", "fl", "florida"}
    def tokens(s):
        s = re.sub(r"[^a-z0-9\s]", " ", s.lower())
        return set(w for w in s.split() if w not in stop and len(w) > 1)
    ta, tb = tokens(sunbiz_addr), tokens(clinic_addr)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def _name_variants(clinic_name: str) -> list:
    """Genera variantes de búsqueda con subconjuntos de palabras distintivas."""
    words = [w for w in _normalize(clinic_name).split()
             if w not in _GEO_TERMS and len(w) > 3]
    full = " ".join(words)
    variants = []
    if len(words) >= 2:
        variants.append(" ".join(words[:2]))
    if len(words) >= 3:
        variants.append(" ".join(words[1:3]))
        variants.append(" ".join(words[:3]))
    return [v for v in dict.fromkeys(variants) if v and v != full]


def _is_entity_name(name: str) -> bool:
    """Determina si un nombre corresponde a una entidad (LLC, Inc, etc.)."""
    last = name.strip().split()[-1].lower().rstrip(".,") if name.strip() else ""
    return last in _ENTITY_SUFFIXES


# ── HTTP ──────────────────────────────────────────────────────

def _get(url: str, params: dict = None, delay: float = 3.0) -> Optional[BeautifulSoup]:
    time.sleep(delay)
    try:
        r = _get_scraper().get(url, params=params, timeout=20)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "lxml")
        return None
    except Exception:
        return None


# ── Búsqueda de entidades ─────────────────────────────────────

def search_entity(name: str, delay: float = 3.0) -> list:
    """Busca por nombre de entidad en Sunbiz. Retorna lista de candidatos."""
    term = re.sub(r"[^a-zA-Z0-9\s]", " ", name).strip().upper()
    soup = _get(SEARCH_URL, params={
        "inquiryType":          "EntityName",
        "inquiryDirectionType": "ForwardList",
        "searchNameOrder":      term,
    }, delay=delay)
    if not soup:
        return []
    results = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "SearchResultDetail" not in href:
            continue
        td = a.find_parent("td")
        if not td:
            continue
        siblings = td.find_next_siblings("td")
        doc_num = siblings[0].get_text(strip=True) if len(siblings) > 0 else ""
        status  = siblings[1].get_text(strip=True) if len(siblings) > 1 else ""
        results.append({
            "nombre_legal": a.get_text(strip=True),
            "documento":    doc_num,
            "status":       status,
            "detail_url":   BASE + href,
        })
        if len(results) >= 15:
            break
    return results


def search_by_officer(officer_name: str, delay: float = 3.0) -> list:
    """
    Busca entidades por nombre de officer/director/manager.
    Útil cuando la entidad se registró con nombre del dueño, no del negocio.
    """
    term = re.sub(r"[^a-zA-Z0-9\s]", " ", officer_name).strip().upper()
    soup = _get(SEARCH_URL, params={
        "inquiryType":          "OfficerName",
        "inquiryDirectionType": "ForwardList",
        "searchNameOrder":      term,
    }, delay=delay)
    if not soup:
        return []
    results = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "SearchResultDetail" not in href:
            continue
        td = a.find_parent("td")
        if not td:
            continue
        siblings = td.find_next_siblings("td")
        doc_num = siblings[0].get_text(strip=True) if len(siblings) > 0 else ""
        status  = siblings[1].get_text(strip=True) if len(siblings) > 1 else ""
        results.append({
            "nombre_legal": a.get_text(strip=True),
            "documento":    doc_num,
            "status":       status,
            "detail_url":   BASE + href,
        })
        if len(results) >= 10:
            break
    return results


def search_fictitious_name(name: str, delay: float = 3.0) -> list:
    """
    Busca en el índice de nombres ficticios (DBA) de Sunbiz.
    Muchas clínicas operan bajo un nombre comercial distinto al nombre legal
    de su LLC (ej: 'Brickell Dental Care' → dba de 'SMITH DENTAL SERVICES LLC').
    """
    term = re.sub(r"[^a-zA-Z0-9\s]", " ", name).strip().upper()
    soup = _get(FICTITIOUS_URL, params={
        "inquiryType":          "FictitiousName",
        "inquiryDirectionType": "ForwardList",
        "searchNameOrder":      term,
    }, delay=delay)
    if not soup:
        return []
    results = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "SearchResultDetail" not in href:
            continue
        td = a.find_parent("td")
        if not td:
            continue
        siblings = td.find_next_siblings("td")
        doc_num = siblings[0].get_text(strip=True) if len(siblings) > 0 else ""
        status  = siblings[1].get_text(strip=True) if len(siblings) > 1 else ""
        results.append({
            "nombre_legal": a.get_text(strip=True),
            "documento":    doc_num,
            "status":       status,
            "detail_url":   BASE + href,
            "is_dba":       True,
        })
        if len(results) >= 15:
            break
    return results


# ── Detalle de entidad ────────────────────────────────────────

def get_entity_detail(detail_url: str, delay: float = 3.0) -> dict:
    """
    Extrae información de la página de detalle de Sunbiz.
    La página es texto lineal con secciones por palabras clave.
    """
    soup = _get(detail_url, delay=delay)
    if not soup:
        return {"error": "No se pudo acceder al detalle"}

    lines = [l.strip() for l in soup.get_text(separator="\n").split("\n") if l.strip()]

    data = {
        "nombre_legal":         "",
        "documento":            "",
        "status_legal":         "",
        "fecha_registro":       "",
        "direccion_registrada": "",
        "agente_registrado":    "",
        "officers":             [],
        "phones":               [],
        "error":                None,
    }

    SECTION_MARKERS = {
        "filing information", "principal address", "mailing address",
        "registered agent name & address", "authorized person(s) detail",
        "name & address", "annual reports", "document images",
        "previous on list", "next on list", "return to list",
        "events", "no name history", "detail by entity name",
        "no annual reports filed", "florida department of state",
        "division of corporations", "search records", "search by entity name",
    }
    ENTITY_TYPES = {"limited liability", "corporation", "profit corp", "not for profit"}

    def is_section(line):
        return line.lower() in SECTION_MARKERS

    # Extrae números de teléfono de toda la página
    full_text = "\n".join(lines)
    raw_phones = re.findall(r'\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b', full_text)
    data["phones"] = list({re.sub(r"\D", "", p) for p in raw_phones})

    i = 0
    while i < len(lines):
        line  = lines[i]
        lower = line.lower()

        if any(x in lower for x in ENTITY_TYPES) and not data["nombre_legal"]:
            if i + 1 < len(lines) and not is_section(lines[i + 1]):
                data["nombre_legal"] = lines[i + 1]

        elif lower == "document number" and i + 1 < len(lines):
            data["documento"] = lines[i + 1]; i += 2; continue

        elif lower == "status" and i + 1 < len(lines):
            data["status_legal"] = lines[i + 1]; i += 2; continue

        elif lower == "date filed" and i + 1 < len(lines):
            data["fecha_registro"] = lines[i + 1]; i += 2; continue

        elif lower == "principal address":
            j, addr = i + 1, []
            while j < len(lines) and not is_section(lines[j]) and j < i + 5:
                addr.append(lines[j]); j += 1
            data["direccion_registrada"] = " ".join(addr)
            i = j; continue

        elif lower == "registered agent name & address":
            j, agent = i + 1, []
            while j < len(lines) and not is_section(lines[j]) and j < i + 4:
                agent.append(lines[j]); j += 1
            data["agente_registrado"] = ", ".join(agent[:2])
            i = j; continue

        elif lower == "authorized person(s) detail":
            j = i + 1
            if j < len(lines) and lines[j].lower() == "name & address":
                j += 1
            while j < len(lines) and not is_section(lines[j]):
                raw = lines[j].replace("\xa0", " ")
                if raw.lower().startswith("title") and j + 1 < len(lines):
                    titulo = re.sub(r"(?i)^title\s*", "", raw).strip()
                    nombre = lines[j + 1]
                    addr   = lines[j + 2] if j + 2 < len(lines) else ""
                    if nombre and not is_section(nombre):
                        data["officers"].append({
                            "nombre":    nombre,
                            "titulo":    titulo,
                            "direccion": addr,
                        })
                    j += 3
                else:
                    j += 1
            i = j; continue

        i += 1

    return data


def get_fictitious_detail(detail_url: str, delay: float = 3.0) -> dict:
    """
    Extrae información de la página de detalle de nombre ficticio (DBA).
    Retorna el nombre del dueño y si es una entidad o persona física.
    """
    soup = _get(detail_url, delay=delay)
    if not soup:
        return {"error": "No se pudo acceder", "dueno": "", "dueno_es_entidad": False}

    lines = [l.strip() for l in soup.get_text(separator="\n").split("\n") if l.strip()]

    data = {
        "nombre_ficticio":  "",
        "dueno":            "",
        "dueno_es_entidad": False,
        "status":           "",
        "error":            None,
    }

    _FICT_SECTIONS = {
        "filing information", "owner information", "owner name & address",
        "document images", "annual reports", "return to list",
        "florida department of state", "division of corporations",
        "previous on list", "next on list", "fictitious name",
    }

    i = 0
    while i < len(lines):
        lower = lines[i].lower()

        if lower == "fictitious name" and i + 1 < len(lines):
            if lines[i + 1].lower() not in _FICT_SECTIONS:
                data["nombre_ficticio"] = lines[i + 1]

        elif lower == "status" and i + 1 < len(lines):
            val = lines[i + 1]
            if val.lower() not in _FICT_SECTIONS:
                data["status"] = val; i += 2; continue

        elif lower in ("owner information", "name & address", "owner name & address"):
            j = i + 1
            while j < len(lines) and lines[j].lower() in _FICT_SECTIONS:
                j += 1
            if j < len(lines):
                owner = lines[j]
                data["dueno"] = owner
                data["dueno_es_entidad"] = _is_entity_name(owner)
            i = j
            continue

        i += 1

    return data


# ── Función principal ─────────────────────────────────────────

def lookup_clinic(
    clinic_name: str,
    clinic_address: str = "",
    clinic_zip: str = "",
    clinic_phone: str = "",
    delay: float = 3.0,
) -> dict:
    """
    Busca una clínica en Sunbiz usando cuatro estrategias:
      1. Nombre de entidad exacto
      2. Officer/keyword del nombre
      3. Variantes del nombre (subconjuntos)
      4. Nombre ficticio / DBA

    Scoring: nombre 65% + ZIP 20% + dirección 15% + teléfono 10% (bonus).
    """
    MIN_SCORE = 0.35

    empty = {
        "nombre_legal":       "",
        "documento":          "",
        "status_legal":       "",
        "agente_registrado":  "",
        "dueno":              "",
        "dueno_titulo":       "",
        "officers":           [],
        "match_score":        0.0,
        "sunbiz_url":         "",
        "error":              None,
    }

    phone_digits = re.sub(r"\D", "", clinic_phone)[-10:] if clinic_phone else ""

    def _score_candidates(candidates: list) -> list:
        scored = []
        for c in candidates:
            if c.get("status", "").strip().lower() not in ("active", ""):
                continue
            name_sc = _name_score(clinic_name, c["nombre_legal"])
            if name_sc >= 0.20:
                scored.append((name_sc, c))
        return sorted(scored, key=lambda x: x[0], reverse=True)

    # ── Estrategia 1: nombre de entidad exacto ────────────────
    candidates = search_entity(clinic_name, delay=delay)
    scored = _score_candidates(candidates)

    # ── Estrategia 2: officer por keywords ────────────────────
    if not scored:
        keywords = [w for w in _normalize(clinic_name).split()
                    if w not in _GEO_TERMS and len(w) > 3]
        for kw in keywords[:2]:
            officer_candidates = search_by_officer(kw, delay=delay)
            officer_scored = _score_candidates(officer_candidates)
            officer_scored = [
                (sc, c) for sc, c in officer_scored
                if (clinic_zip and clinic_zip in c.get("detail_url", ""))
                or sc >= 0.40
            ]
            scored.extend(officer_scored)
        scored = sorted(scored, key=lambda x: x[0], reverse=True)

    # ── Estrategia 3: variantes del nombre ───────────────────
    if not scored:
        seen_urls = set()
        for variant in _name_variants(clinic_name):
            var_candidates = search_entity(variant, delay=delay)
            for sc, c in _score_candidates(var_candidates):
                url = c.get("detail_url", "")
                if url not in seen_urls:
                    seen_urls.add(url)
                    scored.append((sc, c))
        scored.sort(key=lambda x: x[0], reverse=True)

    # ── Estrategia 4: nombre ficticio / DBA ──────────────────
    if not scored:
        dba_candidates = search_fictitious_name(clinic_name, delay=delay)
        dba_scored = _score_candidates(dba_candidates)
        scored.extend(dba_scored[:3])
        scored.sort(key=lambda x: x[0], reverse=True)

    if not scored:
        empty["error"] = f"Sin entidad activa encontrada para '{clinic_name}'"
        return empty

    # ── Evalúa top 3 candidatos con scoring combinado ────────
    best_candidate = None
    best_score     = 0.0
    best_detail    = {}

    for name_sc, candidate in scored[:3]:

        if candidate.get("is_dba"):
            # DBA: obtener dueño del detalle ficticio
            fict = get_fictitious_detail(candidate["detail_url"], delay=delay)
            if fict.get("error") or not fict.get("dueno"):
                continue

            dueno_name = fict["dueno"]

            if fict["dueno_es_entidad"]:
                # El dueño es una LLC — buscarla para obtener officers
                entity_candidates = search_entity(dueno_name, delay=delay)
                if not entity_candidates:
                    continue
                detail = get_entity_detail(entity_candidates[0]["detail_url"], delay=delay)
                # Usar el nombre del DBA como nombre visible, el legal de la entidad
                if not detail.get("nombre_legal"):
                    detail["nombre_legal"] = dueno_name
            else:
                # El dueño es una persona física — construir detalle mínimo
                detail = {
                    "nombre_legal":         candidate["nombre_legal"],
                    "documento":            candidate["documento"],
                    "status_legal":         candidate.get("status", ""),
                    "agente_registrado":    "",
                    "direccion_registrada": "",
                    "officers": [{"nombre": dueno_name, "titulo": "OWNER", "direccion": ""}],
                    "phones":   [],
                    "error":    None,
                }
        else:
            detail = get_entity_detail(candidate["detail_url"], delay=delay)

        addr_block = detail.get("direccion_registrada", "")
        addr_sc    = _address_overlap(addr_block, clinic_address) if clinic_address else 0.0
        zip_sc     = 0.20 if _zip_match(addr_block, clinic_zip) else 0.0
        phone_sc   = 0.10 if (
            phone_digits and len(phone_digits) >= 10
            and phone_digits in detail.get("phones", [])
        ) else 0.0

        total = name_sc * 0.65 + zip_sc + addr_sc * 0.15 + phone_sc

        if total > best_score:
            best_score     = total
            best_candidate = candidate
            best_detail    = detail

    if not best_candidate or best_score < MIN_SCORE:
        empty["error"] = (
            f"Score {best_score:.2f} bajo umbral {MIN_SCORE} para '{clinic_name}'"
        )
        return empty

    # ── Officer principal ─────────────────────────────────────
    officers = best_detail.get("officers", [])
    primary  = None
    for priority in ("president", "manager", "director", "ceo", "owner", "member"):
        for o in officers:
            if priority in o.get("titulo", "").lower():
                primary = o
                break
        if primary:
            break
    if not primary and officers:
        primary = officers[0]

    return {
        "nombre_legal":       best_detail.get("nombre_legal") or best_candidate["nombre_legal"],
        "documento":          best_detail.get("documento") or best_candidate["documento"],
        "status_legal":       best_detail.get("status_legal") or best_candidate.get("status", ""),
        "agente_registrado":  best_detail.get("agente_registrado", ""),
        "dueno":              primary["nombre"] if primary else "",
        "dueno_titulo":       primary["titulo"] if primary else "",
        "officers":           officers,
        "match_score":        round(best_score, 2),
        "sunbiz_url":         best_candidate["detail_url"],
        "error":              None,
    }


if __name__ == "__main__":
    test_cases = [
        {
            "nombre":    "Brickell Dental Care",
            "direccion": "801 Brickell Key Blvd, Miami, FL 33131",
            "zip":       "33131",
            "telefono":  "(305) 374-1000",
        },
        {
            "nombre":    "Miami Dental Group",
            "direccion": "7950 NW 53rd St, Miami, FL 33166",
            "zip":       "33166",
            "telefono":  "",
        },
        {
            "nombre":    "Coral Gables Dentistry",
            "direccion": "169 Miracle Mile, Coral Gables, FL 33134",
            "zip":       "33134",
            "telefono":  "",
        },
    ]

    for tc in test_cases:
        print(f"\nBuscando: {tc['nombre']}")
        result = lookup_clinic(
            tc["nombre"], tc["direccion"], tc["zip"],
            clinic_phone=tc["telefono"], delay=3.0,
        )
        if result["error"]:
            print(f"  Sin datos: {result['error']}")
        else:
            print(f"  Entidad  : {result['nombre_legal']} ({result['status_legal']})")
            print(f"  Dueño    : {result['dueno']} — {result['dueno_titulo']}")
            print(f"  Agente   : {result['agente_registrado']}")
            print(f"  Score    : {result['match_score']}")
            print(f"  Link     : {result['sunbiz_url'][:80]}")
