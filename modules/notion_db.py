"""
Módulo Notion
Crea y gestiona la base de datos de prospectos.
"""

import os
import requests


NOTION_VERSION = "2022-06-28"
BASE_URL       = "https://api.notion.com/v1"

ETAPAS = ["No contactado", "En proceso", "Contactado", "Respondió"]

INVERSION_META = ["Sin anuncios", "Baja", "Media", "Alta"]


def _headers(token: str) -> dict:
    return {
        "Authorization":  f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type":   "application/json",
    }


# ── Estructura de la base de datos ───────────────────────────

DB_SCHEMA = {
    "Nombre":           {"title": {}},
    "Categoría":        {"select": {"options": [
        {"name": "dental",   "color": "blue"},
        {"name": "estetica", "color": "pink"},
        {"name": "medspa",   "color": "purple"},
        {"name": "wellness", "color": "green"},
    ]}},
    "Ciudad":           {"select": {"options": [
        {"name": "Miami",   "color": "yellow"},
        {"name": "Orlando", "color": "orange"},
        {"name": "Dallas",  "color": "red"},
    ]}},
    "Etapa":            {"select": {"options": [
        {"name": "No contactado", "color": "gray"},
        {"name": "En proceso",    "color": "yellow"},
        {"name": "Contactado",    "color": "blue"},
        {"name": "Respondió",     "color": "green"},
    ]}},
    "Inversión Meta":   {"select": {"options": [
        {"name": "Sin anuncios", "color": "gray"},
        {"name": "Baja",         "color": "yellow"},
        {"name": "Media",        "color": "orange"},
        {"name": "Alta",         "color": "red"},
    ]}},
    "Anuncios Activos": {"number": {"format": "number"}},
    "Rating":           {"number": {"format": "number"}},
    "Reviews":          {"number": {"format": "number"}},
    "Teléfono":         {"phone_number": {}},
    "Web":              {"url": {}},
    "Dirección":        {"rich_text": {}},
    "ZIP":              {"rich_text": {}},
    "Email Contacto":   {"email": {}},
    "Email Dueño":      {"email": {}},
    "Dueño / Manager":  {"rich_text": {}},
    "Entidad Legal":    {"rich_text": {}},
    "Google Maps":      {"url": {}},
    "Google Place ID":  {"rich_text": {}},
    "Página Facebook":  {"url": {}},
    "¿Corre Anuncios?": {"select": {"options": [
        {"name": "Sí",          "color": "green"},
        {"name": "No",          "color": "gray"},
        {"name": "Sin verificar","color": "yellow"},
    ]}},
    "Sunbiz URL":       {"url": {}},
    "Sunbiz Score":     {"number": {"format": "number"}},
    "Notas":            {"rich_text": {}},
    # ── Campaña de email ──────────────────────────────────────
    "Campaña Email":    {"select": {"options": [
        {"name": "No iniciada", "color": "gray"},
        {"name": "Activa",      "color": "green"},
        {"name": "Pausada",     "color": "yellow"},
        {"name": "Completada",  "color": "blue"},
        {"name": "Cancelada",   "color": "red"},
    ]}},
    "Email Etapa":      {"number": {"format": "number"}},
    "Email Enviados":   {"number": {"format": "number"}},
    "Email Abiertos":   {"number": {"format": "number"}},
    "Último Email":     {"date": {}},
    "Próximo Email":    {"date": {}},
}


# ── Crear página raíz y base de datos ────────────────────────

def create_database(token: str, parent_page_id: str) -> str:
    """Crea la base de datos de prospectos dentro de la página raíz."""
    payload = {
        "parent":     {"type": "page_id", "page_id": parent_page_id},
        "title":      [{"text": {"content": "Prospectos de Clínicas"}}],
        "icon":       {"type": "emoji", "emoji": "🏥"},
        "properties": DB_SCHEMA,
    }
    r = requests.post(f"{BASE_URL}/databases", headers=_headers(token), json=payload)
    if r.status_code != 200:
        raise RuntimeError(f"No se pudo crear base de datos: {r.json()}")
    return r.json()["id"]


def setup_notion(token: str, parent_page_id: str) -> str:
    """
    Crea la base de datos dentro de la página que el usuario compartió con la integración.
    Retorna el database_id listo para guardar en .env
    """
    print("Creando base de datos 'Prospectos de Clínicas'...")
    db_id = create_database(token, parent_page_id)
    print(f"  Base de datos creada: {db_id}")
    return db_id


