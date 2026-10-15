"""41 brand assets: the mascot (named 41) and the logo, lifted from the get41.ai site.

The classic mascot is black with white eyes. In the vibe check each level gets its own body colour (the level's
highlighter ink) and face, so the character reacts to the result.

It also exports the shared design (colour and type tokens, embedded fonts) as functions, so every page built on
it uses one stylesheet source.
"""

import base64
import pkgutil
import re
from typing import Dict

LIMBS = "M 294.40,760.00 L 486.40,760.00 L 486.40,760.00 L 486.40,850.88 A 69.12,69.12 0 0 1 417.28,920.00 L 363.52,920.00 A 69.12,69.12 0 0 1 294.40,850.88 L 294.40,760.00 L 294.40,760.00 Z M 537.60,760.00 L 729.60,760.00 L 729.60,760.00 L 729.60,850.88 A 69.12,69.12 0 0 1 660.48,920.00 L 606.72,920.00 A 69.12,69.12 0 0 1 537.60,850.88 L 537.60,760.00 L 537.60,760.00 Z M 140.80,331.20 L 224.00,331.20 L 224.00,331.20 L 224.00,587.20 L 224.00,587.20 L 140.80,587.20 A 76.80,76.80 0 0 1 64.00,510.40 L 64.00,408.00 A 76.80,76.80 0 0 1 140.80,331.20 Z M 800.00,331.20 L 883.20,331.20 A 76.80,76.80 0 0 1 960.00,408.00 L 960.00,510.40 A 76.80,76.80 0 0 1 883.20,587.20 L 800.00,587.20 L 800.00,587.20 L 800.00,331.20 L 800.00,331.20 Z"
BODY = "M 320.00,152.00 L 704.00,152.00 A 128.00,128.00 0 0 1 832.00,280.00 L 832.00,664.00 A 128.00,128.00 0 0 1 704.00,792.00 L 320.00,792.00 A 128.00,128.00 0 0 1 192.00,664.00 L 192.00,280.00 A 128.00,128.00 0 0 1 320.00,152.00 Z"

INK = "#0A0A0A"


def _level_colors() -> dict:
    """Body colour per level: 0 is the classic black 41, 1 to 5 come from levels.json so the mascot, the cards and
    the badge always share one palette. Loaded with pkgutil (works from a folder, a wheel and a zipapp)."""
    import json
    import pkgutil
    levels = json.loads(pkgutil.get_data("vibecheck", "data/levels.json").decode("utf-8"))["levels"]
    colors = {0: INK}
    colors.update((i, lv["color"]) for i, lv in enumerate(levels, start=1))
    return colors


# Level 3 is a deeper yellow (#FFE01F) than the neon #F5FF00 it used to be: neon fades into a white background when
# it is a flat fill.
_BODY_FILL = _level_colors()


