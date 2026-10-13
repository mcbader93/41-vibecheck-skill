"""Self-contained HTML report. No external requests: fonts are embedded, no CDN, no analytics."""

import math
from html import escape
from typing import List, Optional

from .. import __version__
from .. import texts
from ..texts import Fmt
from .brand import BRAND_ROOT_CSS, font_css, logo_svg, mascot_svg

CTA_URL = "https://get41.ai/?ref=vibecheck"
PRO_URL = "https://get41.ai/?ref=vibecheck-pro"    # early-access form for Pro


def level_color(score: Optional[float], levels: List[dict]) -> str:
    c = levels[0]["color"]
    for l in levels:
        if score is not None and score >= l["min"]:
            c = l["color"]
    return c


def marked(text: str, color: str, extra: str = "") -> str:
    """Wrap text in a highlighter stroke of the given marker colour."""
    return '<span class="mark %s" style="--mark-ink:%s"><span class="mark-text">%s</span></span>' % (extra, color, text)


# ---------------------------------------------------------------- radar

def radar_svg(radar: List[dict], levels: List[dict], size: int = 440, labels: bool = True,
              ink: str = "var(--ink)", grid: str = "var(--grid)", surface: str = "var(--card)",
              interactive: bool = True, font_scale: float = 1.0) -> str:
    n = len(radar)
    pad = 92 * font_scale if labels else 16
    cx = cy = size / 2.0
    r = size / 2.0 - pad

    def pt(i: int, v: float):
        a = -math.pi / 2 + 2 * math.pi * i / n
        return cx + r * v / 100.0 * math.cos(a), cy + r * v / 100.0 * math.sin(a)

    out = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-labelledby="radar-title" class="radar">' % (size, size),
           '<title id="radar-title">Vibe check radar: one score per check, 0 to 100, where 100 is the best score</title>']
    for ring in (20, 40, 60, 80, 100):
        pts = " ".join("%.1f,%.1f" % pt(i, ring) for i in range(n))
        out.append('<polygon points="%s" fill="none" stroke="%s" stroke-width="1"/>' % (pts, grid))
    for i in range(n):
        x, y = pt(i, 100)
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1"/>' % (cx, cy, x, y, grid))
    # connect only the measured axes; unavailable axes are labelled n/a instead of being drawn as 0
    shape = " ".join("%.1f,%.1f" % pt(i, max(r_["score"], 2)) for i, r_ in enumerate(radar) if r_["available"])
    out.append('<polygon points="%s" fill="%s" fill-opacity="0.07" stroke="%s" stroke-width="2" stroke-linejoin="round"/>' % (shape, ink, ink))
    for i, a in enumerate(radar):
        if not a["available"]:
            continue
        x, y = pt(i, max(a["score"], 2))
        col = ink
        tip = "%s: %d of 100" % (a["label"], a["score"])
        if interactive:
            out.append('<g class="pt" data-tip="%s" tabindex="0"><circle cx="%.1f" cy="%.1f" r="16" fill="transparent"/>'
                       '<circle cx="%.1f" cy="%.1f" r="6" fill="%s" stroke="%s" stroke-width="2"/></g>'
                       % (escape(tip), x, y, x, y, col, surface))
        else:
            out.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="%s" stroke-width="%.1f"/>'
                       % (x, y, 6 * font_scale, col, surface, 2 * font_scale))
    if labels:
        for i, a in enumerate(radar):
            ang = -math.pi / 2 + 2 * math.pi * i / n
            lx = cx + (r + 22 * font_scale) * math.cos(ang)
            ly = cy + (r + 22 * font_scale) * math.sin(ang)
            anchor = "middle" if abs(math.cos(ang)) < 0.3 else ("start" if math.cos(ang) > 0 else "end")
            dy = -14 * font_scale if math.sin(ang) < -0.3 else (8 * font_scale if math.sin(ang) > 0.3 else -6 * font_scale)
            score = "%d" % a["score"] if a["available"] else "n/a"
            words = a["label"].split(" ")
            side = abs(math.cos(ang)) > 0.9    # labels left and right of the chart have the least room
            if len(words) > 3 or (side and len(words) > 1):
                # two lines, split where the longer line is shortest
                k = min(range(1, len(words)), key=lambda k: max(len(" ".join(words[:k])), len(" ".join(words[k:]))))
                lines = [" ".join(words[:k]), " ".join(words[k:])]
            else:
                lines = [a["label"]]
            ty = ly + dy - (len(lines) - 1) * 7 * font_scale
            out.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="rl" font-size="%.1f" fill="%s">' % (lx, ty, anchor, 12.5 * font_scale, ink))
            for k, l in enumerate(lines):
                out.append('<tspan x="%.1f" dy="%s">%s</tspan>' % (lx, "0" if k == 0 else "%.1f" % (15 * font_scale), escape(l)))
            out.append('<tspan x="%.1f" dy="%.1f" class="rs" font-size="%.1f">%s</tspan></text>' % (lx, 17 * font_scale, 13 * font_scale, score))
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- page

