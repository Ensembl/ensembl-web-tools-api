#!/usr/bin/env python3
"""Generate the VEP two-repo overview (repo-overview.html) — a hand-built,
theme-aware SVG flow chart, matching the house style of dataflow-diagram.py
(no mermaid, no runtime).

Scope: the VEP slice only. The tools API also serves BLAST; none of that is
drawn. Everything the two repos talk to that is *not* one of the two repos is
drawn in the right-hand column and marked EXTERNAL. The spec JSONs are marked
API SEAM — those are the reads that become calls to the annotation API.

Re-run after edits; writes the HTML next to this script.
"""
import html, os

W = 1240

# --- lanes -------------------------------------------------------------------
LANES = [
    ("FE",  "Frontend",  "standalone-web-vep",    "fe",   210),
    ("BE",  "Backend",   "ensembl-web-tools-api · vep/", "be", 640),
    ("EXT", "Outside",   "services, data, the web", "ext", 1055),
]
LX = {lid: x for lid, _, _, _, x in LANES}
LANE_CLASS = {lid: cls for lid, _, _, cls, _ in LANES}
BAND_W = {"FE": 330, "BE": 420, "EXT": 300}

HEAD_TOP, HEAD_H = 16, 44
TOP = HEAD_TOP + HEAD_H + 22

# --- nodes -------------------------------------------------------------------
# (id, lane, y, title, subtitle, kind)
#   kind: plain | seam (the JSON→API seam) | ext (external system)
NODES = [
    # Phase 1 — build the form
    ("species",  "FE",  TOP,        "Species selector",         "VepSpeciesSelector (overlay)",   "plain"),
    ("meta",     "EXT", TOP,        "Genome metadata / search", "genome + species lookup",        "ext"),
    ("formcfg",  "BE",  TOP + 78,   "GET form_config/{genome}", "vep_resources",                  "plain"),
    ("panels",   "BE",  TOP + 148,  "form_panels.get_visible_panels", "which panels/options show", "plain"),
    ("specjson", "BE",  TOP + 222,  "specs/*.json",             "annotation_library + per-genome", "seam"),
    ("form",     "FE",  TOP + 148,  "Job options form",         "VepFormOptionsPanel",            "plain"),

    # Phase 2 — submit
    ("submit",   "FE",  TOP + 300,  "Submit",                   "parameters + VCF",               "plain"),
    ("post",     "BE",  TOP + 300,  "POST submissions",         "ConfigIniParams",                "plain"),
    ("emit",     "BE",  TOP + 370,  "config_interpreter",       "options → config.ini lines",     "plain"),
    ("pin",      "BE",  TOP + 440,  "Pin sidecars",             "parsing · expected cols · panels", "plain"),
    ("vepsup",   "EXT", TOP + 370,  "VEP support files",        "gff + fasta paths (metadata)",   "ext"),

    # Phase 3 — run
    ("runner",   "BE",  TOP + 516,  "Launch / poll run",        "nextflow.py (prod) · DUMP_INI (dev)", "plain"),
    ("seqera",   "EXT", TOP + 516,  "Seqera / Nextflow",        "runs VEP + plugins",             "ext"),
    ("plugdata", "EXT", TOP + 586,  "Plugin data on /nfs",      "gnomAD, ClinVar, GO, …",         "ext"),

    # Phase 4 — results
    ("results",  "BE",  TOP + 660,  "GET results",              "vcf_results + spec_interpreter", "plain"),
    ("filters",  "BE",  TOP + 730,  "Filter / download",        "results_filters · TSV, VCF",     "plain"),
    ("detail",   "FE",  TOP + 660,  "Results + annotations",    "displaySpecRenderer",            "plain"),
    ("links",    "EXT", TOP + 660,  "Link-outs",                "ClinVar, AmiGO, OpenTargets, …", "ext"),
]
NODE = {n[0]: n for n in NODES}
NH = 46

