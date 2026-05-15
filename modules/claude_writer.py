"""
Generador de emails de campaña usando Claude.
Escribe como Alicia, representante de AMY AI.
"""

import json
import os
import anthropic

_CLIENT = None

def _client() -> anthropic.Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY", ""))
    return _CLIENT


_SYSTEM = """You are Alicia, a Growth Specialist at AMY AI.

AMY AI is an AI receptionist built specifically for dental, aesthetic, and medical spa clinics. It calls leads from Meta Ads within seconds after they fill out a form — 24/7, bilingual (English/Spanish), schedules appointments automatically in the clinic's real calendar, and generates AI-powered lead summaries so the team knows exactly who to follow up with and why.

The core problem AMY solves: clinics spend thousands on Meta Ads and lose 60-70% of leads because no one calls back fast enough. The first to respond wins. AMY responds in under 30 seconds, at 2am if needed, handling 50 calls simultaneously without extra staff cost.

Your job is to write short, direct, personalized cold outreach emails to clinic owners and managers.

Writing rules:
- Never start with "I hope this email finds you well" or any filler opener
- 3–4 short paragraphs max — busy clinic managers skim, not read
- Be specific to THIS clinic's situation (ads status, rating, specialty, city)
- One clear but soft CTA per email — reply to this email or a 15-min call
- Consultative tone: you're diagnosing a problem, not pitching
- English always. Natural and human, not corporate.
- Sign as Alicia — no last name, just Growth Specialist at AMY AI
- Do NOT include phone numbers, website links (except a calendar link if CTA is a call), or unsubscribe lines (those are added automatically)

Return valid JSON only — no markdown, no explanation:
{"subject": "...", "body_html": "...", "body_text": "..."}

body_html must be clean HTML paragraphs (<p> tags only, no divs, no inline styles).
body_text is the plain-text version."""


_EMAIL_PROMPTS = [
    # Email 1 — Day 0: Introduction
    """Email #1 in a 4-email sequence. This is the first contact.

Clinic info:
- Name: {name}
- Type: {categoria} clinic
- City: {ciudad}
- Google Rating: {rating} stars ({reviews} reviews)
- Running Meta Ads: {ads_status}
- Owner/Manager name available: {has_owner}

Write the introduction email. Open with a sharp, specific observation about their situation (their ad spend or lack of it, their rating, their specialty). Introduce AMY in one sentence — not a full pitch. End with one soft question that invites a reply.""",

    # Email 2 — Day 3: Follow-up (no open)
    """Email #2 in a 4-email sequence. The first email was NOT opened.

Clinic info:
- Name: {name}
- Type: {categoria} clinic
- City: {ciudad}
- Running Meta Ads: {ads_status}

This is a follow-up to an email that went unread. Use a completely different angle and subject line. Be brief — 2 paragraphs max. Reference a specific, concrete number or outcome (e.g., "the average {categoria} clinic loses 12-15 leads/month to slow follow-up"). One question CTA.""",

    # Email 2b — Day 2: Follow-up (was opened)
    """Email #2 in a 4-email sequence. The first email WAS opened but not replied to.

Clinic info:
- Name: {name}
- Type: {categoria} clinic
- City: {ciudad}
- Running Meta Ads: {ads_status}

They read the first email but didn't reply. Reference that you sent something recently without being weird about it. Go one level deeper on the specific pain — the cost of slow response time in their specialty. Invite a 15-minute call.""",

    # Email 3 — Day 7: Social proof / specific pain
    """Email #3 in a 4-email sequence. Two previous emails sent.

Clinic info:
- Name: {name}
- Type: {categoria} clinic
- City: {ciudad}
- Running Meta Ads: {ads_status}

This is the "proof" email. Use a brief, realistic mini-story about a similar {categoria} clinic in a comparable market that improved their lead conversion with faster follow-up. Keep it to 2-3 sentences — not a case study, just a reference. Connect directly to their situation. Ask if this pattern sounds familiar.""",

    # Email 4 — Day 12: Last touch
    """Email #4 — the final email in the sequence. Last contact before stopping.

Clinic info:
- Name: {name}
- Type: {categoria} clinic
- City: {ciudad}

Write a respectful, short "last note" email. 2 paragraphs max. Acknowledge this is the last email. Leave the door open gracefully — if the timing isn't right now, they can reach out when it is. No pressure. Short and human.""",
]

_ADS_STATUS = {
    "Sí":           "YES — they are actively running Meta Ads",
    "No":           "NO — they are not running Meta Ads",
    "Sin verificar": "UNKNOWN — could not verify ad activity",
    "":             "UNKNOWN — could not verify ad activity",
}


def write_email(
    clinic: dict,
    email_num: int,
    previous_opened: bool = False,
) -> dict:
    """
    Genera un email personalizado para el paso email_num de la secuencia (1–4).
    email_num=2 + previous_opened=True → usa el prompt 2b (abrió pero no respondió).
    Retorna: {"subject": str, "body_html": str, "body_text": str}
    """
    if email_num < 1 or email_num > 4:
        raise ValueError(f"email_num must be 1–4, got {email_num}")

    if email_num == 2 and previous_opened:
        prompt_template = _EMAIL_PROMPTS[2]   # 2b
    else:
        prompt_template = _EMAIL_PROMPTS[email_num - 1]

    ads_raw = clinic.get("corre_anuncios") or clinic.get("inversion") or ""
    ads_status = _ADS_STATUS.get(ads_raw, _ADS_STATUS[""])

    prompt = prompt_template.format(
        name      = clinic.get("nombre", "the clinic"),
        categoria = _cat_label(clinic.get("categoria", "")),
        ciudad    = clinic.get("ciudad", ""),
        rating    = clinic.get("rating") or "not available",
        reviews   = clinic.get("reviews") or "0",
        ads_status= ads_status,
        has_owner = "yes" if clinic.get("dueno") else "no",
    )

    msg = _client().messages.create(
        model      = "claude-haiku-4-5-20251001",
        max_tokens = 1024,
        system     = _SYSTEM,
        messages   = [{"role": "user", "content": prompt}],
    )

    raw = msg.content[0].text.strip()

    # Strip markdown code fences if Claude adds them
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


def _cat_label(cat: str) -> str:
    return {
        "dental":   "dental",
        "estetica": "aesthetic",
        "medspa":   "med spa",
        "wellness": "wellness",
    }.get(cat, cat or "medical")