# ── Operaciones sobre prospectos ─────────────────────────────

def ensure_db_schema(token: str, db_id: str) -> None:
    """Agrega columnas faltantes al schema de Notion sin tocar las existentes."""
    r = requests.get(f"{BASE_URL}/databases/{db_id}", headers=_headers(token))
    if r.status_code != 200:
        return
    existing = set(r.json().get("properties", {}).keys())
    missing  = {k: v for k, v in DB_SCHEMA.items() if k not in existing}
    if not missing:
        return
    print(f"  Agregando columnas faltantes: {list(missing.keys())}")
    requests.patch(
        f"{BASE_URL}/databases/{db_id}",
        headers=_headers(token),
        json={"properties": missing},
    )


def _find_clinic_page_id(token: str, db_id: str, google_place_id: str):
    """Retorna el page_id si la clínica ya existe, si no retorna None."""
    payload = {
        "filter": {
            "property": "Google Place ID",
            "rich_text": {"equals": google_place_id},
        }
    }
    r = requests.post(
        f"{BASE_URL}/databases/{db_id}/query",
        headers=_headers(token),
        json=payload,
    )
    if r.status_code != 200:
        return None
    results = r.json().get("results", [])
    return results[0]["id"] if results else None


def upsert_clinic(token: str, db_id: str, clinic: dict) -> dict:
    """
    Inserta o actualiza una clínica (por Google Place ID).
    - Si no existe: crea → action "created"
    - Si existe: actualiza con los datos nuevos (Sunbiz, Meta, etc.) → action "updated"
    Retorna: {"action": "created"|"updated"|"error", "id": str, "error": str}
    """
    place_id    = clinic.get("google_place_id", "")
    existing_id = _find_clinic_page_id(token, db_id, place_id) if place_id else None
    properties  = _build_properties(clinic)

    if existing_id:
        r = requests.patch(
            f"{BASE_URL}/pages/{existing_id}",
            headers=_headers(token),
            json={"properties": properties},
        )
        if r.status_code != 200:
            return {"action": "error", "id": None, "error": str(r.json())}
        return {"action": "updated", "id": existing_id, "error": None}

    payload = {"parent": {"database_id": db_id}, "properties": properties}
    r = requests.post(f"{BASE_URL}/pages", headers=_headers(token), json=payload)
    if r.status_code != 200:
        return {"action": "error", "id": None, "error": str(r.json())}
    return {"action": "created", "id": r.json()["id"], "error": None}


def update_clinic(token: str, page_id: str, fields: dict) -> bool:
    """Actualiza campos específicos de una clínica existente."""
    properties = _build_properties(fields)
    r = requests.patch(
        f"{BASE_URL}/pages/{page_id}",
        headers=_headers(token),
        json={"properties": properties},
    )
    return r.status_code == 200


