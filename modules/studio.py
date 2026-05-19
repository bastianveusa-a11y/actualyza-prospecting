import json
import os
import anthropic

CLIENT = anthropic.Anthropic()
VIDEO_PROJECT = os.path.expanduser("~/scrapy/actualyza-videos")

SYSTEM_PROMPT = """You are a creative director and social media strategist for Actualyza, a company that sells AI infrastructure to clinics and medical practices. Your specialty is short-form vertical video (30s Reels/TikTok).

AMY is Actualyza's flagship product: an AI voice agent that answers calls 24/7, books appointments, and follows up with leads — fully automated.

Target audience: owners of dental, medical, and aesthetic clinics in the US (Miami, Orlando, Dallas). They are busy, stressed about missed calls and lost patients, skeptical of tech.

SCENE TIMING (30fps, 900 frames total):
- S1 HOOK:    0–75   (2.5s) — Two lines. Line1: Inter Black 900. Line2: Playfair italic gradient. Optional subline (light, 300).
- REHOOK:     75–120 (1.5s) — Auto-generated pattern interrupt (62% stat), no copy needed.
- S2 PROBLEM: 120–270 (5s) — 3 stats. Value: Inter Black 900, huge. Label: Playfair italic, soft.
- S3 AMY:     270–480 (7s) — Chat. AMY messages: Playfair italic. Patient: Inter light. Delays: 10/35/65/90.
- S4 RESULT:  480–690 (7s) — Animated counter + label + 3 mini stats.
- S5 CTA:     690–900 (7s) — Logo + gradient button + URL (Playfair italic).

TYPOGRAPHY RULE: Mix Inter Black (900) for numbers/impact + Playfair Display italic for emotion/AMY voice/copy.

SUBTITLE CHUNKS: 12 timed captions covering the full 900 frames. Each chunk: {start, end, text}. Keep text short (max 6 words). Spread evenly across scenes.

Generate BOTH English (lang:"en") and Spanish (lang:"es") configs in one response.

Always output a SINGLE valid JSON with two keys: "en" and "es". No markdown, no explanation."""

CALENDAR = [
  {"id": "A1", "week": 1,  "pillar": "Dolor",      "concept": "3 patients called today. 3 hung up. Show the exact dollar amount lost."},
  {"id": "A2", "week": 1,  "pillar": "Dolor",      "concept": "It's 11pm. Your competition just booked 3 patients while you slept."},
  {"id": "A3", "week": 2,  "pillar": "Dolor",      "concept": "The math: how much your clinic loses per month from missed calls. Show the calculator."},
  {"id": "B1", "week": 3,  "pillar": "Prueba",     "concept": "AMY handles 3 simultaneous calls at 2am. Show the chat in real time."},
  {"id": "B2", "week": 3,  "pillar": "Prueba",     "concept": "Lead comes in at midnight → AMY calls in 28 seconds → appointment booked. Full flow."},
  {"id": "B3", "week": 4,  "pillar": "Prueba",     "concept": "Patient didn't pick up — AMY follows up 3 times automatically. Show each attempt."},
  {"id": "C1", "week": 5,  "pillar": "Resultado",  "concept": "$2,160/month in lost patients — and exactly how AMY gets it back."},
  {"id": "C2", "week": 5,  "pillar": "Resultado",  "concept": "30 days with AMY: the timeline of what changes week by week."},
  {"id": "C3", "week": 6,  "pillar": "Resultado",  "concept": "Receptionist vs AMY: side-by-side cost and availability comparison."},
  {"id": "D1", "week": 7,  "pillar": "Objeción",   "concept": "'But I already have a receptionist' — handled in 15 seconds with facts."},
  {"id": "D2", "week": 7,  "pillar": "Objeción",   "concept": "'It sounds robotic' — play AMY's actual conversation, let them hear it."},
  {"id": "D3", "week": 8,  "pillar": "Objeción",   "concept": "'It's too expensive' — ROI calculator on screen, math does the selling."},
  {"id": "E1", "week": 9,  "pillar": "Especialidad","concept": "Dental clinics: no-shows cost $300 each. AMY reduces them 80% with reminders."},
  {"id": "E2", "week": 9,  "pillar": "Especialidad","concept": "Aesthetic clinics: high-ticket appointments + AMY qualifies before booking."},
  {"id": "E3", "week": 10, "pillar": "Especialidad","concept": "Medical practices: after-hours patient routing + emergency triage with AMY."},
  {"id": "F1", "week": 11, "pillar": "Cierre",     "concept": "Free trial CTA: what happens in the first 14 days, step by step."},
  {"id": "F2", "week": 11, "pillar": "Cierre",     "concept": "Setup takes 48 hours. Your clinic runs itself in 72. Show the timeline."},
  {"id": "F3", "week": 12, "pillar": "Cierre",     "concept": "Final urgency: limited spots available. Waitlist is growing. Act now."},
]

