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

# EN track: TOFU-heavy start, mix in MOFU/BOFU progressively
# ES track: starts mid-funnel so EN+ES never show same pillar same day
# Each day: post EN[day] + ES[day+45] → completely different concept & pillar

_EN = [
  # TOFU — Dolor (weeks 1-3)
  {"id":"A01","funnel":"TOFU","pillar":"Dolor",      "concept":"3 patients called today. 3 hung up. Show the exact dollar amount lost and what that means per month."},
  {"id":"A02","funnel":"TOFU","pillar":"Dolor",      "concept":"It's 11pm. Your competitor just booked 3 patients through their AI while your phone went to voicemail."},
  {"id":"A03","funnel":"TOFU","pillar":"Dolor",      "concept":"Your receptionist is great — but she can't answer 3 calls at once at 2am on a Sunday. Show the gap."},
  {"id":"A04","funnel":"TOFU","pillar":"Dolor",      "concept":"A patient called, got voicemail, and booked with your competitor in under 60 seconds. This happens every day."},
  {"id":"A05","funnel":"TOFU","pillar":"Dolor",      "concept":"How many calls did your clinic miss last week? Most owners have no idea. Show them how to find out — and what it costs."},
  {"id":"A06","funnel":"TOFU","pillar":"Dolor",      "concept":"Your best lead called at 7pm Friday. Your office was closed. Monday they were already a patient somewhere else."},
  {"id":"A07","funnel":"TOFU","pillar":"Dolor",      "concept":"The average dental clinic misses 22% of incoming calls. At $300/appointment, that's $85K/year walking out the door."},
  {"id":"A08","funnel":"TOFU","pillar":"Dolor",      "concept":"No-shows cost clinics $150-400 each. Most have no system to prevent them. Show the annual bleed."},
  {"id":"A09","funnel":"TOFU","pillar":"Dolor",      "concept":"Your receptionist handles 3 things at once: a patient at the desk, a call, and the phone ringing again. One of them loses. Always."},
  {"id":"A10","funnel":"TOFU","pillar":"Dolor",      "concept":"Aesthetic clinic owners: your highest-ticket patients are the ones who hang up when they hit voicemail. They don't call back."},
  {"id":"A11","funnel":"TOFU","pillar":"Dolor",      "concept":"You're running Meta Ads. Lead fills the form. Nobody calls for 4 hours. Lead is cold. Money wasted. Show the math."},
  {"id":"A12","funnel":"TOFU","pillar":"Dolor",      "concept":"Your front desk leaves at 5pm. New leads keep coming in until 10pm. What happens to them?"},
  {"id":"A13","funnel":"TOFU","pillar":"Dolor",      "concept":"Saturday morning: your clinic is closed. 12 people searched for a dentist near them. 0 reached you. Show where they went."},
  {"id":"A14","funnel":"TOFU","pillar":"Dolor",      "concept":"The cost of one missed call: not $0. It's the lifetime value of that patient. For dental, that's $4,000-$12,000. Show the real number."},
  {"id":"A15","funnel":"TOFU","pillar":"Dolor",      "concept":"Your competitor has an AI that calls every lead within 30 seconds. You have a voicemail. That's the entire game right there."},
  # MOFU — Infra / Prueba (weeks 4-6)
  {"id":"B01","funnel":"MOFU","pillar":"Infra",      "concept":"It's not a chatbot. Actualyza builds a complete AI infrastructure: voice agent + CRM + dashboard + analytics — all customized for your clinic."},
  {"id":"B02","funnel":"MOFU","pillar":"Infra",      "concept":"Real-time dashboard: see every call, every appointment booked, every hot lead — live. Your whole clinic in one panel."},
  {"id":"B03","funnel":"MOFU","pillar":"Infra",      "concept":"After every call: Lead Score 0-100, temperature Hot/Warm/Cold, objections detected, next action recommended. 7 data points, automatically."},
  {"id":"B04","funnel":"MOFU","pillar":"Infra",      "concept":"AMY integrates with Cal.com, checks live availability, books the appointment during the call, and sends a confirmation email. All in under 60 seconds."},
  {"id":"B05","funnel":"MOFU","pillar":"Infra",      "concept":"Every hour, AMY reviews your CRM and calls every uncontacted lead. Your team only talks to pre-qualified, interested patients."},
  {"id":"B06","funnel":"MOFU","pillar":"Infra",      "concept":"Meta Ad fires → AMY gets the lead → calls in under 30 seconds → books the appointment. Zero human intervention. Show the full flow."},
  {"id":"B07","funnel":"MOFU","pillar":"Prueba",     "concept":"AMY speaks English, Spanish, Portuguese, French, Mandarin — detects the caller's language automatically. No accent. No hesitation."},
  {"id":"B08","funnel":"MOFU","pillar":"Prueba",     "concept":"Patient didn't pick up — AMY follows up automatically every hour. Leads go cold in 5 minutes. AMY never lets that happen."},
  {"id":"B09","funnel":"MOFU","pillar":"Prueba",     "concept":"Watch AMY book a full appointment in real time: patient calls, asks about pricing, gets answers, picks a slot, gets a confirmation. 47 seconds."},
  {"id":"B10","funnel":"MOFU","pillar":"Prueba",     "concept":"AMY's voice is fully customized: your clinic name, your tone, your treatment menu, your pricing. Patients don't know it's AI."},
  {"id":"B11","funnel":"MOFU","pillar":"Prueba",     "concept":"Lead score in action: every call gets graded 0-100. Hot leads get flagged immediately. Your team focuses only on the ones ready to buy."},
  {"id":"B12","funnel":"MOFU","pillar":"Prueba",     "concept":"3 calls happening simultaneously at 2am. AMY handles all three, books two, scores all three. Your receptionist is asleep."},
  {"id":"B13","funnel":"MOFU","pillar":"Infra",      "concept":"CRM updates in real time after every call. No manual data entry. No lost notes. Every patient history, complete and current."},
  {"id":"B14","funnel":"MOFU","pillar":"Prueba",     "concept":"Dental clinic, Miami: AMY detected a Spanish-speaking caller, switched languages mid-sentence, booked a cleaning. Patient gave 5 stars."},
  {"id":"B15","funnel":"MOFU","pillar":"Infra",      "concept":"Setup takes 48 hours. Live in 72. Actualyza configures everything: voice, scripts, CRM, dashboard. You just show up to appointments."},
  # BOFU — Resultado / Objeción / Cierre (weeks 7-9)
  {"id":"C01","funnel":"BOFU","pillar":"Resultado",  "concept":"Before Actualyza vs After: leads contacted in hours vs 30 seconds, data lost vs CRM updated in real time. Side by side."},
  {"id":"C02","funnel":"BOFU","pillar":"Resultado",  "concept":"Cost of a full-time receptionist vs Actualyza AI infrastructure. Show the math. Same coverage, fraction of the cost."},
  {"id":"C03","funnel":"BOFU","pillar":"Resultado",  "concept":"30 days with Actualyza: week-by-week timeline of what changes — calls answered, appointments booked, revenue recovered."},
  {"id":"C04","funnel":"BOFU","pillar":"Resultado",  "concept":"Clinic recovered $18,000 in missed revenue in the first 30 days. Here's exactly how: calls answered, leads scored, appointments booked."},
  {"id":"C05","funnel":"BOFU","pillar":"Resultado",  "concept":"No-show rate dropped 80% in 3 weeks. AMY sends reminders, confirms, reschedules. That's $24,000 saved per year for a mid-size dental clinic."},
  {"id":"C06","funnel":"BOFU","pillar":"Objeción",   "concept":"'But I already have a receptionist.' She can't work 24/7, speak 10 languages, and score every lead. AMY can. They work together."},
  {"id":"C07","funnel":"BOFU","pillar":"Objeción",   "concept":"'It sounds robotic.' No — AMY is fully personalized to your clinic: name, voice, tone, and treatment menu. Patients think it's human."},
  {"id":"C08","funnel":"BOFU","pillar":"Objeción",   "concept":"'Setup sounds complicated.' 48 hours to configure. 72 hours live. Actualyza handles everything. Zero tech knowledge needed."},
  {"id":"C09","funnel":"BOFU","pillar":"Objeción",   "concept":"'What if a patient needs something complex?' AMY handles intake and booking. Complex cases get transferred to your team — flagged and pre-qualified."},
  {"id":"C10","funnel":"BOFU","pillar":"Objeción",   "concept":"'We're a small clinic, we can't afford it.' AMY costs less than one missed appointment per day. Most clinics recoup the investment in week one."},
  {"id":"C11","funnel":"BOFU","pillar":"Especialidad","concept":"Dental clinics: no-shows cost $300 each. AMY sends reminders, confirms, and reschedules automatically. 80% reduction."},
  {"id":"C12","funnel":"BOFU","pillar":"Especialidad","concept":"Aesthetic clinics: high-ticket patients need pre-qualification. AMY screens before booking so only serious leads get through."},
  {"id":"C13","funnel":"BOFU","pillar":"Especialidad","concept":"Medical clinics: insurance questions at 9pm. AMY answers the most common ones, captures the lead, and flags for follow-up."},
  {"id":"C14","funnel":"BOFU","pillar":"Cierre",     "concept":"14-day free trial. No credit card. Fully operational from day 1. Your AI infrastructure, live in 72 hours. What are you waiting for?"},
  {"id":"C15","funnel":"BOFU","pillar":"Cierre",     "concept":"Every day without AMY is another day your competitor answers calls you're missing. The free trial starts the moment you say yes."},
]

