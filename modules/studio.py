import json
import subprocess
import os
import anthropic

CLIENT = anthropic.Anthropic()
VIDEO_PROJECT = os.path.expanduser("~/scrapy/actualyza-videos")

SYSTEM_PROMPT = """You are a creative director and social media strategist for Actualyza, a company that sells AI infrastructure to clinics and medical practices. Your specialty is short-form video content (30s Reels/TikTok).

AMY is Actualyza's flagship product: an AI voice agent that answers calls 24/7, books appointments, and follows up with leads — fully automated.

Target audience: owners of dental, medical, and aesthetic clinics in the US (Miami, Orlando, Dallas). They are busy, stressed about missed calls and lost patients, and skeptical of tech solutions.

Your videos follow a 5-scene structure (30s total):
1. HOOK (3s): Brutal, specific pain point. Two short lines max.
2. PROBLEM (5s): 3 statistics that quantify the pain. Short values + labels.
3. AMY IN ACTION (11s): A realistic chat conversation showing AMY handling the exact problem. Max 4 messages. Footer line: time/context that makes it powerful.
4. RESULT (6s): One big stat (format: number+×) + label + 3 mini supporting stats.
5. CTA (5s): Action button text + URL.

Always output a SINGLE valid JSON object. No markdown, no explanation, just the JSON."""

CALENDAR = [
  # WEEK 1-2: DOLOR
  {"id": "A1", "week": 1, "pillar": "Dolor", "concept": "Every missed call is a missed patient — the core problem video"},
  {"id": "A2", "week": 1, "pillar": "Dolor", "concept": "It's 11pm. Your competition just booked 3 patients. You didn't."},
  {"id": "A3", "week": 2, "pillar": "Dolor", "concept": "The math: how much money your clinic loses per month from missed calls"},
  # WEEK 3-4: PRUEBA
  {"id": "B1", "week": 3, "pillar": "Prueba", "concept": "AMY handles 3 simultaneous calls — what that looks like"},
  {"id": "B2", "week": 3, "pillar": "Prueba", "concept": "Lead comes in at midnight → AMY calls in 28 seconds → appointment booked"},
  {"id": "B3", "week": 4, "pillar": "Prueba", "concept": "Patient didn't pick up — AMY follows up 3 times automatically"},
  # WEEK 5-6: RESULTADO
  {"id": "C1", "week": 5, "pillar": "Resultado", "concept": "$2,160/month in lost patients — and how AMY gets it back"},
  {"id": "C2", "week": 5, "pillar": "Resultado", "concept": "30 days with AMY: the timeline of what changes"},
  {"id": "C3", "week": 6, "pillar": "Resultado", "concept": "Receptionist vs AMY: cost comparison that makes the decision obvious"},
  # WEEK 7-8: OBJECIONES
  {"id": "D1", "week": 7, "pillar": "Objeción", "concept": "'But I already have a receptionist' — handled in 15 seconds"},
  {"id": "D2", "week": 7, "pillar": "Objeción", "concept": "'It sounds robotic' — play AMY's actual voice"},
  {"id": "D3", "week": 8, "pillar": "Objeción", "concept": "'It's too expensive' — the ROI calculator on screen"},
  # WEEK 9-10: ESPECIALIDAD
  {"id": "E1", "week": 9, "pillar": "Especialidad", "concept": "Dental clinics: the specific problem of no-shows and how AMY reduces them 80%"},
  {"id": "E2", "week": 9, "pillar": "Especialidad", "concept": "Aesthetic clinics: high-ticket appointments + AMY qualification before booking"},
  {"id": "E3", "week": 10, "pillar": "Especialidad", "concept": "Medical practices: after-hours emergency triage + AMY routing"},
  # WEEK 11-12: CIERRE
  {"id": "F1", "week": 11, "pillar": "Cierre", "concept": "Free trial CTA: what you get in 14 days, zero risk"},
  {"id": "F2", "week": 11, "pillar": "Cierre", "concept": "The setup is 48 hours. Your clinic runs itself in 72."},
  {"id": "F3", "week": 12, "pillar": "Cierre", "concept": "Final urgency: clinics on the waitlist. Spots limited."},
]


def generate_video_config(concept: str) -> dict:
    """Ask Claude to generate a full VideoConfig JSON for the given concept."""
    message = CLIENT.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"""Generate a complete VideoConfig JSON for this video concept:

"{concept}"

The JSON must follow this exact structure:
{{
  "hook": {{"line1": "...", "line2": "..."}},
  "problem": {{
    "intro": "...",
    "stats": [
      {{"value": "XX%", "label": "..."}},
      {{"value": "$XXX", "label": "..."}},
      {{"value": "XXX", "label": "..."}}
    ]
  }},
  "chat": {{
    "label": "Active — answering now",
    "messages": [
      {{"from": "patient", "text": "...", "delay": 20}},
      {{"from": "amy", "text": "...", "delay": 60}},
      {{"from": "patient", "text": "...", "delay": 110}},
      {{"from": "amy", "text": "✅ ...", "delay": 150}}
    ],
    "footer": "..."
  }},
  "result": {{
    "mainStat": "3",
    "mainLabel": "...",
    "subStats": [
      {{"n": "100%", "l": "..."}},
      {{"n": "<30s", "l": "..."}},
      {{"n": "24/7", "l": "..."}}
    ]
  }},
  "cta": {{"button": "Start Free Trial — 14 days", "url": "actualyza.com"}},
  "voice": {{"script": "30-second voiceover script that matches all 5 scenes..."}},
  "social": {{
    "description": "Full Instagram/TikTok caption with line breaks and emojis...",
    "hashtags": ["#Tag1", "#Tag2", "#Tag3", "#Tag4", "#Tag5", "#Tag6", "#Tag7", "#Tag8", "#Tag9", "#Tag10"],
    "bestTime": "Day and time recommendation with brief reason",
    "hookText": "First line for the caption (the scroll-stopper)"
  }}
}}

Return ONLY the JSON. No markdown fences, no explanation."""
        }]
    )
    raw = message.content[0].text.strip()
    return json.loads(raw)


def stream_studio_generate(concept: str):
    """Generator: yields SSE events for the full video creation pipeline."""

    yield f"data: {json.dumps({'type': 'start', 'msg': 'Generating video concept...'})}\n\n"

    try:
        config = generate_video_config(concept)
        yield f"data: {json.dumps({'type': 'config', 'config': config})}\n\n"
        yield f"data: {json.dumps({'type': 'log', 'msg': 'Script and social copy ready ✓'})}\n\n"

        # Write config to video project for local rendering
        config_path = os.path.join(VIDEO_PROJECT, "render-config.json")
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        yield f"data: {json.dumps({'type': 'log', 'msg': 'Config saved to video project ✓'})}\n\n"

        # Build the render command
        props_json = json.dumps(config).replace("'", "\\'")
        render_cmd = f"cd ~/scrapy/actualyza-videos && railway run node scripts/generate-audio.js && npx remotion render src/index.ts AmyReel out/video-latest.mp4 --props='{props_json}'"

        yield f"data: {json.dumps({'type': 'done', 'render_cmd': render_cmd, 'config': config})}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'msg': str(e)})}\n\n"


def get_calendar():
    return CALENDAR
