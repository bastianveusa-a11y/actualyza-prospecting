"""
Consejo Estratégico — motor de 8 agentes, 3 rondas, Claude only.
Todas las respuestas son bloqueantes; el caller hace streaming vía SSE.
"""

import json
import os
import queue
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import anthropic

DB_PATH = Path(__file__).parent.parent / "data" / "consejo.db"

CLAUDE_MODEL_FAST   = "claude-haiku-4-5-20251001"   # R1 y R2 — velocidad
CLAUDE_MODEL_JUDGE  = "claude-sonnet-4-6"            # R3 — calidad

SEATS = [
    {
        "id": 1, "name": "FINANZAS", "tag": "finanzas", "color": "green",
        "icon": "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z",
        "prompt": (
            "Eres el asiento de FINANZAS del Consejo Estratégico.\n\n"
            "Tu rol: analizar costos, márgenes, break-even y viabilidad financiera. El número manda.\n\n"
            "Reglas:\n"
            "- Marca cada cifra con [DATO] si es verificable o [SUPUESTO] si la estás asumiendo. Prohibido inventar con seguridad.\n"
            "- Incluye siempre: estructura de costos estimada, margen bruto, punto de break-even, y si aplica comisión de pasarela (Stripe: ~2.9% + $0.30/transacción en EE.UU.).\n"
            "- Español directo. Sin relleno corporativo. Sin yes-man.\n"
            "- Máximo 220 palabras."
        ),
    },
    {
        "id": 2, "name": "MERCADO", "tag": "mercado", "color": "blue",
        "icon": "M3.5 18.5l6-6 4 4L22 6.92M22 6.92V11m0-4.08H17.92",
        "prompt": (
            "Eres el asiento de MERCADO del Consejo Estratégico.\n\n"
            "Tu rol: competencia, posicionamiento y tamaño real de mercado.\n\n"
            "Reglas:\n"
            "- Marca [DATO] o [SUPUESTO] en toda cifra o claim de mercado.\n"
            "- Analiza: ¿quién más hace esto?, ¿cómo se diferencia esta propuesta?, ¿hay demanda real o es crear mercado desde cero?\n"
            "- Español directo. Sin yes-man.\n"
            "- Máximo 220 palabras."
        ),
    },
    {
        "id": 3, "name": "CLIENTE", "tag": "cliente", "color": "teal",
        "icon": "M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2M12 11a4 4 0 100-8 4 4 0 000 8z",
        "prompt": (
            "Eres el asiento de CLIENTE del Consejo Estratégico.\n\n"
            "Tu rol: simular al comprador real — sus miedos, objeciones y proceso de decisión.\n\n"
            "Reglas:\n"
            "- Habla como si fueras el cliente mirando esta propuesta. Primera persona plural ('nosotros los clientes...').\n"
            "- Lista al menos 3 objeciones concretas que tendrías antes de comprar.\n"
            "- ¿Qué te haría decir sí? ¿Qué te haría salir corriendo?\n"
            "- Marca [SUPUESTO] si asumes algo sobre el cliente que no está confirmado.\n"
            "- Español directo. Máximo 220 palabras."
        ),
    },
    {
        "id": 4, "name": "MARKETING", "tag": "marketing", "color": "orange",
        "icon": "M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z",
        "prompt": (
            "Eres el asiento de MARKETING & ADQUISICIÓN del Consejo Estratégico.\n\n"
            "Tu rol: canales, funnel de venta y costo de adquisición de cliente (CAC).\n\n"
            "Reglas:\n"
            "- Analiza: ¿cómo llegas al primer cliente?, ¿qué canal tiene mejor relación CAC/LTV?, ¿cuánto cuesta adquirir uno?\n"
            "- Marca [DATO] o [SUPUESTO] en toda cifra de CAC, conversión o volumen.\n"
            "- Español directo. Sin términos de marketing sin sustancia.\n"
            "- Máximo 220 palabras."
        ),
    },
    {
        "id": 5, "name": "RETENCIÓN", "tag": "retencion", "color": "purple",
        "icon": "M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z",
        "prompt": (
            "Eres el asiento de RETENCIÓN del Consejo Estratégico.\n\n"
            "Tu rol: recompra, reducción de churn y nurturing post-venta.\n\n"
            "Reglas:\n"
            "- Analiza: ¿por qué el cliente se va?, ¿qué lo hace volver?, ¿hay mécanismo de recompra natural o hay que forzarlo?\n"
            "- Calcula o estima el LTV (Lifetime Value) aunque sea a grandes rasgos.\n"
            "- Marca [DATO] o [SUPUESTO] en toda cifra.\n"
            "- Español directo. Máximo 220 palabras."
        ),
    },
    {
        "id": 6, "name": "ESTRATEGIA", "tag": "estrategia", "color": "gold",
        "icon": "M13 10V3L4 14h7v7l9-11h-7z",
        "prompt": (
            "Eres el asiento de ESTRATEGIA & MODELO del Consejo Estratégico.\n\n"
            "Tu rol: visión a 24 meses — ¿esto escala?, ¿es defendible?, ¿qué modelo de negocio encaja mejor?\n\n"
            "Reglas:\n"
            "- Evalúa: barreras de entrada, ventaja competitiva sostenible, cómo se ve esto en 12 y 24 meses.\n"
            "- ¿Es un negocio o un proyecto? ¿Puede correr sin el dueño?\n"
            "- Marca [SUPUESTO] en todo lo que proyectes sin datos duros.\n"
            "- Español directo. Máximo 220 palabras."
        ),
    },
    {
        "id": 7, "name": "EL ESCÉPTICO", "tag": "esceptico", "color": "red",
        "icon": "M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z",
        "prompt": (
            "Eres EL ESCÉPTICO del Consejo Estratégico.\n\n"
            "Tu rol: atacar la idea. Buscar los supuestos frágiles, los agujeros que nadie quiere ver, y lo que se puede caer.\n\n"
            "Reglas:\n"
            "- No suavices. No equilibres con elogios. Tu trabajo es destruir argumentos débiles, no criticar educadamente.\n"
            "- Haz al menos 2 preguntas específicas y difíciles que el dueño de la idea no ha podido contestar aún.\n"
            "- Marca [SUPUESTO] en todo lo que el presentador asume sin datos.\n"
            "- Español directo y sin filtro. Máximo 200 palabras."
        ),
    },
]

