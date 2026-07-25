#!/usr/bin/env python3
"""Generate the VEP concept map (concept-map.html) — the one-page "how it hangs
together" view, in the spirit of the original hand-drawn plan: four boxes,
numbered arrows, nothing else.

Deliberately the *least* detailed of the three diagrams beside it:
  concept-map        — the shape of the thing (this file)
  dataflow-diagram   — the per-request sequence, dev/prod branches
  repo-overview      — module-level map of both repos and everything outside

Re-run after edits; writes the HTML next to this script.
"""
import html, os, re

W, H = 1260, 620

# --- boxes -------------------------------------------------------------------
# id: (x, y, w, h, title, subtitle, kind)   kind: repo | seam | ext
# Pipeline sits to the RIGHT of the backend rather than below it — same row, the
# way the original sketch had "run + poll" trailing off the backend — which frees
# the whole lower right for the margin notes.
BOX = {
    "FE":   (60,  140, 240, 116, "Frontend", "standalone-web-vep", "repo"),
    "BE":   (600, 140, 260, 116, "Backend", "ensembl-web-tools-api · vep", "repo"),
    "PIPE": (980, 140, 230, 116, "Pipeline", "Nextflow / Seqera", "ext"),
    "API":  (400, 420, 300, 104, "Metadata API", "a JSON file today", "seam"),
}

# --- arrows ------------------------------------------------------------------
# (from, to, phase, label, y along the shared edge)
FLOWS = [
    ("FE", "BE", 1, "form_config — on species select", 162),
    ("BE", "FE", 1, "panels + options to render", 190),
    ("FE", "BE", 2, "run job + the chosen options", 218),
    ("BE", "FE", 4, "annotations + display spec", 246),
]
# BE ↔ Pipeline, same row
SIDE = [
    ("BE", "PIPE", 3, "run + poll", 180),
    ("PIPE", "BE", 3, "output VCF", 224),
]
# (from, to, phase, label, x on the source edge, y of the horizontal run,
#  x on the target edge) — separate run heights so they never sit on each other.
DOWN = [
    # The two dog-legs must not cross, so the ask arrives on the API's left and
    # the answer leaves from its right. Each horizontal run is also kept wider
    # than its own label, so the risers stay clear of the text.
    ("BE", "API", 1, "which options exist for this genome", 710, 320, 450),
    ("API", "BE", 2, "config + parsing + display for them", 600, 366, 840),
]

# --- what actually stands in for the two non-repo boxes ----------------------
# The pipeline has a genuine dev branch. The metadata API does not: spec_loader
# reads app/vep/specs off disk with no env override, so the JSON is the live
# implementation in dev and prod alike — labelled as such rather than "in dev".
SUBS = {
    "API":  ["dev and prod alike —", "app/vep/specs/*.json, read from disk"],
    "PIPE": ["in dev —", "config.ini dumped to dev-data,", "manual HPC run, VCF placed back"],
}

# --- margin notes (the sketch's scribbles), in the free lower-right ----------
NOTES = [
    (900, 424, "②  options → config.ini,"),
    (900, 446, "     and pin the spec to the job"),
    (900, 478, "④  parse with the PINNED spec,"),
    (900, 500, "     never the current one"),
]
CAPTION = [
    (60, 424, "①  Pick a species and the form is built from"),
    (60, 446, "     the options that genome actually has."),
    (60, 478, "③  The run happens outside both repos."),
    (60, 516, "★  marks where each numbered flow starts."),
]

# Text extents. A flat per-character average was badly wrong for these strings:
# the labels are a PROPORTIONAL sans and full of spaces and narrow letters, so a
# 6.4px/char guess drew label plates ~20% wider than the words inside them. These
# are approximate advance widths in em, which keeps the plates snug and keeps the
# layout guard honest.
_ADV_DEFAULT = 0.55
_ADV = {" ": 0.26, "i": 0.25, "l": 0.25, "j": 0.25, "t": 0.33, "f": 0.33, "r": 0.33,
        "I": 0.28, ".": 0.28, ",": 0.28, "·": 0.31, "'": 0.2, "(": 0.33, ")": 0.33,
        "m": 0.85, "w": 0.72, "y": 0.5, "+": 0.58, "-": 0.33, "_": 0.55,
        "—": 1.0, "→": 1.0, "①": 1.0, "②": 1.0, "③": 1.0, "④": 1.0, "★": 1.0}
