"""
Control de presupuesto de APIs con créditos gratuitos por servicio.
Calcula costo neto real (después de free tier) por mes.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

USAGE_FILE = Path(__file__).parent.parent / "data" / "api_usage.json"

# Límites mensuales de uso (unidades, no $)
# Unidades: requests, minutos, emails, imágenes según el servicio
DEFAULTS = {
    # ── Prospecting ──────────────────────────────
    "google_places":  3750,    # requests/mes
    "sunbiz":         500,     # lookups/mes
    "meta_scraping":  5000,    # requests/mes
    "claude_emails":  500,     # emails generados/mes
    "resend_emails":  2800,    # emails enviados/mes
    "flux_images":    100,     # imágenes/mes
    # ── Agencia / Voz ────────────────────────────
    "retell_calls":   500,     # minutos de llamada/mes
    "retell_web":     200,     # minutos de demo web/mes
    "openai":         1000,    # requests LLM/mes (si se usa directo)
    # ── Infraestructura ──────────────────────────
    "railway":        1,       # instancias activas (costo fijo mensual)
    "vercel":         1,       # proyectos activos (costo fijo mensual)
    "notion":         1,       # workspace (costo fijo mensual)
}

# Costo y créditos gratuitos por servicio
# free_units: unidades cubiertas por plan gratuito/crédito mensual
# cost_per_unit: costo $ por unidad DESPUÉS del free tier
# fixed_cost: costo fijo mensual independiente del uso
PRICING = {
    # ── Prospecting ──────────────────────────────
    "google_places": {
        "label":         "Google Places API",
        "cost_per_unit": 0.017,
        "free_units":    11765,    # $200 crédito / $0.017
        "fixed_cost":    0,
        "note":          "$200 crédito/mes Google Cloud",
    },
    "sunbiz": {
        "label":         "Sunbiz / State Registry",
        "cost_per_unit": 0,
        "free_units":    99999,
        "fixed_cost":    0,
        "note":          "Scraping web — gratis",
    },
    "meta_scraping": {
        "label":         "Meta Ads Library API",
        "cost_per_unit": 0,
        "free_units":    99999,
        "fixed_cost":    0,
        "note":          "API gratuita",
    },
    "claude_emails": {
        "label":         "Claude AI (emails)",
        "cost_per_unit": 0.002,
        "free_units":    0,
        "fixed_cost":    0,
        "note":          "Haiku ~$0.002/email",
    },
    "resend_emails": {
        "label":         "Resend (email delivery)",
        "cost_per_unit": 0.0004,
        "free_units":    3000,
        "fixed_cost":    0,
        "note":          "3,000 gratis/mes · $0.0004 c/u después",
    },
    "flux_images": {
        "label":         "Replicate / Flux (imágenes)",
        "cost_per_unit": 0.04,
        "free_units":    0,
        "fixed_cost":    0,
        "note":          "$0.04/imagen",
    },
    # ── Agencia / Voz ────────────────────────────
    "retell_calls": {
        "label":         "Retell AI (llamadas salientes)",
        "cost_per_unit": 0.11,     # ~$0.11/min · varía por modelo de voz
        "free_units":    0,
        "fixed_cost":    0,
        "note":          "~$0.11/min · actualizar según plan",
    },
    "retell_web": {
        "label":         "Retell AI (demo web)",
        "cost_per_unit": 0.11,
        "free_units":    0,
        "fixed_cost":    0,
        "note":          "Misma tarifa · demo en landing page",
    },
    "openai": {
        "label":         "OpenAI (LLM directo)",
        "cost_per_unit": 0.003,    # ~$0.003/request GPT-4o-mini promedio
        "free_units":    0,
        "fixed_cost":    0,
        "note":          "GPT-4o-mini ~$0.003/req promedio",
    },
    # ── Infraestructura ──────────────────────────
    "railway": {
        "label":         "Railway (backend hosting)",
        "cost_per_unit": 0,
        "free_units":    99999,
        "fixed_cost":    20,       # ~$20/mes Hobby/Pro plan
        "note":          "~$20/mes plan Hobby + uso",
    },
    "vercel": {
        "label":         "Vercel (web hosting)",
        "cost_per_unit": 0,
        "free_units":    99999,
        "fixed_cost":    0,        # Free tier por ahora
        "note":          "Free tier activo",
    },
    "notion": {
        "label":         "Notion (base de datos)",
        "cost_per_unit": 0,
        "free_units":    99999,
        "fixed_cost":    0,        # Free tier
        "note":          "Free tier activo",
    },
}


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _load() -> dict:
    if USAGE_FILE.exists():
        try:
            return json.loads(USAGE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save(data: dict) -> None:
    USAGE_FILE.parent.mkdir(exist_ok=True)
    USAGE_FILE.write_text(json.dumps(data, indent=2))


def get_status(service: str) -> dict:
    data    = _load()
    month   = _current_month()
    limit   = int(os.getenv(f"{service.upper()}_MONTHLY_LIMIT", DEFAULTS.get(service, 100)))
    entry   = data.get(service, {})
    pricing = PRICING.get(service, {"cost_per_unit": 0, "free_units": 0, "label": service, "note": ""})

    if entry.get("month") != month:
        entry = {"month": month, "count": 0}

    count     = entry.get("count", 0)
    remaining = max(0, limit - count)
    billable  = max(0, count - pricing["free_units"])
    cost_usd  = round(billable * pricing["cost_per_unit"], 4)

    return {
        "service":    service,
        "label":      pricing["label"],
        "note":       pricing["note"],
        "month":      month,
        "count":      count,
        "limit":      limit,
        "remaining":  remaining,
        "blocked":    remaining <= 0,
        "pct":        round(count / limit * 100, 1) if limit > 0 else 0,
        "free_units": pricing["free_units"],
        "billable":   billable,
        "cost_usd":   cost_usd,
    }


def increment(service: str, n: int = 1) -> dict:
    status = get_status(service)
    if status["blocked"]:
        raise BudgetExceeded(
            f"{service}: límite mensual de {status['limit']} alcanzado "
            f"(mes {status['month']})."
        )

    data  = _load()
    month = _current_month()
    entry = data.get(service, {})

    if entry.get("month") != month:
        entry = {"month": month, "count": 0}

    entry["count"] = entry.get("count", 0) + n
    data[service]  = entry
    _save(data)

    updated = get_status(service)

    if updated["remaining"] <= updated["limit"] * 0.2 and updated["remaining"] > 0:
        print(f"  ⚠ {service}: {updated['remaining']} requests restantes este mes ({updated['pct']}% usado)")

    return updated


def check(service: str) -> None:
    status = get_status(service)
    if status["blocked"]:
        raise BudgetExceeded(
            f"{service}: límite mensual de {status['limit']} alcanzado "
            f"(mes {status['month']})."
        )


def get_monthly_cost() -> dict:
    """Retorna el costo total estimado del mes actual, desglosado por servicio."""
    services = list(DEFAULTS.keys())
    breakdown = [get_status(s) for s in services]
    total = round(sum(s["cost_usd"] for s in breakdown), 2)
    return {
        "month":     _current_month(),
        "total_usd": total,
        "services":  breakdown,
    }


def print_report() -> None:
    report = get_monthly_cost()
    print(f"\n── Uso de APIs — {report['month']} ──────────────────")
    for s in report["services"]:
        bar_filled = int(s["pct"] / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        cost_str = f"  ${s['cost_usd']:.2f}" if s["cost_usd"] > 0 else "  gratis"
        tag = " BLOQUEADO" if s["blocked"] else (" ⚠ CERCA" if s["pct"] >= 80 else "")
        print(f"  {s['label']:<22} [{bar}] {s['count']:>4}/{s['limit']:<4} ({s['pct']}%){cost_str}{tag}")
    print(f"\n  Total estimado este mes: ${report['total_usd']:.2f}\n")


class BudgetExceeded(Exception):
    pass