JUDGE = {
    "id": 8, "name": "EL JUEZ", "tag": "juez", "color": "gold",
    "prompt": (
        "Eres EL JUEZ del Consejo Estratégico.\n\n"
        "Tu rol: no opinaste en rondas 1 y 2. Ahora lees todo lo que dijeron los 7 asientos y entregas el veredicto final.\n\n"
        "El veredicto DEBE tener exactamente estas secciones con estos encabezados:\n"
        "CONSENSO: en qué están de acuerdo la mayoría de los asientos.\n"
        "CONFLICTO REAL: la tensión más importante sin resolver entre asientos.\n"
        "RECOMENDACIÓN: qué hacer. Una sola línea clara, sin ambigüedad.\n"
        "RIESGO PRINCIPAL: el mayor peligro identificado en todo el debate.\n"
        "DATO QUE FALTA: qué información específica cambiaría esta decisión.\n"
        "SI FUERA TÚ: una instrucción concreta en primera persona — qué harías mañana.\n\n"
        "Reglas:\n"
        "- Marca [DATO] o [SUPUESTO] en toda cifra.\n"
        "- Sin rodeos. Sin diplomacia innecesaria. Español directo.\n"
        "- Máximo 380 palabras."
    ),
}


def _init_db() -> None:
    DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS consultas (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                ts   TEXT NOT NULL,
                question TEXT NOT NULL,
                result   TEXT NOT NULL
            )
        """)


def _save_consulta(question: str, result: dict) -> int:
    _init_db()
    with sqlite3.connect(DB_PATH) as db:
        cur = db.execute(
            "INSERT INTO consultas (ts, question, result) VALUES (?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), question, json.dumps(result, ensure_ascii=False)),
        )
        return cur.lastrowid


def get_history(limit: int = 20) -> list[dict]:
    _init_db()
    with sqlite3.connect(DB_PATH) as db:
        rows = db.execute(
            "SELECT id, ts, question FROM consultas ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"id": r[0], "ts": r[1], "question": r[2]} for r in rows]


def get_consulta(consulta_id: int) -> dict | None:
    _init_db()
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute(
            "SELECT id, ts, question, result FROM consultas WHERE id = ?", (consulta_id,)
        ).fetchone()
    if not row:
        return None
    return {"id": row[0], "ts": row[1], "question": row[2], "result": json.loads(row[3])}


def _call_claude(system_prompt: str, user_message: str, model: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["CLAUDE_API_KEY"])
    msg = client.messages.create(
        model=model,
        max_tokens=700,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return msg.content[0].text.strip()


def _run_seat_r1(seat: dict, question: str) -> dict:
    content = _call_claude(
        seat["prompt"],
        f"La decisión o pregunta a debatir:\n\n{question}",
        CLAUDE_MODEL_FAST,
    )
    return {"id": seat["id"], "name": seat["name"], "tag": seat["tag"],
            "color": seat["color"], "round": 1, "content": content}


def _run_seat_r2(seat: dict, question: str, r1_results: list[dict]) -> dict:
    others = "\n\n".join(
        f"[{r['name']}]: {r['content']}"
        for r in r1_results if r["id"] != seat["id"]
    )
    user_msg = (
        f"La decisión a debatir:\n\n{question}\n\n"
        f"--- Lo que dijeron los otros asientos en Ronda 1 ---\n\n{others}\n\n"
        "Tu turno en Ronda 2: lee las posiciones anteriores. "
        "Ataca el argumento más débil que veas, defiende o refina tu posición con nueva evidencia. "
        "Puedes cambiar de opinión si los datos lo justifican, pero dilo explícitamente."
    )
    content = _call_claude(seat["prompt"], user_msg, CLAUDE_MODEL_FAST)
    return {"id": seat["id"], "name": seat["name"], "tag": seat["tag"],
            "color": seat["color"], "round": 2, "content": content}


def _run_judge(question: str, r1: list[dict], r2: list[dict]) -> dict:
    all_rounds = "\n\n".join(
        f"[{r['name']} — Ronda {r['round']}]: {r['content']}"
        for r in (r1 + r2)
    )
    user_msg = (
        f"La decisión debatida:\n\n{question}\n\n"
        f"--- Debate completo (Rondas 1 y 2) ---\n\n{all_rounds}\n\n"
        "Entrega el veredicto final."
    )
    content = _call_claude(JUDGE["prompt"], user_msg, CLAUDE_MODEL_JUDGE)
    return {"id": 8, "name": "EL JUEZ", "tag": "juez", "color": "gold", "round": 3, "content": content}


def stream_consejo(question: str):
    """
    Generator que hace yield de eventos SSE.
    Corre R1 y R2 en paralelo (7 threads), R3 en serie (El Juez).
    """
    q: queue.Queue = queue.Queue()
    r1_results: list[dict] = []
    r2_results: list[dict] = []

    def _yield_event(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    yield _yield_event({"type": "start", "round": 1, "total_seats": 7})

    # ── Ronda 1 — paralela ────────────────────────────────────────
    r1_done = [0]
    lock = threading.Lock()

    def _r1_worker(seat):
        try:
            result = _run_seat_r1(seat, question)
        except Exception as exc:
            result = {"id": seat["id"], "name": seat["name"], "tag": seat["tag"],
                      "color": seat["color"], "round": 1,
                      "content": f"[Error: {exc}]", "error": True}
        with lock:
            r1_results.append(result)
            r1_done[0] += 1
        q.put(("seat", result))

    threads = [threading.Thread(target=_r1_worker, args=(s,), daemon=True) for s in SEATS]
    for t in threads:
        t.start()

    delivered = 0
    while delivered < 7:
        kind, data = q.get()
        if kind == "seat":
            yield _yield_event({"type": "seat", **data})
            delivered += 1

    yield _yield_event({"type": "round_done", "round": 1})

    # ── Ronda 2 — paralela ────────────────────────────────────────
    yield _yield_event({"type": "start", "round": 2, "total_seats": 7})

    r2_done = [0]

    def _r2_worker(seat):
        try:
            result = _run_seat_r2(seat, question, r1_results)
        except Exception as exc:
            result = {"id": seat["id"], "name": seat["name"], "tag": seat["tag"],
                      "color": seat["color"], "round": 2,
                      "content": f"[Error: {exc}]", "error": True}
        with lock:
            r2_results.append(result)
            r2_done[0] += 1
        q.put(("seat", result))

    threads2 = [threading.Thread(target=_r2_worker, args=(s,), daemon=True) for s in SEATS]
    for t in threads2:
        t.start()

    delivered2 = 0
    while delivered2 < 7:
        kind, data = q.get()
        if kind == "seat":
            yield _yield_event({"type": "seat", **data})
            delivered2 += 1

    yield _yield_event({"type": "round_done", "round": 2})

    # ── Ronda 3 — El Juez ────────────────────────────────────────
    yield _yield_event({"type": "start", "round": 3, "total_seats": 1})
    try:
        verdict = _run_judge(question, r1_results, r2_results)
        yield _yield_event({"type": "seat", **verdict})
    except Exception as exc:
        yield _yield_event({"type": "error", "message": str(exc)})
        return

    yield _yield_event({"type": "round_done", "round": 3})

    # ── Guardar en historial ──────────────────────────────────────
    try:
        all_seats = r1_results + r2_results + [verdict]
        consulta_id = _save_consulta(question, {"seats": all_seats})
        yield _yield_event({"type": "done", "consulta_id": consulta_id})
    except Exception:
        yield _yield_event({"type": "done", "consulta_id": None})
