"""
Envío de emails de campaña vía Resend.
Incluye tags para rastreo de apertura por webhook.
"""

import os
import resend

_FROM    = None
_FOOTER  = """<p style="font-size:12px;color:#888;margin-top:32px;border-top:1px solid #eee;padding-top:16px;">
You received this email because your clinic was identified as a potential fit for AMY AI.<br>
<a href="{unsubscribe_url}" style="color:#888;">Unsubscribe</a>
</p>"""

_HTML_WRAPPER = """<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;font-size:15px;line-height:1.6;color:#1a1a2e;max-width:580px;margin:0 auto;padding:24px 16px;">
{body}
<p style="margin-top:24px;">Best,<br>
<strong>Alicia</strong><br>
<span style="color:#666;font-size:13px;">Growth Specialist &nbsp;·&nbsp; AMY AI</span>
</p>
{footer}
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
    Envía un email de campaña vía Resend con tags para tracking.
    Retorna: {"ok": bool, "message_id": str, "error": str|None}
    """
    from_addr = f"{os.getenv('FROM_NAME', 'Alicia | AMY AI')} <{os.getenv('FROM_EMAIL', 'contact@actualyza.com')}>"
    unsub_url = f"{base_url}/unsubscribe?id={notion_id}"

    full_html = _HTML_WRAPPER.format(
        body   = body_html,
        footer = _FOOTER.format(unsubscribe_url=unsub_url),
    )
    full_text = body_text + f"\n\n---\nUnsubscribe: {unsub_url}"

    try:
        client = _resend_client()
        resp   = client.Emails.send({
            "from":    from_addr,
            "to":      [to_email],
            "subject": subject,
            "html":    full_html,
            "text":    full_text,
            "tags": [
                {"name": "notion_id",  "value": notion_id[:50]},
                {"name": "email_num",  "value": str(email_num)},
            ],
        })
        return {"ok": True, "message_id": resp.get("id", ""), "error": None}
    except Exception as e:
        return {"ok": False, "message_id": "", "error": str(e)}