CSS = """
/* get41.ai design system: a whiteboard with a dot grid, ink, and neon highlighter strokes.
   Light only. Colour never arrives as a flat fill, only as a marker stroke with multiply blend.
   Display: Bricolage Grotesque. Body: system sans. Monospace: dollar figures only. */
""" + BRAND_ROOT_CSS + """*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 var(--font-sans);-webkit-font-smoothing:antialiased;position:relative}
body::before{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;
background-image:radial-gradient(var(--dot-color) 1px,transparent 1.4px);background-size:26px 26px;background-position:center center;
-webkit-mask-image:radial-gradient(ellipse 75% 75% at 50% 45%,#000 55%,transparent 100%);mask-image:radial-gradient(ellipse 75% 75% at 50% 45%,#000 55%,transparent 100%)}
::selection{background:rgba(245,255,0,.55)}
.money,.mono{font-family:var(--font-mono);font-variant-numeric:tabular-nums}
.num{font-variant-numeric:tabular-nums}
.wrap{max-width:900px;margin:0 auto;padding-inline:20px;padding-block:22px 72px}
header.top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:36px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;font:700 18px var(--font-display);letter-spacing:-.02em;color:var(--ink);text-decoration:none}
.meta{color:var(--ink-muted);font-size:13px}
h1,h2,h3{font-family:var(--font-display);letter-spacing:var(--heading-tracking);line-height:var(--heading-leading);margin:0;text-wrap:balance}
h2{font-size:clamp(24px,3.2vw,32px);font-weight:600;margin:0 0 6px}
.sub{color:var(--ink-muted);font-size:15px;margin:0 0 20px}
section{margin-top:64px}
/* highlighter mark */
.mark{position:relative;display:inline-block;color:var(--ink)}
.mark-text{position:relative;z-index:1}
.mark::before,.mark::after{content:"";position:absolute;z-index:0;background:var(--mark-ink,var(--evaluate));mix-blend-mode:multiply;pointer-events:none}
.mark::before{left:-.30em;right:-.17em;top:-.09em;bottom:-.13em;opacity:.84;border-radius:17px 5px 21px 7px;transform:rotate(-1.2deg)}
.mark::after{display:none}
.mark-diagnose{--mark-ink:var(--diagnose)}.mark-fix{--mark-ink:var(--fix)}.mark-evaluate{--mark-ink:var(--evaluate)}
.mark-diagnose::before{left:-.21em;right:-.33em;border-radius:6px 20px 5px 23px;transform:rotate(1.4deg);opacity:.8}
.mark-fix::before{left:-.27em;right:-.23em;border-radius:22px 8px 14px 6px;transform:rotate(-.7deg);opacity:.82}
.mark-hero::after{display:block;left:-.23em;right:-.31em;top:.03em;bottom:-.17em;opacity:.5;border-radius:9px 24px 7px 19px;transform:rotate(.85deg)}
.mark-flat::before{top:-.07em;bottom:-.07em;transform:rotate(0deg)}
.mark-underline::before{top:auto;height:.34em;bottom:.04em}
/* hero */
.hero{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 28px;align-items:center}
.hero > *{min-width:0}
.hero .side{grid-column:2;grid-row:1 / span 3;align-self:start;margin-top:10px;display:flex;flex-direction:column;align-items:center;gap:6px;text-align:center}
.hero .side .mascot{width:clamp(96px,16vw,150px);height:auto}
.hero .side .btns{flex-direction:column;margin-top:6px;gap:6px}
.hero .side .btn{padding:8px 14px;font-size:14px}
.hero .full{grid-column:1 / -1}
@media (max-width:560px){.hero{grid-template-columns:minmax(0,1fr) auto}.hero .side .mascot{width:84px}}
.kicker{font-size:13px;font-weight:600;color:var(--ink-muted)}
.level h1{font-size:clamp(34px,6vw,54px);font-weight:700;margin-top:6px}
.score{font-family:var(--font-display);font-size:clamp(44px,7vw,64px);font-weight:700;line-height:1;letter-spacing:-.03em;margin-top:8px}
.score small{font-size:.4em;color:var(--ink-muted);font-weight:400;letter-spacing:0}
.blurb{font-size:19px;line-height:1.5;color:var(--ink);max-width:60ch;margin:6px 0 0}
.scale{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:4px;margin-top:14px;border-top:1px solid var(--divider);padding-top:12px}
.scale span{font-size:13px;color:var(--text-quiet);line-height:1.3}
.scale span small{display:block;font-size:11px;color:var(--text-quiet);margin-bottom:2px}
.scale span.on{color:var(--ink);font-weight:600}
@media (max-width:560px){.scale span{font-size:11.5px}}
.tag{display:inline-block;font-size:12px;font-weight:600;border:1px solid var(--border);border-radius:var(--radius-sm);padding:2px 8px;color:var(--ink-muted);background:var(--bg-raised)}
.radarbox{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:24px;align-items:center;background:var(--bg-raised);border:1px solid var(--border);border-radius:var(--radius-lg);padding:18px}
@media (max-width:720px){.radarbox{grid-template-columns:minmax(0,1fr)}}
.radar{max-width:440px;display:block;margin:0 auto;overflow:visible}
.radar .rl{font-weight:600;font-family:var(--font-sans)}
.radar .rs{font-family:var(--font-display);font-weight:700;fill:var(--ink-muted)}
.radar .pt{cursor:default;outline:none}
.radar .pt:focus circle:last-child,.radar .pt:hover circle:last-child{r:8}
.axes{list-style:none;margin:0;padding:0;display:grid}
.axes li{display:grid;grid-template-columns:1fr auto 5.6em;gap:12px;align-items:center;font-size:14px;padding:9px 0;border-bottom:1px solid var(--border-soft)}
.axes li:last-child{border-bottom:0}
.axes .v{font-family:var(--font-display);font-weight:700;min-width:2.2em;text-align:right}
.axes .m{font-family:var(--font-mono);color:var(--ink-muted);font-size:13px;text-align:right}
.potential{background:var(--bg-raised);border:1px solid var(--border);border-radius:var(--radius-lg);padding:24px}
.potential .big{font-size:34px;font-weight:700;letter-spacing:-.02em;margin:10px 0 6px;font-family:var(--font-display)}
.based{font-size:12.5px;color:var(--ink-muted);margin:18px 0 0;line-height:1.5}
.based b{color:var(--ink);font-weight:600}
.based.warn{color:var(--ink)}
.based.warn:before{content:"!";display:inline-grid;place-items:center;width:15px;height:15px;border-radius:50%;background:var(--ink);color:#fff;font-weight:800;font-size:10px;margin-right:6px}
.pro{background:var(--bg-raised);border:1px solid var(--ink);border-radius:var(--radius-lg);padding:24px}
.pro ul{margin:0 0 4px;padding-left:20px}
.pro li{margin-bottom:6px}
.previews{grid-template-columns:repeat(3,minmax(0,1fr))}
@media (max-width:720px){.previews{grid-template-columns:minmax(0,1fr)}}
#pro-preview{margin-top:16px}
.locked .blur{filter:blur(5px);user-select:none;pointer-events:none;margin-top:12px;font-size:14px;color:var(--ink-muted)}
.fixes{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:20px}
@media (max-width:720px){.fixes{grid-template-columns:minmax(0,1fr)}}
.fix{border:1px solid var(--border);border-radius:var(--radius-lg);padding:16px;background:var(--bg);display:flex;flex-direction:column;gap:8px}
.fix .n{font-size:12px;color:var(--ink-muted);font-weight:600}
.fix h3{font-size:17px;font-weight:600}
.fix p{margin:0;font-size:14px;color:var(--ink-muted)}
.fix .save{margin-top:auto;font-family:var(--font-mono);font-weight:700;font-size:18px}
.fix .save small{display:block;font-family:var(--font-sans);font-weight:500;font-size:12px;color:var(--ink-muted)}
.cards{display:grid;gap:12px}
.card{background:var(--bg-raised);border:1px solid var(--border);border-radius:var(--radius-lg);padding:18px 20px}
.card .hd{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.card h3{font-size:19px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:14px;background:var(--bg-raised)}
th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--border-soft);vertical-align:top}
th{font-size:12px;color:var(--ink-muted);font-weight:600}
td.r,th.r{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--border);border-radius:var(--radius-lg)}
details{margin-top:14px}
summary{cursor:pointer;font-weight:600;font-size:14px}
footer{margin-top:80px;border-top:1px solid var(--ink);padding-top:28px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:20px;align-items:start}
footer .mascot{width:72px;height:auto}
footer .cta{font-family:var(--font-display);font-size:clamp(22px,3vw,28px);font-weight:700;letter-spacing:-.02em;max-width:30ch;line-height:1.15}
.btns{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px;align-items:center}
.btn{display:inline-flex;align-items:center;gap:8px;border-radius:var(--radius-md);padding:12px 22px;font:600 15px var(--font-sans);text-decoration:none;cursor:pointer;transition:transform .15s ease,box-shadow .15s ease}
.btn.pri{background:var(--ink);color:#fff;border:1px solid var(--ink)}
.btn.sec{background:transparent;color:var(--ink);border:1px solid var(--ink);font-weight:500}
.btn:hover{transform:translateY(-2px);box-shadow:0 10px 24px -8px rgba(10,10,10,.18)}
@media (prefers-reduced-motion:reduce){.btn:hover{transform:none}}
.btn:focus-visible,summary:focus-visible,.pt:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.priv{font-size:13px;color:var(--ink-muted);margin-top:24px;max-width:70ch;grid-column:1 / -1}
.tip{position:fixed;pointer-events:none;background:var(--ink);color:#fff;font-size:13px;padding:6px 10px;border-radius:var(--radius-md);opacity:0;transition:opacity .1s;z-index:9}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media print{.btns,.tip{display:none}body::before{display:none}.card,.potential{break-inside:avoid}}
"""