# --- edges -------------------------------------------------------------------
# (from, to, label, kind)   kind: flow | ext | seam
EDGES = [
    ("species", "meta",     "species search",              "ext"),
    ("species", "formcfg",  "on selection",                "flow"),
    ("formcfg", "panels",   "",                            "flow"),
    ("panels",  "specjson", "reads options",               "seam"),
    ("formcfg", "form",     "panels + options",            "flow"),
    ("submit",  "post",     "parameters + VCF",            "flow"),
    ("post",    "emit",     "",                            "flow"),
    ("emit",    "specjson", "reads config spec",           "seam"),
    ("emit",    "vepsup",   "gff / fasta",                 "ext"),
    ("emit",    "pin",      "",                            "flow"),
    ("pin",     "runner",   "",                            "flow"),
    ("runner",  "seqera",   "launch + poll",               "ext"),
    ("seqera",  "plugdata", "reads",                       "ext"),
    ("runner",  "results",  "output VCF + sidecars",       "flow"),
    ("submit",  "runner",   "poll status · 15s",           "flow"),
    ("results", "detail",   "annotations + spec",  "flow"),
    ("detail",  "links",    "user clicks out",             "ext"),
    ("results", "filters",  "",                            "flow"),
]

# --- contracts: the seams where one side must match the other ---------------
# (anchor node, text) — drawn as a numbered marker on the node, listed below.
CONTRACTS = [
    ("form",     "Option id = submission parameter name"),
    ("post",     "Every option id is a ConfigIniParams field"),
    ("emit",     "Emitted fields = the CSQ columns VEP writes"),
    ("pin",      "Pinned spec digest = the ruleset results are read with"),
    ("results",  "Expected columns present (extras ignored)"),
    ("detail",   "Display refs resolve to parse targets; scopes from plugin_scopes"),
]
CONTRACT_AT = {}
for i, (nid, _) in enumerate(CONTRACTS, start=1):
    CONTRACT_AT.setdefault(nid, i)


def esc(t):
    return html.escape(t, quote=True)


frags = []
H = max(n[2] for n in NODES) + NH + 34

# lane bands + headers
back, heads = [], []
for lid, title, sub, cls, cx in LANES:
    bw = BAND_W[lid]
    back.append(
        f'<rect x="{cx-bw/2:.1f}" y="8" width="{bw}" height="{H-16:.1f}" rx="12" class="band-{cls}"/>'
    )
    heads.append(
        f'<rect x="{cx-150:.1f}" y="{HEAD_TOP}" width="300" height="{HEAD_H}" rx="9" class="hd-{cls}"/>'
        f'<text x="{cx:.1f}" y="{HEAD_TOP+16:.1f}" class="hd-title" text-anchor="middle" dominant-baseline="central">{esc(title)}</text>'
        f'<text x="{cx:.1f}" y="{HEAD_TOP+31:.1f}" class="hd-sub" text-anchor="middle" dominant-baseline="central">{esc(sub)}</text>'
    )

NODE_W = {"FE": 250, "BE": 320, "EXT": 230}


def node_box(nid):
    _, lane, y, title, sub, kind = NODE[nid]
    cx, w = LX[lane], NODE_W[lane]
    return cx - w / 2, y, w, NH