_UPPER = 0.67


def text_w(s, px, safety=1.04):
    """Approximate rendered width. Deliberately a slight over-estimate: a plate
    narrower than its text would clip the words."""
    em = sum(_ADV.get(c, _UPPER if c.isupper() else _ADV_DEFAULT) for c in s)
    return em * px * safety


LBL_PX, NOTE_PX, PAD = 11.5, 12.5, 12

# Each numbered flow gets a star at its tail, marking where that phase begins.
# First declaration of a phase wins, scanning FE↔BE, then BE↔pipeline, then seam.
_START, _seen = set(), set()
for _tag, _rows in (("FLOWS", FLOWS), ("SIDE", SIDE), ("DOWN", DOWN)):
    for _i, _r in enumerate(_rows):
        if _r[2] not in _seen:
            _seen.add(_r[2])
            _START.add((_tag, _i))


def esc(t):
    return html.escape(t, quote=True)


_GLYPH = {"①": 1, "②": 2, "③": 3, "④": 4}


def note_markup(text):
    """Colour a leading ①②③④ to match its flow's number circle and star."""
    if text[:1] in _GLYPH:
        return f'<tspan class="f{_GLYPH[text[0]]}">{esc(text[0])}</tspan>{esc(text[1:])}'
    return esc(text)


f = []
SEGS = []      # (flow, x1, y1, x2, y2) for the crossing check
STARS = []     # bounding boxes of the flow-start markers
LBOX = []      # (flow, x, y, w, h) label backgrounds, same

# boxes
for bid, (x, y, w, h, title, sub, kind) in BOX.items():
    f.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" class="bx bx-{kind}"/>')
    f.append(
        f'<text x="{x+w/2}" y="{y+h/2-8}" class="bx-t" text-anchor="middle" dominant-baseline="central">{esc(title)}</text>'
        f'<text x="{x+w/2}" y="{y+h/2+16}" class="bx-s" text-anchor="middle" dominant-baseline="central">{esc(sub)}</text>'
    )
    if kind == "seam":
        f.append(
            f'<rect x="{x+w-84}" y="{y-11}" width="76" height="22" rx="11" class="pill pill-seam"/>'
            f'<text x="{x+w-46}" y="{y}" class="pill-t" text-anchor="middle" dominant-baseline="central">API SEAM</text>'
        )
    if kind == "ext":
        f.append(
            f'<rect x="{x+w-80}" y="{y-11}" width="72" height="22" rx="11" class="pill pill-ext"/>'
            f'<text x="{x+w-44}" y="{y}" class="pill-t" text-anchor="middle" dominant-baseline="central">EXTERNAL</text>'
        )


def star(cx, cy, phase, r=8.0, ri=3.4):
    """A five-pointed tail marker — the counterpart to the arrowhead."""
    import math
    pts = []
    for k in range(10):
        a = math.radians(-90 + k * 36)
        rad = r if k % 2 == 0 else ri
        pts.append(f"{cx + rad * math.cos(a):.1f},{cy + rad * math.sin(a):.1f}")
    f.append(f'<polygon points="{" ".join(pts)}" class="start f{phase}"/>')
    STARS.append((cx - r, cy - r, 2 * r, 2 * r))


def num(cx, cy, n):
    f.append(
        f'<circle cx="{cx}" cy="{cy}" r="11" class="num f{n}"/>'
        f'<text x="{cx}" y="{cy}" class="num-t" text-anchor="middle" dominant-baseline="central">{n}</text>'
    )


# horizontal arrows between FE and BE
for _idx, (frm, to, phase, label, y) in enumerate(FLOWS):
    fx, fy, fw, fh, *_ = BOX[frm]
    tx, ty, tw, th, *_ = BOX[to]
    ltr = tx > fx
    x1 = fx + fw if ltr else fx
    x2 = tx if ltr else tx + tw
    gap = 9 if ltr else -9
    f.append(f'<line x1="{x1}" y1="{y}" x2="{x2-gap}" y2="{y}" class="ar" marker-end="url(#a)"/>')
    _flow = f"{frm}->{to}@{y}"
    SEGS.append((_flow, x1, y, x2 - gap, y))
    mid = (x1 + x2) / 2
    tw_ = text_w(label, LBL_PX) + PAD
    LBOX.append((_flow, mid - tw_ / 2, y - 10, tw_, 20))
    f.append(
        f'<rect x="{mid-tw_/2:.1f}" y="{y-10}" width="{tw_:.1f}" height="20" rx="5" class="lbl-bg"/>'
        f'<text x="{mid}" y="{y}" class="lbl" text-anchor="middle" dominant-baseline="central">{esc(label)}</text>'
    )
    if ("FLOWS", _idx) in _START:
        star(x1 + (11 if ltr else -11), y, phase)
    # the number sits between the tail (star or box edge) and the label plate
    tail = x1 + 19 if ltr else x1 - 19
    edge = mid - tw_ / 2 if ltr else mid + tw_ / 2
    num((tail + edge) / 2, y, phase)

