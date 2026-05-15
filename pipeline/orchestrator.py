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

from modules.google_places import search_clinics, CATEGORIES
from modules.meta_ads import count_ads_for_page
from modules.notion_db import upsert_clinic, ensure_db_schema
from modules.sunbiz import lookup_clinic as sunbiz_lookup
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

# Orden de procesamiento
CITIES = [
    ("Miami",   "FL"),
    ("Orlando", "FL"),
    ("Dallas",  "TX"),
]

PROGRESS_FILE = Path(__file__).parent.parent / "data" / "progress.json"
LOG_FILE      = Path(__file__).parent.parent / "data" / "runs.log"


# ── Progreso persistente ──────────────────────────────────────

def _fresh_state() -> dict:
    state = {}
    for city, state_code in CITIES:
        state[city] = {}
        for cat in CATEGORIES:
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


def should_monthly_reset(state: dict) -> bool:
    """
    Retorna True si todos los mercados están completos Y han pasado 28+ días
    desde la última ejecución. Dispara el barrido mensual automático.
    """
    all_complete = all(
        state.get(city, {}).get(cat, {}).get("status") == "complete"
        for city, _ in CITIES
        for cat in CATEGORIES
    )
    if not all_complete:
        return False

    last_runs = [
        state[city][cat]["last_run"]
        for city, _ in CITIES
        for cat in CATEGORIES
        if state.get(city, {}).get(cat, {}).get("last_run")
    ]
    if not last_runs:
        return False

    try:
        latest_str = max(last_runs)
        latest     = datetime.fromisoformat(latest_str.replace("Z", "+00:00"))
        days       = (datetime.now(timezone.utc) - latest).days
        return days >= 28
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

def next_pending(state: dict) -> Optional[Tuple[str, str, str]]:
    """Devuelve (city, state_code, category) del siguiente bloque a procesar."""
    for city, state_code in CITIES:
        for cat in CATEGORIES:
            entry = state.get(city, {}).get(cat, {})
            if entry.get("status") != "complete":
                return city, state_code, cat
    return None


def process_clinic(clinic: dict, run_stats: dict) -> str:
    """
    Enriquece con Meta y guarda en Notion.
    Retorna: 'created' | 'skipped' | 'error'
    """
    name = clinic.get("nombre", "")

    # Meta Ad Library
    meta = count_ads_for_page(
        page_name=name,
        user_token=META_TOKEN,
        delay=META_DELAY,
    )
    clinic["anuncios_activos"] = meta["count"]
    clinic["inversion_meta"]   = meta["level"]
    if meta.get("method", "").startswith("scraping"):
        try:
            increment("meta_scraping", 1)
        except BudgetExceeded:
            pass  # Meta scraping es sin costo — solo registramos, no bloqueamos

    # Sunbiz — datos legales del dueño
    sunbiz = sunbiz_lookup(
        clinic_name=name,
        clinic_address=clinic.get("direccion", ""),
        clinic_zip=clinic.get("zip", ""),
        clinic_phone=clinic.get("telefono", ""),
        delay=SUNBIZ_DELAY,
    )
    if not sunbiz.get("error"):
        clinic["entidad_legal"]     = sunbiz.get("nombre_legal", "")
        clinic["dueno"]             = sunbiz.get("dueno", "")
        clinic["agente_registrado"] = sunbiz.get("agente_registrado", "")
        clinic["sunbiz_url"]        = sunbiz.get("sunbiz_url", "")
        clinic["match_score"]       = sunbiz.get("match_score", 0.0)

    # Guardar en Notion
    result = upsert_clinic(NOTION_TOKEN, NOTION_DB_ID, clinic)
    action = result.get("action", "error")

    if action == "created":
        run_stats["created"] += 1
        log(f"  ✓ {name} | {clinic['rating']}★ | {meta['level']} ({meta['count']} anuncios)")
    elif action == "updated":
        run_stats["updated"] += 1
        dueno = clinic.get("dueno", "—")
        log(f"  ↻ {name} | actualizado | dueño: {dueno}")
    else:
        run_stats["errors"] += 1
        log(f"  ✗ Error guardando '{name}': {result.get('error', '')}")

    return action


def run_pipeline() -> None:
    log("=" * 55)
    log("PIPELINE INICIADO")
    log(f"Tanda máxima: {MAX_PER_RUN} clínicas nuevas")
    log("=" * 55)

    # Validaciones básicas
    if not GOOGLE_KEY:
        log("ERROR: GOOGLE_PLACES_API_KEY no configurada. Saliendo.")
        return
    if not NOTION_TOKEN or not NOTION_DB_ID:
        log("ERROR: Notion no configurado. Saliendo.")
        return

    # Muestra uso actual de APIs
    print_report()

    # Verifica que Google Places tenga presupuesto antes de arrancar
    try:
        check("google_places")
    except BudgetExceeded as e:
        log(f"DETENIDO: {e}")
        return

    ensure_db_schema(NOTION_TOKEN, NOTION_DB_ID)

    state = load_progress()
    if should_monthly_reset(state):
        log("Reset mensual automático — todos los mercados serán re-buscados.")
        state = _fresh_state()
        save_progress(state)

    run_stats = {"created": 0, "updated": 0, "errors": 0}
    run_start = datetime.now(timezone.utc).isoformat()

    while run_stats["created"] + run_stats["updated"] < MAX_PER_RUN:
        target = next_pending(state)
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
            if run_stats["created"] + run_stats["updated"] >= MAX_PER_RUN:
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
    log(f"  Actualizadas        : {stats['updated']}")
    log(f"  Errores             : {stats['errors']}")
    log(f"  Iniciado            : {start}")
    log(f"  Finalizado          : {datetime.now(timezone.utc).isoformat()}")
    log("=" * 55)


if __name__ == "__main__":
    run_pipeline()