# eyes per level, in the mascot's 1024 coordinate space (eyes sit around x 397 and 627, y 380 to 544)
_EYES = {
    # 0 classic 41 (logo, footers): the standard white eyes on the black body
    0: '<g fill="#FFFFFF"><rect x="340.8" y="380.8" width="112" height="163.2" rx="56"/>'
       '<rect x="571.2" y="380.8" width="112" height="163.2" rx="56"/></g>',
    # 1 Prompt roulette: crying, sad brows, closed eyes, two tears
    1: ('<g fill="none" stroke="%s" stroke-linecap="round">'
        '<path d="M340 395 L445 360" stroke-width="26"/><path d="M684 395 L579 360" stroke-width="26"/>'
        '<path d="M345 465 Q397 505 450 465" stroke-width="30"/><path d="M574 465 Q627 505 680 465" stroke-width="30"/></g>'
        '<g fill="#00B4FF" stroke="%s" stroke-width="10">'
        '<path d="M372 505 C335 570 325 610 372 645 C419 610 409 570 372 505 Z"/>'
        '<path d="M652 505 C615 570 605 610 652 645 C699 610 689 570 652 505 Z"/></g>') % (INK, INK),
    # 2 Token bonfire: unimpressed, flat "- -" eyes
    2: '<g fill="%s"><rect x="336" y="452" width="120" height="32" rx="16"/>'
       '<rect x="568" y="452" width="120" height="32" rx="16"/></g>' % INK,
    # 3 Agent wrangler: standard eyes behind round glasses
    3: ('<g fill="%s"><rect x="361" y="405" width="72" height="110" rx="36"/>'
        '<rect x="591" y="405" width="72" height="110" rx="36"/></g>'
        '<g fill="none" stroke="%s" stroke-width="22" stroke-linecap="round">'
        '<rect x="307" y="370" width="180" height="180" rx="70"/><rect x="537" y="370" width="180" height="180" rx="70"/>'
        '<path d="M487 445 Q512 425 537 445"/><path d="M307 440 L200 420"/><path d="M717 440 L824 420"/></g>') % (INK, INK),
    # 4 Claude whisperer: sunglasses
    4: ('<g fill="%s" stroke="%s" stroke-width="20" stroke-linejoin="round" stroke-linecap="round">'
        '<path d="M300 400 L490 400 L478 488 Q470 530 420 530 L370 530 Q318 530 310 488 Z"/>'
        '<path d="M534 400 L724 400 L714 488 Q706 530 654 530 L604 530 Q554 530 546 488 Z"/>'
        '<path d="M490 412 L534 412" fill="none"/><path d="M300 405 L196 395" fill="none"/>'
        '<path d="M724 405 L828 395" fill="none"/></g>'
        '<path d="M335 425 L380 425" stroke="#FFFFFF" stroke-opacity=".7" stroke-width="14" stroke-linecap="round"/>'
        '<path d="M569 425 L614 425" stroke="#FFFFFF" stroke-opacity=".7" stroke-width="14" stroke-linecap="round"/>') % (INK, INK),
    # 5 AI superfactory: happy, upturned arcs and a little black crown
    5: ('<path d="M342 500 Q397 400 452 500" fill="none" stroke="%s" stroke-width="38" stroke-linecap="round"/>'
        '<path d="M572 500 Q627 400 682 500" fill="none" stroke="%s" stroke-width="38" stroke-linecap="round"/>'
        '<path d="M424 166 L402 78 L464 118 L512 56 L560 118 L622 78 L600 166 Z" fill="%s" stroke="%s" '
        'stroke-width="12" stroke-linejoin="round"/>') % (INK, INK, INK, INK),
}

LOGO_DIGITS = (
    '<g fill="#FFFFFF" transform="translate(287.60 606.50) scale(0.38 -0.38)">'
    '<path d="M390 0V145H65V326L346 730H486L185 293V255H390V420H515V0Z"/>'
    '<path d="M84 0V110H274V619L83 477V609L251 730H399V110H552V0Z" transform="translate(564 0)"/></g>'
)


def mascot_svg(level: int = 0, size: int = 96, label: str = "41, the mascot") -> str:
    """Level 1 to 5: the whole mascot flat in the level's colour, body, arms and legs alike; eyes and accessories
    stay ink. 0 is the classic black 41."""
    lv = level if level in _EYES else 0
    if lv == 0:
        figure = '<path fill="{ink}" d="{limbs}"/><path fill="{ink}" d="{body}"/>'.format(ink=INK, limbs=LIMBS, body=BODY)
    else:
        figure = '<path fill="{c}" d="{limbs}"/><path fill="{c}" d="{body}"/>'.format(c=_BODY_FILL[lv], limbs=LIMBS, body=BODY)
    return ('<svg class="mascot" xmlns="http://www.w3.org/2000/svg" viewBox="40 40 944 900" width="{w}" height="{h}" '
            'role="img" aria-label="{label}">{figure}{eyes}</svg>').format(
                w=size, h=round(size * 900 / 944), label=label, figure=figure, eyes=_EYES[lv])


def logo_svg(height: int = 34) -> str:
    """The 41 mark: the mascot wearing the name where its eyes would be."""
    return ('<svg class="logo41" xmlns="http://www.w3.org/2000/svg" viewBox="64 140 896 792" height="{h}" width="{w}" '
            'role="img" aria-label="41"><g fill="#0A0A0A"><path d="{limbs}"/><path d="{body}"/></g>{digits}</svg>'
            ).format(h=height, w=round(height * 896 / 792), limbs=LIMBS, body=BODY, digits=LOGO_DIGITS)


