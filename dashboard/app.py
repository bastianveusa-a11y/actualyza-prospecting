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

# Force unbuffered stdout so logs appear immediately in Railway
sys.stdout.reconfigure(line_buffering=True)
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import quote_plus

import requests as http

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, jsonify, render_template, request, Response, redirect
from flask_sock import Sock
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

app = Flask(__name__, template_folder="templates")
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))
sock = Sock(app)

NOTION_TOKEN    = os.getenv("NOTION_TOKEN", "")
NOTION_DB_ID    = os.getenv("NOTION_DATABASE_ID", "")
DASH_USER       = os.getenv("DASHBOARD_USER", "actualyza")
DASH_PASS       = os.getenv("DASHBOARD_PASS", "")
REVIEWER_USER   = os.getenv("REVIEWER_USER", "")
REVIEWER_PASS   = os.getenv("REVIEWER_PASS", "")
BUDGET_FILE     = Path(__file__).parent.parent / "data" / "api_usage.json"
LOG_FILE        = Path(__file__).parent.parent / "data" / "runs.log"
ASSETS_FILE       = Path(__file__).parent.parent / "data" / "creative_assets.json"
APPROVALS_FILE    = Path(__file__).parent.parent / "data" / "creative_approvals.json"
NEXT_RUN_DAYS     = 7
CREATIVE_TTL_DAYS = 30