# edges first (under the boxes)
for frm, to, label, kind in EDGES:
    x1, y1, w1, h1 = node_box(frm)
    x2, y2, w2, h2 = node_box(to)
    c1, c2 = x1 + w1 / 2, x2 + w2 / 2
    cls = {"flow": "e-flow", "ext": "e-ext", "seam": "e-seam"}[kind]
    if abs(c1 - c2) < 2 and y2 > y1:           # straight down, same lane
        sy, ey = y1 + h1, y2
        frags.append(
            f'<line x1="{c1:.1f}" y1="{sy:.1f}" x2="{c1:.1f}" y2="{ey-7:.1f}" class="{cls}" marker-end="url(#ah2)"/>'
        )
        if label:
            frags.append(
                f'<text x="{c1+8:.1f}" y="{(sy+ey)/2:.1f}" class="e-lbl" dominant-baseline="central">{esc(label)}</text>'
            )
    elif abs(c1 - c2) < 2:                     # back up the same lane: route round the left
        my1, my2 = y1 + h1 / 2, y2 + h2 / 2
        bx = x1 - 40                           # just outside the boxes, inside the band
        frags.append(
            f'<path d="M{x1:.1f},{my1:.1f} H{bx:.1f} V{my2:.1f} H{x2-7:.1f}" class="{cls}" fill="none" marker-end="url(#ah2)"/>'
        )
        if label:
            # in the lane gap, and in the clear strip under the target row so it
            # misses both the boxes and the other gap labels
            tw = len(label) * 6.0 + 10
            lx, ly = x1 - 73, y2 + h2 + 16
            frags.append(
                f'<rect x="{lx-tw/2:.1f}" y="{ly-9:.1f}" width="{tw:.1f}" height="18" rx="4" class="e-lbl-bg"/>'
                f'<text x="{lx:.1f}" y="{ly:.1f}" class="e-lbl" text-anchor="middle" dominant-baseline="central">{esc(label)}</text>'
            )
    else:                                      # across lanes
        left_to_right = c2 > c1
        sx = x1 + w1 if left_to_right else x1
        ex = x2 if left_to_right else x2 + w2
        my1, my2 = y1 + h1 / 2, y2 + h2 / 2
        gap = 7 if left_to_right else -7
        if abs(my1 - my2) < 2:                 # straight across
            frags.append(
                f'<line x1="{sx:.1f}" y1="{my1:.1f}" x2="{ex-gap:.1f}" y2="{my1:.1f}" class="{cls}" marker-end="url(#ah2)"/>'
            )
            lx = sx + (72 if left_to_right else -72)
            # opposing edges can share a row (results->detail and detail->links),
            # so sit above the line going right and below it going left
            ly = my1 + (-13 if left_to_right else 13)
            if label:
                tw = len(label) * 6.0 + 10
                frags.append(
                    f'<rect x="{lx-tw/2:.1f}" y="{ly-9:.1f}" width="{tw:.1f}" height="18" rx="4" class="e-lbl-bg"/>'
                    f'<text x="{lx:.1f}" y="{ly:.1f}" class="e-lbl" text-anchor="middle" dominant-baseline="central">{esc(label)}</text>'
                )
        else:                                  # dog-leg
            midx = sx + (72 if left_to_right else -72)
            frags.append(
                f'<path d="M{sx:.1f},{my1:.1f} H{midx:.1f} V{my2:.1f} H{ex-gap:.1f}" class="{cls}" fill="none" marker-end="url(#ah2)"/>'
            )
            if label:
                tw = len(label) * 6.0 + 10
                frags.append(
                    f'<rect x="{midx-tw/2:.1f}" y="{(my1+my2)/2-9:.1f}" width="{tw:.1f}" height="18" rx="4" class="e-lbl-bg"/>'
                    f'<text x="{midx:.1f}" y="{(my1+my2)/2:.1f}" class="e-lbl" text-anchor="middle" dominant-baseline="central">{esc(label)}</text>'
                )

# boxes
for nid, lane, y, title, sub, kind in NODES:
    x, _, w, h = node_box(nid)
    cx = x + w / 2
    cls = {"plain": f"nb nb-{LANE_CLASS[lane]}", "seam": "nb nb-seam", "ext": "nb nb-ext"}[kind]
    frags.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h}" rx="8" class="{cls}"/>')
    frags.append(
        f'<text x="{cx:.1f}" y="{y+17:.1f}" class="nb-t" text-anchor="middle" dominant-baseline="central">{esc(title)}</text>'
        f'<text x="{cx:.1f}" y="{y+32:.1f}" class="nb-s" text-anchor="middle" dominant-baseline="central">{esc(sub)}</text>'
    )
    if kind == "seam":
        frags.append(
            f'<rect x="{x+w-72:.1f}" y="{y-9:.1f}" width="66" height="18" rx="9" class="pill-seam"/>'
            f'<text x="{x+w-39:.1f}" y="{y:.1f}" class="pill-t" text-anchor="middle" dominant-baseline="central">API SEAM</text>'
        )
    if kind == "ext":
        frags.append(
            f'<rect x="{x+w-66:.1f}" y="{y-9:.1f}" width="60" height="18" rx="9" class="pill-ext"/>'
            f'<text x="{x+w-36:.1f}" y="{y:.1f}" class="pill-t" text-anchor="middle" dominant-baseline="central">EXTERNAL</text>'
        )
    if nid in CONTRACT_AT:
        n = CONTRACT_AT[nid]
        frags.append(
            f'<circle cx="{x-11:.1f}" cy="{y+h/2:.1f}" r="10" class="ct-c"/>'
            f'<text x="{x-11:.1f}" y="{y+h/2:.1f}" class="ct-t" text-anchor="middle" dominant-baseline="central">C{n}</text>'
        )

