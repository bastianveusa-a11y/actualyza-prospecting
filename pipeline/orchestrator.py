"""
Orquestador del pipeline de prospección
Corre en tandas: busca clínicas, verifica anuncios Meta, guarda en Notion.
Lleva registro de progreso para no repetir trabajo entre ejecuciones.

Uso: python3 -m pipeline.orchestrator
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from modules.google_places import search_clinics, CATEGORIES, AVAILABLE_CITIES
from modules.meta_ads import count_ads_for_page
from modules.notion_db import upsert_clinic, ensure_db_schema
from modules.state_registry import lookup as registry_lookup
from modules.email_scraper import scrape_email
from modules.api_budget import increment, check, print_report, BudgetExceeded

# ── Config desde .env ─────────────────────────────────────────
GOOGLE_KEY    = os.getenv("GOOGLE_PLACES_API_KEY", "")
NOTION_TOKEN  = os.getenv("NOTION_TOKEN", "")
NOTION_DB_ID  = os.getenv("NOTION_DATABASE_ID", "")
META_TOKEN    = os.getenv("META_USER_TOKEN") or None
MAX_PER_RUN   = int(os.getenv("MAX_CLINICS_PER_RUN", "20"))
PLACES_DELAY  = 1.2   # segundos entre calls a Google Places
META_DELAY    = 2.5   # segundos entre calls a Meta
SUNBIZ_DELAY  = 3.5   # segundos entre calls a Sunbiz (Cloudflare)
EMAIL_DELAY   = 1.5   # segundos entre requests al sitio web de la clínica

# Todas las ciudades US por defecto (España excluida — se agrega cuando se active)
DEFAULT_CITIES = [
    (c["city"], c["state"])
    for c in AVAILABLE_CITIES
    if c.get("country", "US") == "US"
]

# Mapa city→state para lookup rápido
_STATE_MAP = {c["city"]: c["state"] for c in AVAILABLE_CITIES}

PROGRESS_FILE = Path(__file__).parent.parent / "data" / "progress.json"
LOG_FILE      = Path(__file__).parent.parent / "data" / "runs.log"


# ── Progreso persistente ──────────────────────────────────────

def _resolve_targets(targets) -> list:
    """Convierte targets del dashboard en [(city, state_code, [cats])]."""
    if not targets:
        return [(city, sc, list(CATEGORIES.keys())) for city, sc in DEFAULT_CITIES]
    result = []
    for t in targets:
        city = t.get("city", "").strip()
        sc   = t.get("state", _STATE_MAP.get(city, "")).strip()
        cats = t.get("categories") or list(CATEGORIES.keys())
        if city and sc:
            result.append((city, sc, [c for c in cats if c in CATEGORIES]))
    return result or [(city, sc, list(CATEGORIES.keys())) for city, sc in DEFAULT_CITIES]


def _fresh_state(resolved=None) -> dict:
    targets = resolved or _resolve_targets(None)
    state = {}
    for city, state_code, cats in targets:
        state.setdefault(city, {})
        for cat in cats:
            state[city][cat] = {
                "status":          "pending",
                "next_page_token": None,
                "processed":       0,
                "last_run":        None,
            }
    return state


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except Exception:
            pass
    return _fresh_state()


def save_progress(state: dict) -> None:
    PROGRESS_FILE.parent.mkdir(exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def should_monthly_reset(state: dict, resolved: list) -> bool:
    """Retorna True si todos los targets están completos y han pasado 28+ días."""
    all_complete = all(
        state.get(city, {}).get(cat, {}).get("status") == "complete"
        for city, _, cats in resolved
        for cat in cats
    )
    if not all_complete:
        return False

    last_runs = [
        state[city][cat]["last_run"]
        for city, _, cats in resolved
        for cat in cats
        if state.get(city, {}).get(cat, {}).get("last_run")
    ]
    if not last_runs:
        return False

    try:
        latest = datetime.fromisoformat(max(last_runs).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - latest).days >= 28
    except Exception:
        return False


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── Lógica principal ──────────────────────────────────────────

def next_pending(state: dict, resolved: list) -> Optional[Tuple[str, str, str]]:
    """Devuelve (city, state_code, category) del siguiente bloque a procesar."""
    for city, state_code, cats in resolved:
        for cat in cats:
            entry = state.get(city, {}).get(cat, {})
            if entry.get("status") != "complete":
                return city, state_code, cat
    return None


def process_clinic(clinic: dict, run_stats: dict, skip_existing: bool = True) -> str:
    """
    Enriquece con Meta y guarda en Notion.
    skip_existing=True: si ya existe en Notion la salta sin enriquecer.
    Retorna: 'created' | 'skipped' | 'updated' | 'error'
    """
    name = clinic.get("nombre", "")

    if skip_existing:
        place_id = clinic.get("google_place_id", "")
        if place_id:
            from modules.notion_db import _find_clinic_page_id
            if _find_clinic_page_id(NOTION_TOKEN, NOTION_DB_ID, place_id):
                run_stats["skipped"] = run_stats.get("skipped", 0) + 1
                return "skipped"

    # Meta Ad Library — usa el sitio web de la clínica para encontrar el slug exacto de FB/IG
    meta = count_ads_for_page(
        page_name=name,
        user_token=META_TOKEN,
        delay=META_DELAY,
        website_url=clinic.get("web") or None,
    )
    clinic["anuncios_activos"] = meta["count"]
    clinic["inversion_meta"]   = meta["level"]
    clinic["corre_anuncios"]   = meta.get("has_ads")   # True / False / None
    if meta.get("fb_slug"):
        clinic["facebook_page"] = f"https://facebook.com/{meta['fb_slug']}"
    if meta.get("method", "").startswith("scraping"):
        try:
            increment("meta_scraping", 1)
        except BudgetExceeded:
            pass  # Meta scraping es sin costo — solo registramos, no bloqueamos

    # Registro mercantil estatal — solo para clínicas de EE.UU.
    city_meta = next((c for c in AVAILABLE_CITIES if c["city"] == clinic.get("ciudad")), {})
    if city_meta.get("country", "US") == "US":
        registry = registry_lookup(
            state=clinic.get("estado", ""),
            clinic_name=name,
            clinic_address=clinic.get("direccion", ""),
            clinic_zip=clinic.get("zip", ""),
            clinic_phone=clinic.get("telefono", ""),
            delay=SUNBIZ_DELAY,
        )
        if not registry.get("error"):
            clinic["entidad_legal"]     = registry.get("nombre_legal", "")
            clinic["dueno"]             = registry.get("dueno", "")
            clinic["agente_registrado"] = registry.get("agente_registrado", "")
            clinic["sunbiz_url"]        = registry.get("sunbiz_url", "")
            clinic["match_score"]       = registry.get("match_score", 0.0)

    # Email de contacto desde el sitio web
    if clinic.get("web") and not clinic.get("email_contacto"):
        email_result = scrape_email(clinic["web"], delay=EMAIL_DELAY)
        if email_result.get("email"):
            clinic["email_contacto"] = email_result["email"]
            log(f"    📧 {email_result['email']}")

    # Guardar en Notion
    result = upsert_clinic(NOTION_TOKEN, NOTION_DB_ID, clinic)
    action = result.get("action", "error")

    if action == "created":
        run_stats["created"] += 1
        slug_info   = f" @{meta['fb_slug']}"             if meta.get("fb_slug")      else ""
        term_info   = f" [búsqueda: '{meta['search_term']}']" if meta.get("search_term") else ""
        log(f"  ✓ {name} | {clinic['rating']}★ | {meta['level']} ({meta['count']} anuncios){slug_info}{term_info}")
    elif action == "updated":
        run_stats["updated"] += 1
        dueno = clinic.get("dueno", "—")
        log(f"  ↻ {name} | actualizado | dueño: {dueno}")
    else:
        run_stats["errors"] += 1
        log(f"  ✗ Error guardando '{name}': {result.get('error', '')}")

    return action


def run_pipeline(stop_flag=None, targets=None) -> None:
    resolved = _resolve_targets(targets)
    cities_desc = ", ".join(f"{c}/{'+'.join(cats)}" for c, _, cats in resolved)

    log("=" * 55)
    log("PIPELINE INICIADO")
    log(f"Objetivos: {cities_desc}")
    log(f"Tanda máxima: {MAX_PER_RUN} clínicas nuevas")
    log("=" * 55)

    if not GOOGLE_KEY:
        log("ERROR: GOOGLE_PLACES_API_KEY no configurada. Saliendo.")
        return
    if not NOTION_TOKEN or not NOTION_DB_ID:
        log("ERROR: Notion no configurado. Saliendo.")
        return

    print_report()

    try:
        check("google_places")
    except BudgetExceeded as e:
        log(f"DETENIDO: {e}")
        return

    ensure_db_schema(NOTION_TOKEN, NOTION_DB_ID)

    state = load_progress()

    # Inicializa entradas faltantes para los targets solicitados
    for city, state_code, cats in resolved:
        state.setdefault(city, {})
        for cat in cats:
            if cat not in state[city]:
                state[city][cat] = {
                    "status": "pending", "next_page_token": None,
                    "processed": 0, "last_run": None,
                }

    if should_monthly_reset(state, resolved):
        log("Reset mensual automático — mercados seleccionados serán re-buscados.")
        for city, _, cats in resolved:
            for cat in cats:
                state[city][cat] = {
                    "status": "pending", "next_page_token": None,
                    "processed": 0, "last_run": None,
                }
        save_progress(state)

    run_stats = {"created": 0, "updated": 0, "errors": 0, "skipped": 0}
    run_start = datetime.now(timezone.utc).isoformat()

    while run_stats["created"] < MAX_PER_RUN:
        if stop_flag and stop_flag():
            log("PIPELINE DETENIDO POR EL USUARIO.")
            save_progress(state)
            _print_summary(run_stats, run_start)
            return

        target = next_pending(state, resolved)
        if not target:
            log("Todos los mercados procesados. Pipeline completo.")
            break

        city, state_code, cat = target
        entry = state[city][cat]

        log(f"\n── {city} / {cat} ──")

        # Verifica presupuesto antes de cada búsqueda
        try:
            increment("google_places", 1)
        except BudgetExceeded as e:
            log(f"DETENIDO por límite mensual: {e}")
            save_progress(state)
            _print_summary(run_stats, run_start)
            return

        result = search_clinics(
            city=city,
            state=state_code,
            category_key=cat,
            api_key=GOOGLE_KEY,
            max_results=20,
            page_token=entry.get("next_page_token"),
            delay=PLACES_DELAY,
        )

        if result["error"]:
            log(f"  Error en Google Places: {result['error']}")
            entry["status"] = "error"
            save_progress(state)
            time.sleep(5)
            continue

        clinics = result["clinics"]
        log(f"  {len(clinics)} clínicas encontradas en esta página")

        for clinic in clinics:
            if stop_flag and stop_flag():
                log("PIPELINE DETENIDO POR EL USUARIO.")
                entry["last_run"] = run_start
                save_progress(state)
                _print_summary(run_stats, run_start)
                return

            if run_stats["created"] >= MAX_PER_RUN:
                log(f"  Tanda de {MAX_PER_RUN} alcanzada — pausando hasta próxima ejecución.")
                # Marca progreso parcial: la próxima ejecución re-busca esta página
                # y la deduplicación de Notion descarta las ya insertadas
                entry["status"]   = "in_progress"
                entry["last_run"] = run_start
                save_progress(state)
                _print_summary(run_stats, run_start)
                return

            clinic["ciudad"]    = city
            clinic["estado"]    = state_code
            clinic["categoria"] = cat
            process_clinic(clinic, run_stats)

        # Actualiza estado de paginación
        next_token = result.get("next_page_token")
        entry["processed"] += len(clinics)
        entry["last_run"]   = run_start

        if next_token:
            entry["next_page_token"] = next_token
            entry["status"]          = "in_progress"
            log(f"  Hay más páginas — continuará en próxima ejecución")
        else:
            entry["next_page_token"] = None
            entry["status"]          = "complete"
            log(f"  Categoría {cat} en {city}: completa ({entry['processed']} clínicas procesadas)")

        save_progress(state)

    _print_summary(run_stats, run_start)


def _print_summary(stats: dict, start: str) -> None:
    log("\n" + "=" * 55)
    log("RESUMEN DE ESTA EJECUCIÓN")
    log(f"  Nuevas en Notion    : {stats['created']}")
    log(f"  Ya existían (skip)  : {stats.get('skipped', 0)}")
    log(f"  Errores             : {stats['errors']}")
    log(f"  Iniciado            : {start}")
    log(f"  Finalizado          : {datetime.now(timezone.utc).isoformat()}")
    log("=" * 55)


def run_enrichment(stop_flag=None, progress_cb=None) -> None:
    """
    Recorre todas las clínicas en Notion y actualiza sus datos:
    Meta Ads, email de contacto, registro mercantil.
    Solo procesa clínicas que tengan datos incompletos.
    progress_cb(processed, total, updated, skipped) — llamado tras cada clínica.
    """
    import requests as _req

    log("=" * 55)
    log("ENRICHMENT INICIADO — actualizando clínicas existentes")
    log("=" * 55)

    if not NOTION_TOKEN or not NOTION_DB_ID:
        log("ERROR: Notion no configurado. Saliendo.")
        return

    # Obtener todas las clínicas de Notion
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    clinics = []
    cursor  = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = _req.post(f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
                         headers=headers, json=body).json()
        for page in resp.get("results", []):
            def _txt(p, field):
                items = p.get("properties", {}).get(field, {}).get("rich_text", [])
                return items[0]["plain_text"] if items else ""
            def _sel(p, field):
                s = p.get("properties", {}).get(field, {}).get("select")
                return s["name"] if s else ""
            def _url(p, field):
                return p.get("properties", {}).get(field, {}).get("url") or ""
            def _eml(p, field):
                return p.get("properties", {}).get(field, {}).get("email") or ""
            def _phn(p, field):
                return p.get("properties", {}).get(field, {}).get("phone_number") or ""

            clinics.append({
                "notion_id":   page["id"],
                "nombre":      (page.get("properties", {}).get("Nombre", {}).get("title") or [{}])[0].get("plain_text", ""),
                "ciudad":      _sel(page, "Ciudad"),
                "estado":      _txt(page, "Estado") or _sel(page, "Ciudad").split(", ")[-1] if _sel(page, "Ciudad") else "",
                "web":         _url(page, "Web"),
                "telefono":    _phn(page, "Teléfono"),
                "direccion":   _txt(page, "Dirección"),
                "zip":         _txt(page, "ZIP"),
                "email":       _eml(page, "Email Contacto"),
                "dueno":       _txt(page, "Dueño / Manager"),
                "inversion":   _sel(page, "Inversión Meta"),
            })
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    total = len(clinics)
    log(f"  {total} clínicas en Notion")

    stats = {"updated": 0, "skipped": 0, "errors": 0}
    run_start = datetime.now(timezone.utc).isoformat()

    for i, clinic in enumerate(clinics):
        if stop_flag and stop_flag():
            log("ENRICHMENT DETENIDO POR EL USUARIO.")
            break

        name      = clinic.get("nombre", "")
        page_id   = clinic["notion_id"]
        needs_meta  = not clinic.get("inversion")
        needs_email = not clinic.get("email") and clinic.get("web")
        needs_dueno = not clinic.get("dueno")

        if not (needs_meta or needs_email or needs_dueno):
            stats["skipped"] += 1
            if progress_cb:
                progress_cb(i + 1, total, stats["updated"], stats["skipped"])
            continue

        log(f"  [{i+1}/{total}] {name}")
        updates = {}

        if needs_meta:
            meta = count_ads_for_page(page_name=name, user_token=META_TOKEN, delay=META_DELAY,
                                      website_url=clinic.get("web") or None)
            updates["anuncios_activos"] = meta["count"]
            updates["inversion_meta"]   = meta["level"]
            updates["corre_anuncios"]   = meta.get("has_ads")
            if meta.get("fb_slug"):
                updates["facebook_page"] = f"https://facebook.com/{meta['fb_slug']}"
            try:
                increment("meta_scraping", 1)
            except BudgetExceeded:
                pass

        if needs_email:
            email_result = scrape_email(clinic["web"], delay=EMAIL_DELAY)
            if email_result.get("email"):
                updates["email_contacto"] = email_result["email"]
                log(f"    📧 {email_result['email']}")

        if needs_dueno:
            city_meta = next((c for c in AVAILABLE_CITIES if c["city"] == clinic.get("ciudad")), {})
            if city_meta.get("country", "US") == "US":
                estado = city_meta.get("state", "")
                registry = registry_lookup(state=estado, clinic_name=name,
                                           clinic_address=clinic.get("direccion", ""),
                                           clinic_zip=clinic.get("zip", ""),
                                           delay=SUNBIZ_DELAY)
                if not registry.get("error"):
                    updates["entidad_legal"]     = registry.get("nombre_legal", "")
                    updates["dueno"]             = registry.get("dueno", "")
                    updates["agente_registrado"] = registry.get("agente_registrado", "")
                    updates["sunbiz_url"]        = registry.get("sunbiz_url", "")
                    updates["match_score"]       = registry.get("match_score", 0.0)
                    if updates.get("dueno"):
                        log(f"    👤 {updates['dueno']}")

        if updates:
            from modules.notion_db import update_clinic
            ok = update_clinic(NOTION_TOKEN, page_id, updates)
            if ok:
                stats["updated"] += 1
            else:
                stats["errors"] += 1

        if progress_cb:
            progress_cb(i + 1, total, stats["updated"], stats["skipped"])

    log("\n" + "=" * 55)
    log("ENRICHMENT COMPLETADO")
    log(f"  Actualizadas : {stats['updated']}")
    log(f"  Sin cambios  : {stats['skipped']}")
    log(f"  Errores      : {stats['errors']}")
    log(f"  Iniciado     : {run_start}")
    log(f"  Finalizado   : {datetime.now(timezone.utc).isoformat()}")
    log("=" * 55)


if __name__ == "__main__":
    run_pipeline()