def _build_properties(data: dict) -> dict:
    """Convierte un dict de datos de clínica al formato de propiedades de Notion."""
    props = {}

    def txt(val):
        return [{"text": {"content": str(val)[:2000]}}] if val else []

    if "nombre" in data and data["nombre"]:
        props["Nombre"] = {"title": txt(data["nombre"])}
    if "categoria" in data:
        props["Categoría"] = {"select": {"name": data["categoria"]}}
    if "ciudad" in data:
        props["Ciudad"] = {"select": {"name": data["ciudad"]}}
    if "etapa" in data:
        props["Etapa"] = {"select": {"name": data["etapa"]}}
    else:
        props["Etapa"] = {"select": {"name": "No contactado"}}
    if "inversion_meta" in data:
        props["Inversión Meta"] = {"select": {"name": data["inversion_meta"]}}
    if "anuncios_activos" in data and data["anuncios_activos"] != "":
        props["Anuncios Activos"] = {"number": int(data["anuncios_activos"])}
    if "rating" in data and data["rating"] != "":
        props["Rating"] = {"number": float(data["rating"])}
    if "reviews" in data and data["reviews"] != "":
        props["Reviews"] = {"number": int(data["reviews"])}
    if "telefono" in data and data["telefono"]:
        props["Teléfono"] = {"phone_number": data["telefono"]}
    if "web" in data and data["web"]:
        props["Web"] = {"url": data["web"]}
    if "direccion" in data:
        props["Dirección"] = {"rich_text": txt(data["direccion"])}
    if "zip" in data:
        props["ZIP"] = {"rich_text": txt(data["zip"])}
    if "email_contacto" in data and data["email_contacto"]:
        props["Email Contacto"] = {"email": data["email_contacto"]}
    if "email_dueno" in data and data["email_dueno"]:
        props["Email Dueño"] = {"email": data["email_dueno"]}
    if "dueno" in data:
        props["Dueño / Manager"] = {"rich_text": txt(data["dueno"])}
    if "entidad_legal" in data:
        props["Entidad Legal"] = {"rich_text": txt(data["entidad_legal"])}
    if "google_maps_url" in data and data["google_maps_url"]:
        props["Google Maps"] = {"url": data["google_maps_url"]}
    if "google_place_id" in data:
        props["Google Place ID"] = {"rich_text": txt(data["google_place_id"])}
    if "facebook_page" in data and data["facebook_page"]:
        props["Página Facebook"] = {"url": data["facebook_page"]}
    if "corre_anuncios" in data:
        val = data["corre_anuncios"]
        name = "Sí" if val is True else ("No" if val is False else "Sin verificar")
        props["¿Corre Anuncios?"] = {"select": {"name": name}}
    if "sunbiz_url" in data and data["sunbiz_url"]:
        props["Sunbiz URL"] = {"url": data["sunbiz_url"]}
    if "match_score" in data and data["match_score"]:
        props["Sunbiz Score"] = {"number": float(data["match_score"])}
    if "notas" in data:
        props["Notas"] = {"rich_text": txt(data["notas"])}

    # ── Campaña de email ──────────────────────────────────────
    if "campana_email" in data:
        props["Campaña Email"] = {"select": {"name": data["campana_email"]}}
    if "email_etapa" in data and data["email_etapa"] is not None:
        props["Email Etapa"] = {"number": int(data["email_etapa"])}
    if "email_enviados" in data and data["email_enviados"] is not None:
        props["Email Enviados"] = {"number": int(data["email_enviados"])}
    if "email_abiertos" in data and data["email_abiertos"] is not None:
        props["Email Abiertos"] = {"number": int(data["email_abiertos"])}
    if "ultimo_email" in data and data["ultimo_email"]:
        props["Último Email"] = {"date": {"start": data["ultimo_email"]}}
    if "proximo_email" in data and data["proximo_email"]:
        props["Próximo Email"] = {"date": {"start": data["proximo_email"]}}

    return props


def add_lead_from_instagram(username: str, full_name: str, comment: str,
                            post_id: str, source: str = "instagram_comment") -> str:
    """Creates a Notion lead row from an Instagram comment. Returns page ID."""
    import requests as _req
    from datetime import datetime

    token = os.getenv("NOTION_TOKEN", "")
    db_id = os.getenv("NOTION_DATABASE_ID", "")
    if not token or not db_id:
        raise ValueError("NOTION_TOKEN or NOTION_DATABASE_ID not set")

    note = f"IG @{username}: \"{comment}\" — post {post_id} — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
    payload = {
        "parent": {"database_id": db_id},
        "properties": {
            "Nombre": {"title": [{"text": {"content": full_name or f"@{username}"}}]},
            "Estado": {"select": {"name": "Nuevo"}},
            "Notas": {"rich_text": [{"text": {"content": note}}]},
        },
    }
    hdrs = {"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    r = _req.post("https://api.notion.com/v1/pages", headers=hdrs, json=payload, timeout=15)
    r.raise_for_status()
    return r.json().get("id", "")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    token = os.getenv("NOTION_TOKEN")
    db_id = os.getenv("NOTION_DATABASE_ID")

    parent_page_id = os.getenv("NOTION_PARENT_PAGE_ID", "")
    if not db_id:
        if not parent_page_id:
            print("Falta NOTION_PARENT_PAGE_ID en .env")
            print("Crea una página en Notion, compártela con la integración, y pega el ID aquí.")
        else:
            print("NOTION_DATABASE_ID vacío — creando base de datos...")
            db_id = setup_notion(token, parent_page_id)
            print(f"\nAgrega esto a tu .env:\nNOTION_DATABASE_ID={db_id}")
    else:
        print(f"Base de datos ya configurada: {db_id}")