CONFIG_TEMPLATE = {
    "lang": "en",
    "hook": {"line1": "...", "line2": "...", "subline": "..."},
    "problem": {
        "intro": "...",
        "stats": [
            {"value": "XX%", "label": "short label"},
            {"value": "$XXX", "label": "short label"},
            {"value": "XX", "label": "short label"},
        ],
    },
    "chat": {
        "label": "Active — answering now",
        "messages": [
            {"from": "patient", "text": "...", "delay": 10},
            {"from": "amy",     "text": "...", "delay": 35},
            {"from": "patient", "text": "...", "delay": 65},
            {"from": "amy",     "text": "✅ ...", "delay": 90},
        ],
        "footer": "...",
    },
    "result": {
        "mainStat": "3",
        "mainLabel": "...",
        "subStats": [
            {"n": "100%", "l": "calls answered"},
            {"n": "<30s", "l": "response time"},
            {"n": "24/7", "l": "always on"},
        ],
    },
    "cta": {"button": "Start Free Trial — 14 days", "url": "actualyza.com"},
    "voice": {"script": "30-second voiceover script matching all 5 scenes..."},
    "subtitles": [
        {"start": 0,   "end": 55,  "text": "max 6 words"},
        {"start": 55,  "end": 90,  "text": "max 6 words"},
        {"start": 90,  "end": 150, "text": "max 6 words"},
        {"start": 150, "end": 210, "text": "max 6 words"},
        {"start": 210, "end": 270, "text": "max 6 words"},
        {"start": 270, "end": 360, "text": "max 6 words"},
        {"start": 360, "end": 430, "text": "max 6 words"},
        {"start": 430, "end": 510, "text": "max 6 words"},
        {"start": 510, "end": 600, "text": "max 6 words"},
        {"start": 600, "end": 690, "text": "max 6 words"},
        {"start": 690, "end": 810, "text": "max 6 words"},
        {"start": 810, "end": 900, "text": "actualyza.com"},
    ],
    "social": {
        "description": "Full caption with emojis and line breaks...",
        "hashtags": ["#Tag1","#Tag2","#Tag3","#Tag4","#Tag5","#Tag6","#Tag7","#Tag8","#Tag9","#Tag10"],
        "bestTime": "Day/time + brief reason",
        "hookText": "First scroll-stopping line",
    },
}


def generate_video_configs(concept: str) -> dict:
    """Returns {'en': VideoConfig, 'es': VideoConfig}."""
    template_str = json.dumps({"en": CONFIG_TEMPLATE, "es": {**CONFIG_TEMPLATE, "lang": "es"}}, indent=2)
    message = CLIENT.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"""Generate complete VideoConfig JSON for BOTH English and Spanish for this concept:

"{concept}"

Follow this exact structure (fill in all "..." fields):
{template_str}

Rules:
- Hook line1: short, punchy, specific number or fact (Inter Black style — direct, brutal)
- Hook line2: emotional gut-punch (Playfair italic style — dramatic, personal)
- Hook subline: quantifies the pain (e.g. "That's $540 gone.")
- Chat delays MUST be: 10, 35, 65, 90 (faster pacing for retention)
- Subtitles: 12 chunks, max 6 words each, match the voiceover script timing
- Spanish: translate concept + adapt culturally, don't just translate word-for-word
- CTA button EN: "Start Free Trial — 14 days" | ES: "Prueba Gratis — 14 días"
- Return ONLY valid JSON with keys "en" and "es". No markdown."""
        }]
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw)


def stream_studio_generate(concept: str):
    """Generator: yields SSE events for the full video creation pipeline."""

    yield f"data: {json.dumps({'type': 'start', 'msg': 'Generating EN + ES configs...'})}\n\n"

    try:
        configs = generate_video_configs(concept)
        config_en = configs.get("en", {})
        config_es = configs.get("es", {})

        yield f"data: {json.dumps({'type': 'configs', 'en': config_en, 'es': config_es})}\n\n"
        yield f"data: {json.dumps({'type': 'log', 'msg': 'Scripts and social copy ready ✓'})}\n\n"

        # Save both configs to video project
        config_path = os.path.join(VIDEO_PROJECT, "render-config.json")
        with open(config_path, "w") as f:
            json.dump({"en": config_en, "es": config_es}, f, indent=2)
        yield f"data: {json.dumps({'type': 'log', 'msg': 'Configs saved to video project ✓'})}\n\n"

        # Build render commands for both
        props_en = json.dumps(config_en).replace("'", "\\'")
        props_es = json.dumps(config_es).replace("'", "\\'")

        cmd_en = (
            f"cd ~/scrapy/actualyza-videos && "
            f"railway run npm run audio:en && "
            f"npx remotion render src/index.ts AmyReel-EN out/video-en.mp4 --props='{props_en}'"
        )
        cmd_es = (
            f"cd ~/scrapy/actualyza-videos && "
            f"railway run npm run audio:es && "
            f"npx remotion render src/index.ts AmyReel-ES out/video-es.mp4 --props='{props_es}'"
        )

        yield f"data: {json.dumps({'type': 'done', 'cmd_en': cmd_en, 'cmd_es': cmd_es, 'en': config_en, 'es': config_es})}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'msg': str(e)})}\n\n"


def get_calendar():
    return CALENDAR