# ES track: same size but offset pillar order so EN+ES same day = different funnel stage
_ES = [
  # BOFU primero (para que día 1: EN=TOFU, ES=BOFU)
  {"id":"Z01","funnel":"BOFU","pillar":"Cierre",      "concept":"Prueba gratis 14 días. Sin tarjeta de crédito. Tu infraestructura de IA, activa en 72 horas. ¿Qué estás esperando?"},
  {"id":"Z02","funnel":"BOFU","pillar":"Resultado",   "concept":"Antes de Actualyza vs Después: leads contactados en horas vs 30 segundos, datos perdidos vs CRM actualizado en tiempo real. Comparativa."},
  {"id":"Z03","funnel":"BOFU","pillar":"Resultado",   "concept":"El costo de una recepcionista vs Actualyza. El mismo servicio, 24/7, sin ausencias. Haz la matemática."},
  {"id":"Z04","funnel":"BOFU","pillar":"Objeción",    "concept":"'Ya tengo recepcionista.' Ella no puede trabajar 24/7, hablar 10 idiomas y calificar cada lead. AMY sí. Trabajan juntas."},
  {"id":"Z05","funnel":"BOFU","pillar":"Objeción",    "concept":"'Suena robótico.' No — AMY está personalizada con el nombre de tu clínica, tu tono y tu menú de tratamientos. Los pacientes no saben que es IA."},
  {"id":"Z06","funnel":"BOFU","pillar":"Objeción",    "concept":"'La instalación parece complicada.' 48 horas para configurar, 72 horas en vivo. Actualyza lo maneja todo. Tú solo apareces a las citas."},
  {"id":"Z07","funnel":"BOFU","pillar":"Objeción",    "concept":"'Somos una clínica pequeña.' AMY cuesta menos que una cita perdida al día. La mayoría recupera la inversión en la primera semana."},
  {"id":"Z08","funnel":"BOFU","pillar":"Especialidad","concept":"Clínicas dentales: las ausencias cuestan $300 cada una. AMY envía recordatorios, confirma y reprograma automáticamente. Reducción del 80%."},
  {"id":"Z09","funnel":"BOFU","pillar":"Especialidad","concept":"Clínicas estéticas: los pacientes de alto valor necesitan pre-calificación. AMY filtra antes de agendar para que solo lleguen los serios."},
  {"id":"Z10","funnel":"BOFU","pillar":"Especialidad","concept":"Clínicas médicas: preguntas de seguro a las 9pm. AMY responde las más comunes, captura el lead y lo marca para seguimiento."},
  {"id":"Z11","funnel":"BOFU","pillar":"Resultado",   "concept":"Clínica recuperó $18,000 en ingresos perdidos en los primeros 30 días. Así fue: llamadas atendidas, leads calificados, citas agendadas."},
  {"id":"Z12","funnel":"BOFU","pillar":"Resultado",   "concept":"Tasa de ausencias bajó 80% en 3 semanas. AMY envía recordatorios, confirma, reprograma. $24,000 ahorrados al año para una clínica mediana."},
  {"id":"Z13","funnel":"BOFU","pillar":"Cierre",      "concept":"Cada día sin AMY es otro día que tu competidor responde las llamadas que tú estás perdiendo. La prueba gratis empieza cuando dices que sí."},
  {"id":"Z14","funnel":"BOFU","pillar":"Resultado",   "concept":"30 días con Actualyza: cronograma semana a semana de qué cambia — llamadas atendidas, citas agendadas, ingresos recuperados."},
  {"id":"Z15","funnel":"BOFU","pillar":"Objeción",    "concept":"'¿Qué pasa con casos complejos?' AMY maneja el ingreso y la agenda. Los casos complejos se transfieren a tu equipo — pre-calificados y listos."},
  # TOFU — Dolor
  {"id":"Y01","funnel":"TOFU","pillar":"Dolor",       "concept":"3 pacientes llamaron hoy. 3 colgaron. Muestra exactamente cuánto dinero perdiste y qué significa al mes."},
  {"id":"Y02","funnel":"TOFU","pillar":"Dolor",       "concept":"Son las 11pm. Tu competidor acaba de agendar 3 pacientes con su IA mientras tu teléfono mandó al buzón de voz."},
  {"id":"Y03","funnel":"TOFU","pillar":"Dolor",       "concept":"Tu recepcionista es excelente — pero no puede contestar 3 llamadas a la vez a las 2am un domingo. Muestra el hueco."},
  {"id":"Y04","funnel":"TOFU","pillar":"Dolor",       "concept":"Un paciente llamó a las 7pm del viernes. Tu clínica estaba cerrada. El lunes ya era paciente de tu competencia."},
  {"id":"Y05","funnel":"TOFU","pillar":"Dolor",       "concept":"¿Cuántas llamadas perdió tu clínica la semana pasada? La mayoría de los dueños no lo saben. Muéstrales cómo calcularlo — y lo que cuesta."},
  {"id":"Y06","funnel":"TOFU","pillar":"Dolor",       "concept":"La clínica dental promedio pierde el 22% de las llamadas entrantes. A $300 por cita, eso es $85K al año saliendo por la puerta."},
  {"id":"Y07","funnel":"TOFU","pillar":"Dolor",       "concept":"Las ausencias cuestan entre $150-$400 cada una. La mayoría de las clínicas no tiene sistema para prevenirlas. Muestra el costo anual."},
  {"id":"Y08","funnel":"TOFU","pillar":"Dolor",       "concept":"Tu recepcionista maneja 3 cosas a la vez: un paciente en el mostrador, una llamada y el teléfono sonando de nuevo. Uno siempre pierde."},
  {"id":"Y09","funnel":"TOFU","pillar":"Dolor",       "concept":"Clínicas estéticas: tus pacientes de mayor valor son los que cuelgan cuando escuchan el buzón. No vuelven a llamar."},
  {"id":"Y10","funnel":"TOFU","pillar":"Dolor",       "concept":"Corres Meta Ads. El lead llena el formulario. Nadie llama en 4 horas. El lead se enfría. El dinero se va. Muestra la matemática."},
  {"id":"Y11","funnel":"TOFU","pillar":"Dolor",       "concept":"Tu front desk se va a las 5pm. Los leads siguen llegando hasta las 10pm. ¿Qué les pasa a ellos?"},
  {"id":"Y12","funnel":"TOFU","pillar":"Dolor",       "concept":"Sábado por la mañana: tu clínica está cerrada. 12 personas buscaron un dentista cerca. Ninguna te encontró disponible. ¿Dónde fueron?"},
  {"id":"Y13","funnel":"TOFU","pillar":"Dolor",       "concept":"El costo de una llamada perdida no es $0. Es el valor de vida de ese paciente. En odontología, eso es $4,000-$12,000. Muestra el número real."},
  {"id":"Y14","funnel":"TOFU","pillar":"Dolor",       "concept":"Tu competidor tiene IA que llama a cada lead en 30 segundos. Tú tienes buzón de voz. Así se está ganando el juego ahora mismo."},
  {"id":"Y15","funnel":"TOFU","pillar":"Dolor",       "concept":"El sábado por la noche, AMY de tu competencia agendó 5 citas mientras la tuya mandaba llamadas al voicemail. ¿Cuánto tiempo más?"},
  # MOFU — Infra / Prueba
  {"id":"X01","funnel":"MOFU","pillar":"Infra",       "concept":"No es un chatbot. Actualyza construye una infraestructura completa de IA: agente de voz + CRM + dashboard + analítica — todo personalizado para tu clínica."},
  {"id":"X02","funnel":"MOFU","pillar":"Infra",       "concept":"Dashboard en tiempo real: ve cada llamada, cada cita agendada, cada lead caliente — en vivo. Toda tu clínica en un solo panel."},
  {"id":"X03","funnel":"MOFU","pillar":"Infra",       "concept":"Después de cada llamada: Lead Score 0-100, temperatura Caliente/Tibio/Frío, objeciones detectadas, próxima acción recomendada. 7 datos, automáticamente."},
  {"id":"X04","funnel":"MOFU","pillar":"Infra",       "concept":"AMY se integra con Cal.com, revisa disponibilidad en vivo, agenda la cita durante la llamada y envía confirmación por email. Todo en menos de 60 segundos."},
  {"id":"X05","funnel":"MOFU","pillar":"Infra",       "concept":"Cada hora, AMY revisa tu CRM y llama a todos los leads sin contactar. Tu equipo solo habla con pacientes pre-calificados e interesados."},
  {"id":"X06","funnel":"MOFU","pillar":"Prueba",      "concept":"AMY habla inglés, español, portugués, francés, mandarín — detecta el idioma automáticamente. Sin acento. Sin dudas."},
  {"id":"X07","funnel":"MOFU","pillar":"Prueba",      "concept":"El paciente no contestó — AMY hace seguimiento automático cada hora. Los leads se enfrían en 5 minutos. AMY no deja que eso pase."},
  {"id":"X08","funnel":"MOFU","pillar":"Prueba",      "concept":"Mira a AMY agendar una cita completa en tiempo real: el paciente llama, pregunta precios, recibe respuestas, elige horario, recibe confirmación. 47 segundos."},
  {"id":"X09","funnel":"MOFU","pillar":"Infra",       "concept":"El anuncio de Meta se activa → AMY recibe el lead → llama en menos de 30 segundos → agenda la cita. Cero intervención humana. Muestra el flujo completo."},
  {"id":"X10","funnel":"MOFU","pillar":"Prueba",      "concept":"Lead Score en acción: cada llamada se califica de 0-100. Los leads calientes se marcan de inmediato. Tu equipo se enfoca solo en los listos para comprar."},
  {"id":"X11","funnel":"MOFU","pillar":"Infra",       "concept":"El CRM se actualiza en tiempo real después de cada llamada. Sin ingreso manual de datos. Sin notas perdidas. Historial completo de cada paciente."},
  {"id":"X12","funnel":"MOFU","pillar":"Prueba",      "concept":"3 llamadas simultáneas a las 2am. AMY atiende las tres, agenda dos, califica las tres. Tu recepcionista está durmiendo."},
  {"id":"X13","funnel":"MOFU","pillar":"Infra",       "concept":"La voz de AMY es completamente personalizada: nombre de tu clínica, tu tono, tu menú de tratamientos. Los pacientes no saben que es IA."},
  {"id":"X14","funnel":"MOFU","pillar":"Prueba",      "concept":"Clínica dental, Miami: AMY detectó un paciente hispanohablante, cambió de idioma a mitad de la llamada, agendó una limpieza. El paciente dio 5 estrellas."},
  {"id":"X15","funnel":"MOFU","pillar":"Infra",       "concept":"La instalación tarda 48 horas. En vivo en 72. Actualyza configura todo: voz, scripts, CRM, dashboard. Tú solo apareces a las citas."},
]