# dog-legs between BE and the metadata API
for _idx, (frm, to, phase, label, x, midy, ex) in enumerate(DOWN):
    fx, fy, fw, fh, *_ = BOX[frm]
    tx, ty, tw, th, *_ = BOX[to]
    down = ty > fy
    y1 = fy + fh if down else fy          # leave the source box
    y2 = ty if down else ty + th          # arrive at the target box
    gap = 9 if down else -9
    f.append(
        f'<path d="M{x},{y1} V{midy} H{ex} V{y2-gap}" class="ar ar-seam" fill="none" marker-end="url(#a)"/>'
    )
    _flow = f"{frm}->{to}(seam)"
    SEGS += [(_flow, x, y1, x, midy), (_flow, x, midy, ex, midy), (_flow, ex, midy, ex, y2 - gap)]
    lx = (x + ex) / 2
    tw_ = text_w(label, LBL_PX) + PAD
    LBOX.append((_flow, lx - tw_ / 2, midy - 10, tw_, 20))
    f.append(
        f'<rect x="{lx-tw_/2:.1f}" y="{midy-10}" width="{tw_:.1f}" height="20" rx="5" class="lbl-bg"/>'
        f'<text x="{lx}" y="{midy}" class="lbl" text-anchor="middle" dominant-baseline="central">{esc(label)}</text>'
    )
    num(x, y1 + (24 if down else -24), phase)
    if ("DOWN", _idx) in _START:
        star(x, y1 + (11 if down else -11), phase)

# arrows between BE and the pipeline (same row, so drawn like the FE↔BE ones)
for _idx, (frm, to, phase, label, y) in enumerate(SIDE):
    fx, fy, fw, fh, *_ = BOX[frm]
    tx, ty, tw, th, *_ = BOX[to]
    ltr = tx > fx
    x1 = fx + fw if ltr else fx
    x2 = tx if ltr else tx + tw
    gap = 9 if ltr else -9
    f.append(f'<line x1="{x1}" y1="{y}" x2="{x2-gap}" y2="{y}" class="ar ar-ext" marker-end="url(#a)"/>')
    _flow = f"{frm}->{to}@{y}"
    SEGS.append((_flow, x1, y, x2 - gap, y))
    mid = (x1 + x2) / 2
    tw_ = text_w(label, LBL_PX) + PAD
    LBOX.append((_flow, mid - tw_ / 2, y - 10, tw_, 20))
    f.append(
        f'<rect x="{mid-tw_/2:.1f}" y="{y-10}" width="{tw_:.1f}" height="20" rx="5" class="lbl-bg"/>'
        f'<text x="{mid}" y="{y}" class="lbl" text-anchor="middle" dominant-baseline="central">{esc(label)}</text>'
    )
    if ltr:
        num(mid, y - 26, phase)   # above: the gap is too short to sit beside it
    if ("SIDE", _idx) in _START:
        star(x1 + (11 if ltr else -11), y, phase)

# the dev / today stand-ins, under their box
SUB_LINES = []
for _bid, _lines in SUBS.items():
    _bx, _by, _bw, _bh, *_ = BOX[_bid]
    for _i, _line in enumerate(_lines):
        _y = _by + _bh + 20 + _i * 15
        _cls = "sub-k" if _i == 0 else "sub-t"
        f.append(f'<text x="{_bx}" y="{_y}" class="{_cls}" dominant-baseline="central">{esc(_line)}</text>')
        SUB_LINES.append((_bx, _y, _line))