JS = """
(function(){
var tip=document.querySelector('.tip');
document.querySelectorAll('.pt').forEach(function(g){
 function show(e){tip.textContent=g.getAttribute('data-tip');tip.style.opacity=1;var r=g.getBoundingClientRect();
  tip.style.left=Math.min(window.innerWidth-tip.offsetWidth-8,Math.max(8,r.left+r.width/2-tip.offsetWidth/2))+'px';tip.style.top=(r.top-38)+'px';}
 function hide(){tip.style.opacity=0}
 g.addEventListener('mouseenter',show);g.addEventListener('focus',show);g.addEventListener('mouseleave',hide);g.addEventListener('blur',hide);
});
var btn=document.getElementById('share');
if(btn){btn.addEventListener('click',function(){
 var tpl=document.getElementById('share-money');
 var svg=tpl.innerHTML.trim().replace('/*FONTS*/',document.getElementById('fonts').textContent);
 var img=new Image();
 var url='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);
 img.onload=function(){var c=document.createElement('canvas');c.width=1080;c.height=1080;var x=c.getContext('2d');x.drawImage(img,0,0,1080,1080);
  c.toBlob(function(b){var a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='41-vibe-check.png';document.body.appendChild(a);a.click();
  setTimeout(function(){URL.revokeObjectURL(a.href);a.remove()},500)},'image/png')};
 img.onerror=function(){var a=document.createElement('a');a.href=url;a.download='41-vibe-check.svg';document.body.appendChild(a);a.click();a.remove()};
 img.src=url;
});}
})();
"""


