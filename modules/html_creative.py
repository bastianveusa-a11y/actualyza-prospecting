"""
Renderiza creativos de ventas HTML→JPEG con Playwright.
Diseño: navy profundo, stat gigante, foto de clínica visible a la derecha.
"""

from pathlib import Path

from modules.image_gen import _COPY, _ensure_fonts

_FONT_DIR    = Path(__file__).parent.parent / "data" / "fonts"
_FONT_BOLD   = _FONT_DIR / "Inter-Bold.ttf"
_FONT_REG    = _FONT_DIR / "Inter-Regular.ttf"
_FONT_ITALIC = _FONT_DIR / "PlayfairDisplay-Italic.ttf"

_ACCENT_A = "#C9A96E"
_ACCENT_B = "#40C898"

_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
@font-face {{
  font-family: 'Inter';
  font-weight: 900;
  src: url('{font_bold}');
}}
@font-face {{
  font-family: 'Inter';
  font-weight: 700;
  src: url('{font_bold}');
}}
@font-face {{
  font-family: 'Inter';
  font-weight: 400;
  src: url('{font_reg}');
}}
@font-face {{
  font-family: 'Playfair';
  font-style: italic;
  font-weight: 400;
  src: url('{font_italic}');
}}

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
  width: 1200px;
  height: 630px;
  overflow: hidden;
  font-family: 'Inter', sans-serif;
  background: #090f24;
  position: relative;
}}

/* ── Foto clínica full-bleed background ── */
.bg-photo {{
  position: absolute;
  inset: 0;
  background-image: url('{flux_url}');
  background-size: cover;
  background-position: center right;
  z-index: 0;
}}

/* ── Gradient: navy sólido izq → transparente derecha ── */
.gradient {{
  position: absolute;
  inset: 0;
  background: linear-gradient(
    to right,
    #090f24 0%,
    #090f24 36%,
    rgba(9,15,36,0.93) 50%,
    rgba(9,15,36,0.55) 66%,
    rgba(9,15,36,0.18) 82%,
    rgba(9,15,36,0.04) 100%
  );
  z-index: 1;
}}

/* ── Barra de acento izquierda ── */
.accent-bar {{
  position: absolute;
  left: 0; top: 0;
  width: 4px; height: 100%;
  background: {accent};
  z-index: 3;
}}

/* ── Panel de contenido ── */
.content {{
  position: absolute;
  left: 0; top: 0;
  width: 700px; height: 630px;
  padding: 42px 60px 34px 58px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  z-index: 2;
}}

/* ── Wordmark ── */
.wordmark {{
  display: flex;
  align-items: baseline;
  gap: 0;
  margin-bottom: 28px;
}}
.wm-main {{
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 3.5px;
  color: {accent};
  text-transform: uppercase;
}}
.wm-sep {{
  margin: 0 7px;
  color: rgba(255,255,255,0.18);
  font-weight: 400;
  font-size: 12px;
}}
.wm-sub {{
  font-size: 10.5px;
  font-weight: 400;
  letter-spacing: 2px;
  color: rgba(255,255,255,0.28);
  text-transform: uppercase;
}}

/* ── Stat grande ── */
.stat {{
  font-family: 'Inter', sans-serif;
  font-weight: 900;
  font-size: {stat_size}px;
  line-height: 0.88;
  color: {accent};
  letter-spacing: -3px;
  margin-bottom: 10px;
}}

.stat-label {{
  font-size: 12.5px;
  font-weight: 400;
  color: rgba(255,255,255,0.36);
  text-transform: uppercase;
  letter-spacing: 2.5px;
  margin-bottom: 20px;
}}

/* ── Separador acento ── */
.sep {{
  width: 42px;
  height: 3px;
  background: {accent};
  opacity: 0.72;
  margin-bottom: 18px;
  border-radius: 2px;
}}

/* ── Headline Playfair Italic ── */
.headline {{
  font-family: 'Playfair', Georgia, serif;
  font-style: italic;
  font-weight: 400;
  font-size: 38px;
  line-height: 1.24;
  color: #eeeff8;
  margin-bottom: 13px;
}}

/* ── Subtext ── */
.subtext {{
  font-size: 13.5px;
  font-weight: 400;
  color: rgba(255,255,255,0.33);
  line-height: 1.58;
  max-width: 560px;
}}

/* ── CTA ── */
.cta-strip {{
  display: flex;
  align-items: center;
  gap: 14px;
  border-top: 1px solid rgba(255,255,255,0.07);
  padding-top: 15px;
}}
.cta-text {{
  font-size: 15.5px;
  font-weight: 700;
  color: {accent};
  letter-spacing: 0.2px;
}}
.cta-btn {{
  width: 26px; height: 26px;
  border-radius: 50%;
  border: 1.5px solid {accent};
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: {accent};
  opacity: 0.65;
  flex-shrink: 0;
}}
</style>
</head>
<body>
  <div class="bg-photo"></div>
  <div class="gradient"></div>
  <div class="accent-bar"></div>
  <div class="content">
    <div>
      <div class="wordmark">
        <span class="wm-main">AMY AI</span>
        <span class="wm-sep">·</span>
        <span class="wm-sub">Actualyza</span>
      </div>
      <div class="stat">{hook_num}</div>
      <div class="stat-label">{hook_label}</div>
      <div class="sep"></div>
      <div class="headline">{headline}</div>
      <div class="subtext">{hook_sub}</div>
    </div>
    <div class="cta-strip">
      <div class="cta-text">{cta}</div>
      <div class="cta-btn">→</div>
    </div>
  </div>
</body>
</html>"""


def render_creative(flux_url: str, categoria: str, email_num: int, style: str = "a") -> bytes:
    """
    Renderiza un creativo HTML→JPEG con Playwright.
    Lanza RuntimeError si Playwright o Chromium no están disponibles.
    """
    from playwright.sync_api import sync_playwright

    _ensure_fonts()

    copy      = _COPY.get((categoria, email_num),
                _COPY.get(("dental", email_num), _COPY[("dental", 2)]))
    accent    = _ACCENT_A if style == "a" else _ACCENT_B
    hook_num  = copy.get("hook_num", "")
    stat_size = 125 if len(hook_num) <= 3 else (102 if len(hook_num) <= 5 else 84)

    html = _TEMPLATE.format(
        font_bold    = _FONT_BOLD.as_uri(),
        font_reg     = _FONT_REG.as_uri(),
        font_italic  = _FONT_ITALIC.as_uri(),
        flux_url     = flux_url,
        accent       = accent,
        stat_size    = stat_size,
        hook_num     = hook_num,
        hook_label   = copy.get("hook_label", ""),
        headline     = copy.get("headline", "").replace("\n", "<br>"),
        hook_sub     = copy.get("hook_sub", ""),
        cta          = copy.get("cta", ""),
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ])
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        page.set_content(html, wait_until="load")
        page.wait_for_timeout(800)   # da tiempo a que cargue la foto de Flux
        jpeg = page.screenshot(
            type="jpeg",
            quality=93,
            clip={"x": 0, "y": 0, "width": 1200, "height": 630},
        )
        browser.close()

    return jpeg
