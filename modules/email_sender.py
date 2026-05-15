"""
Envío de emails de campaña vía Resend.

Diseñado para máxima entregabilidad en bandeja principal:
- HTML minimalista — sin max-width, sin colores, sin bordes decorativos
- FROM name sin nombre de empresa (señal de email masivo para Gmail)
- Email 1 se envía como texto plano puro (sin pixel de tracking)
- Emails 2-4 usan HTML simple con tracking de aperturas
"""

import os
import resend

# HTML que imita un email personal compuesto en Gmail — sin señales de marketing
_HTML_WRAPPER = """<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;font-size:14px;line-height:1.55;color:#1a1a1a;margin:0;padding:0">
{body}
<p style="margin-top:20px;margin-bottom:4px">Best,</p>
<p style="margin:0">Alicia<br>Growth Specialist, AMY AI</p>
<p style="margin-top:20px;font-size:11px;color:#bbb">
<a href="{unsubscribe_url}" style="color:#bbb;text-decoration:none">Unsubscribe</a>
</p>
</body>
</html>"""


def _resend_client():
    resend.api_key = os.getenv("RESEND_API_KEY", "")
    return resend


def send_campaign_email(
    to_email: str,
    subject: str,
    body_html: str,
    body_text: str,
    notion_id: str,
    email_num: int,
    base_url: str = "https://actualyza-prospecting-production.up.railway.app",
) -> dict:
    """
    Envía un email de campaña vía Resend.
    Email 1 → texto plano (sin pixel de tracking, máxima entregabilidad).
    Emails 2-4 → HTML minimalista con tracking de aperturas.
    Retorna: {"ok": bool, "message_id": str, "error": str|None}
    """
    # FROM name solo con nombre de persona — el dominio aporta la marca
    from_name = os.getenv("FROM_NAME", "Alicia")
    from_addr = f"{from_name} <{os.getenv('FROM_EMAIL', 'contact@actualyza.com')}>"
    unsub_url = f"{base_url}/unsubscribe?id={notion_id}"
    full_text = body_text + f"\n\n--\nUnsubscribe: {unsub_url}"

    payload = {
        "from":    from_addr,
        "to":      [to_email],
        "subject": subject,
        "text":    full_text,
        "tags": [
            {"name": "notion_id",  "value": notion_id[:50]},
            {"name": "email_num",  "value": str(email_num)},
        ],
    }

    # Email 1 va sin HTML — evita el pixel de tracking y señales de email masivo
    # Es el momento más crítico: primer contacto en frío
    if email_num > 1:
        payload["html"] = _HTML_WRAPPER.format(
            body          = body_html,
            unsubscribe_url = unsub_url,
        )

    try:
        client = _resend_client()
        resp   = client.Emails.send(payload)
        msg_id = resp.id if hasattr(resp, "id") else (resp.get("id", "") if isinstance(resp, dict) else "")
        return {"ok": True, "message_id": msg_id, "error": None}
    except Exception as e:
        return {"ok": False, "message_id": "", "error": str(e)}