# "≈ " set in the text font, for amounts shown in the mono number font
APPROX = '<span style="font-family:var(--font-sans);margin-right:.15em">≈</span>'


def share_svg(res: dict, fonts: str) -> str:
    """1080 x 1080 share image in the get41.ai style: paper, dot grid, ink, one highlighter stroke, the mascot."""
    v = res["vibe"] or {}
    levels = v.get("levels") or []
    f = Fmt(res["money"], res["total_usd"])
    radar = radar_svg(res["radar"], levels, size=600, labels=True, ink="#0A0A0A", grid="#D9D3CA",
                      surface="#FCFAF6", interactive=False, font_scale=1.25)
    radar = radar.replace('<svg viewBox="0 0 600 600" width="100%"', '<svg x="240" y="372" width="600" height="600" viewBox="0 0 600 600"')
    radar = radar.replace('class="rs"', 'class="rs" fill="#5B5650"')
    stats = _badge_stats(res, f)
    name = v.get("name", "")
    color = v.get("color", "#F5FF00")
    name_w = 0.52 * 76 * len(name)          # Bricolage Grotesque 700 averages about 0.52em per character
    mascot = mascot_svg(v.get("level", 3), 210).replace('<svg class="mascot"', '<svg x="798" y="64"')
    logo = logo_svg(46).replace('<svg class="logo41"', '<svg x="72" y="66"')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1080" viewBox="0 0 1080 1080">'
        '<defs><style>/*FONTS*/ text{font-family:"Bricolage Grotesque",-apple-system,"Segoe UI",sans-serif}'
        '.m{font-family:"JetBrains Mono",monospace}.rl{font-weight:600;font-family:-apple-system,"Segoe UI",Roboto,sans-serif}'
        '.rs{font-weight:700}</style>'
        '<pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse"><circle cx="13" cy="13" r="1.2" fill="rgba(0,0,0,0.13)"/></pattern>'
        '</defs>'
        '<rect width="1080" height="1080" fill="#FCFAF6"/><rect width="1080" height="1080" fill="url(#dots)"/>'
        '%s<text x="132" y="101" font-size="30" font-weight="700" fill="#0A0A0A" letter-spacing="-0.6">vibe check</text>'
        '%s'
        '<text x="72" y="214" font-size="28" fill="#5B5650">Level %s of 5</text>'
        '<rect x="56" y="244" width="%.0f" height="92" rx="16" fill="%s" opacity="0.84" style="mix-blend-mode:multiply" transform="rotate(-1.2 56 290)"/>'
        '<text x="72" y="316" font-size="76" font-weight="700" fill="#0A0A0A" letter-spacing="-2.2">%s</text>'
        '<text x="72" y="410" font-size="92" font-weight="700" fill="#0A0A0A" letter-spacing="-2.5">%s<tspan font-size="38" fill="#5B5650" font-weight="400" letter-spacing="0">/100</tspan></text>'
        '<text x="1008" y="410" text-anchor="end" font-size="24" fill="#5B5650">100 is the best score</text>'
        '%s'
        '<line x1="72" y1="948" x2="1008" y2="948" stroke="#0A0A0A" stroke-width="2"/>'
        '%s'
        '<text x="1008" y="1026" text-anchor="end" font-size="28" fill="#5B5650">get41.ai</text>'
        '</svg>'
    ) % (logo, mascot, v.get("level", "?"), name_w + 40, color, escape(name), v.get("score", "n/a"), radar, stats)


