"""
Actualyza Prospecting — Dashboard
Sirve estadísticas en tiempo real desde Notion.
Uso: python3 dashboard/app.py
"""

import base64
import json
import os
import sys
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import requests as http

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, jsonify, render_template, request, Response
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

app = Flask(__name__, template_folder="templates")

NOTION_TOKEN    = os.getenv("NOTION_TOKEN", "")
NOTION_DB_ID    = os.getenv("NOTION_DATABASE_ID", "")
DASH_USER       = os.getenv("DASHBOARD_USER", "actualyza")
DASH_PASS       = os.getenv("DASHBOARD_PASS", "")
BUDGET_FILE     = Path(__file__).parent.parent / "data" / "api_usage.json"
LOG_FILE        = Path(__file__).parent.parent / "data" / "runs.log"


def _require_auth(f):
    """Protege rutas con HTTP Basic Auth cuando DASHBOARD_PASS está definida."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not DASH_PASS:
            return f(*args, **kwargs)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                user, pwd = base64.b64decode(auth[6:]).decode().split(":", 1)
                if user == DASH_USER and pwd == DASH_PASS:
                    return f(*args, **kwargs)
            except Exception:
                pass
        return Response(
            "Acceso restringido",
            401,
            {"WWW-Authenticate": 'Basic realm="Actualyza Dashboard"'},
        )
    return decorated

_cache: dict = {"data": None, "ts": 0.0}
CACHE_TTL = 300  # 5 minutos


# ── Notion helpers ────────────────────────────────────────────

def _prop(page: dict, name: str, kind: str):
    p = page.get("properties", {}).get(name, {})
    if kind == "title":
        items = p.get("title", [])
        return items[0]["plain_text"] if items else ""
    if kind == "select":
        s = p.get("select")
        return s["name"] if s else ""
    if kind == "number":
        return p.get("number") or 0
    if kind == "rich_text":
        items = p.get("rich_text", [])
        return items[0]["plain_text"] if items else ""
    if kind in ("url", "phone_number", "email"):
        return p.get(kind) or ""
    return ""


def fetch_clinics() -> list:
    headers = {
        "Authorization":  f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type":   "application/json",
    }
    results = []
    cursor  = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = http.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=headers,
            json=body,
        ).json()
        for page in resp.get("results", []):
            results.append({
                "nombre":    _prop(page, "Nombre",          "title"),
                "ciudad":    _prop(page, "Ciudad",          "select"),
                "categoria": _prop(page, "Categoría",       "select"),
                "etapa":     _prop(page, "Etapa",           "select"),
                "inversion": _prop(page, "Inversión Meta",  "select"),
                "anuncios":  _prop(page, "Anuncios Activos","number"),
                "rating":    _prop(page, "Rating",          "number"),
                "reviews":   _prop(page, "Reviews",         "number"),
                "telefono":  _prop(page, "Teléfono",        "phone_number"),
                "web":       _prop(page, "Web",             "url"),
                "dueno":     _prop(page, "Dueño / Manager", "rich_text"),
                "entidad":   _prop(page, "Entidad Legal",   "rich_text"),
                "sunbiz":    _prop(page, "Sunbiz URL",      "url"),
                "score":     _prop(page, "Sunbiz Score",    "number"),
                "maps":      _prop(page, "Google Maps",     "url"),
                "direccion": _prop(page, "Dirección",       "rich_text"),
                "zip":       _prop(page, "ZIP",             "rich_text"),
            })
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]
    return results


def get_clinics() -> list:
    global _cache
    now = time.time()
    if _cache["data"] is None or (now - _cache["ts"]) > CACHE_TTL:
        _cache["data"] = fetch_clinics()
        _cache["ts"]   = now
    return _cache["data"]


# ── Stats ─────────────────────────────────────────────────────

def compute_stats(clinics: list) -> dict:
    total = len(clinics)
    if not total:
        return {"total": 0}

    def count_by(field):
        d = {}
        for c in clinics:
            v = c.get(field, "") or "—"
            d[v] = d.get(v, 0) + 1
        return d

    por_ciudad    = count_by("ciudad")
    por_categoria = count_by("categoria")
    por_inversion = count_by("inversion")
    por_etapa     = count_by("etapa")

    con_dueno    = sum(1 for c in clinics if c["dueno"])
    alta_media   = (por_inversion.get("Alta", 0) + por_inversion.get("Media", 0))
    sin_contactar = por_etapa.get("No contactado", 0)

    ratings   = [c["rating"] for c in clinics if c["rating"]]
    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0

    # Top prospects: mayor inversión primero, luego rating
    _inv_order = {"Alta": 4, "Media": 3, "Baja": 2, "Sin anuncios": 1, "": 0}
    top = sorted(
        clinics,
        key=lambda c: (_inv_order.get(c["inversion"], 0), c["rating"]),
        reverse=True,
    )[:50]

    return {
        "total":          total,
        "con_dueno":      con_dueno,
        "pct_dueno":      round(con_dueno / total * 100) if total else 0,
        "alta_media":     alta_media,
        "sin_contactar":  sin_contactar,
        "avg_rating":     avg_rating,
        "por_ciudad":     por_ciudad,
        "por_categoria":  por_categoria,
        "por_inversion":  por_inversion,
        "por_etapa":      por_etapa,
        "top":            top,
    }


def get_budget() -> dict:
    defaults = {
        "google_places": int(os.getenv("GOOGLE_PLACES_MONTHLY_LIMIT", "3750")),
        "sunbiz":        int(os.getenv("SUNBIZ_MONTHLY_LIMIT",        "500")),
        "meta_scraping": int(os.getenv("META_SCRAPING_MONTHLY_LIMIT", "300")),
    }
    raw   = {}
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    if BUDGET_FILE.exists():
        try:
            raw = json.loads(BUDGET_FILE.read_text())
        except Exception:
            pass

    out = {}
    for service, limit in defaults.items():
        entry = raw.get(service, {})
        count = entry.get("count", 0) if entry.get("month") == month else 0
        out[service] = {
            "count":     count,
            "limit":     limit,
            "pct":       round(count / limit * 100, 1) if limit else 0,
            "remaining": max(0, limit - count),
        }
    return out


def get_log(n: int = 40) -> list:
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text().splitlines()
    return [l for l in reversed(lines) if l.strip()][:n]


# ── Routes ────────────────────────────────────────────────────

@app.route("/")
@_require_auth
def index():
    return render_template("index.html")

@app.route("/api/stats")
@_require_auth
def api_stats():
    clinics = get_clinics()
    return jsonify(compute_stats(clinics))

@app.route("/api/clinics")
@_require_auth
def api_clinics():
    return jsonify(get_clinics())

@app.route("/api/budget")
@_require_auth
def api_budget():
    return jsonify(get_budget())

@app.route("/api/log")
@_require_auth
def api_log():
    return jsonify(get_log())

@app.route("/api/refresh", methods=["POST"])
@_require_auth
def api_refresh():
    global _cache
    _cache = {"data": None, "ts": 0.0}
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5055))
    print()
    print("  ┌────────────────────────────────────────┐")
    print("  │  Actualyza Dashboard                   │")
    print(f"  │  http://localhost:{port}                 │")
    print("  └────────────────────────────────────────┘")
    print()
    app.run(host="0.0.0.0", port=port, debug=False)
