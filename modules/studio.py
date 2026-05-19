import json
import os
import re
import anthropic
from datetime import datetime

CLIENT = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
)
VIDEO_PROJECT = os.path.expanduser("~/scrapy/actualyza-videos")

SYSTEM_PROMPT = """You are a creative director and social media strategist for Actualyza. Your specialty is short-form vertical video (30s Reels/TikTok) that converts clinic owners into customers.

━━━ WHAT ACTUALYZA IS ━━━
Actualyza is a complete AI infrastructure company — NOT just a voice agent. We build and deploy fully customized AI systems for clinics and medical practices. Every deployment is tailored to the client's business: their voice, their workflows, their CRM, their pricing.

The flagship product is called AMY — but AMY is the face of a full infrastructure stack:

CORE CAPABILITIES (all customizable per client):
1. AI Voice Agent (AMY) — answers every call 24/7, speaks the caller's language naturally (10+ languages: English, Spanish, Portuguese, French, Mandarin, and more). Never misses a call. 2am, Sundays, holidays.
2. Real-time appointment booking — connects to Cal.com, checks availability live, books during the call, sends automatic email confirmation. Under 60 seconds.
3. Automatic lead follow-up — every hour, reviews the CRM and calls all uncontacted leads. Competitors take hours, AMY takes under 30 seconds.
4. AI call analysis — after every call: Lead Score 0–100, Hot/Warm/Cold temperature, urgency level, estimated payment capacity, detected objections, recommended next action. 7 data points per call.
5. Real-time dashboard — live view of calls, appointments booked, hottest leads, most requested treatments, revenue pipeline.
6. CRM integration — updates automatically after every call. Zero manual data entry.
7. Meta Ads integration — lead fills form → AMY calls in under 30 seconds automatically.
8. Full customization — AMY's voice, name, personality, treatment menu, pricing, scripts — all configured for each client's brand.

WHAT MAKES ACTUALYZA DIFFERENT FROM COMPETITORS:
- It's not a generic chatbot or off-the-shelf tool. It's a bespoke AI infrastructure.
- Clients don't manage the tech — Actualyza handles everything. They just show up to appointments.
- Setup takes 48 hours. Live in 72.
- 14-day free trial, no credit card required, fully operational from day 1.
- Multilingual by default — AMY detects the caller's language and responds naturally.
- Fraction of the cost of a human receptionist. Zero absences, errors, or sick days.

BEFORE vs AFTER ACTUALYZA:
Before: Leads not contacted for hours → AMY: contacted within 30 seconds
Before: Human agent only during business hours → AMY: 24/7, 365 days
Before: Data lost or poorly captured → CRM updated in real time
Before: Don't know which leads to prioritize → Lead Score + temperature on every call
Before: Team wastes time on cold calls → only speaks with pre-qualified leads
Before: High monthly staffing cost → fraction of the cost

TARGET AUDIENCE: Owners of dental, medical, and aesthetic clinics in the US — Miami, Orlando, Dallas. They are busy, stressed about missed calls, losing patients to competitors, and skeptical of tech promises. They need to see ROI fast and feel the pain before they'll listen to the solution.

━━━ VIDEO STRUCTURE ━━━
SCENE TIMING (30fps, 900 frames = 30 seconds):
- S1 HOOK:    0–75   (2.5s) — Specific pain point. Inter Black 900 + Playfair italic gradient. Optional subline.
- REHOOK:     75–120 (1.5s) — Auto pattern interrupt, no copy needed from you.
- S2 PROBLEM: 120–270 (5s) — 3 stats quantifying the pain. Inter Black 900 value + Playfair italic label.
- S3 AMY:     270–480 (7s) — Chat showing AMY solving the exact problem. Delays: 10/35/65/90.
- S4 RESULT:  480–690 (7s) — Big animated counter + label + 3 supporting mini stats.
- S5 CTA:     690–900 (7s) — Logo + gradient CTA button + URL.

TYPOGRAPHY RULE: Inter Black 900 for numbers/impact. Playfair Display italic for emotion, AMY's voice, and supporting copy.
SUBTITLE CHUNKS: 12 timed captions, max 6 words each, spread across all 900 frames.

Generate BOTH English (lang:"en") and Spanish (lang:"es") in one response.
Output ONLY a valid JSON with keys "en" and "es". No markdown, no explanation."""