CATEGORIES = ["dental", "estetica", "medspa", "wellness"]
EMAIL_NUMS  = [2, 3]

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
                main_ok     = user == DASH_USER and pwd == DASH_PASS
                reviewer_ok = REVIEWER_USER and REVIEWER_PASS and user == REVIEWER_USER and pwd == REVIEWER_PASS
                if main_ok or reviewer_ok:
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
                "email":           _prop(page, "Email Contacto",   "email"),
                "facebook_page":   _prop(page, "Página Facebook",  "url"),
                "corre_anuncios":  _prop(page, "¿Corre Anuncios?", "select"),
                "campana_email":   _prop(page, "Campaña Email",    "select"),
                "email_etapa":     _prop(page, "Email Etapa",      "number"),
                "email_enviados":  _prop(page, "Email Enviados",   "number"),
                "email_abiertos":  _prop(page, "Email Abiertos",   "number"),
                "notion_id":       page["id"],
                "last_edited":     page.get("last_edited_time", ""),
            }
            # Link directo a Meta Ad Library para esta clínica
            fb = c["facebook_page"]
            if fb:
                slug = fb.rstrip('/').split('/')[-1].split('?')[0]
                c["meta_ads_url"] = (
                    f"https://www.facebook.com/ads/library/"
                    f"?active_status=active&ad_type=all&country=US"
                    f"&q={quote_plus(slug)}&search_type=page"
                )
            else:
                c["meta_ads_url"] = (
                    f"https://www.facebook.com/ads/library/"
                    f"?active_status=active&ad_type=all&country=US"
                    f"&q={quote_plus(c['nombre'])}&search_type=keyword_unordered"
                )
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
        "google_places":  int(os.getenv("GOOGLE_PLACES_MONTHLY_LIMIT", "3750")),
        "sunbiz":         int(os.getenv("SUNBIZ_MONTHLY_LIMIT",        "500")),
        "meta_scraping":  int(os.getenv("META_SCRAPING_MONTHLY_LIMIT", "300")),
        "claude_emails":  int(os.getenv("CLAUDE_MONTHLY_LIMIT",        "500")),
        "resend_emails":  int(os.getenv("RESEND_MONTHLY_LIMIT",        "2800")),
        "flux_images":    int(os.getenv("FLUX_MONTHLY_LIMIT",          "100")),
    }
    # Metadata por servicio: icono, nota de costo/plan, si tiene costo real
    meta = {
        "google_places":  {"icon": "🗺",  "label": "Google Places",   "note": "$200 crédito/mes",       "paid": True},
        "sunbiz":         {"icon": "⚖️",  "label": "Sunbiz",           "note": "sin costo",              "paid": False},
        "meta_scraping":  {"icon": "📢", "label": "Meta Scraping",    "note": "sin costo",              "paid": False},
        "claude_emails":  {"icon": "🤖", "label": "Claude (emails)",  "note": "~$0.002 por email",      "paid": True},
        "resend_emails":  {"icon": "📨", "label": "Resend",           "note": "3,000 gratis/mes",       "paid": False},
        "flux_images":    {"icon": "🎨", "label": "Flux (imágenes)",  "note": "~$0.004 por imagen",     "paid": True},
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
            **meta.get(service, {}),
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
    _stop_requested                  = False
    _pipeline_state["running"]       = True
    _pipeline_state["last_started"]  = datetime.now(timezone.utc).isoformat()
    _pipeline_state["error"]         = None
    targets = _pipeline_state.get("targets")
    try:
        from pipeline.orchestrator import run_pipeline
        run_pipeline(stop_flag=lambda: _stop_requested, targets=targets)
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
    _pipeline_state["targets"] = (request.json or {}).get("targets") or None
    threading.Thread(target=_run_pipeline_bg, daemon=True).start()
    return jsonify({"ok": True, "status": "started"})


@app.route("/api/available-cities")
@_require_auth
def api_available_cities():
    from modules.google_places import AVAILABLE_CITIES, CATEGORIES
    return jsonify({
        "cities":     AVAILABLE_CITIES,
        "categories": [{"key": k, "label": v.title()} for k, v in CATEGORIES.items()],
    })


@app.route("/campaigns")
@_require_auth
def campaigns_page():
    return render_template("campaigns.html")


@app.route("/creatives")
@_require_auth
def creatives_page():
    return render_template("creatives.html")


@app.route("/preview")
@_require_auth
def preview_page():
    return render_template("preview.html")


@app.route("/api/notifications")
@_require_auth
def api_notifications():
    return jsonify({"ok": True, "notifications": _get_notifications()})


@app.route("/api/notifications/dismiss", methods=["POST"])
@_require_auth
def api_notifications_dismiss():
    # Client-side only — notifications re-appear on next page load if condition persists
    return jsonify({"ok": True})


@app.route("/api/creatives/status")
@_require_auth
def api_creatives_status():
    approvals = _load_approvals()
    result = {}
    now = datetime.now(timezone.utc)
    for cat in CATEGORIES:
        for num in EMAIL_NUMS:
            key = f"{cat}_{num}"
            entry = approvals.get(key, {})
            days_since = None
            if entry.get("approved_at"):
                try:
                    approved_at = datetime.fromisoformat(entry["approved_at"])
                    if approved_at.tzinfo is None:
                        approved_at = approved_at.replace(tzinfo=timezone.utc)
                    days_since = (now - approved_at).days
                except Exception:
                    pass
            result[key] = {
                "a":          entry.get("a"),
                "b":          entry.get("b"),
                "approved":   entry.get("approved"),
                "approved_url": entry.get("approved_url"),
                "approved_at":  entry.get("approved_at"),
                "days_since": days_since,
                "overdue":    days_since is not None and days_since >= CREATIVE_TTL_DAYS,
                "generating": entry.get("generating", False),
                "error":      entry.get("error"),
            }
    return jsonify({"ok": True, "creatives": result, "ttl_days": CREATIVE_TTL_DAYS})


@app.route("/api/creatives/generate/<cat>/<int:num>", methods=["POST"])
@_require_auth
def api_creatives_generate(cat, num):
    if cat not in CATEGORIES or num not in EMAIL_NUMS:
        return jsonify({"ok": False, "error": "Categoría o email_num inválido"}), 400
    _generate_two_options_bg(cat, num)
    return jsonify({"ok": True, "message": f"Generando opciones para {cat}_e{num}…"})


@app.route("/api/creatives/generate-all", methods=["POST"])
@_require_auth
def api_creatives_generate_all():
    """Un solo thread secuencial para evitar rate-limit 429 en Replicate."""
    import threading
    def _run_all():
        cases = [(cat, num) for cat in CATEGORIES for num in EMAIL_NUMS]
        for cat, num in cases:
            key = f"{cat}_{num}"
            _update_approval_key(key, {"generating": True, "error": None})
        for cat, num in cases:
            key = f"{cat}_{num}"
            print(f"  ⟳ [generate-all] Procesando {key}…", flush=True)
            import traceback
            from modules.image_gen import generate_background
            from modules.canva_api import is_authorized, upload_asset_binary
            try:
                flux_url = generate_background(cat, num)
                print(f"  ✓ [{key}] Flux OK", flush=True)
                canva_ok = is_authorized()
                for style in ("a", "b"):
                    composed = _compose(flux_url, cat, num, style)
                    print(f"  ✓ [{key}] Render {style.upper()} OK ({len(composed)//1024}KB)", flush=True)
                    if canva_ok:
                        url = upload_asset_binary(composed, name=f"amy-{cat}-e{num}-{style}")
                    else:
                        cache_key = f"{key}_{style}"
                        _image_cache[cache_key] = composed
                        url = f"/api/creative-image/{cache_key}"
                    _update_approval_key(key, {style: {"url": url, "generated_at": datetime.now(timezone.utc).isoformat()}})
                _update_approval_key(key, {"generating": False, "error": None})
                print(f"  ✓ [{key}] Completado", flush=True)
            except Exception as e:
                print(f"  ✗ [{key}] Error: {e}\n{traceback.format_exc()}", flush=True)
                _update_approval_key(key, {"generating": False, "error": str(e)})
    threading.Thread(target=_run_all, daemon=True).start()
    return jsonify({"ok": True, "message": "Generando todas las opciones en background (secuencial)…"})


@app.route("/api/creatives/approve/<cat>/<int:num>", methods=["POST"])
@_require_auth
def api_creatives_approve(cat, num):
    if cat not in CATEGORIES or num not in EMAIL_NUMS:
        return jsonify({"ok": False, "error": "Categoría o email_num inválido"}), 400
    data   = request.json or {}
    option = data.get("option", "").lower()
    if option not in ("a", "b"):
        return jsonify({"ok": False, "error": "option debe ser 'a' o 'b'"}), 400
    approvals = _load_approvals()
    key   = f"{cat}_{num}"
    entry = approvals.setdefault(key, {})
    opt   = entry.get(option)
    if not opt or not opt.get("url"):
        return jsonify({"ok": False, "error": f"Opción {option.upper()} no generada aún"}), 400
    # Guardar en historial
    if entry.get("approved_url"):
        history = entry.get("history", [])
        history.append({
            "option":      entry.get("approved"),
            "url":         entry["approved_url"],
            "approved_at": entry.get("approved_at"),
        })
        entry["history"] = history[-10:]  # keep last 10
    entry["approved"]     = option
    entry["approved_url"] = opt["url"]
    entry["approved_at"]  = datetime.now(timezone.utc).isoformat()
    _save_approvals(approvals)
    # Sync al asset store que usan los emails
    assets = _load_assets()
    assets[key] = opt["url"]
    _save_assets(assets)
    return jsonify({"ok": True, "approved_url": opt["url"]})


@app.route("/api/preview-email", methods=["POST"])
@_require_auth
def api_preview_email():
    data         = request.json or {}
    page_id      = data.get("notion_id", "").strip()
    email_num    = int(data.get("email_num", 1))
    prev_opened  = bool(data.get("previous_opened", False))
    if not page_id:
        return jsonify({"ok": False, "error": "notion_id requerido"}), 400
    clinics = get_clinics()
    clinic  = next((c for c in clinics if c["notion_id"] == page_id), None)
    if not clinic:
        return jsonify({"ok": False, "error": "Clínica no encontrada"}), 404
    try:
        from modules.claude_writer import write_email
        generated = write_email(clinic, email_num=email_num, previous_opened=prev_opened)
        return jsonify({"ok": True, **generated})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/enable-group", methods=["POST"])
@_require_auth
def api_enable_group():
    global _cache
    data     = request.json or {}
    city     = data.get("city", "").strip()
    category = data.get("category", "").strip()
    if not city or not category:
        return jsonify({"ok": False, "error": "city y category requeridos"}), 400

    clinics  = get_clinics()
    eligible = [
        c for c in clinics
        if c["ciudad"] == city
        and c["categoria"] == category
        and c.get("email")
        and (not c.get("campana_email") or c.get("campana_email") == "No iniciada")
    ]
    if not eligible:
        return jsonify({"ok": True, "enabled": 0, "total": 0})

    from modules.claude_writer import write_email
    from modules.email_sender  import send_campaign_email
    from datetime import date, timedelta

    enabled, errors = 0, []
    for clinic in eligible:
        try:
            gen    = write_email(clinic, email_num=1)
            result = send_campaign_email(
                to_email  = clinic["email"],
                subject   = gen["subject"],
                body_html = gen["body_html"],
                body_text = gen["body_text"],
                notion_id = clinic["notion_id"],
                email_num = 1,
            )
            if result["ok"]:
                hoy     = date.today().isoformat()
                proximo = (date.today() + timedelta(days=3)).isoformat()
                _notion_patch(clinic["notion_id"], {
                    "Campaña Email":  {"select": {"name": "Activa"}},
                    "Email Etapa":    {"number": 1},
                    "Email Enviados": {"number": 1},
                    "Último Email":   {"date":   {"start": hoy}},
                    "Próximo Email":  {"date":   {"start": proximo}},
                })
                enabled += 1
            else:
                errors.append({"clinic": clinic["nombre"], "error": result["error"]})
        except Exception as e:
            errors.append({"clinic": clinic["nombre"], "error": str(e)})

    _cache = {"data": None, "ts": 0.0}
    return jsonify({"ok": True, "enabled": enabled, "total": len(eligible), "errors": errors})


@app.route("/api/generate-creative", methods=["POST"])
@_require_auth
def api_generate_creative():
    """
    Genera un creativo completo: Flux (fondo) → Canva (composición) → PNG final.
    Si Canva no está autorizado, retorna solo la imagen Flux como fallback.
    Body: { "categoria": str, "email_num": int }
    """
    data      = request.json or {}
    categoria = data.get("categoria", "dental").strip()
    email_num = int(data.get("email_num", 2))

    try:
        from modules.api_budget import increment
        increment("flux_images", 1)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 429

    try:
        from modules.image_gen import generate_background, compose_creative
        from modules.canva_api import is_authorized, upload_asset_binary

        flux_url = generate_background(categoria, email_num)
        composed = compose_creative(flux_url, categoria, email_num)

        if is_authorized():
            try:
                final_url = upload_asset_binary(composed, name=f"amy-ai-{categoria}-e{email_num}")
                return jsonify({"ok": True, "image_url": final_url, "source": "canva"})
            except Exception as canva_err:
                pass  # fallback a local

        # Fallback: servir desde Flask static
        static_path = Path(__file__).parent / "static" / "img" / "creatives"
        static_path.mkdir(parents=True, exist_ok=True)
        (static_path / f"{categoria}_{email_num}.jpg").write_bytes(composed)
        return jsonify({"ok": True, "image_url": f"/static/img/creatives/{categoria}_{email_num}.jpg", "source": "local"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Creative assets (persistidos en Notion, refresh mensual) ──────────────────

_NOTION_ASSETS_PAGE_TITLE  = "actualyza-creative-assets-config"
_CANVA_TOKEN_NOTION_TITLE  = "actualyza-canva-token-config"
_ASSETS_MAX_AGE_DAYS       = 30


def _backup_canva_token() -> None:
    """Guarda el token de Canva en Notion para sobrevivir redeploys de Railway."""
    from modules.canva_api import TOKEN_FILE
    if not TOKEN_FILE.exists():
        return
    try:
        content = TOKEN_FILE.read_text()
        hdrs = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
        r = http.post("https://api.notion.com/v1/search", headers=hdrs,
                      json={"query": _CANVA_TOKEN_NOTION_TITLE, "filter": {"value": "page", "property": "object"}},
                      timeout=10)
        for result in r.json().get("results", []):
            t = result.get("properties", {}).get("title", {}).get("title", [])
            if t and _CANVA_TOKEN_NOTION_TITLE in t[0].get("plain_text", ""):
                blocks = http.get(f"https://api.notion.com/v1/blocks/{result['id']}/children",
                                  headers=hdrs, timeout=10).json().get("results", [])
                for block in blocks:
                    if block.get("type") == "code":
                        http.patch(f"https://api.notion.com/v1/blocks/{block['id']}",
                                   headers=hdrs, timeout=10,
                                   json={"code": {"rich_text": [{"type": "text", "text": {"content": content}}], "language": "json"}})
                        return
                return
        http.post("https://api.notion.com/v1/pages", headers=hdrs, timeout=10,
                  json={"parent": {"type": "workspace", "workspace": True},
                        "properties": {"title": {"title": [{"text": {"content": _CANVA_TOKEN_NOTION_TITLE}}]}},
                        "children": [{"object": "block", "type": "code",
                                      "code": {"rich_text": [{"type": "text", "text": {"content": content}}], "language": "json"}}]})
    except Exception as e:
        print(f"  ⚠ No se pudo respaldar token Canva: {e}")


def _restore_canva_token() -> None:
    """Restaura token de Canva desde Notion si el archivo local no existe (redeploy)."""
    from modules.canva_api import TOKEN_FILE
    if TOKEN_FILE.exists():
        return
    try:
        hdrs = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
        r = http.post("https://api.notion.com/v1/search", headers=hdrs,
                      json={"query": _CANVA_TOKEN_NOTION_TITLE, "filter": {"value": "page", "property": "object"}},
                      timeout=10)
        for result in r.json().get("results", []):
            t = result.get("properties", {}).get("title", {}).get("title", [])
            if t and _CANVA_TOKEN_NOTION_TITLE in t[0].get("plain_text", ""):
                blocks = http.get(f"https://api.notion.com/v1/blocks/{result['id']}/children",
                                  headers={k: v for k, v in hdrs.items() if k != "Content-Type"},
                                  timeout=10).json().get("results", [])
                for block in blocks:
                    if block.get("type") == "code":
                        text = block["code"]["rich_text"]
                        if text:
                            TOKEN_FILE.parent.mkdir(exist_ok=True)
                            TOKEN_FILE.write_text(text[0]["plain_text"])
                            print("  ✓ Token Canva restaurado desde Notion")
                            return
    except Exception as e:
        print(f"  ⚠ No se pudo restaurar token Canva: {e}")

def _notion_get_assets_page() -> dict | None:
    """Busca la página de config de assets en Notion."""
    try:
        r = http.post(
            "https://api.notion.com/v1/search",
            headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"},
            json={"query": _NOTION_ASSETS_PAGE_TITLE, "filter": {"value": "page", "property": "object"}},
            timeout=10,
        )
        for result in r.json().get("results", []):
            title = result.get("properties", {}).get("title", {}).get("title", [])
            if title and _NOTION_ASSETS_PAGE_TITLE in (title[0].get("plain_text", "")):
                return result
    except Exception:
        pass
    return None


def _load_assets() -> dict:
    """Carga assets desde Notion (fuente de verdad) con fallback a archivo local."""
    # 1. Intentar desde Notion
    try:
        page = _notion_get_assets_page()
        if page:
            # El contenido JSON está en el primer bloque de código de la página
            blocks = http.get(
                f"https://api.notion.com/v1/blocks/{page['id']}/children",
                headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28"},
                timeout=10,
            ).json().get("results", [])
            for block in blocks:
                if block.get("type") == "code":
                    text = block["code"]["rich_text"]
                    if text:
                        data = json.loads(text[0]["plain_text"])
                        # Cache local para evitar llamadas repetidas
                        _save_local_assets(data)
                        return data
    except Exception:
        pass
    # 2. Fallback al archivo local
    if ASSETS_FILE.exists():
        try:
            return json.loads(ASSETS_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_local_assets(data: dict) -> None:
    ASSETS_FILE.parent.mkdir(exist_ok=True)
    ASSETS_FILE.write_text(json.dumps(data, indent=2))


def _save_assets(data: dict) -> None:
    """Guarda assets en Notion (persistente) y localmente (cache)."""
    import datetime
    data["_saved_at"] = datetime.datetime.utcnow().isoformat()
    _save_local_assets(data)
    # Guardar en Notion
    try:
        content_json      = json.dumps(data, indent=2)
        page = _notion_get_assets_page()
        if page:
            # Actualizar bloque de código existente
            blocks = http.get(
                f"https://api.notion.com/v1/blocks/{page['id']}/children",
                headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28"},
                timeout=10,
            ).json().get("results", [])
            for block in blocks:
                if block.get("type") == "code":
                    http.patch(
                        f"https://api.notion.com/v1/blocks/{block['id']}",
                        headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"},
                        json={"code": {"rich_text": [{"type": "text", "text": {"content": content_json}}], "language": "json"}},
                        timeout=10,
                    )
                    return
        # Crear página nueva si no existe (workspace root, no en la DB de clínicas)
        http.post(
            "https://api.notion.com/v1/pages",
            headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"},
            json={
                "parent":     {"type": "workspace", "workspace": True},
                "properties": {"title": {"title": [{"text": {"content": _NOTION_ASSETS_PAGE_TITLE}}]}},
                "children": [{
                    "object": "block", "type": "code",
                    "code": {"rich_text": [{"type": "text", "text": {"content": content_json}}], "language": "json"},
                }],
            },
            timeout=10,
        )
    except Exception as e:
        print(f"  ⚠ No se pudo guardar assets en Notion: {e}")


def _assets_need_refresh(assets: dict) -> bool:
    """Retorna True si los assets faltan o tienen más de 30 días."""
    import datetime
    all_keys = {f"{c}_{n}" for c in CATEGORIES for n in EMAIL_NUMS}
    if not all_keys.issubset(assets.keys()):
        return True
    saved_at = assets.get("_saved_at")
    if not saved_at:
        return True
    age = datetime.datetime.utcnow() - datetime.datetime.fromisoformat(saved_at)
    return age.days >= _ASSETS_MAX_AGE_DAYS


def _load_approvals() -> dict:
    if APPROVALS_FILE.exists():
        try:
            return json.loads(APPROVALS_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_approvals(data: dict) -> None:
    APPROVALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    APPROVALS_FILE.write_text(json.dumps(data, indent=2, default=str))


def _get_notifications() -> list:
    """Retorna notificaciones activas: creativos por renovar, errores de pipeline, etc."""
    notes = []
    approvals = _load_approvals()
    now = datetime.now(timezone.utc)

    overdue, pending = [], []
    for cat in CATEGORIES:
        for num in EMAIL_NUMS:
            key = f"{cat}_{num}"
            entry = approvals.get(key, {})
            if not entry.get("approved_at"):
                pending.append(key)
            else:
                approved_at = datetime.fromisoformat(entry["approved_at"])
                if approved_at.tzinfo is None:
                    approved_at = approved_at.replace(tzinfo=timezone.utc)
                if (now - approved_at).days >= CREATIVE_TTL_DAYS:
                    overdue.append(key)

    if overdue:
        notes.append({
            "id":      "creative_refresh",
            "type":    "warning",
            "title":   f"{len(overdue)} creativo{'s' if len(overdue)>1 else ''} necesita{'n' if len(overdue)>1 else ''} renovación",
            "body":    "Han pasado 30 días. Aprueba nuevas opciones o se reutilizarán los anteriores.",
            "action":  "/creatives",
            "action_label": "Ver creativos",
        })
    if pending:
        notes.append({
            "id":      "creative_pending",
            "type":    "info",
            "title":   f"{len(pending)} creativo{'s' if len(pending)>1 else ''} sin aprobar",
            "body":    "Genera y aprueba opciones para usar en los emails.",
            "action":  "/creatives",
            "action_label": "Ir a creativos",
        })
    if _pipeline_state.get("error"):
        notes.append({
            "id":      "pipeline_error",
            "type":    "error",
            "title":   "Error en el pipeline",
            "body":    str(_pipeline_state["error"])[:120],
            "action":  None,
            "action_label": None,
        })
    return notes


_approvals_lock = __import__("threading").Lock()


def _update_approval_key(key: str, updates: dict) -> None:
    """Lee, actualiza solo el key indicado y guarda — protegido con lock."""
    with _approvals_lock:
        data = _load_approvals()
        entry = data.setdefault(key, {})
        entry.update(updates)
        _save_approvals(data)


def _compose(flux_url: str, cat: str, num: int, style: str) -> bytes:
    """Renderiza creativo: Playwright si disponible, Pillow como fallback."""
    try:
        from modules.html_creative import render_creative
        return render_creative(flux_url, cat, num, style)
    except Exception:
        from modules.image_gen import compose_creative
        return compose_creative(flux_url, cat, num, style)


def _generate_two_options_bg(cat: str, num: int):
    """Genera 2 opciones de creativo (estilos A y B) para un caso en background."""
    import threading
    def _run():
        import traceback
        from modules.image_gen import generate_background
        from modules.canva_api import is_authorized, upload_asset_binary
        key = f"{cat}_{num}"
        _update_approval_key(key, {"generating": True, "error": None})
        print(f"  ⟳ [{key}] Iniciando generación A+B…", flush=True)
        try:
            flux_url = generate_background(cat, num)
            print(f"  ✓ [{key}] Flux OK: {flux_url[:60]}…", flush=True)
            canva_ok = is_authorized()
            for style in ("a", "b"):
                composed = _compose(flux_url, cat, num, style)
                print(f"  ✓ [{key}] Render {style.upper()} OK ({len(composed)//1024}KB)", flush=True)
                if canva_ok:
                    url = upload_asset_binary(composed, name=f"amy-{cat}-e{num}-{style}")
                    print(f"  ✓ [{key}] Canva {style.upper()}: {url[:60]}…", flush=True)
                else:
                    cache_key = f"{key}_{style}"
                    _image_cache[cache_key] = composed
                    url = f"/api/creative-image/{cache_key}"
                    print(f"  ⚠ [{key}] Cache {style.upper()}: {url}", flush=True)
                _update_approval_key(key, {style: {"url": url, "generated_at": datetime.now(timezone.utc).isoformat()}})
            print(f"  ✓ [{key}] Completado", flush=True)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"  ✗ [{key}] Error: {e}\n{tb}", flush=True)
            _update_approval_key(key, {"error": str(e)})
        finally:
            _update_approval_key(key, {"generating": False})
    threading.Thread(target=_run, daemon=True).start()


def _generate_all_assets_bg(force: bool = False):
    """
    Genera los 8 creativos en background.
    Solo genera si faltan o tienen más de 30 días (a menos que force=True).
    """
    import threading
    def _run():
        existing = _load_assets()
        if not force and not _assets_need_refresh(existing):
            print("  ✓ Creativos vigentes — próximo refresh en menos de 30 días")
            return
        print("  ⟳ Generando creativos (Flux + Canva)…")
        for cat in CATEGORIES:
            for num in EMAIL_NUMS:
                key = f"{cat}_{num}"
                if not force and key in existing and existing.get("_saved_at"):
                    continue
                try:
                    from modules.image_gen  import generate_background
                    from modules.api_budget import increment
                    increment("flux_images", 1)
                    print(f"  ⟳ Generando background Flux para {key}…", flush=True)
                    img_url = generate_background(cat, num)
                    print(f"  ✓ Flux OK para {key}: {img_url[:60]}…", flush=True)
                    try:
                        from modules.image_gen import compose_creative
                        from modules.canva_api import is_authorized, upload_asset_binary
                        composed = compose_creative(img_url, cat, num)
                        print(f"  ✓ Composición OK para {key} ({len(composed)/1024:.0f}KB)", flush=True)
                        if is_authorized():
                            print(f"  ⟳ Subiendo a Canva…", flush=True)
                            canva_url = upload_asset_binary(composed, name=f"amy-ai-{cat}-e{num}")
                            img_url   = canva_url
                            print(f"  ✓ Canva OK para {key}: {canva_url[:60]}…", flush=True)
                        else:
                            # Sin Canva: guardar en memoria y servir desde Flask con URL estable
                            print(f"  ⚠ Canva no autorizado — guardando en cache interno", flush=True)
                            _image_cache[key] = composed
                            img_url = f"/api/creative-image/{key}"
                    except Exception as ce:
                        print(f"  ✗ Composición/Canva falló para {key}: {ce}", flush=True)
                    existing[key] = img_url
                    _save_assets(existing)
                    print(f"  ✓ {key} guardado → {img_url[:60]}", flush=True)
                except Exception as e:
                    print(f"  ✗ Error {key}: {e}")
    threading.Thread(target=_run, daemon=True).start()


@app.route("/api/creative-assets")
@_require_auth
def api_creative_assets():
    """Retorna las URLs de creativos generados por categoría."""
    assets = _load_assets()
    # Estructura: { "dental": {"2": url, "3": url}, ... }
    result = {}
    for cat in CATEGORIES:
        result[cat] = {}
        for num in EMAIL_NUMS:
            key = f"{cat}_{num}"
            if key in assets:
                result[cat][str(num)] = assets[key]
    return jsonify({"ok": True, "assets": result})


@app.route("/api/creative-test")
@_require_auth
def api_creative_test():
    """Genera UN creativo (dental_2) en tiempo real y devuelve resultado o error."""
    import traceback
    try:
        from modules.image_gen import generate_background, compose_creative
        step = "flux"
        img_url = generate_background("dental", 2)
        step = "compose"
        composed = compose_creative(img_url, "dental", 2)
        step = "canva"
        from modules.canva_api import is_authorized, upload_asset_binary
        if is_authorized():
            canva_url = upload_asset_binary(composed, name="amy-ai-dental-e2-test")
            return jsonify({"ok": True, "step": "done", "url": canva_url, "flux_url": img_url})
        return jsonify({"ok": True, "step": "done_no_canva", "flux_url": img_url, "composed_kb": len(composed)//1024})
    except Exception as e:
        return jsonify({"ok": False, "step": step, "error": str(e), "trace": traceback.format_exc()})


@app.route("/api/creative-render")
@_require_auth
def api_creative_render():
    """
    Renderiza un creativo con Playwright (HTML→JPEG) usando flux_url existente.
    Fallback a Pillow si Playwright no está disponible.
    Params: flux_url, cat (default dental), num (default 2), style (default a)
    """
    import traceback
    flux_url = request.args.get("flux_url", "")
    cat      = request.args.get("cat", "dental")
    num      = int(request.args.get("num", "2"))
    style    = request.args.get("style", "a")
    if not flux_url:
        return Response("flux_url param required", 400)
    try:
        try:
            from modules.html_creative import render_creative
            jpeg = render_creative(flux_url, cat, num, style)
        except Exception:
            from modules.image_gen import compose_creative
            jpeg = compose_creative(flux_url, cat, num, style)
        return Response(jpeg, mimetype="image/jpeg")
    except Exception as e:
        return Response(f"Error: {e}\n{traceback.format_exc()}", 500)


@app.route("/api/creative-image/<key>")
def api_creative_image(key):
    """Sirve imagen compuesta desde cache en memoria (fallback sin Canva)."""
    img = _image_cache.get(key)
    if not img:
        return Response("Not found", 404)
    return Response(img, mimetype="image/jpeg")


@app.route("/api/regenerate-assets", methods=["POST"])
@_require_auth
def api_regenerate_assets():
    _generate_all_assets_bg(force=True)
    return jsonify({"ok": True, "message": "Regenerando en background…"})


@app.route("/api/creative-status")
@_require_auth
def api_creative_status():
    """Diagnóstico: muestra qué assets existen, si Canva está activo, y si hay errores."""
    from modules.canva_api import is_authorized
    assets   = _load_assets()
    canva_ok = is_authorized()
    keys     = {f"{c}_{n}" for c in CATEGORIES for n in EMAIL_NUMS}
    present  = {k: assets[k] for k in keys if k in assets}
    missing  = [k for k in keys if k not in assets]
    return jsonify({
        "canva_authorized": canva_ok,
        "notion_token_set": bool(NOTION_TOKEN),
        "replicate_key_set": bool(os.getenv("REPLICATE_API_TOKEN") or os.getenv("REPLICATE_API_KEY")),
        "assets_saved_at": assets.get("_saved_at"),
        "assets_present": present,
        "assets_missing": missing,
        "local_file_exists": ASSETS_FILE.exists(),
    })


# ── Canva OAuth ───────────────────────────────────────────────────────────────

@app.route("/oauth/canva")
@_require_auth
def canva_oauth_start():
    """Inicia el flujo OAuth con PKCE (requerido por Canva)."""
    from modules.canva_api import get_oauth_url, generate_pkce
    from flask import session
    client_id    = os.getenv("CANVA_CLIENT_ID", "")
    redirect_uri = os.getenv("CANVA_REDIRECT_URI",
                             "https://actualyza-prospecting-production.up.railway.app/oauth/canva/callback")
    if not client_id:
        return "CANVA_CLIENT_ID no configurado en Railway", 500
    verifier, challenge = generate_pkce()
    session["canva_code_verifier"] = verifier
    url = get_oauth_url(client_id, redirect_uri, code_challenge=challenge, state="actualyza")
    return redirect(url)


@app.route("/oauth/canva/callback")
def canva_oauth_callback():
    """Recibe el code de Canva y lo intercambia por access token (con PKCE)."""
    from flask import session
    code  = request.args.get("code", "")
    error = request.args.get("error", "")
    if error:
        return f"Canva OAuth error: {error}", 400
    if not code:
        return "Código de autorización faltante", 400

    verifier = session.pop("canva_code_verifier", "")
    if not verifier:
        return "Sesión expirada — vuelve a intentar conectar Canva", 400

    from modules.canva_api import exchange_code
    client_id     = os.getenv("CANVA_CLIENT_ID", "")
    client_secret = os.getenv("CANVA_CLIENT_SECRET", "")
    redirect_uri  = os.getenv("CANVA_REDIRECT_URI",
                              "https://actualyza-prospecting-production.up.railway.app/oauth/canva/callback")
    try:
        exchange_code(code, client_id, client_secret, redirect_uri, verifier)
        _backup_canva_token()  # persiste en Notion para sobrevivir redeploys
        return redirect("/creatives?canva=connected")
    except Exception as e:
        return f"Error al obtener token: {e}", 500


@app.route("/api/canva-status")
@_require_auth
def api_canva_status():
    from modules.canva_api import is_authorized
    return jsonify({"authorized": is_authorized()})


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

    # Verificar que el token es válido usando /me (no requiere ads_read)
    verify = http.get(
        "https://graph.facebook.com/v21.0/me",
        params={"access_token": short_token, "fields": "id,name"},
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
    # Use /me to verify token validity (ads_archive requires ads_read app review)
    r = http.get(
        "https://graph.facebook.com/v21.0/me",
        params={"access_token": token, "fields": "id,name"},
        timeout=10,
    ).json()
    if "error" in r:
        msg = r["error"].get("message", "")
        return jsonify({"ok": False, "status": "expirado", "error": msg})
    return jsonify({"ok": True, "status": "activo", "name": r.get("name", "")})


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


# ── Notion PATCH helper ───────────────────────────────────────

def _notion_patch(page_id: str, properties: dict) -> bool:
    r = http.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers={
            "Authorization":  f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type":   "application/json",
        },
        json={"properties": properties},
    )
    return r.status_code == 200


# ── Clinic update (ads Sí/No, etapa, etc.) ───────────────────

@app.route("/api/update-clinic", methods=["PATCH"])
@_require_auth
def api_update_clinic():
    global _cache
    data      = request.json or {}
    page_id   = data.get("notion_id", "").strip()
    if not page_id:
        return jsonify({"ok": False, "error": "notion_id requerido"}), 400

    props = {}
    if "corre_anuncios" in data:
        val = data["corre_anuncios"]   # "Sí" | "No" | "Sin verificar"
        props["¿Corre Anuncios?"] = {"select": {"name": val}}
        inv_map = {"Sí": "Baja", "No": "Sin anuncios", "Sin verificar": "Sin anuncios"}
        if val in inv_map and "inversion_meta" not in data:
            props["Inversión Meta"] = {"select": {"name": inv_map[val]}}
    if "inversion_meta" in data:
        props["Inversión Meta"] = {"select": {"name": data["inversion_meta"]}}
    if "etapa" in data:
        props["Etapa"] = {"select": {"name": data["etapa"]}}

    ok = _notion_patch(page_id, props)
    if ok:
        _cache = {"data": None, "ts": 0.0}
    return jsonify({"ok": ok})


# ── Campaigns ─────────────────────────────────────────────────

@app.route("/api/campaigns")
@_require_auth
def api_campaigns():
    clinics = get_clinics()
    campos  = ["notion_id", "nombre", "ciudad", "categoria", "email",
               "corre_anuncios", "campana_email", "email_etapa",
               "email_enviados", "email_abiertos", "lead_score"]
    # Solo leads con correo (elegibles para campaña)
    rows = [{k: c.get(k) for k in campos} for c in clinics if c.get("email")]
    rows.sort(key=lambda r: r.get("lead_score", 0), reverse=True)
    return jsonify(rows)   # lista vacía si nadie tiene correo → el JS muestra todos con aviso


@app.route("/api/enable-campaign", methods=["POST"])
@_require_auth
def api_enable_campaign():
    global _cache
    data    = request.json or {}
    page_id = data.get("notion_id", "").strip()
    if not page_id:
        return jsonify({"ok": False, "error": "notion_id requerido"}), 400

    # Buscar la clínica en cache
    clinics = get_clinics()
    clinic  = next((c for c in clinics if c["notion_id"] == page_id), None)
    if not clinic:
        return jsonify({"ok": False, "error": "Clínica no encontrada"}), 404

    test_email = (data.get("test_email") or "").strip()
    es_prueba  = bool(test_email)

    # En modo prueba el destino es el correo de prueba; en real necesita correo de la clínica
    if not es_prueba and not clinic.get("email"):
        return jsonify({"ok": False, "error": "Sin email de contacto"}), 400

    destino = test_email or clinic["email"]

    try:
        from modules.claude_writer import write_email
        from modules.email_sender  import send_campaign_email

        generated = write_email(clinic, email_num=1)
        result    = send_campaign_email(
            to_email  = destino,
            subject   = f"[PRUEBA] {generated['subject']}" if es_prueba else generated["subject"],
            body_html = generated["body_html"],
            body_text = generated["body_text"],
            notion_id = page_id,
            email_num = 1,
        )
        if not result["ok"]:
            return jsonify({"ok": False, "error": result["error"]}), 500

        # Solo actualiza Notion si no es prueba
        if not es_prueba:
            from datetime import date, timedelta
            hoy     = date.today().isoformat()
            proximo = (date.today() + timedelta(days=3)).isoformat()
            _notion_patch(page_id, {
                "Campaña Email": {"select": {"name": "Activa"}},
                "Email Etapa":   {"number": 1},
                "Email Enviados":{"number": 1},
                "Último Email":  {"date":   {"start": hoy}},
                "Próximo Email": {"date":   {"start": proximo}},
            })
            _cache = {"data": None, "ts": 0.0}

        return jsonify({"ok": True, "subject": generated["subject"], "email_num": 1, "prueba": es_prueba})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/send-next-email", methods=["POST"])
@_require_auth
def api_send_next_email():
    global _cache
    data    = request.json or {}
    page_id = data.get("notion_id", "").strip()
    if not page_id:
        return jsonify({"ok": False, "error": "notion_id requerido"}), 400

    clinics = get_clinics()
    clinic  = next((c for c in clinics if c["notion_id"] == page_id), None)
    if not clinic:
        return jsonify({"ok": False, "error": "Clínica no encontrada"}), 404

    test_email    = (data.get("test_email") or "").strip()
    es_prueba     = bool(test_email)
    es_prueba     = bool(test_email)
    if not es_prueba and not clinic.get("email"):
        return jsonify({"ok": False, "error": "Sin email de contacto"}), 400

    current_etapa = int(clinic.get("email_etapa") or 0)
    next_etapa    = current_etapa + 1
    if next_etapa > 4:
        return jsonify({"ok": False, "error": "Secuencia completa (4 emails enviados)"}), 400

    prev_opened = (clinic.get("email_abiertos") or 0) > 0
    destino     = test_email or clinic["email"]

    try:
        from modules.claude_writer import write_email
        from modules.email_sender  import send_campaign_email
        from datetime import date, timedelta

        generated = write_email(clinic, email_num=next_etapa, previous_opened=prev_opened)
        result    = send_campaign_email(
            to_email  = destino,
            subject   = f"[PRUEBA] {generated['subject']}" if es_prueba else generated["subject"],
            body_html = generated["body_html"],
            body_text = generated["body_text"],
            notion_id = page_id,
            email_num = next_etapa,
        )
        if not result["ok"]:
            return jsonify({"ok": False, "error": result["error"]}), 500

        if not es_prueba:
            enviados  = int(clinic.get("email_enviados") or 0) + 1
            days_next = [0, 3, 5, 7][min(next_etapa - 1, 3)]
            hoy       = date.today().isoformat()
            proximo   = (date.today() + timedelta(days=days_next)).isoformat() if next_etapa < 4 else None

            patch = {
                "Email Etapa":    {"number": next_etapa},
                "Email Enviados": {"number": enviados},
                "Último Email":   {"date":   {"start": hoy}},
            }
            if next_etapa == 4:
                patch["Campaña Email"] = {"select": {"name": "Completada"}}
            if proximo:
                patch["Próximo Email"] = {"date": {"start": proximo}}

            _notion_patch(page_id, patch)
            _cache = {"data": None, "ts": 0.0}
        return jsonify({"ok": True, "subject": generated["subject"], "email_num": next_etapa, "prueba": es_prueba})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/pause-campaign", methods=["POST"])
@_require_auth
def api_pause_campaign():
    global _cache
    page_id = (request.json or {}).get("notion_id", "").strip()
    ok = _notion_patch(page_id, {"Campaña Email": {"select": {"name": "Pausada"}}})
    if ok:
        _cache = {"data": None, "ts": 0.0}
    return jsonify({"ok": ok})


# ── Resend webhook (open / click tracking) ────────────────────

@app.route("/webhook/resend", methods=["POST"])
def webhook_resend():
    global _cache
    payload = request.json or {}
    ev_type = payload.get("type", "")
    ev_data = payload.get("data", {})

    notion_id = None
    email_num = None
    # Resend manda tags como dict {"notion_id": "...", "email_num": "1"}
    tags = ev_data.get("tags", {})
    if isinstance(tags, dict):
        notion_id = tags.get("notion_id")
        email_num = tags.get("email_num")
    elif isinstance(tags, list):
        for tag in tags:
            if tag.get("name") == "notion_id":
                notion_id = tag["value"]
            if tag.get("name") == "email_num":
                email_num = tag["value"]

    if not notion_id:
        return jsonify({"ok": True})

    if ev_type == "email.opened":
        # Incrementa contador de aperturas en Notion
        clinics  = get_clinics()
        clinic   = next((c for c in clinics if c["notion_id"] == notion_id), None)
        abiertos = int(clinic.get("email_abiertos") or 0) + 1 if clinic else 1
        _notion_patch(notion_id, {"Email Abiertos": {"number": abiertos}})
        _cache = {"data": None, "ts": 0.0}

    elif ev_type == "email.clicked":
        # Marca como lead caliente — mover a "En proceso"
        _notion_patch(notion_id, {"Etapa": {"select": {"name": "En proceso"}}})
        _cache = {"data": None, "ts": 0.0}

    elif ev_type in ("email.bounced", "email.complained"):
        _notion_patch(notion_id, {"Campaña Email": {"select": {"name": "Cancelada"}}})
        _cache = {"data": None, "ts": 0.0}

    return jsonify({"ok": True})


# ── Cal.com webhook ───────────────────────────────────────────

@app.route("/webhook/cal", methods=["POST"])
def webhook_cal():
    global _cache
    payload     = request.json or {}
    trigger     = payload.get("triggerEvent", "")
    data        = payload.get("payload", {})
    attendees   = data.get("attendees", [])
    attendee    = attendees[0] if attendees else {}
    booker_email = attendee.get("email", "").lower().strip()
    start_time   = data.get("startTime", "")

    if not booker_email:
        return jsonify({"ok": True})

    clinics = get_clinics()
    clinic  = next((c for c in clinics if (c.get("email") or "").lower() == booker_email), None)

    if trigger == "BOOKING_CREATED":
        props = {"Etapa": {"select": {"name": "Reunión agendada"}}}
        if start_time:
            try:
                meet_date = start_time[:10]  # YYYY-MM-DD
                props["Próximo Email"] = {"date": {"start": meet_date}}
            except Exception:
                pass
        if clinic:
            _notion_patch(clinic["notion_id"], props)
            _cache = {"data": None, "ts": 0.0}
        else:
            print(f"  ⚠ Cal booking: clínica no encontrada para {booker_email}")

    elif trigger in ("BOOKING_CANCELLED", "BOOKING_RESCHEDULED"):
        if clinic:
            etapa = "En proceso" if trigger == "BOOKING_CANCELLED" else "Reunión agendada"
            _notion_patch(clinic["notion_id"], {"Etapa": {"select": {"name": etapa}}})
            _cache = {"data": None, "ts": 0.0}

    return jsonify({"ok": True})


@app.route("/api/send-booking-link", methods=["POST"])
@_require_auth
def api_send_booking_link():
    """Envía el link de Cal.com directamente a un lead caliente."""
    global _cache
    data    = request.json or {}
    page_id = data.get("notion_id", "").strip()
    if not page_id:
        return jsonify({"ok": False, "error": "notion_id requerido"}), 400

    clinics = get_clinics()
    clinic  = next((c for c in clinics if c["notion_id"] == page_id), None)
    if not clinic:
        return jsonify({"ok": False, "error": "Clínica no encontrada"}), 404
    if not clinic.get("email"):
        return jsonify({"ok": False, "error": "Sin email de contacto"}), 400

    booking_url = os.getenv("CAL_BOOKING_URL", "https://cal.com/actualyza/amy-ai-demo")

    subject  = "Quick question — when works for a 15-min call?"
    body_text = (
        f"Hi,\n\nI'd love to show you exactly how AMY AI works for "
        f"{_cat_label_plain(clinic.get('categoria', ''))} clinics — takes 15 minutes.\n\n"
        f"Pick a time that works for you: {booking_url}\n\nBest,\nAlicia"
    )
    body_html = (
        f"<p>Hi,</p>"
        f"<p>I'd love to show you exactly how AMY AI works for "
        f"{_cat_label_plain(clinic.get('categoria', ''))} clinics — takes 15 minutes.</p>"
        f"<p>Pick a time that works for you: "
        f"<a href='{booking_url}'>{booking_url}</a></p>"
    )

    from modules.email_sender import send_campaign_email
    result = send_campaign_email(
        to_email  = clinic["email"],
        subject   = subject,
        body_html = body_html,
        body_text = body_text,
        notion_id = page_id,
        email_num = 5,  # fuera de secuencia — no afecta etapa
    )
    return jsonify({"ok": result["ok"], "error": result.get("error")})


def _cat_label_plain(cat: str) -> str:
    return {"dental": "dental", "estetica": "esthetic", "medspa": "med spa", "wellness": "wellness"}.get(cat, "medical")


# ── Unsubscribe ───────────────────────────────────────────────

@app.route("/unsubscribe")
def unsubscribe():
    page_id = request.args.get("id", "").strip()
    if page_id:
        _notion_patch(page_id, {"Campaña Email": {"select": {"name": "Cancelada"}}})
    return "<html><body style='font-family:Arial;text-align:center;padding:60px'>" \
           "<h2>Unsubscribed</h2><p>You won't receive further emails from AMY AI.</p></body></html>"


# ── Video translation ─────────────────────────────────────────

_image_cache        = {}  # key (cat_num) → composed JPEG bytes (fallback when Canva unavailable)
_video_rooms        = {}  # room_id → list of ws objects
_video_rooms_lock   = threading.Lock()
_daily_rooms        = {}  # room_id → daily.co room URL (in-memory; 2h TTL matches room exp)
_translation_state  = {}  # room_id → bool (True = enabled)


def _vroom_join(room_id: str, ws) -> None:
    with _video_rooms_lock:
        _video_rooms.setdefault(room_id, []).append(ws)
        count = len(_video_rooms[room_id])
    print(f"  [room] {room_id}: +1 participante → total={count}", flush=True)


def _vroom_leave(room_id: str, ws) -> None:
    with _video_rooms_lock:
        if room_id in _video_rooms:
            _video_rooms[room_id] = [p for p in _video_rooms[room_id] if p is not ws]
            count = len(_video_rooms[room_id])
            if not _video_rooms[room_id]:
                del _video_rooms[room_id]
                count = 0
    print(f"  [room] {room_id}: -1 participante → total={count}", flush=True)


def _vroom_other(room_id: str, ws):
    with _video_rooms_lock:
        for p in _video_rooms.get(room_id, []):
            if p is not ws:
                return p
    return None


def _handle_transcript(transcript: str, ws, room_id: str, src: str, tgt: str) -> None:
    import base64
    import json as _j
    try:
        print(f"  [translate] '{transcript}' ({src}→{tgt})")
        if not _translation_state.get(room_id, True):
            try:
                ws.send(_j.dumps({"type": "caption", "original": transcript, "translated": ""}))
            except Exception:
                pass
            return
        from modules.video_translator import translate_text, synthesize_speech
        t0 = time.time()
        translated = translate_text(transcript, src, tgt)
        print(f"  [claude] '{translated}' ({time.time()-t0:.2f}s)")
        if not translated:
            return
        # Send caption back to the speaker
        try:
            ws.send(_j.dumps({"type": "caption", "original": transcript, "translated": translated}))
        except Exception:
            pass
        # Generate TTS and send to the other participant
        t1 = time.time()
        audio = synthesize_speech(translated, tgt)
        print(f"  [elevenlabs] {len(audio)/1024:.1f}KB ({time.time()-t1:.2f}s)")
        other = _vroom_other(room_id, ws)
        total = len(_video_rooms.get(room_id, []))
        print(f"  [room] buscando otro en {room_id}: total={total} other={'sí' if other else 'NO'}", flush=True)
        if other and audio:
            try:
                other.send(_j.dumps({
                    "type":       "audio",
                    "original":   transcript,
                    "translated": translated,
                    "audio_b64":  base64.b64encode(audio).decode(),
                }))
                print(f"  [room] audio enviado al otro ✓", flush=True)
            except Exception as e:
                print(f"  [room] ERROR enviando audio al otro: {e}", flush=True)
    except Exception as e:
        print(f"  ✗ Error traducción video: {e}")


@sock.route("/ws/video/<room_id>")
def video_ws(ws, room_id):
    src = request.args.get("lang",   "en")
    tgt = request.args.get("target", "es")
    print(f"  [video] WS conectado: room={room_id} src={src} tgt={tgt}")
    _vroom_join(room_id, ws)
    try:
        from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
        dg = DeepgramClient(os.getenv("DEEPGRAM_API_KEY", ""))
        conn = dg.listen.websocket.v("1")

        def _on_transcript(_, result, **kwargs):
            try:
                text = result.channel.alternatives[0].transcript
                is_final = result.is_final
                if text:
                    print(f"  [deepgram] transcript is_final={is_final}: '{text}'")
                if text and is_final:
                    threading.Thread(
                        target=_handle_transcript,
                        args=(text, ws, room_id, src, tgt),
                        daemon=True,
                    ).start()
            except Exception as e:
                print(f"  [deepgram] error en callback: {e}")

        conn.on(LiveTranscriptionEvents.Transcript, _on_transcript)
        opts = LiveOptions(
            model="nova-2", language=src, smart_format=True,
            interim_results=False, endpointing=300,
            encoding="linear16", sample_rate=16000, channels=1,
        )
        started = conn.start(opts)
        print(f"  [deepgram] conn.start={started}")
        if not started:
            ws.send(json.dumps({"type": "error", "message": "Deepgram no disponible"}))
            return
        ws.send(json.dumps({"type": "ready"}))
        chunks = 0
        while True:
            msg = ws.receive()
            if msg is None:
                break
            if isinstance(msg, bytes):
                conn.send(msg)
                chunks += 1
                if chunks % 50 == 0:
                    print(f"  [video] {chunks} chunks enviados a Deepgram")
            else:
                try:
                    data = json.loads(msg)
                    if data.get("type") == "ping":
                        ws.send(json.dumps({"type": "pong"}))
                    elif data.get("type") == "set_translation":
                        enabled = bool(data.get("enabled", True))
                        _translation_state[room_id] = enabled
                        other = _vroom_other(room_id, ws)
                        if other:
                            try:
                                other.send(json.dumps({"type": "translation_status", "enabled": enabled}))
                            except Exception:
                                pass
                except Exception:
                    pass
    except Exception as e:
        print(f"  ✗ Video WS error: {e}")
    finally:
        try:
            conn.finish()
        except Exception:
            pass
        _vroom_leave(room_id, ws)


@app.route("/privacy")
def privacy_page():
    return render_template("privacy.html")


@app.route("/demo")
def demo_page():
    return render_template("demo.html")


@app.route("/video")
def video_page():
    return render_template("video.html")


@app.route("/api/video/create-room", methods=["POST"])
@_require_auth
def api_create_video_room():
    import secrets as _sec
    api_key = os.getenv("DAILY_API_KEY", "")
    if not api_key:
        return jsonify({"ok": False, "error": "DAILY_API_KEY no configurada"}), 500
    room_name = f"amy-{_sec.token_hex(4)}"
    r = http.post(
        "https://api.daily.co/v1/rooms",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "name": room_name,
            "privacy": "public",
            "properties": {
                "exp": int(time.time()) + 7200,
                "enable_screenshare": True,
                "enable_chat": False,
                "start_video_off": False,
                "start_audio_off": False,
            },
        },
        timeout=15,
    )
    if not r.ok:
        return jsonify({"ok": False, "error": r.text}), 500
    data = r.json()
    _daily_rooms[room_name] = data["url"]
    return jsonify({"ok": True, "room_id": room_name, "room_url": data["url"]})


@app.route("/api/video/room-url/<room_id>")
def api_video_room_url(room_id):
    url = _daily_rooms.get(room_id)
    if url:
        return jsonify({"ok": True, "url": url})
    # Fallback: ask Daily.co directly (covers server restart between host & guest join)
    api_key = os.getenv("DAILY_API_KEY", "")
    if api_key:
        r = http.get(
            f"https://api.daily.co/v1/rooms/{room_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if r.ok:
            url = r.json().get("url", "")
            _daily_rooms[room_id] = url
            return jsonify({"ok": True, "url": url})
    return jsonify({"ok": False, "error": "Sala no encontrada"}), 404


# ── End video translation ──────────────────────────────────────

_restore_canva_token()     # recupera token Canva desde Notion si se perdió en redeploy
_generate_all_assets_bg()  # genera creativos al arrancar si faltan

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5055))
    print()
    print("  ┌────────────────────────────────────────┐")
    print("  │  Actualyza Dashboard                   │")
    print(f"  │  http://localhost:{port}                 │")
    print("  └────────────────────────────────────────┘")
    print()
    app.run(host="0.0.0.0", port=port, debug=False)