# margin notes
for x, y, text in NOTES + CAPTION:
    cls = "note-t" + (" note-be" if x > 500 else "")
    f.append(f'<text x="{x}" y="{y}" class="{cls}" dominant-baseline="central">{note_markup(text)}</text>')

# --- refuse to emit a page whose text runs off the canvas -------------------
# The first version clipped the right-hand notes, and a plain eyeball of the
# generator would not have caught it: the numbers only bite once rendered.
_overflow = []
for x, y, text in NOTES + CAPTION:
    right = x + text_w(text, NOTE_PX, safety=1.06)
    if right > W - 8:
        _overflow.append(f"note {text!r} reaches x={right:.0f}, past the {W}px canvas")
for _x, _y, _line in SUB_LINES:
    _right = _x + len(_line) * 10.5 * 0.6 * 1.06        # mono: uniform advance
    if _right > W - 8:
        _overflow.append(f"stand-in line {_line!r} reaches x={_right:.0f}, past the {W}px canvas")
    if _y + 8 > H - 8:
        _overflow.append(f"stand-in line {_line!r} runs off the bottom of the canvas")
for _bid, (_x, _y, _w, _h, *_rest) in BOX.items():
    if _x + _w > W - 8 or _y + _h > H - 8:
        _overflow.append(f"box {_bid} extends past the canvas")
