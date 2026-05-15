"""
Actualyza Prospecting — Dashboard
Sirve estadísticas en tiempo real desde Notion.
Uso: python3 dashboard/app.py
"""

import base64
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
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
NEXT_RUN_DAYS   = 7

_pipeline_state: dict = {
    "running":        False,
    "last_started":   None,
    "last_finished":  None,
    "error":          None,
}
_stop_requested: bool = False


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


def _completeness(c: dict) -> int:
    score = 0
    if c.get("telefono"):  score += 10
    if c.get("web"):       score += 10
    if c.get("email"):     score += 15
    if c.get("dueno"):     score += 20
    if c.get("entidad"):   score +=  5
    if c.get("sunbiz"):    score += 10
    if c.get("maps"):      score +=  5
    if c.get("direccion"): score +=  5
    if c.get("rating", 0) > 0: score += 10
    if c.get("inversion") not in ("", None): score += 10
    return min(100, score)


def _lead_score(c: dict) -> int:
    inv  = {"Alta": 40, "Media": 30, "Baja": 15, "Sin anuncios": 5}.get(c.get("inversion", ""), 0)
    own  = 25 if c.get("dueno") else 0
    cmp_ = round(c.get("completeness", 0) * 0.20)
    rat  = round(min(15.0, (c.get("rating", 0) / 5.0) * 15))
    return inv + own + cmp_ + rat


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
            c = {
                "nombre":      _prop(page, "Nombre",          "title"),
                "ciudad":      _prop(page, "Ciudad",          "select"),
                "categoria":   _prop(page, "Categoría",       "select"),
                "etapa":       _prop(page, "Etapa",           "select"),
                "inversion":   _prop(page, "Inversión Meta",  "select"),
                "anuncios":    _prop(page, "Anuncios Activos","number"),
                "rating":      _prop(page, "Rating",          "number"),
                "reviews":     _prop(page, "Reviews",         "number"),
                "telefono":    _prop(page, "Teléfono",        "phone_number"),
                "web":         _prop(page, "Web",             "url"),
                "dueno":       _prop(page, "Dueño / Manager", "rich_text"),
                "entidad":     _prop(page, "Entidad Legal",   "rich_text"),
                "sunbiz":      _prop(page, "Sunbiz URL",      "url"),
                "score":       _prop(page, "Sunbiz Score",    "number"),
                "maps":        _prop(page, "Google Maps",     "url"),
                "direccion":   _prop(page, "Dirección",       "rich_text"),
                "zip":         _prop(page, "ZIP",             "rich_text"),
                "email":       _prop(page, "Email Contacto",  "email"),
                "last_edited": page.get("last_edited_time", ""),
            }
            c["completeness"] = _completeness(c)
            c["lead_score"]   = _lead_score(c)
            results.append(c)
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

    con_dueno     = sum(1 for c in clinics if c["dueno"])
    con_email     = sum(1 for c in clinics if c.get("email"))
    alta_media    = (por_inversion.get("Alta", 0) + por_inversion.get("Media", 0))
    sin_contactar = por_etapa.get("No contactado", 0)

    ratings   = [c["rating"] for c in clinics if c["rating"]]
    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0

    completeness_vals = [c.get("completeness", 0) for c in clinics]
    avg_completeness  = round(sum(completeness_vals) / len(completeness_vals)) if completeness_vals else 0

    top = sorted(clinics, key=lambda c: c.get("lead_score", 0), reverse=True)[:50]

    return {
        "total":            total,
        "con_dueno":        con_dueno,
        "pct_dueno":        round(con_dueno / total * 100) if total else 0,
        "con_email":        con_email,
        "pct_email":        round(con_email / total * 100) if total else 0,
        "alta_media":       alta_media,
        "sin_contactar":    sin_contactar,
        "avg_rating":       avg_rating,
        "avg_completeness": avg_completeness,
        "por_ciudad":       por_ciudad,
        "por_categoria":    por_categoria,
        "por_inversion":    por_inversion,
        "por_etapa":        por_etapa,
        "top":              top,
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

@app.route("/api/pipeline")
@_require_auth
def api_pipeline():
    clinics  = get_clinics()
    times    = [c["last_edited"] for c in clinics if c.get("last_edited")]
    last_run = max(times) if times else None

    next_run_iso = None
    if last_run:
        try:
            last_dt      = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
            next_dt      = last_dt + timedelta(days=NEXT_RUN_DAYS)
            next_run_iso = next_dt.isoformat()
        except Exception:
            pass

    cities = ["Miami", "Orlando", "Dallas"]
    cats   = ["dental", "estetica", "medspa", "wellness"]
    segs   = {}
    for c in clinics:
        key = f"{c['ciudad']}/{c['categoria']}"
        segs[key] = segs.get(key, 0) + 1
    seg_done  = sum(1 for city in cities for cat in cats if segs.get(f"{city}/{cat}", 0) > 0)
    seg_total = len(cities) * len(cats)

    return jsonify({
        "last_run":  last_run,
        "next_run":  next_run_iso,
        "seg_done":  seg_done,
        "seg_total": seg_total,
        "segs":      segs,
    })


def _parse_run_progress() -> dict:
    start_iso = _pipeline_state.get("last_started", "")
    total     = int(os.getenv("MAX_CLINICS_PER_RUN", "20"))
    empty     = {"created": 0, "updated": 0, "errors": 0, "processed": 0, "segment": "", "total": total}
    if not start_iso or not LOG_FILE.exists():
        return empty
    try:
        start_dt = datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc)
    except Exception:
        return empty

    run_lines = []
    for raw in LOG_FILE.read_text().splitlines():
        if raw.startswith("[") and " UTC]" in raw:
            try:
                ts = datetime.strptime(raw[1:20], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if ts >= start_dt - timedelta(seconds=5):
                    run_lines.append(raw)
            except Exception:
                pass
        elif run_lines:
            run_lines.append(raw)

    created = sum(1 for l in run_lines if "  ✓ " in l)
    updated = sum(1 for l in run_lines if "  ↻ " in l)
    errors  = sum(1 for l in run_lines if "  ✗ " in l)

    segment = ""
    for l in reversed(run_lines):
        if "── " in l and " / " in l and "UTC" not in l:
            segment = l.replace("──", "").strip()
            break

    return {
        "created":   created,
        "updated":   updated,
        "errors":    errors,
        "processed": created + updated,
        "segment":   segment,
        "total":     total,
    }


def _run_pipeline_bg():
    global _pipeline_state, _cache, _stop_requested
    _stop_requested              = False
    _pipeline_state["running"]   = True
    _pipeline_state["last_started"]  = datetime.now(timezone.utc).isoformat()
    _pipeline_state["error"]         = None
    try:
        from pipeline.orchestrator import run_pipeline
        run_pipeline(stop_flag=lambda: _stop_requested)
        _cache = {"data": None, "ts": 0.0}
    except Exception as e:
        _pipeline_state["error"] = str(e)
    finally:
        _pipeline_state["running"]       = False
        _pipeline_state["last_finished"] = datetime.now(timezone.utc).isoformat()


@app.route("/api/run-pipeline", methods=["POST"])
@_require_auth
def api_run_pipeline():
    if _pipeline_state["running"]:
        return jsonify({"ok": False, "error": "Pipeline ya está corriendo"}), 409
    threading.Thread(target=_run_pipeline_bg, daemon=True).start()
    return jsonify({"ok": True, "status": "started"})


@app.route("/meta-token")
@_require_auth
def meta_token_page():
    return render_template("meta_token.html")


@app.route("/api/exchange-meta-token", methods=["POST"])
@_require_auth
def api_exchange_meta_token():
    short_token = (request.json or {}).get("token", "").strip()
    if not short_token:
        return jsonify({"ok": False, "error": "Token vacío"}), 400

    app_id     = os.getenv("META_APP_ID", "")
    app_secret = os.getenv("META_APP_SECRET", "")
    if not app_id or not app_secret:
        return jsonify({"ok": False, "error": "META_APP_ID o META_APP_SECRET no configurados"}), 500

    # Verificar que el token corto funciona
    verify = http.get(
        "https://graph.facebook.com/v21.0/ads_archive",
        params={
            "access_token":          short_token,
            "ad_reached_countries":  '["US"]',
            "ad_active_status":      "ACTIVE",
            "search_terms":          "test",
            "limit":                 1,
            "fields":                "id",
        },
        timeout=10,
    ).json()
    if "error" in verify:
        return jsonify({"ok": False, "error": verify["error"].get("message", "Token inválido")}), 400

    # Intercambiar por token de 60 días
    exchange = http.get(
        "https://graph.facebook.com/oauth/access_token",
        params={
            "grant_type":       "fb_exchange_token",
            "client_id":        app_id,
            "client_secret":    app_secret,
            "fb_exchange_token": short_token,
        },
        timeout=10,
    ).json()

    if "error" in exchange:
        return jsonify({"ok": False, "error": exchange["error"].get("message", "Error al intercambiar")}), 400

    long_token = exchange.get("access_token", "")
    expires_in = exchange.get("expires_in", 0)
    days = round(expires_in / 86400) if expires_in else 60

    return jsonify({"ok": True, "token": long_token, "days": days})


@app.route("/api/check-meta-token")
@_require_auth
def api_check_meta_token():
    token = os.getenv("META_USER_TOKEN", "")
    if not token:
        return jsonify({"ok": False, "status": "sin_token"})
    r = http.get(
        "https://graph.facebook.com/v21.0/ads_archive",
        params={
            "access_token": token, "ad_reached_countries": '["US"]',
            "ad_active_status": "ACTIVE", "search_terms": "test",
            "limit": 1, "fields": "id",
        },
        timeout=10,
    ).json()
    if "error" in r:
        msg = r["error"].get("message", "")
        return jsonify({"ok": False, "status": "expirado", "error": msg})
    return jsonify({"ok": True, "status": "activo"})


@app.route("/api/reset-progress", methods=["POST"])
@_require_auth
def api_reset_progress():
    PROGRESS_FILE = Path(__file__).parent.parent / "data" / "progress.json"
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
    return jsonify({"ok": True})


@app.route("/api/stop-pipeline", methods=["POST"])
@_require_auth
def api_stop_pipeline():
    global _stop_requested
    _stop_requested = True
    return jsonify({"ok": True})


@app.route("/api/pipeline-status")
@_require_auth
def api_pipeline_status():
    return jsonify({
        "running":        _pipeline_state["running"],
        "last_started":   _pipeline_state["last_started"],
        "last_finished":  _pipeline_state["last_finished"],
        "error":          _pipeline_state["error"],
        "progress":       _parse_run_progress() if _pipeline_state["running"] else {},
        "log":            get_log(20),
    })


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