def mascot_vibe_svg(size: int = 280, label: str = "41, the mascot, vibing with headphones and shades") -> str:
    """The vibing pose: the classic black 41 with headphones, round shades and a mustache,
    music notes floating up. Classes .bob and .note let a page animate it (off for reduced motion)."""
    paper, gold, gold_dk = "#FCFAF6", "#E9B949", "#8A6514"
    notes = (
        '<g class="note n1" fill="{ink}" transform="translate(20 -120)"><ellipse cx="896" cy="300" rx="36" ry="27" transform="rotate(-20 896 300)"/>'
        '<rect x="917" y="150" width="15" height="150" rx="7"/><path d="M924 150 Q990 170 978 236 Q960 196 924 196 Z"/></g>'
        '<g class="note n2" fill="{ink}" transform="translate(-30 -150)"><ellipse cx="96" cy="330" rx="30" ry="22" transform="rotate(-20 96 330)"/>'
        '<rect x="113" y="205" width="13" height="125" rx="6"/><ellipse cx="176" cy="300" rx="30" ry="22" transform="rotate(-20 176 300)"/>'
        '<rect x="193" y="175" width="13" height="125" rx="6"/><path d="M113 205 L206 175 L206 205 L113 235 Z"/></g>'
    ).format(ink=INK)
    # headphones in ink, kept apart from the black head by a paper-coloured edge
    phones = (
        '<path d="M196 330 C196 30 828 30 828 330" fill="none" stroke="{paper}" stroke-width="66" stroke-linecap="round"/>'
        '<path d="M196 330 C196 30 828 30 828 330" fill="none" stroke="{ink}" stroke-width="40" stroke-linecap="round"/>'
        '<rect x="128" y="270" width="132" height="216" rx="58" fill="{ink}" stroke="{paper}" stroke-width="16"/>'
        '<rect x="764" y="270" width="132" height="216" rx="58" fill="{ink}" stroke="{paper}" stroke-width="16"/>'
        '<rect x="162" y="318" width="22" height="120" rx="11" fill="{gold}"/>'
        '<rect x="840" y="318" width="22" height="120" rx="11" fill="{gold}"/>'
    ).format(ink=INK, paper=paper, gold=gold)
    shades = (
        '<g stroke="#FFFFFF" stroke-width="18" fill="{ink}">'
        '<circle cx="392" cy="452" r="80"/><circle cx="632" cy="452" r="80"/></g>'
        '<path d="M472 444 Q512 418 552 444" fill="none" stroke="#FFFFFF" stroke-width="16" stroke-linecap="round"/>'
        '<path d="M347 425 Q362 400 390 394" fill="none" stroke="#FFFFFF" stroke-width="12" stroke-linecap="round" opacity=".8"/>'
        '<path d="M587 425 Q602 400 630 394" fill="none" stroke="#FFFFFF" stroke-width="12" stroke-linecap="round" opacity=".8"/>'
    ).format(ink=INK)
    stache = ('<path d="M512 590 C482 556 424 556 400 598 C428 584 452 602 474 610 C494 616 506 606 512 598 '
              'C518 606 530 616 550 610 C572 602 596 584 624 598 C600 556 542 556 512 590 Z" fill="#FFFFFF"/>')
    return ('<svg class="mascot vibe" xmlns="http://www.w3.org/2000/svg" viewBox="20 20 1004 960" width="{w}" height="{h}" '
            'role="img" aria-label="{label}" overflow="visible">{notes}<g class="bob"><g transform="rotate(-5 512 560)">'
            '<path fill="{ink}" d="{limbs}"/><path fill="{ink}" d="{body}"/>{shades}{stache}{phones}'
            '</g></g></svg>').format(w=size, h=round(size * 960 / 1004), label=label, notes=notes, ink=INK, limbs=LIMBS,
                                     body=BODY, shades=shades, stache=stache, phones=phones)


