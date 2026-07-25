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
import html, os

W, H = 1060, 660

# --- boxes -------------------------------------------------------------------
# id: (x, y, w, h, title, subtitle, kind)   kind: repo | seam | ext
BOX = {
    "FE":   (70,  128, 250, 116, "Frontend", "standalone-web-vep", "repo"),
    "BE":   (610, 128, 270, 116, "Backend", "ensembl-web-tools-api · vep", "repo"),
    "API":  (240, 430, 310, 104, "Metadata API", "a JSON file today", "seam"),
    "PIPE": (650, 430, 250, 104, "Pipeline", "VEP via Nextflow / Seqera", "ext"),
}

# --- arrows ------------------------------------------------------------------
# (from, to, phase, label, y-or-x offset along the shared edge)
# The FE↔BE arrows stack inside the boxes' shared height, like the sketch.
FLOWS = [
    ("FE", "BE", 1, "form_config — on species select", 152),
    ("BE", "FE", 1, "panels + options to render", 182),
    ("FE", "BE", 2, "run job + the chosen options", 212),
    ("BE", "FE", 4, "annotations + display spec", 242),
]
# (from, to, phase, label, x on the source edge, y of the horizontal run,
#  x on the target edge) — each gets its own run height so they never sit on
# top of one another.
DOWN = [
    ("BE", "API", 1, "which options exist for this genome", 660, 312, 500),
    ("API", "BE", 2, "config + parsing + display for them", 430, 380, 800),
]
SIDE = [
    ("BE", "PIPE", 3, "run, then poll until it settles", 470),
    ("PIPE", "BE", 3, "output VCF", 505),
]

# --- what the backend does between the arrows (the sketch's margin notes) ----
NOTES = [
    (610 + 270 + 22, 300, "②  options → config.ini"),
    (610 + 270 + 22, 322, "     …and pin the spec to the job"),
    (610 + 270 + 22, 352, "④  parse with the PINNED spec,"),
    (610 + 270 + 22, 374, "     never the current one"),
]

CAPTION = [
    (70, 300, "①  Pick a species → the form is built from the options"),
    (70, 322, "     that genome actually has."),
    (70, 352, "③  The run happens outside both repos."),
]


def esc(t):
    return html.escape(t, quote=True)


f = []

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


def num(cx, cy, n):
    f.append(
        f'<circle cx="{cx}" cy="{cy}" r="11" class="num"/>'
        f'<text x="{cx}" y="{cy}" class="num-t" text-anchor="middle" dominant-baseline="central">{n}</text>'
    )


# horizontal arrows between FE and BE
for frm, to, phase, label, y in FLOWS:
    fx, fy, fw, fh, *_ = BOX[frm]
    tx, ty, tw, th, *_ = BOX[to]
    ltr = tx > fx
    x1 = fx + fw if ltr else fx
    x2 = tx if ltr else tx + tw
    gap = 9 if ltr else -9
    f.append(f'<line x1="{x1}" y1="{y}" x2="{x2-gap}" y2="{y}" class="ar" marker-end="url(#a)"/>')
    mid = (x1 + x2) / 2
    tw_ = len(label) * 6.6 + 12
    f.append(
        f'<rect x="{mid-tw_/2:.1f}" y="{y-10}" width="{tw_:.1f}" height="20" rx="5" class="lbl-bg"/>'
        f'<text x="{mid}" y="{y}" class="lbl" text-anchor="middle" dominant-baseline="central">{esc(label)}</text>'
    )
    num(x1 + (26 if ltr else -26), y, phase)

# dog-legs between BE and the metadata API
for frm, to, phase, label, x, midy, ex in DOWN:
    fx, fy, fw, fh, *_ = BOX[frm]
    tx, ty, tw, th, *_ = BOX[to]
    down = ty > fy
    y1 = fy + fh if down else fy          # leave the source box
    y2 = ty if down else ty + th          # arrive at the target box
    gap = 9 if down else -9
    f.append(
        f'<path d="M{x},{y1} V{midy} H{ex} V{y2-gap}" class="ar ar-seam" fill="none" marker-end="url(#a)"/>'
    )
    lx = (x + ex) / 2
    tw_ = len(label) * 6.4 + 12
    f.append(
        f'<rect x="{lx-tw_/2:.1f}" y="{midy-10}" width="{tw_:.1f}" height="20" rx="5" class="lbl-bg"/>'
        f'<text x="{lx}" y="{midy}" class="lbl" text-anchor="middle" dominant-baseline="central">{esc(label)}</text>'
    )
    num(x, y1 + (24 if down else -24), phase)

