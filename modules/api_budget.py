"""
Control de presupuesto de APIs.
Lleva un contador mensual por servicio y bloquea cuando se alcanza el límite.
El contador se resetea automáticamente cada mes.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

USAGE_FILE = Path(__file__).parent.parent / "data" / "api_usage.json"

# Límites mensuales por servicio
# Google Places: $200 crédito / $0.032 por request = 6,250 gratuitos
# Dejamos un margen amplio — 200 requests cuesta $6.40 (cubierto por crédito)
DEFAULTS = {
    "google_places": 3750,  # 60% de 6,250 gratuitos — margen del 40% libre
    "sunbiz":        500,   # sin costo — límite por cortesía al servidor
    "meta_scraping": 300,   # sin costo — límite por cortesía
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
    """
    Retorna el estado de uso de un servicio para el mes actual.
    {count, limit, remaining, month, blocked}
    """
    data    = _load()
    month   = _current_month()
    limit   = int(os.getenv(f"{service.upper()}_MONTHLY_LIMIT", DEFAULTS.get(service, 100)))
    entry   = data.get(service, {})

    # Reset automático si cambió el mes
    if entry.get("month") != month:
        entry = {"month": month, "count": 0}

    count     = entry.get("count", 0)
    remaining = max(0, limit - count)

    return {
        "service":   service,
        "month":     month,
        "count":     count,
        "limit":     limit,
        "remaining": remaining,
        "blocked":   remaining <= 0,
        "pct":       round(count / limit * 100, 1) if limit > 0 else 0,
    }


def increment(service: str, n: int = 1) -> dict:
    """
    Registra n requests para el servicio dado.
    Retorna el estado actualizado.
    Lanza BudgetExceeded si ya se superó el límite.
    """
    status = get_status(service)
    if status["blocked"]:
        raise BudgetExceeded(
            f"{service}: límite mensual de {status['limit']} alcanzado "
            f"(mes {status['month']}). Resetea en el próximo mes."
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

    # Alerta cuando queda menos del 20%
    if updated["remaining"] <= updated["limit"] * 0.2 and updated["remaining"] > 0:
        print(f"  ⚠ {service}: {updated['remaining']} requests restantes este mes ({updated['pct']}% usado)")

    return updated


def check(service: str) -> None:
    """Lanza BudgetExceeded si el servicio ya está bloqueado."""
    status = get_status(service)
    if status["blocked"]:
        raise BudgetExceeded(
            f"{service}: límite mensual de {status['limit']} alcanzado "
            f"(mes {status['month']})."
        )


def print_report() -> None:
    """Imprime un resumen del uso de todas las APIs este mes."""
    print(f"\n── Uso de APIs — {_current_month()} ──────────────────")
    for service in DEFAULTS:
        s = get_status(service)
        bar_filled = int(s["pct"] / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        status_tag = " BLOQUEADO" if s["blocked"] else (" ⚠ CERCA" if s["pct"] >= 80 else "")
        print(f"  {service:<20} [{bar}] {s['count']:>4}/{s['limit']:<4} ({s['pct']}%){status_tag}")
    print()


class BudgetExceeded(Exception):
    pass