def mascot_secure_svg(size: int = 140, label: str = "41, the mascot, with a shield") -> str:
    """The classic 41 holding a green shield with a lock: for the trust section."""
    shield = (
        '<path d="M770 470 L920 524 L920 652 C920 760 846 822 770 852 C694 822 620 760 620 652 L620 524 Z" '
        'fill="#17E68C" stroke="{ink}" stroke-width="18" stroke-linejoin="round"/>'
        '<path d="M728 668 L728 628 A42 42 0 0 1 812 628 L812 668" fill="none" stroke="{ink}" stroke-width="20"/>'
        '<rect x="704" y="660" width="132" height="104" rx="18" fill="{ink}"/>'
        '<circle cx="770" cy="702" r="15" fill="#FFFFFF"/><rect x="763" y="706" width="14" height="32" rx="6" fill="#FFFFFF"/>'
    ).format(ink=INK)
    return ('<svg class="mascot secure" xmlns="http://www.w3.org/2000/svg" viewBox="40 40 944 900" width="{w}" height="{h}" '
            'role="img" aria-label="{label}"><path fill="{ink}" d="{limbs}"/><path fill="{ink}" d="{body}"/>{eyes}{shield}</svg>'
            ).format(w=size, h=round(size * 900 / 944), label=label, ink=INK, limbs=LIMBS, body=BODY, eyes=_EYES[0],
                     shield=shield)


def mascot_puller_svg(size: int = 90, label: str = "41, the mascot, pulling the counter's lever") -> str:
    """The vibing 41 with its right arm drawn on its own (class .arm), so a page can swing it down to pull a slot
    machine lever standing to its right. At rest the arm is raised; the page animates the pull and the notes."""
    parts = [p.strip() + " Z" for p in LIMBS.split(" Z") if p.strip()]
    rest = " ".join(parts[:3])
    right_arm = parts[3]
    svg = mascot_vibe_svg(size, label)
    svg = svg.replace('<g transform="rotate(-5 512 560)">', '<g>')
    svg = svg.replace('<path fill="{}" d="{}"/>'.format(INK, LIMBS),
                      '<g class="arm"><path fill="{}" d="{}"/></g><path fill="{}" d="{}"/>'.format(INK, right_arm, INK, rest))
    return svg.replace('class="mascot vibe"', 'class="mascot vibe puller"')


# ---------------------------------------------------------------- shared design: tokens and fonts

# The get41.ai design tokens as a CSS :root block. render.py builds the report's stylesheet around it, so a token
# change lands everywhere it is used. Keep the text byte-stable: the report is diffed against it.
BRAND_ROOT_CSS = """:root{--bg:#FCFAF6;--bg-raised:#FFFFFF;--dot-color:rgba(0,0,0,.13);--ink:#0A0A0A;--ink-muted:#5B5650;--text-quiet:#6B655D;
--evaluate:#F5FF00;--diagnose:#00B4FF;--fix:#17E68C;--reserve:#FF4D1C;
--border:#E7E2DA;--border-soft:#EEEAE3;--divider:#D9D3CA;--grid:#E2DDD4;--card:#FFFFFF;
--radius-sm:6px;--radius-md:8px;--radius-lg:12px;
--font-sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--font-mono:"JetBrains Mono","IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;
--font-display:"Bricolage Grotesque","Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--heading-tracking:-.03em;--heading-leading:1.12;color-scheme:light}
"""


def brand_css() -> str:
    """The shared :root token block (colours, radii, font stacks) as CSS text."""
    return BRAND_ROOT_CSS


def brand_tokens() -> Dict[str, str]:
    """The same tokens as a dict, "--ink" -> "#0A0A0A". For tests and for code that needs a single value."""
    return dict(re.findall(r"(--[a-z-]+):([^;}]+)", BRAND_ROOT_CSS))


def _font(name: str) -> str:
    """One bundled font file as base64. pkgutil works from a folder, a wheel and a zipapp."""
    return base64.b64encode(pkgutil.get_data("vibecheck.report", "fonts/" + name)).decode("ascii")


def font_css() -> str:
    """@font-face rules with the fonts embedded as data URIs, so a page makes no external request."""
    return (
        "@font-face{font-family:'Bricolage Grotesque';font-style:normal;font-weight:400;font-display:swap;"
        "src:url(data:font/woff2;base64,%s) format('woff2')}"
        "@font-face{font-family:'Bricolage Grotesque';font-style:normal;font-weight:700;font-display:swap;"
        "src:url(data:font/woff2;base64,%s) format('woff2')}"
        "@font-face{font-family:'JetBrains Mono';font-style:normal;font-weight:100 800;font-display:swap;"
        "src:url(data:font/woff2;base64,%s) format('woff2')}"
    ) % (_font("bricolage-400.woff2"), _font("bricolage-700.woff2"), _font("jetbrainsmono-latin.woff2"))