# Merge: each slot[i] = EN track concept i, ES track concept i (different pillar by design)
CALENDAR = []
for i, (en_item, es_item) in enumerate(zip(_EN, _ES)):
    day = i + 1
    week = (i // 5) + 1
    CALENDAR.append({**en_item, "day": day, "week": week, "track": "en"})
    CALENDAR.append({**es_item, "day": day, "week": week, "track": "es"})

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
    """Returns {'en': VideoConfig, 'es': VideoConfig} from a single concept (translated)."""
    return generate_video_configs_pair(concept, concept)


def generate_video_configs_pair(concept_en: str, concept_es: str) -> dict:
    """Returns {'en': VideoConfig, 'es': VideoConfig} using separate concepts per language."""
    template_str = json.dumps({"en": CONFIG_TEMPLATE, "es": {**CONFIG_TEMPLATE, "lang": "es"}}, indent=2)
    message = CLIENT.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"""Generate complete VideoConfig JSON for BOTH English and Spanish.

IMPORTANT: Each language has its OWN independent concept — do NOT translate one into the other. Generate each script entirely from its own concept.

English concept:
"{concept_en}"

Spanish concept:
"{concept_es}"

Follow this exact structure (fill in all "..." fields):
{template_str}

Rules:
- Hook line1: short, punchy, specific number or fact (Inter Black style — direct, brutal)
- Hook line2: emotional gut-punch (Playfair italic style — dramatic, personal)
- Hook subline: quantifies the pain (e.g. "That's $540 gone.")
- Chat delays MUST be: 10, 35, 65, 90 (faster pacing for retention)
- Subtitles: 12 chunks, max 6 words each, match the voiceover script timing
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


def stream_studio_generate(concept: str, cal_id: str = "", concept_en: str = "", concept_es: str = ""):
    """Generator: yields SSE events for the full video creation pipeline."""

    yield f"data: {json.dumps({'type': 'start', 'msg': 'Generating EN + ES configs...'})}\n\n"

    try:
        en = concept_en or concept
        es = concept_es or concept
        configs = generate_video_configs_pair(en, es)
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

        # Register both videos in publish DB
        from modules.publish import save_video, get_videos
        save_video(slug, concept, "en", config_en)
        save_video(slug, concept, "es", config_es)
        yield f"data: {json.dumps({'type': 'log', 'msg': 'Videos registrados en Publicar ✓'})}\n\n"

        # Get video IDs for GitHub Actions payload
        all_videos = get_videos(limit=10)
        id_en = next((v["id"] for v in all_videos if v["slug"] == slug and v["lang"] == "en"), None)
        id_es = next((v["id"] for v in all_videos if v["slug"] == slug and v["lang"] == "es"), None)

        # Trigger GitHub Actions render workflow
        gh_result = _trigger_github_render(slug, concept, config_en, config_es, id_en, id_es)
        if gh_result:
            yield f"data: {json.dumps({'type': 'log', 'msg': '🚀 GitHub Actions render iniciado — sin tocar nada más ✓'})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'log', 'msg': '⚠️  GitHub Actions no configurado — render manual con npm run go:en'})}\n\n"

        out_en = f"out/{slug}-en.mp4"
        out_es = f"out/{slug}-es.mp4"
        yield f"data: {json.dumps({'type': 'done', 'slug': slug, 'out_en': out_en, 'out_es': out_es, 'en': config_en, 'es': config_es, 'github_triggered': bool(gh_result)})}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'msg': str(e)})}\n\n"


def _trigger_github_render(slug, concept, config_en, config_es, id_en, id_es):
    """Dispatch a repository_dispatch event to GitHub Actions to render the video."""
    import requests as _req
    token = os.getenv("GH_RENDER_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    repo  = os.getenv("GITHUB_RENDER_REPO", "bastianveusa-a11y/actualyza-videos")
    print(f"[GH dispatch] token={'SET('+str(len(token))+'chars)' if token else 'MISSING'} repo={repo}", flush=True)
    if not token:
        return False
    payload = {
        "event_type": "render-video",
        "client_payload": {
            "slug": slug,
            "concept": concept,
            "lang": "both",
            "video_id_en": id_en,
            "video_id_es": id_es,
            "config": {"slug": slug, "concept": concept, "en": config_en, "es": config_es},
        }
    }
    r = _req.post(
        f"https://api.github.com/repos/{repo}/dispatches",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json=payload,
        timeout=10,
    )
    print(f"[GH dispatch] status={r.status_code} body={r.text[:300]}", flush=True)
    return r.status_code == 204


def get_calendar():
    return CALENDAR


def get_calendar_days():
    """Return [{day, week, en, es}] — one entry per day, pre-paired."""
    en_items = [c for c in CALENDAR if c["track"] == "en"]
    es_items = [c for c in CALENDAR if c["track"] == "es"]
    return [
        {"day": en["day"], "week": en["week"], "en": en, "es": es}
        for en, es in zip(en_items, es_items)
    ]