def _badge_stats(res: dict, f: Fmt) -> str:
    """The badge's bottom row: up to two stats side by side, each a big figure over a small caption, like the
    report's potential card. First the work multiple on the same plan (plan users only), then the saving: dollars a
    month with the share of spend or usage when dollars are known, otherwise the share alone. The badge always
    carries the money figures (the owner's call: there is no switch to leave them out).
    Returns an SVG <g id="stats"> group."""
    lim = res.get("limits") or {}
    noun = "usage" if res["money"] in ("usage_share", "api_equivalent") else "spend"
    share = Fmt.share(res.get("combined_share"))
    items = []
    if lim.get("plan") and lim.get("share_saved", 0) >= 0.05:
        items.append((texts.multiple(lim["multiple"]), "the work, same plan"))
    if res.get("combined_monthly_usd") is not None and res["money"] != "usage_share":
        # "≈" instead of "about": the figure must stay short enough to sit beside the multiple
        money = f.money(res["combined_monthly_usd"], approx=True).replace("about ", "")
        known = res.get("combined_share") is not None
        items.append(("≈ " + money, ("a month, %s of your %s" % (share, noun)) if known else "a month"))
    elif res.get("combined_share") is not None:
        items.append((share, "of your %s avoidable" % noun))
    # no share and no dollars: the badge shows only what is known, never "n/a"
    out = []
    for k, (big, small) in enumerate(items):
        x = 72 + 300 * k   # 300px per stat leaves room for get41.ai at the right edge
        out.append('<text x="%d" y="1004" font-size="48" font-weight="700" fill="#0A0A0A" letter-spacing="-1.2">%s</text>'
                   '<text x="%d" y="1040" font-size="22" fill="#5B5650">%s</text>' % (x, escape(big), x, escape(small)))
    return '<g id="stats">%s</g>' % "".join(out)


def site_font_css(base: str = "fonts/") -> str:
    """@font-face rules pointing at font files, for pages served under a CSP that forbids data: fonts."""
    return (
        "@font-face{font-family:'Bricolage Grotesque';font-weight:400;font-display:swap;src:url(%sbricolage-400.woff2) format('woff2')}"
        "@font-face{font-family:'Bricolage Grotesque';font-weight:700;font-display:swap;src:url(%sbricolage-700.woff2) format('woff2')}"
        "@font-face{font-family:'JetBrains Mono';font-weight:100 800;font-display:swap;src:url(%sjetbrainsmono-latin.woff2) format('woff2')}"
    ) % (base, base, base)