def _hit(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


# phase markers vs the label backgrounds and the boxes
_MARK = re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="11"', "".join(f))
_LBLS = [(float(a), float(b), float(c), 20.0) for a, b, c in
         re.findall(r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="20" rx="5"', "".join(f))]


for _mx, _my in _MARK:
    _m = (float(_mx) - 11, float(_my) - 11, 22, 22)
    for _l in _LBLS:
        if _hit(_m, _l):
            _overflow.append(f"phase marker at ({_mx},{_my}) sits on an arrow label")
    for _bid, (_bx, _by, _bw, _bh, *_r) in BOX.items():
        if _hit(_m, (_bx, _by, _bw, _bh)):
            _overflow.append(f"phase marker at ({_mx},{_my}) sits on the {_bid} box")

def _crosses(a, b):
    """True where one axis-aligned segment passes through the other."""
    (_, ax1, ay1, ax2, ay2), (_, bx1, by1, bx2, by2) = a, b
    a_vert, b_vert = ax1 == ax2, bx1 == bx2
    if a_vert == b_vert:
        return False                       # parallel: overlap is a separate concern
    v, h = (a, b) if a_vert else (b, a)
    vx, vy1, vy2 = v[1], min(v[2], v[4]), max(v[2], v[4])
    hy, hx1, hx2 = h[2], min(h[1], h[3]), max(h[1], h[3])
    return hx1 < vx < hx2 and vy1 < hy < vy2


for _i in range(len(SEGS)):
    for _j in range(_i + 1, len(SEGS)):
        if SEGS[_i][0] != SEGS[_j][0] and _crosses(SEGS[_i], SEGS[_j]):
            _overflow.append(f"arrows {SEGS[_i][0]} and {SEGS[_j][0]} cross")

for _flow, _lx, _ly, _lw, _lh in LBOX:
    for _s in SEGS:
        # a label riding its own horizontal run is the whole point; its own
        # risers, and every other flow's line, are not.
        own_run = _s[0] == _flow and _s[2] == _s[4] and _s[2] == _ly + _lh / 2
        if own_run:
            continue
        if _hit((_lx, _ly, _lw, _lh), (min(_s[1], _s[3]), min(_s[2], _s[4]),
                                       abs(_s[3] - _s[1]) or 1, abs(_s[4] - _s[2]) or 1)):
            _overflow.append(f"label on the {_flow} arrow sits on the {_s[0]} line")

# every arrow that carries a phase must actually show its number, and every
# distinct phase exactly one start star (an edit once silently dropped four).
_expect_num = len(FLOWS) + len(DOWN) + sum(1 for _f, _to, *_ in SIDE if BOX[_to][0] > BOX[_f][0])
if len(_MARK) != _expect_num:
    _overflow.append(f"{len(_MARK)} phase markers drawn, expected {_expect_num}")
if len(STARS) != len({_r[2] for _r in FLOWS + SIDE + DOWN}):
    _overflow.append(f"{len(STARS)} start stars drawn, expected one per numbered flow")

for _s in STARS:
    for _l in _LBLS:
        if _hit(_s, _l):
            _overflow.append(f"flow-start star at {_s[:2]} sits on an arrow label")
    for _m in _MARK:
        if _hit(_s, (float(_m[0]) - 11, float(_m[1]) - 11, 22, 22)):
            _overflow.append(f"flow-start star at {_s[:2]} sits on a phase marker")
    for _bid, (_bx, _by, _bw, _bh, *_r) in BOX.items():
        if _hit(_s, (_bx, _by, _bw, _bh)):
            _overflow.append(f"flow-start star at {_s[:2]} sits on the {_bid} box")

if _overflow:
    raise SystemExit("concept-map layout overflows:\n  " + "\n  ".join(_overflow))

svg = (
    f'<svg class="d-svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
    f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="VEP concept map">'
    f'<defs><marker id="a" markerWidth="10" markerHeight="10" refX="8" refY="3.2" orient="auto" '
    f'markerUnits="userSpaceOnUse"><path d="M0,0 L8,3.2 L0,6.4 Z" class="ah"/></marker></defs>'
    + "".join(f) + "</svg>"
)

PAGE = r"""<meta charset="utf-8">
<!-- Generated by concept-map.py. Edit that and re-run; changes made here are lost
     on the next generate. -->
<title>Web Ensembl VEP — concept map</title>
<style>
  :root{
    --paper:#f4f6f8; --surface:#ffffff; --ink:#131820; --muted:#59636f; --faint:#808b97;
    --line:#dde2e8; --accent:#1c6f8c; --accent-soft:#e3eef2;
    --fs-mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
    --fs-sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; --maxw:84rem;
    --plate:#ffffff; --bx-repo-bg:#ffffff; --bx-repo-bd:#9aa6b2;
    --seam-bg:#e3eef2; --seam-bd:#1c6f8c; --ext-bg:#f6f0e2; --ext-bd:#a08a52;
    --ar:#5b6672; --num:#8a3d6b; --note:#4a5763; --p1:#8a3d6b; --p2:#1c6f8c; --p3:#8a5a1f; --p4:#4b5aa8;
  }
  @media (prefers-color-scheme: dark){:root{
    --paper:#0d1116; --surface:#161d25; --ink:#eaeff4; --muted:#9aa5b1; --faint:#6f7b87;
    --line:#26303a; --accent:#5fb4c8; --accent-soft:#123039;
    --plate:#0f141b; --bx-repo-bg:#131a22; --bx-repo-bd:#44515f;
    --seam-bg:#123039; --seam-bd:#5fb4c8; --ext-bg:#2a2416; --ext-bd:#b39a5c;
    --ar:#8793a2; --num:#d081ac; --note:#9aa5b1; --p1:#b8497f; --p2:#2d8ba6; --p3:#98762f; --p4:#5d67c4;
  }
  :root[data-theme="light"]{
    --paper:#f4f6f8; --surface:#ffffff; --ink:#131820; --muted:#59636f; --line:#dde2e8;
    --plate:#ffffff; --bx-repo-bg:#ffffff; --bx-repo-bd:#9aa6b2;
    --seam-bg:#e3eef2; --seam-bd:#1c6f8c; --ext-bg:#f6f0e2; --ext-bd:#a08a52;
    --ar:#5b6672; --num:#8a3d6b; --note:#4a5763; --p1:#8a3d6b; --p2:#1c6f8c; --p3:#8a5a1f; --p4:#4b5aa8;
  }
  :root[data-theme="dark"]{
    --paper:#0d1116; --surface:#161d25; --ink:#eaeff4; --muted:#9aa5b1; --line:#26303a;
    --plate:#0f141b; --bx-repo-bg:#131a22; --bx-repo-bd:#44515f;
    --seam-bg:#123039; --seam-bd:#5fb4c8; --ext-bg:#2a2416; --ext-bd:#b39a5c;
    --ar:#8793a2; --num:#d081ac; --note:#9aa5b1; --p1:#b8497f; --p2:#2d8ba6; --p3:#98762f; --p4:#5d67c4;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--fs-sans);
       font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
  .wrap{max-width:var(--maxw);margin:0 auto;padding:2.4rem 1.4rem 3.4rem}
  .eyebrow{font-family:var(--fs-mono);font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;
           color:var(--accent);margin:0 0 .5rem}
  h1{font-size:1.7rem;line-height:1.22;margin:0 0 .6rem;letter-spacing:-.01em}
  .lede{color:var(--muted);margin:0 0 1.3rem;max-width:58rem}
  .plate-shell{background:var(--surface);border:1px solid var(--line);border-radius:14px;overflow:hidden}
  .plate-cap{display:flex;justify-content:space-between;gap:1rem;padding:.7rem 1rem;
             border-bottom:1px solid var(--line);font-family:var(--fs-mono);font-size:.72rem;
             letter-spacing:.08em;text-transform:uppercase;color:var(--faint)}
  .plate{padding:1rem;overflow-x:auto;background:var(--plate)}
  .d-svg{display:block;margin:0 auto}
  .bx{stroke-width:1.6}
  .bx-repo{fill:var(--bx-repo-bg);stroke:var(--bx-repo-bd)}
  .bx-seam{fill:var(--seam-bg);stroke:var(--seam-bd)}
  .bx-ext{fill:var(--ext-bg);stroke:var(--ext-bd)}
  .bx-t{fill:var(--ink);font:600 17px var(--fs-sans)}
  .bx-s{fill:var(--muted);font:400 11.5px var(--fs-mono)}
  .ar{stroke:var(--ar);stroke-width:1.7}
  .ar-seam{stroke:var(--seam-bd);stroke-dasharray:3 3}
  .ar-ext{stroke:var(--ext-bd);stroke-dasharray:5 4}
  .ah{fill:var(--ar)}
  .lbl{fill:var(--ink);font:400 11.5px var(--fs-sans)}
  .lbl-bg{fill:var(--plate)}
  .start{stroke:var(--paper);stroke-width:1.5}
  .f1{fill:var(--p1)} .f2{fill:var(--p2)} .f3{fill:var(--p3)} .f4{fill:var(--p4)} .num-t{fill:#fff;font:600 11px var(--fs-mono)}
  .pill-seam{fill:var(--seam-bd)} .pill-ext{fill:var(--ext-bd)}
  .pill-t{fill:#fff;font:600 9px var(--fs-mono);letter-spacing:.04em}
  .note-t{fill:var(--note);font:400 12.5px var(--fs-sans)}
  .sub-k{fill:var(--muted);font:600 10.5px var(--fs-mono);letter-spacing:.02em}
  .sub-t{fill:var(--muted);font:400 10.5px var(--fs-mono)}
  .grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(20rem,1fr));gap:.8rem;margin-top:1.3rem}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:1rem 1.1rem}
  .card h3{margin:0 0 .5rem;font-size:.95rem}
  .card p{margin:0;color:var(--muted);font-size:.88rem}
  code{font-family:var(--fs-mono);font-size:.85em;background:var(--accent-soft);
       padding:.05rem .3rem;border-radius:4px}
  .foot{margin-top:1.7rem;color:var(--faint);font-size:.82rem;border-top:1px solid var(--line);padding-top:.9rem}
  .foot b{color:var(--muted)}
</style>
<div class="wrap">
  <p class="eyebrow">VEP: Concept map</p>
  <h1>The shape of it, as built</h1>
  <p class="lede">Four things and the traffic between them. The frontend never reads a spec — it renders whatever the backend hands it, which is what lets the metadata API replace the JSON without the frontend noticing.</p>
  <div class="plate-shell">
    <div class="plate-cap"><span>One submission, start to finish</span><span>dashed = leaves the backend</span></div>
    <div class="plate">__SVG__</div>
  </div>
  <div class="grid2">
    <div class="card"><h3>Why the API sits under the backend, not beside the frontend</h3>
      <p>Deciding which options a genome supports needs genome metadata the frontend does not hold, so the backend asks and applies the activation rules. The frontend is handed a finished list.</p></div>
    <div class="card"><h3>Why the spec is pinned at submit</h3>
      <p>A job is read back with the same ruleset it was built with. The options, the config, the parsing and the results layout all come from one document, pinned beside the job under a content digest.</p></div>
  </div>
  <p class="foot"><b>Generated by</b> <code>concept-map.py</code> — the least detailed of the three. See <code>dataflow-diagram.html</code> for the per-request sequence and <code>repo-overview.html</code> for the module-level map.</p>
</div>
"""

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "concept-map.html")
with open(out, "w", encoding="utf-8") as fh:
    fh.write(PAGE.replace("__SVG__", svg))
print(f"wrote {out}")