CALENDAR = [
  # ── DOLOR (semanas 1-2) ──────────────────────────────────────
  {"id": "A1", "week": 1,  "pillar": "Dolor",       "concept": "3 patients called today. 3 hung up. Show the exact dollar amount lost and what that means per month."},
  {"id": "A2", "week": 1,  "pillar": "Dolor",       "concept": "It's 11pm. Your competitor just booked 3 patients through their AI while your phone went to voicemail."},
  {"id": "A3", "week": 2,  "pillar": "Dolor",       "concept": "Your receptionist is great — but she can't answer 3 calls at once at 2am on a Sunday. Show the gap."},
  # ── INFRAESTRUCTURA (semanas 3-4) ────────────────────────────
  {"id": "B1", "week": 3,  "pillar": "Infra",       "concept": "It's not a chatbot. Actualyza builds a complete AI infrastructure: voice agent + CRM + dashboard + analytics — all customized for your clinic."},
  {"id": "B2", "week": 3,  "pillar": "Infra",       "concept": "Real-time dashboard: see every call, every appointment booked, every hot lead — live. Your whole clinic in one panel."},
  {"id": "B3", "week": 4,  "pillar": "Infra",       "concept": "After every call: Lead Score 0-100, temperature Hot/Warm/Cold, objections detected, next action recommended. 7 data points, automatically."},
  # ── PRUEBA EN ACCIÓN (semanas 5-6) ───────────────────────────
  {"id": "C1", "week": 5,  "pillar": "Prueba",      "concept": "Lead fills out a Meta Ads form → AMY calls in under 30 seconds → appointment booked. Show the full automated flow."},
  {"id": "C2", "week": 5,  "pillar": "Prueba",      "concept": "AMY speaks English, Spanish, Portuguese, French, Mandarin — detects the language automatically. No accent. No hesitation."},
  {"id": "C3", "week": 6,  "pillar": "Prueba",      "concept": "Patient didn't pick up — AMY follows up automatically. Lead goes cold in 5 minutes. AMY never lets that happen."},
  # ── RESULTADO (semanas 7-8) ──────────────────────────────────
  {"id": "D1", "week": 7,  "pillar": "Resultado",   "concept": "Before Actualyza vs After: leads contacted in hours vs 30 seconds, data lost vs CRM updated in real time. Side by side."},
  {"id": "D2", "week": 7,  "pillar": "Resultado",   "concept": "Cost of a full-time receptionist vs Actualyza AI infrastructure. Show the math. Same coverage, fraction of the cost."},
  {"id": "D3", "week": 8,  "pillar": "Resultado",   "concept": "30 days with Actualyza: week-by-week timeline of what changes — calls answered, appointments booked, revenue recovered."},
  # ── OBJECIONES (semanas 9-10) ────────────────────────────────
  {"id": "E1", "week": 9,  "pillar": "Objeción",    "concept": "'But I already have a receptionist.' She can't work 24/7, speak 10 languages, and score every lead. AMY can."},
  {"id": "E2", "week": 9,  "pillar": "Objeción",    "concept": "'It sounds robotic.' No — it's fully personalized to your clinic name, voice, tone, and treatment menu."},
  {"id": "E3", "week": 10, "pillar": "Objeción",    "concept": "'Setup sounds complicated.' 48 hours to configure, 72 hours live. Actualyza handles everything. You just show up."},
  # ── ESPECIALIDAD (semanas 11-12) ─────────────────────────────
  {"id": "F1", "week": 11, "pillar": "Especialidad","concept": "Dental clinics: no-shows cost $300 each. AMY sends reminders, confirms, and reschedules automatically. 80% reduction."},
  {"id": "F2", "week": 11, "pillar": "Especialidad","concept": "Aesthetic clinics: high-ticket patients need pre-qualification. AMY screens before booking so only serious leads get through."},
  {"id": "F3", "week": 12, "pillar": "Cierre",      "concept": "14-day free trial. No credit card. Fully operational from day 1. Your AI infrastructure, live in 72 hours."},
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


def _make_slug(concept: str, cal_id: str = "") -> str:
    """Turn concept into a short filesystem-safe slug."""
    base = cal_id + "-" if cal_id else ""
    words = re.sub(r"[^a-z0-9 ]", "", concept.lower()).split()
    slug = "-".join(words[:5])
    date = datetime.now().strftime("%m%d")
    return f"{base}{slug}-{date}"


def stream_studio_generate(concept: str, cal_id: str = ""):
    """Generator: yields SSE events for the full video creation pipeline."""

    yield f"data: {json.dumps({'type': 'start', 'msg': 'Generating EN + ES configs...'})}\n\n"

    try:
        configs = generate_video_configs(concept)
        config_en = configs.get("en", {})
        config_es = configs.get("es", {})

        yield f"data: {json.dumps({'type': 'configs', 'en': config_en, 'es': config_es})}\n\n"
        yield f"data: {json.dumps({'type': 'log', 'msg': 'Scripts and social copy ready ✓'})}\n\n"

        # Build unique slug for this video
        slug = _make_slug(concept, cal_id)
        out_dir = os.path.join(VIDEO_PROJECT, "out", slug)

        # Save configs per-video (never overwritten)
        config_path = os.path.join(VIDEO_PROJECT, "out", f"{slug}.json")
        os.makedirs(os.path.join(VIDEO_PROJECT, "out"), exist_ok=True)
        with open(config_path, "w") as f:
            json.dump({"slug": slug, "concept": concept, "en": config_en, "es": config_es}, f, indent=2)
        yield f"data: {json.dumps({'type': 'log', 'msg': f'Config saved → out/{slug}.json ✓'})}\n\n"

        # Render output filenames (unique per video)
        out_en = f"out/{slug}-en.mp4"
        out_es = f"out/{slug}-es.mp4"

        props_en = json.dumps(config_en).replace("'", "\\'")
        props_es = json.dumps(config_es).replace("'", "\\'")

        cmd_en = (
            f"cd ~/scrapy/actualyza-videos && "
            f"railway run npm run audio:en && "
            f"npx remotion render src/index.ts AmyReel-EN {out_en} --props='{props_en}'"
        )
        cmd_es = (
            f"cd ~/scrapy/actualyza-videos && "
            f"railway run npm run audio:es && "
            f"npx remotion render src/index.ts AmyReel-ES {out_es} --props='{props_es}'"
        )

        yield f"data: {json.dumps({'type': 'done', 'cmd_en': cmd_en, 'cmd_es': cmd_es, 'slug': slug, 'out_en': out_en, 'out_es': out_es, 'en': config_en, 'es': config_es})}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'msg': str(e)})}\n\n"


def get_calendar():
    return CALENDAR