# arrows between BE and the pipeline
for frm, to, phase, label, y in SIDE:
    fx, fy, fw, fh, *_ = BOX[frm]
    tx, ty, tw, th, *_ = BOX[to]
    cx = fx + fw / 2 if frm == "BE" else tx + tw / 2
    down = ty > fy
    y1 = (fy + fh) if down else fy
    y2 = ty if down else (ty + th)
    xx = cx + (40 if down else -40)
    gap = 9 if down else -9
    f.append(f'<line x1="{xx}" y1="{y1}" x2="{xx}" y2="{y2-gap}" class="ar ar-ext" marker-end="url(#a)"/>')
    tw_ = len(label) * 6.4 + 12
    lx = xx + (tw_ / 2 + 12) * (1 if down else -1)
    f.append(
        f'<text x="{lx}" y="{(y1+y2)/2}" class="lbl" text-anchor="middle" dominant-baseline="central">{esc(label)}</text>'
    )
    if down:
        num(xx, y1 + 24, phase)

# margin notes
for x, y, text in NOTES + CAPTION:
    cls = "note-t" + (" note-be" if x > 500 else "")
    f.append(f'<text x="{x}" y="{y}" class="{cls}" dominant-baseline="central">{esc(text)}</text>')

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
    --fs-sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; --maxw:74rem;
    --plate:#ffffff; --bx-repo-bg:#ffffff; --bx-repo-bd:#9aa6b2;
    --seam-bg:#e3eef2; --seam-bd:#1c6f8c; --ext-bg:#f6f0e2; --ext-bd:#a08a52;
    --ar:#5b6672; --num:#8a3d6b; --note:#4a5763;
  }
  @media (prefers-color-scheme: dark){:root{
    --paper:#0d1116; --surface:#161d25; --ink:#eaeff4; --muted:#9aa5b1; --faint:#6f7b87;
    --line:#26303a; --accent:#5fb4c8; --accent-soft:#123039;
    --plate:#0f141b; --bx-repo-bg:#131a22; --bx-repo-bd:#44515f;
    --seam-bg:#123039; --seam-bd:#5fb4c8; --ext-bg:#2a2416; --ext-bd:#b39a5c;
    --ar:#8793a2; --num:#d081ac; --note:#9aa5b1;
  }}
  :root[data-theme="light"]{
    --paper:#f4f6f8; --surface:#ffffff; --ink:#131820; --muted:#59636f; --line:#dde2e8;
    --plate:#ffffff; --bx-repo-bg:#ffffff; --bx-repo-bd:#9aa6b2;
    --seam-bg:#e3eef2; --seam-bd:#1c6f8c; --ext-bg:#f6f0e2; --ext-bd:#a08a52;
    --ar:#5b6672; --num:#8a3d6b; --note:#4a5763;
  }
  :root[data-theme="dark"]{
    --paper:#0d1116; --surface:#161d25; --ink:#eaeff4; --muted:#9aa5b1; --line:#26303a;
    --plate:#0f141b; --bx-repo-bg:#131a22; --bx-repo-bd:#44515f;
    --seam-bg:#123039; --seam-bd:#5fb4c8; --ext-bg:#2a2416; --ext-bd:#b39a5c;
    --ar:#8793a2; --num:#d081ac; --note:#9aa5b1;
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
  .num{fill:var(--num)} .num-t{fill:#fff;font:600 11px var(--fs-mono)}
  .pill-seam{fill:var(--seam-bd)} .pill-ext{fill:var(--ext-bd)}
  .pill-t{fill:#fff;font:600 9px var(--fs-mono);letter-spacing:.04em}
  .note-t{fill:var(--note);font:400 12.5px var(--fs-sans)}
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
