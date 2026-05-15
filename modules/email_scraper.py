"""
Módulo de extracción de correos desde sitios web de clínicas.
Busca en la página principal y en páginas de contacto.
"""

import re
import time
from urllib.parse import urljoin, urlparse

import requests

EMAIL_REGEX = re.compile(r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b')

_BAD_PREFIX = {
    'noreply', 'no-reply', 'donotreply', 'bounce', 'mailer-daemon',
    'postmaster', 'webmaster', 'abuse', 'spam', 'unsubscribe',
    'newsletter', 'notifications', 'alerts', 'marketing',
}

_BAD_DOMAIN_FRAGMENT = {
    'sentry.io', 'wixpress.com', 'squarespace.com', 'amazonaws.com',
    'cloudflare', 'google.com', 'facebook.com', 'instagram.com',
    'twitter.com', 'example.com', 'placeholder', 'yoursite', 'yourdomain',
}

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,es;q=0.8',
}

_CONTACT_PATHS = ['/contact', '/contact-us', '/contacto', '/about', '/about-us', '/sobre-nosotros']


def _good_email(email: str, site_domain: str) -> bool:
    try:
        prefix, domain = email.lower().split('@', 1)
    except ValueError:
        return False
    if any(bad in domain for bad in _BAD_DOMAIN_FRAGMENT):
        return False
    if prefix in _BAD_PREFIX:
        return False
    if domain.endswith(('.png', '.jpg', '.gif', '.svg', '.css', '.js', '.ico')):
        return False
    return True


def _extract(html: str, site_domain: str) -> list:
    seen, result = set(), []
    for email in EMAIL_REGEX.findall(html):
        email = email.lower().strip('.')
        if email in seen or not _good_email(email, site_domain):
            continue
        seen.add(email)
        result.append(email)
    # Emails del mismo dominio del sitio primero
    result.sort(key=lambda e: (0 if site_domain and site_domain in e else 1, e))
    return result


def scrape_email(url: str, delay: float = 1.5, timeout: int = 8) -> dict:
    """
    Busca el correo de contacto en el sitio web.
    Retorna: {"email": str, "source": str, "error": str|None}
    """
    if not url:
        return {"email": "", "source": "", "error": "Sin URL"}
    try:
        parsed      = urlparse(url)
        base        = f"{parsed.scheme}://{parsed.netloc}"
        site_domain = parsed.netloc.replace('www.', '')
    except Exception:
        return {"email": "", "source": "", "error": "URL inválida"}

    pages = [url] + [base.rstrip('/') + p for p in _CONTACT_PATHS]

    for page_url in pages[:4]:
        try:
            time.sleep(delay)
            r = requests.get(page_url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
            if r.status_code != 200:
                continue
            emails = _extract(r.text, site_domain)
            if emails:
                return {"email": emails[0], "source": page_url, "error": None}
        except Exception:
            continue

    return {"email": "", "source": "", "error": "No encontrado"}