def render(res: dict, title: str = "41 vibe check", site: bool = False) -> str:
    """site=True: for get41.ai, whose CSP allows only same-origin scripts and fonts. The page then expects
    report.js and fonts/ next to it (tools/make_site.py writes them)."""
    f = Fmt(res["money"], res["total_usd"])
    v = res["vibe"]
    levels = (v or {}).get("levels") or []
    fonts = site_font_css() if site else font_css()
    h = []
    a = h.append
    a("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">")
    a('<meta name="viewport" content="width=device-width,initial-scale=1">')
    a('<meta name="referrer" content="no-referrer">')
    if not site:
        a("<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; "
          "script-src 'unsafe-inline'; font-src data:; img-src data: blob:; base-uri 'none'; form-action 'none'\">")
    a("<title>%s</title><style id=\"fonts\">%s</style><style>%s</style></head><body>" % (escape(title), fonts, CSS))
    a('<div class="tip" role="tooltip"></div><div class="wrap">')

    # header: brand, version, and the period and sources
    a('<header class="top"><a class="brand" href="%s" target="_blank" rel="noopener noreferrer">%s<span>vibe check v%s</span></a>' % (
        CTA_URL, logo_svg(34), escape(__version__)))
    a('<div class="meta">%s · %s</div></header>' % (escape(texts.period(res)), escape(", ".join(res["sources"]) or "no sources")))

    # hero
    a('<section class="hero" style="margin-top:0" aria-labelledby="lvl">')
    if v:
        a('<div class="kicker">Your vibe, level %d of 5%s</div>' % (
            v["level"], ' <span class="tag">provisional, little data</span>' if v["provisional"] else ""))
        # the mascot with the badge download under it; the share templates are at the end of the page
        a('<div class="side">%s<div class="btns">'
          '<button class="btn sec" id="share" type="button">Download your badge</button></div></div>' % (
              mascot_svg(v["level"], 150, "41, the mascot, reacting to your level")))
        a('<div class="level"><h1 id="lvl">%s</h1></div>' % marked(escape(v["name"]), v["color"], "mark-hero"))
        a('<div class="score num" aria-label="Vibe score %d out of 100">%d<small>/100</small></div>' % (v["score"], v["score"]))
        a('<div class="full">')
        if res.get("previous"):
            a('<div class="meta" style="font-size:14px;margin-top:6px">%s</div>' % escape(texts.since_line(res)))
        a('<p class="blurb">%s</p>' % escape(v["text"]))
        # level scale: the five levels, yours marked
        a('<div class="scale" aria-label="The five levels">')
        for i, l in enumerate(levels):
            hi = (levels[i + 1]["min"] - 1) if i + 1 < len(levels) else 100
            name = escape(l["name"])
            if i + 1 == v["level"]:
                name = marked(name, l["color"], "mark-flat")
            a('<span class="%s"><small>Level %d · %d to %d</small>%s</span>' % (
                "on" if i + 1 == v["level"] else "", i + 1, l["min"], hi, name))
        a("</div>")
        a("</div>")
    else:
        a('<div class="side">%s</div>' % mascot_svg(0, 120, "41, the mascot"))
        a('<h1 id="lvl" class="full">Not enough data yet</h1><p class="blurb full">No model calls with usage were found in these files. '
          'Claude Code keeps sessions for 30 days by default, so try again after a few sessions.</p>')
    a("</section>")

    if not v:
        a('<section class="full" style="margin-top:36px"><div class="potential">%s</div></section>' % _based_on(res, f))
        a(_footer(res))
        a("</div>%s</body></html>" % ('<script src="report.js" defer></script>' if site else "<script>%s</script>" % JS))
        return "".join(h)

    # radar
    n_av = sum(1 for r in res["radar"] if r["available"])
    a('<section aria-labelledby="r-h"><h2 id="r-h">Your radar</h2><p class="sub">%d checks, each scored from 0 to 100. '
      '<b>100 is the best score</b>, so a bigger shape means better vibes.%s</p>' % (len(res["radar"]),
          "" if n_av == len(res["radar"]) else " This source has data for %d of them; the rest show n/a and don't count." % n_av))
    a('<div class="radarbox"><div>%s</div><ul class="axes">' % radar_svg(res["radar"], levels))
    for r in sorted(res["radar"], key=lambda r: (r["score"] if r["available"] else 999)):
        money = f.money_short(r["usd"]) if r["available"] and r["usd"] else ("n/a" if not r["available"] else "none")
        score_html = marked(str(r["score"]), level_color(r["score"], levels), "mark-flat") if r["available"] else "n/a"
        a('<li><span>%s</span><span class="v">%s</span><span class="m">%s</span></li>' % (
            escape(r["label"]), score_html, escape(money)))
    a("</ul></div></section>")

    # potential: the one card that holds every cost number
    a('<section aria-labelledby="p-h"><div class="potential"><h2 id="p-h">Your potential</h2>')
    plan = texts.is_plan(res)
    lim = res.get("limits") or {}
    if res["fixes"]:
        # headline: the work multiple (plan users) next to the saving in dollars and percent, as on the badge
        noun = "usage" if f.mode in ("usage_share", "api_equivalent") else "spend"
        label = '<span style="font-size:20px;font-weight:600">%s</span>'
        parts = []
        if plan and lim.get("share_saved", 0) >= 0.05:
            parts.append("%s %s" % (marked(escape(texts.multiple(lim["multiple"])), "var(--fix)", "mark-fix"),
                                    label % "the work on the same plan"))
        if res.get("combined_monthly_usd") is not None and f.mode != "usage_share":
            money = f.money(res["combined_monthly_usd"], approx=True).replace("about ", "")
            known = res.get("combined_share") is not None
            # "≈" in the text font: the mono number font would leave a wide gap before the amount
            parts.append("%s %s" % (marked('%s<span class="money">%s</span>' % (APPROX, escape(money)), "var(--fix)", "mark-fix"),
                                    label % escape(("a month, %s of your %s" % (Fmt.share(res["combined_share"]), noun))
                                                   if known else "a month")))
        elif f.mode != "usage_share" and res.get("combined_saving_usd") is not None:
            # too few days for a monthly figure: the dollars for the traced period, so the card still shows dollars
            money = f.money(res["combined_saving_usd"], approx=True).replace("about ", "")
            known = res.get("combined_share") is not None
            parts.append("%s %s" % (marked('%s<span class="money">%s</span>' % (APPROX, escape(money)), "var(--fix)", "mark-fix"),
                                    label % escape(("in this period, %s of your %s" % (Fmt.share(res["combined_share"]), noun))
                                                   if known else "in this period")))
        elif not parts or res.get("combined_share") is not None:
            parts.append("%s %s" % (marked(escape(Fmt.share(res["combined_share"])), "var(--fix)", "mark-fix"),
                                    label % escape("of your %s" % noun)))
        big = '<span style="display:inline-flex;flex-wrap:wrap;align-items:baseline;gap:8px 32px">%s</span>' % "".join(
            "<span>%s</span>" % x for x in parts)
        # no sentence under the headline: a period total next to a monthly figure read as two clashing numbers
        a('<div class="big">%s</div><div class="fixes">' % big)
        for k, fx in enumerate(res["fixes"]):
            # each improvement: dollars a month and the share they are of usage or spend, side by side
            share = Fmt.share(fx["saving_usd"] / res["total_usd"]) if res.get("total_usd") else None
            if fx.get("monthly_usd") is not None and f.mode != "usage_share" and (not plan or f.mode == "api_equivalent"):
                money = f.money(fx["monthly_usd"], approx=True).replace("about ", "")
                small = "a month, %s of your %s%s" % (share, noun, ", at API prices" if plan else "") if share else "a month"
                save = '%s%s<small>%s</small>' % (APPROX, escape(money), escape(small + ", estimate"))
            elif plan:
                save = '<span style="font-family:var(--font-display)">frees %s</span><small>%s</small>' % (
                    escape(Fmt.share(fx.get("limit_share", 0))), "of your usage limit, estimate")
            else:
                save = '%s<small>%s</small>' % (escape(f.money(fx["saving_usd"], approx=True)),
                                               "in this period, estimate")
            a('<div class="fix"><div class="n">Improvement %d · %s</div><h3>%s</h3><p>%s</p><div class="save">%s</div></div>' % (
                k + 1, escape(texts.AXIS_SHORT[fx["key"]]), escape(texts.FIX_TITLES[fx["key"]]),
                escape(texts.PRO_FIX_LINE), save))
        a("</div>")
    else:
        a('<p class="sub" style="margin:0">Nothing worth improving right now. Come back after a few more sessions.</p>')
    a(_based_on(res, f))
    a("</div></section>")

    # Pro pitch: the text says "coming soon" and promises nothing else
    a('<section id="pro" aria-labelledby="pro-h"><div class="pro"><h2 id="pro-h">Get the Pro version <span class="tag">coming soon</span></h2>'
      '<p class="sub">This free report reads what is on this machine, or only this one session in the cloud. Pro is planned to go further.</p>'
      '<ul class="sub">'
      '<li>Your whole history, or any timeframe you pick, across all your sessions, local and cloud, instead of what is on this machine or in this one session.</li>'
      '<li>Every check in detail and your habits, with the exact fix for your setup.</li>'
      '<li>Your sessions and models, broken down.</li>'
      '<li>Also available for your entire developer team.</li></ul>'
      '<div class="btns"><a class="btn pri" href="%s" target="_blank" rel="noopener noreferrer">Get notified</a></div></div></section>' % PRO_URL)

    # blurred Pro previews: fixed placeholder text (the same for everyone), never the user's data
    a('<section id="pro-preview" aria-label="Preview of Pro"><div class="cards previews">')
    for title, body in PRO_PREVIEWS:
        a('<article class="card locked"><div class="hd"><h3>%s</h3><span class="tag">Available in Pro</span></div>'
          '<div class="blur" aria-hidden="true">%s</div></article>' % (escape(title), escape(body)))
    a("</div></section>")

    a('<section aria-label="How we calculate"><details><summary>How we calculate</summary><div class="sub" style="margin-top:10px">'
      '<p>Every number comes from code, never from a language model. Costs are tokens times the published per-model prices, '
      'taken from one price file with a checked date. Savings are simulated one after another on a copy of your call log, '
      'so they never double count. The vibe score is the average of the check scores (0 to 100, '
      '100 is best).</p>'
      '<p>Not modelled: batch discounts, the 1.1× US-only data residency surcharge, and Amazon Bedrock and Google Cloud prices.</p>'
      '</div></details></section>')

    a(_footer(res))
    # share templates
    a('<template id="share-money">%s</template>' % share_svg(res, fonts))
    a("</div>%s</body></html>" % ('<script src="report.js" defer></script>' if site else "<script>%s</script>" % JS))
    return "".join(h)


# Fixed placeholder text for the blurred Pro cards. Deliberately the same for every user and never built from
# their data: the blur is a CSS filter, so anything in the HTML can be read by view-source.
PRO_PREVIEWS = (
    ("Every check in detail",
     "What we saw: the pattern, how often it happened and what it cost in this period. What to change: one concrete step "
     "for the next session. How reliable this check is and what it can miss."),
    ("Your habits",
     "How you start a session, how you phrase corrections and what your setup carries into every call. Three habits to "
     "keep and two to change, each with the number behind it."),
    ("Sessions and models",
     "Your busiest sessions and the models you use most, with the calls and the amount for each. Where the biggest leak "
     "sits in every session and how context grew over time."),
)


def _based_on(res: dict, f: Fmt) -> str:
    """The small print in the potential card: what the numbers are based on, plus data-quality warnings.
    Takes the result and the formatter; returns an HTML fragment. Works for measured and estimated results."""
    nc, ns = res["counts"]["calls"], res["counts"]["sessions"]
    total = res.get("tokens_total")
    if nc == 0 or (total is None and not res["counts"]["priced"]):
        # nothing to base figures on: say so instead of "$0.00 traced ... 0 calls"
        return "".join(['<p class="based"><b>Based on</b> no data yet. No model calls with usage found.</p>'] + [
            '<p class="based %s">%s</p>' % ("warn" if d["level"] == "warn" else "", escape(d["text"]))
            for d in res["dq"] if "coverage is unknown" not in d["text"]])
    tok = "tokens not recorded" if total is None else "%s tokens" % texts.tokens(total)
    n_calls = '<span class="num">%s</span> call%s' % ("{:,}".format(nc), "" if nc == 1 else "s")
    n_sess = '<span class="num">%s</span> session%s' % ("{:,}".format(ns), "" if ns == 1 else "s")
    if res["mode"] == "estimated":
        out = ['<p class="based"><b>Based on</b> an estimate from <span class="num">%s</span> repl%s in <span class="num">%s</span> '
               'conversation%s, %s. %s</p>' % ("{:,}".format(nc), "y" if nc == 1 else "ies", "{:,}".format(ns),
                                               "" if ns == 1 else "s", escape(tok), escape(texts.coverage_line(res, f)))]
    else:
        amount = f.money(res["total_usd"]) if res["money"] != "usage_share" else "estimated usage"
        out = ['<p class="based"><b>Based on</b> %s traced%s · %s · %s · %s. %s Prices: %s, checked %s. '
               'Cache lifetime: %s (%s). Every dollar figure is an estimate.</p>' % (
                   escape(amount), " at API list price" if res["money"] == "api_equivalent" else "", escape(tok),
                   n_calls, n_sess, escape(texts.coverage_line(res, f)),
                   escape(res["pricing"]["label"]), escape(res["pricing"]["checked_on"]),
                   "1 hour" if res["ttl"]["value"] == "1h" else "5 minutes", escape(res["ttl"]["how"]))]
    for d in res["dq"]:
        if "coverage is unknown" in d["text"]:
            continue
        out.append('<p class="based %s">%s</p>' % ("warn" if d["level"] == "warn" else "", escape(d["text"])))
    return "".join(out)


def _footer(res: dict) -> str:
    cta = "This is one developer. Get the same view of every AI agent in your company with 41."
    return (
        '<footer><div><div class="cta">%s</div><div class="btns"><a class="btn pri" href="%s" target="_blank" rel="noopener noreferrer">'
        'Visit get41.ai</a></div></div>%s'
        '<p class="priv">Made on your machine by the 41 vibe check v%s. Nothing was sent anywhere. '
        'Your sessions were read here, on your machine. No prompt, answer, code or file name was stored or shown.</p>'
        '</footer>' % (escape(cta), CTA_URL, mascot_svg(0, 72, "41, the mascot"), __version__)
    )