svg = (
    f'<svg class="d-svg" viewBox="0 0 {W} {H:.0f}" width="{W}" height="{H:.0f}" '
    f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="VEP two-repo overview flow chart">'
    f'<defs><marker id="ah2" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto" '
    f'markerUnits="userSpaceOnUse"><path d="M0,0 L7,3 L0,6 Z" class="ah"/></marker></defs>'
    + "".join(back) + "".join(heads) + "".join(frags) + "</svg>"
)

CONTRACT_ROWS = "".join(
    f'<div class="row"><p class="q"><span class="tag">C{i}</span>{esc(text)}</p></div>'
    for i, (_, text) in enumerate(CONTRACTS, start=1)
)

PAGE = r"""<!-- Generated by repo-overview.py. Edit that and re-run; changes made here are lost on the next generate. -->
<title>Web Ensembl VEP — two-repo overview</title>
<style>
  :root{
    --paper:#f4f6f8; --surface:#ffffff; --ink:#131820; --muted:#59636f; --faint:#808b97;
    --line:#dde2e8; --accent:#1c6f8c; --accent-soft:#e3eef2;
    --fs-mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
    --fs-sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; --maxw:84rem;
    --d-plate:#ffffff; --d-ink:#1b2430;
    --band-fe:#eceef1; --band-be:#eaebf6; --band-ext:#efeade;
    --hd-fe:#6b7684; --hd-be:#4a4f8c; --hd-ext:#7a6a45;
    --nb-fe:#ffffff; --nb-be:#ffffff; --nb-bd:#c8d0da;
    --seam-bg:#e3eef2; --seam-bd:#1c6f8c; --ext-bg:#f6f0e2; --ext-bd:#a08a52;
    --e-flow:#7a8794; --e-ext:#a08a52; --e-seam:#1c6f8c; --e-lbl:#5b6672;
    --ct:#8a3d6b;
  }
  @media (prefers-color-scheme: dark){:root{
    --paper:#0d1116; --surface:#161d25; --ink:#eaeff4; --muted:#9aa5b1; --faint:#6f7b87;
    --line:#26303a; --accent:#5fb4c8; --accent-soft:#123039;
    --d-plate:#0f141b; --d-ink:#e6edf4;
    --band-fe:#161d27; --band-be:#1a1c35; --band-ext:#231f14;
    --hd-fe:#7c8794; --hd-be:#5c62b0; --hd-ext:#8a7746;
    --nb-fe:#131a22; --nb-be:#131a22; --nb-bd:#33414f;
    --seam-bg:#123039; --seam-bd:#5fb4c8; --ext-bg:#2a2416; --ext-bd:#b39a5c;
    --e-flow:#8793a2; --e-ext:#b39a5c; --e-seam:#5fb4c8; --e-lbl:#9aa5b1;
    --ct:#d081ac;
  }}
  :root[data-theme="light"]{
    --paper:#f4f6f8; --surface:#ffffff; --ink:#131820; --muted:#59636f; --line:#dde2e8;
    --d-plate:#ffffff; --d-ink:#1b2430;
    --band-fe:#eceef1; --band-be:#eaebf6; --band-ext:#efeade;
    --hd-fe:#6b7684; --hd-be:#4a4f8c; --hd-ext:#7a6a45;
    --nb-fe:#ffffff; --nb-be:#ffffff; --nb-bd:#c8d0da;
    --seam-bg:#e3eef2; --seam-bd:#1c6f8c; --ext-bg:#f6f0e2; --ext-bd:#a08a52;
    --e-flow:#7a8794; --e-ext:#a08a52; --e-seam:#1c6f8c; --e-lbl:#5b6672; --ct:#8a3d6b;
  }
  :root[data-theme="dark"]{
    --paper:#0d1116; --surface:#161d25; --ink:#eaeff4; --muted:#9aa5b1; --line:#26303a;
    --d-plate:#0f141b; --d-ink:#e6edf4;
    --band-fe:#161d27; --band-be:#1a1c35; --band-ext:#231f14;
    --hd-fe:#7c8794; --hd-be:#5c62b0; --hd-ext:#8a7746;
    --nb-fe:#131a22; --nb-be:#131a22; --nb-bd:#33414f;
    --seam-bg:#123039; --seam-bd:#5fb4c8; --ext-bg:#2a2416; --ext-bd:#b39a5c;
    --e-flow:#8793a2; --e-ext:#b39a5c; --e-seam:#5fb4c8; --e-lbl:#9aa5b1; --ct:#d081ac;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--fs-sans);
       font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
  .wrap{max-width:var(--maxw);margin:0 auto;padding:2.4rem 1.4rem 3.4rem}
  .eyebrow{font-family:var(--fs-mono);font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;
           color:var(--accent);margin:0 0 .5rem}
  h1{font-size:1.7rem;line-height:1.22;margin:0 0 .6rem;letter-spacing:-.01em}
  .lede{color:var(--muted);margin:0 0 1.2rem;max-width:62rem}
  .legend{display:flex;flex-wrap:wrap;gap:.5rem 1.25rem;margin:0 0 1.2rem;padding:.9rem 1.1rem;
          background:var(--surface);border:1px solid var(--line);border-radius:12px}
  .chip{display:inline-flex;align-items:center;gap:.5rem;font-size:.85rem;color:var(--ink)}
  .chip small{color:var(--faint)}
  .dot{width:11px;height:11px;border-radius:50%;display:inline-block}
  .dot.fe{background:var(--hd-fe)} .dot.be{background:var(--hd-be)} .dot.ext{background:var(--hd-ext)}
  .dot.seam{background:var(--seam-bd)} .dot.ct{background:var(--ct)}
  .plate-shell{background:var(--surface);border:1px solid var(--line);border-radius:14px;overflow:hidden}
  .plate-cap{display:flex;justify-content:space-between;gap:1rem;padding:.7rem 1rem;
             border-bottom:1px solid var(--line);font-family:var(--fs-mono);font-size:.72rem;
             letter-spacing:.08em;text-transform:uppercase;color:var(--faint)}
  .plate{padding:1rem;overflow-x:auto;background:var(--d-plate)}
  .d-svg{display:block;min-width:1240px;margin:0 auto}
  .band-fe{fill:var(--band-fe)} .band-be{fill:var(--band-be)} .band-ext{fill:var(--band-ext)}
  .hd-fe{fill:var(--hd-fe)} .hd-be{fill:var(--hd-be)} .hd-ext{fill:var(--hd-ext)}
  .hd-title{fill:#fff;font:600 13px var(--fs-sans)}
  .hd-sub{fill:#ffffffc0;font:400 10.5px var(--fs-mono)}
  .nb{stroke:var(--nb-bd);stroke-width:1}
  .nb-fe{fill:var(--nb-fe)} .nb-be{fill:var(--nb-be)}
  .nb-seam{fill:var(--seam-bg);stroke:var(--seam-bd);stroke-width:1.6}
  .nb-ext{fill:var(--ext-bg);stroke:var(--ext-bd);stroke-width:1.4}
  .nb-t{fill:var(--d-ink);font:600 12.5px var(--fs-sans)}
  .nb-s{fill:var(--muted);font:400 10.5px var(--fs-mono)}
  .e-flow{stroke:var(--e-flow);stroke-width:1.5;fill:none}
  .e-ext{stroke:var(--e-ext);stroke-width:1.5;stroke-dasharray:5 4;fill:none}
  .e-seam{stroke:var(--e-seam);stroke-width:1.8;stroke-dasharray:2 3;fill:none}
  .e-lbl{fill:var(--e-lbl);font:400 10px var(--fs-mono)}
  .e-lbl-bg{fill:var(--d-plate)}
  .ah{fill:var(--e-flow)}
  .pill-seam{fill:var(--seam-bd)} .pill-ext{fill:var(--ext-bd)}
  .pill-t{fill:#fff;font:600 9px var(--fs-mono);letter-spacing:.04em}
  .ct-c{fill:var(--ct)} .ct-t{fill:#fff;font:600 9.5px var(--fs-mono)}
  .sectionlabel{font-family:var(--fs-mono);font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;
                color:var(--faint);margin:2rem 0 .7rem}
  .rows{display:flex;flex-direction:column;gap:.5rem}
  .row{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--ct);
       border-radius:10px;padding:.7rem .95rem}
  .row .q{margin:0;font-weight:600;font-size:.92rem;display:flex;gap:.6rem;align-items:baseline}
  .tag{font-family:var(--fs-mono);font-size:.68rem;color:#fff;background:var(--ct);
       padding:.1rem .42rem;border-radius:5px;letter-spacing:.04em;flex:none}
  .grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(21rem,1fr));gap:.8rem;margin-top:1.2rem}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:1rem 1.1rem}
  .card h3{margin:0 0 .5rem;font-size:.95rem;display:flex;align-items:center;gap:.5rem}
  .card ul{margin:0;padding-left:1.05rem;color:var(--muted);font-size:.88rem}
  .card li{margin:.25rem 0}
  code{font-family:var(--fs-mono);font-size:.85em;background:var(--accent-soft);
       padding:.05rem .3rem;border-radius:4px}
  .foot{margin-top:1.8rem;color:var(--faint);font-size:.82rem;border-top:1px solid var(--line);padding-top:.9rem}
  .foot b{color:var(--muted)}
</style>
<div class="wrap">
  <p class="eyebrow">VEP: Repository overview</p>
  <h1>What lives where, and what each repo talks to</h1>
  <p class="lede">The two repos that make up VEP, the path a submission takes through them, and every point where either repo reaches <b>outside itself</b>. Only the VEP slice of the tools API is drawn — it also serves BLAST, which is out of scope here. Two kinds of edge are called out: <b>API&nbsp;seam</b> reads (dev version a local JSON file, live version the metadata API) and <b>external</b> hops.</p>
  <div class="legend" aria-label="Key">
    <span class="chip"><span class="dot fe"></span>Frontend <small>standalone-web-vep</small></span>
    <span class="chip"><span class="dot be"></span>Backend <small>ensembl-web-tools-api vep</small></span>
    <span class="chip"><span class="dot ext"></span>External <small>another service, the filesystem, or the web</small></span>
    <span class="chip"><span class="dot seam"></span>API seam <small>becomes a metadata-API call</small></span>
    <span class="chip"><span class="dot ct"></span>C1-6 <small>contract points</small></span>
  </div>
  <div class="plate-shell">
    <div class="plate-cap"><span>Flow: species selection through to results</span><span>dashed = leaves the repo</span></div>
    <div class="plate">__SVG__</div>
  </div>

  <p class="sectionlabel">Contract points - where one side must match the other</p>
  <div class="rows">__CONTRACTS__</div>

  <div class="grid2">
    <div class="card"><h3><span class="dot seam"></span>The API seam</h3><ul>
      <li>Two reads, both in the backend: <code>form_panels</code> (which options exist) and <code>spec_loader</code> (config + parsing + display for them)</li>
      <li>Today both resolve to <code>specs/annotation_library.json</code> plus a thin per-genome document (<code>human_grch38</code>, <code>human_grch37</code>)</li>
      <li>Everything downstream already works off the assembled document, so swapping the source is a change to those two reads - not to the interpreters</li>
      <li>The frontend never reads a spec: it only ever sees what the backend serves</li></ul></div>
    <div class="card"><h3><span class="dot ext"></span>Outside contacts</h3><ul>
      <li><b>Genome metadata / search</b> - species lookup for the selector, and the gff/fasta paths for a run</li>
      <li><b>Seqera / Nextflow</b> - launch and poll (prod). In dev this is a manual HPC run and a hand-placed VCF</li>
      <li><b>Plugin data on /nfs</b> - read by VEP itself, named by the config the backend emits. Currently specced for locations accessible in dev. Live mode requires moving to equivalent structure visible to web-prod cluster</li>
      <li><b>Link-outs</b> - ClinVar, AmiGO, OpenTargets, MaveDB, ProtVar, opened from the results panel</li></ul></div>
  </div>

  <p class="foot"><b>Generated by</b> <code>repo-overview.py</code> — edit the <code>NODES</code> / <code>EDGES</code> / <code>CONTRACTS</code> lists and re-run. Companion to <code>dataflow-diagram.html</code> (the per-request sequence) and <code>merged-annotation-spec.md</code> (the design).</p>
</div>
"""

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "repo-overview.html")
with open(out, "w") as f:
    f.write(PAGE.replace("__SVG__", svg).replace("__CONTRACTS__", CONTRACT_ROWS))
print(f"wrote {out}")
