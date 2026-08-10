# The VEP JSON specifications, and how to extend them

**How to add new annotation data, new options, and new output to the deployed
VEP tool** — what is data and what is code, the full grammar available in each
spec section, and worked examples from the simplest plugin to the hardest.

Verified 2026-08-09 against `ensembl-web-tools-api` `feature/extended_vep`
(= Ensembl `handover/web-vep`) at `ad15cda`, and `standalone-web-vep` `main` at
`880fa38`. Every table and count below was read out of the models and the
assembled spec rather than remembered; file references are given so you can
re-derive them when they move.

> This guide **supersedes** the two design documents that used to sit here,
> `adding-an-annotation-plugin.md` and `merged-annotation-spec.md`, and the
> `option-tiers-by-species.md` snapshot. All three were folded in on 2026-08-09
> and deleted; their durable content is in this document and in
> [technical-notes.md](./technical-notes.md). See
> [README.md](./README.md) for the mapping.
>
> Companions in this folder: [technical-notes.md](./technical-notes.md) (how the
> surrounding machinery works, and the reasoning behind it),
> [dataflow.md](./dataflow.md) (what calls what, end to end, plus the rendered
> diagrams), and [production-readiness.md](./production-readiness.md) (what must
> change before this leaves dev).

---

## Contents

1. [The one-paragraph version](#1-the-one-paragraph-version)
2. [The shape of the system](#2-the-shape-of-the-system)
3. [Where the data actually lives](#3-where-the-data-actually-lives)
4. [Recipe A — a simple plugin, end to end](#4-recipe-a--a-simple-plugin-end-to-end)
5. [Recipe B — a complex plugin](#5-recipe-b--a-complex-plugin)
6. [Recipe C — a new allele-frequency source](#6-recipe-c--a-new-allele-frequency-source)
7. [Recipe D — options with no data, and new filters](#7-recipe-d--options-with-no-data-and-new-filters)
8. [Reference — the `config` section](#8-reference--the-config-section)
9. [Reference — the `parsing` section](#9-reference--the-parsing-section)
10. [Reference — the `display` section](#10-reference--the-display-section)
11. [What fails at load time, and what the error looks like](#11-what-fails-at-load-time-and-what-the-error-looks-like)
12. [Traps](#12-traps)

---

## 1. The one-paragraph version

An annotation option is described by **JSON, not code**. One merged document per
genome carries three sibling sections — `config` (how a selected option becomes a
line in VEP's `config.ini`), `parsing` (how the CSQ columns that come back become
structured data), and `display` (how that data is laid out in the results panel).
The document is content-digested, pinned beside each job's output, and re-served
at results time, so a job's options, its parsing and its layout are provably the
same ruleset. Adding an annotation is: put the data file where the pipeline can
see it, and author **one config entry** — which carries its own form control in a
`form` block — plus, if it returns data worth showing, a parse plugin and a
display option. That is a JSON edit alone. Neither the submission model nor the
form panels need touching, and the frontend needs no change at all unless you are
inventing a rendering primitive that does not exist yet.

**Scale, as assembled today** (read from `load_merged_spec`, 2026-08-09):

| | human GRCh38 | human GRCh37 |
|---|---:|---:|
| config entries | 37 | 26 |
| …declaring a form control (`form` block) | 35 | 24 |
| …config-only (`parsed_as: []`) | 1 | 1 |
| parse plugins | 38 | 26 |
| display options | 34 | 20 |

---

## 2. The shape of the system

### 2.1 Three repos

| repo | role | branch that ships |
|---|---|---|
| `ensembl-web-tools-api` | the API: form config, submission, config.ini generation, results parsing, the spec documents | fork `feature/extended_vep` → Ensembl `handover/web-vep` |
| `standalone-web-vep` | the VEP frontend, developed standalone | fork `main` |
| `ensembl-client` | where the frontend is integrated for release | Ensembl `integration/vep-v2` |

Frontend work is authored in `standalone-web-vep` (its CI, fixture job and
browser preview all work there) and ported into `ensembl-client`. The two trees
diverge in ~51 integration files; VEP itself sits at the same path in both.

### 2.2 Spec documents and how they compose

```
app/vep/specs/
├── annotation_library.json   ← the SHARED parsing + display definitions (~3,560 lines)
├── base.json                 ← config entries every genome gets (no species data needed)
├── human_grch38.json         ← GRCh38's own config entries (availability + file paths)
├── human_grch37.json         ← GRCh37's own config entries
└── species_annotations.json  ← a TABLE: which of the other 50 species have GO/Phenotypes/CADD
```

`spec_loader.load_merged_spec("human_grch38")` assembles one document
(`_assemble_payload`, `spec_loader.py:162`):

1. Read the genome document. It is thin — identity plus `config.entries`.
2. Layer `base.json`'s entries under it (`_with_base_entries`). A genome may
   **override** a base entry by declaring the same `id`; its version wins.
   `order` is one numbering space across both tiers.
3. Read the `library` the genome names, and **select from it by what the genome
   enables** (`_select_library`, `spec_loader.py:102`):
   - the set of enabled plugins is the union of every config entry's `parsed_as`;
   - a `parsing` plugin is included if it is in that set;
   - a `display` option is included **only if every plugin it reads** (its
     `plugin_refs()`) is in that set.
4. Validate the whole thing as a `MergedSpec` — this runs the consistency checks
   in [§11](#11-what-fails-at-load-time-and-what-the-error-looks-like).
5. Compute the content digest from the *validated model's* canonical dump and
   stamp it onto `spec_version`.

**Consequence worth internalising:** step 3 is why an option can vanish silently.
If your config entry has `parsed_as: []`, no plugin is enabled by it, and any
display option that reads that plugin is filtered out of the assembled spec —
no error, just one fewer option. That has bitten twice.

A species with no spec of its own falls back to `base.json`, optionally plus GO /
Phenotypes / CADD entries built from `species_annotations.json`'s templates
(`species_extra_config_entries`). VEP needs only a GFF and a FASTA, so an
unlisted species still runs — it is simply offered fewer options.

### 2.3 What each genome is offered

The tiers **nest strictly** — base ⊂ GRCh37 ⊂ GRCh38, no entry dropping out along
the way. Counts re-derived 2026-08-09; regenerate with the snippet below rather
than trusting them.

| tier | who gets it | entries |
|---|---|---:|
| 0 | every species with a GFF+FASTA | 8 |
| 1 | the 50 species in `species_annotations.json` | +1 (GO) |
| 2 | 15 of those | +1 (Phenotypes) |
| 3 | 3 of those | +1 (CADD) |
| 4 | human GRCh37 | 26 |
| 5 | human GRCh38 | 37 |

**Tier 0 — the eight in `base.json`:** `hgvs`, `hgvsg` *(wired but hidden)*,
`spdi`, `protein`, `updownstream_distance`, `tss_distance`, `nearest_gene`,
`nearest_exon_jb`. They need no data file beyond the genome itself, which is what
makes them universal. An assembly in no table at all falls back to exactly this
set rather than raising — **gating decides which extra options a species is
offered, never whether it can run.**

**Tiers 1–3 are one table**, a species per row and a dataset per flag: 34 species
have GO alone, 13 GO+Phenotypes, 2 all three, and 1 has **GO+CADD but no
Phenotypes** (turkey). So CADD is a *sibling* of Phenotypes, not a step above it
— the table expresses per-dataset availability, not a ladder, which is why that
one species needs nothing special to express.

Non-human CADD species get a single `snv=` file (no indels), and two of the three
never score `CADD_RAW` — it arrives as the VCF null `.`, reads as absent, and the
RAW row drops itself. Both columns are still emitted and still expected.

**Tier 4 — GRCh37 adds 18 over base:** AlphaMissense, CADD, ClinPred, REVEL,
SpliceAI · Dosage sensitivity, Gene Ontology, LOEUF, NMD, UTRAnnotator ·
Phenotypes, Geno2MP, ClinVar structural variants (+ `clinvar_short`, which has no
control of its own) · IntAct · gnomAD Exomes v2.1.1, Genomes v2.1, SV v2.1.

★ GRCh37 gets the **v2** gnomAD trio, not v4 — that is the whole point of the v2
work, and it is the claim most often written down wrong.

**Tier 5 — GRCh38 adds 11 more:** NIH All of Us, gnomAD CNV v4.1 · EVE & popEVE,
GERP conservation score · MaveDB, mutfunc, ProtVar · OpenTargets · pLI,
RiboSeqORFs · GENCODE promoter. (Human's own GO, Phenotypes and CADD come from
its spec documents, not the species table — its GO file carries an assembly
suffix the table's filename rule does not produce.)

**The asymmetry worth noticing:** tiers 1–3 are a table, tiers 4–5 are
hand-written documents. That is why adding a species is a one-row change while
adding a new *kind* of data to human is not.

★ **Resolve the assembly name from the metadata API**
(`/api/metadata/genome/{accession}/explain`), never from classic Ensembl REST —
the two disagree for several species, and a submission carries the metadata API's
name. A wrong name fails silently: the species drops to tier 0 with no error.

```python
# from app/, PYTHONPATH=. and the py3.11 venv
from vep.utils.spec_loader import load_merged_spec, _species_annotations
from collections import Counter

ids = lambda n: [e.id for e in load_merged_spec(n).config.entries]
base, g37, g38 = ids("base"), ids("human_grch37"), ids("human_grch38")
assert set(base) <= set(g37) <= set(g38), "tiers no longer nest"
print(len(base), len(g37), len(g38))
for combo, n in Counter(
    tuple(sorted(r["datasets"])) for r in _species_annotations()["species"]
).most_common():
    print(n, "+".join(combo))
```

### 2.4 The lifecycle of one submission

```
FORM                      SUBMIT                     PIPELINE            RESULTS
────                      ──────                     ────────            ───────
form_config           →   ConfigIniParams        →   VEP runs        →  results route
  ↑                         ↓                          ↓                    ↓
form_panels.py          config section              output.vcf.gz      parsing + display
(panel list only;       → config.ini                 (CSQ column       sections of the
 every option comes                                   per field)       PINNED sidecar
 from a `form` block)
                        pins 3 sidecars beside the job:
                          parsing_spec.json     ← the WHOLE merged doc (config+parsing+display)
                          expected_columns.json ← the CSQ columns these options must produce
                          display_panels.json   ← the panel/category layout as submitted
```

The three sidecars are what make a job reproducible. They also mean **a spec
change is invisible to an existing job** — the results view renders the pinned
layout, correctly. To see a display change you must make a *new* submission, or
rewrite the sidecar by hand (see [§12](#12-traps)).

### 2.5 What is still code

Two things left this table in August 2026 and are worth naming, because most
older notes still assume them:

- **Form options.** They used to be literal dicts in `form_panels.py`. Every one
  now comes from a `form` block on its own config entry
  ([§8.5](#85-the-form-block)); `form_panels.py` is down from 1,081 to 492 lines
  and holds the panel list, the AF sub-option *generators*, the label decoders
  and the placement — no option data and no species/assembly branching.
- **The submission model.** `ConfigIniParams` used to declare 207 fields, 199 of
  them one per control. It now has **nine**: eight job fields, each actually read
  by attribute, and one `options: dict[str, bool|int|str]` completed and checked
  against the spec. See
  [technical-notes.md § The submission contract](./technical-notes.md#the-submission-contract-configiniparams-207-fields--9).

What genuinely remains code:

| still code | where | why |
|---|---|---|
| the panel list, and the species/assembly predicates | `form_panels.py` | seven panel ids and their labels; a panel with no options is simply not shown |
| AF sub-option **generation** | `form_panels._af_sub_options` | 122 of GRCh38's 169 option nodes are ancestry x sex combinations; nobody should hand-write those, and they are grown from the same `fields=` tables that write the config line |
| AF label **decoding** | `form_panels.af_population_label` | a function over a declared table, shared with the results metadata — not presentation data |
| the always-on VEP invariants (`force_overwrite`, `symbol`, `numbers`, `mane`…) | `pipeline_model.base_config_lines` | invocation invariants, not per-option |
| plugin-data path resolution | `pipeline_model.py` | see [§3](#3-where-the-data-actually-lives) |
| named link builders (3 of them) | `displaySpecRenderer.tsx` | they need job context no annotation field carries |
| formatter functions | `annotationRows.tsx` | the 8 `format` values are names for these |
| results **filter** fields | `app/vep/utils/results_filters.py` + `resultsFilterFields.ts` | the filter path is a streaming scanner over the VCF, not the spec renderer |

Everything else is JSON.

---

## 3. Where the data actually lives

There is **no database**. VEP reads flat, indexed files from a filesystem the
pipeline node can see: bgzipped+tabixed VCF/TSV/BED/GFF, bigWig, and (for
ProtVar) a SQLite `.db`. "Loading new data" means placing an indexed file and
pointing a config entry at it.

### 3.1 The `{path}` token

Config entries never name absolute paths. They write `{path}/my_data.vcf.gz`, and
`config_interpreter` substitutes it (`config_interpreter.py:42`, `:244`). What it
substitutes depends on where you are:

| context | resolver | value |
|---|---|---|
| production | `PLUGIN_PATH`, `pipeline_model.py:76` | **`/[placeholder_path]`** — a deliberate placeholder. Nothing runs against real data until per-genome resolution is wired. This is a known pre-production TODO. |
| dev (`DUMP_INI`) | `_dev_plugin_path(assembly)`, `pipeline_model.py:110` | the real beta layout on nfs, per assembly, plus a named subdir for the few datasets that live in one |

The dev resolver is a *function of the config-entry id*, not a constant:

```python
_DEV_PLUGIN_ROOT = {
    "GRCh38": ".../beta_plugins/grch38",
    "GRCh37": ".../beta_plugins/grch37",
}
_DEV_PLUGIN_SUBDIRS = {           # entry id → subdir under the root
    "allofus": "AllOfUs", "go": "GO_data_files", "phenotypes": "Phenotypes_data_files",
    "gnomad_cnv": "gnomAD_CNV", "gnomad_sv": "gnomAD_SV",
    "gnomad_exomes": "gnomAD_exomes", "gnomad_genomes": "gnomAD_genomes",
}
_DEV_OTHER_SPECIES_ROOT = ".../beta_plugins/other_species"
```

An assembly with no root of its own resolves under the other-species tree — not
under GRCh38, which is what it used to do and which pointed a cattle job at human
files.

**So to add a dataset in dev:** drop the indexed file into the assembly's root
(or add a `_DEV_PLUGIN_SUBDIRS` entry if it needs its own directory) and write
`{path}/<filename>` in the config entry. For a per-assembly file, use
`by_assembly` rather than two entries.

### 3.2 Per-species data files

`species_annotations.json` is a table, not a document per species, because the
file names follow entirely from the production name. Today: **50 species**, of
which 50 carry GO, 15 carry Phenotypes and 3 carry CADD. The `templates` block
states the rule once:

```jsonc
"templates": {
  "go":         { /* a config entry whose params use "{production_name}" */ },
  "phenotypes": { /* … */ },
  "cadd":       { /* uses "{file}" — CADD's files are named per project, not per species */ }
},
"species": [
  { "assembly": "GRCm39", "production_name": "mus_musculus",
    "species_taxonomy_id": "10090", "datasets": ["go", "phenotypes"] }
]
```

Adding a species' GO file is therefore **one row**. `{production_name}` and
`{file}` are substituted by `species_extra_config_entries`; `{path}` is left
alone and resolved later, per entry, like everything else.

Two gotchas already paid for: the classic Ensembl REST assembly names disagree
with the metadata API's for four species, and assembly matching requires a
separator after the table name (`_is_same_assembly`) so that Ciona's assembly
`KH` cannot claim an unrelated `KH…` genome.

### 3.3 The pipeline itself

In dev there is no automated end-to-end run: the API writes a `config.ini` dump
(`DUMP_INI`), the Nextflow/VEP step is run manually on the HPC, and the output
VCF plus its sidecars are copied into `dev-data/`. Seqera wiring is scaffolded
but not live — see `seqera-wiring-todo.md` in this folder.

---

## 4. Recipe A — a simple plugin, end to end

**Definition of simple:** one VEP plugin, one data file, one or two CSQ columns,
each a scalar, shown as label/value rows.

The real example this mirrors is **Geno2MP**, added 2026-08-06. Here it is,
complete and unedited, from the three sections.

### Step 1 — the config entry, control included (`human_grch38.json`)

One entry now carries both halves: how the option emits a `config.ini` line, and
how it appears on the form.

```jsonc
{
  "id": "geno2mp",
  "order": 44,                       // position in the emitted config.ini
  "parsed_as": ["geno2mp"],          // ← the parse plugin(s) this option feeds
  "form": {
    "panel": "variant_impact_predictions",
    "label": "Geno2MP",
    "category": "Annotations",
    "type": "boolean",
    "default": false,
    "order": 850                     // position within the panel — NOT the ini order
  },
  "config": {
    "emit": "plugin",
    "name": "Geno2MP",
    "params": {
      "file": { "by_assembly": {
        "GRCh38": "{path}/Geno2MP.variants_GRCh38.vcf.gz",
        "GRCh37": "{path}/Geno2MP.variants_GRCh37.vcf.gz"
      }}
    }
  }
}
```

→ emits `plugin Geno2MP,file=/…/Geno2MP.variants_GRCh38.vcf.gz`, and puts a
checkbox in "Variant impact predictions" under the "Annotations" category.

The entry's `id` is the seam that carries a selection through the whole system —
it is the form option id, the key in the submission's `options` map, and what
`parsed_as` hangs off. Full `form` grammar in [§8.5](#85-the-form-block).

**Assembly gating is one decision, not three.** Declare the entry in
`human_grch38.json` and it exists for GRCh38 only: `_select_library` drops the
parse plugin and the display option for GRCh37 by itself, and
`_spec_form_options` reads the *assembled* spec, so GRCh37 simply has nothing to
place. pLI was added this way in August 2026 and needed no per-assembly branch
anywhere.

Panels and categories are **backend-only**: the results panel lays itself out
from the pinned form panels and groups by the same `category`, so moving an
option between panels needs no frontend change at all.

### Step 2 — the parse plugin (`annotation_library.json`)

```jsonc
{
  "plugin": "geno2mp",
  "scope": "allele",                        // or "transcript"
  "output": "geno2mp",                      // where it attaches on the response
  "csq_fields": ["Geno2MP_HPO_count", "Geno2MP_URL"],
  "require_any_output": ["hpo_profile_count"],
  "targets": [
    { "field": "hpo_profile_count", "from": "Geno2MP_HPO_count",
      "transform": "scalar", "type": "int" },
    { "field": "url", "from": "Geno2MP_URL",
      "transform": "scalar", "type": "string" }
  ]
}
```

`csq_fields` is load-bearing three times over: it is the "did this plugin run"
test (none of its columns in the header ⇒ skip the plugin entirely), it feeds
`expected_csq_columns` (the runtime missing-field check), and it feeds the
frontend's availability gates. Getting it wrong is silent.

### Step 3 — the display option (`annotation_library.json`)

```jsonc
{
  "option_id": "geno2mp",
  "blocks": [
    { "kind": "rows", "heading": "Geno2MP", "rows": [
      { "label": "HPO profiles",
        "from": "geno2mp.hpo_profile_count",
        "format": "num",
        "link": { "kind": "external", "template": "{value}" },
        "link_from": "geno2mp.url" }
    ]}
  ]
}
```

The reader sees a count; the link goes to the variant's Geno2MP page. `link_from`
on a **row** is a `<plugin>.<field>` ref (it is checked by `field_refs()`); on a
cell or item it is an *element* field. `template: "{value}"` means the value read
from `link_from` **is** the URL.

### Step 4 — mirror into the baseline

`app/tests/human_grch38.baseline.json` is a hand-maintained byte-copy of the
pre-split monolith, compared against the assembled spec by
`test_spec_loader.py::test_assembled_grch38_matches_the_pre_split_baseline`. Make
the **identical edit** there. It mirrors the config entries too, not just
parsing+display — including its own copy of `parsed_as`.

It is not a programmatic dump; all four obvious serialisations differ in size.
But a JSON round-trip *is* byte-identical with
`json.dumps(doc, indent=2, ensure_ascii=False) + "\n"` (`ensure_ascii=False`
matters — SpliceAI's ΔS/ΔP labels), which makes scripted edits safe within a file.

### Step 5 — the frontend fixture

```bash
PYTHONPATH=app .venv/bin/python app/vep/scripts/generate_display_fixture.py
```

Run from the tools-api checkout; it rewrites `displaySpec.fixture.ts` in the
sibling `standalone-web-vep`. The fixture is byte-equal to the served
`display_payload`, and a CI job checks it against the fork's
`feature/extended_vep` — so **the backend half must merge first**.

### Step 6 — verify

```bash
PYTHONPATH=app .venv/bin/python -m pytest app/tests -q
```

(one pre-existing failure: `test_blast.py::test_read_config`, missing `.env`)

```bash
node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json && node node_modules/vitest/vitest.mjs run
```

Then regenerate the dev-data sidecar and restart the API — see
[§12](#12-traps), because this is where most of the wasted time goes.

---

## 5. Recipe B — a complex plugin

"Complex" in practice means one of five things. Each has a construct for it, and
the point of this section is to name which construct solves which problem, so you
reach for the right one instead of inventing a frontend case.

### 5.1 The source packs several columns that belong to one table

**Construct: `zip`.** N aligned `&`-separated columns become a list of objects,
positions preserved so `NA` placeholders keep the columns aligned.

```jsonc
{ "field": "assays", "from": ["MaveDB_score", "MaveDB_accession", "MaveDB_pro"],
  "transform": "zip", "align": "max",
  "as": [ {"field": "score", "type": "float"},
          {"field": "accession"},
          {"field": "pro"} ],
  "drop_when": { "all_null": true },
  "item_fields": ["score", "accession", "pro", "urn"] }
```

`align: max` pads to the longest column, `min` truncates to the shortest — the
existing parsers genuinely disagree, so it is explicit. `item_fields` is purely
declarative: it is what lets a display block reference `score` and have that ref
checked at load time.

### 5.2 The source packs whole sub-records into one column

**Constructs: `chunk`, `records`, `positional`, `regex`.**

| shape | construct |
|---|---|
| a flat run of items, N per object | `chunk` with `size` |
| the same, but the source marks record boundaries | `chunk` with `size` + `record_sep` |
| two levels of separator (records, then fields within a record) | `records` (`sep` / `item_sep`) |
| one object, fields assigned by index | `positional` (+ `wrap: "list"` for a one-element list) |
| named groups out of free text | `regex` (+ `each` to apply per item) |

The `record_sep` case is worth understanding because it is the general lesson.
ProtVar's pocket data used to be one flat `&` run cut every `size`; that is
correct only while every record is exactly that long, and one short record
silently shifts every later record's fields along. `record_sep` chunks each
record on its own, so a malformed one damages only itself. **Both shapes are read
deliberately** — results are retained seven days, so a job submitted before the
data changed is still being parsed after it.

VEP rewrites both `,` and `|` to `&`. A source carrying structure *below* that
level must use a delimiter VEP leaves alone: the enriched ClinVar VCF uses `~`
between subfields and `+` between repeats.

### 5.3 The source spreads one logical table across several columns

**Construct: `joins`.** Every transform reads a single column, so a source that
names a condition in one column, its per-submitter classifications in another and
its RCV records in a third cannot be assembled by transforms alone.

```jsonc
"joins": [
  { "into": "conditions", "from": "submissions",
    "left_key": "name", "right_key": "condition",
    "right_key_pattern": "^[^:]+:[^:]+:(?P<key>.+)$",   // strip a decorated key
    "right_key_sep": "+",                                // one row under several conditions
    "case_insensitive": true,
    "also_match": { "class_type": "class_type" },        // a key alone is not enough
    "count_by": "significance", "nest_as": "submitters"  // summarise AND keep the rows
  }
]
```

Key facts:

- a join writes **either** the matched rows (`as`) **or** how many there were
  (`count_into`) — never both, never neither;
- `count_by` groups and counts in first-seen order (`[{<count_by>, count}]`), and
  `nest_as` keeps each group's own members under it, so a count the reader can
  open stays paired with its evidence;
- a target built only for joins to draw from should set `join_source: true`; it
  is dropped from the output afterwards. Leaving ClinVar's submissions in place
  shipped every submission twice — 40% of that option's payload.

### 5.4 The annotation is about one gene but VEP repeats it everywhere

**Constructs: `applies_to` (RowScope) and `drop_when.unless_matches`.**

VEP repeats a custom's columns on *every* CSQ row of a variant. ClinVar's record
for 22:23834143 is about SMARCB1, but DERL3's transcripts overlap the same
position, and the classification appeared under both.

```jsonc
"applies_to": { "column": "SYMBOL", "listed_in": "ClinVar_GENEINFO",
                "item_pattern": "^(?P<key>[^:]+)" }
```

Narrowing applies only when there is something to narrow *by* — a row with no
symbol, or an annotation naming nothing, is left alone, because dropping those
would trade a wrong attribution for a missing one.

The per-allele analogue is `drop_when.unless_matches`, comparing a produced
element's field against a CSQ column (the row's own `Allele`), optionally
narrowed by `only_if` so the rule applies to a "Variation" association but not a
"Gene" one.

### 5.5 The value needs deriving, linking or reshaping after the fact

**Construct: post-ops** — 12 of them, listed in
[§9.5](#95-post-ops-over-the-produced-list). The ones that most often replace
frontend code:

- `concat` — OpenTargets publishes a p-value as a mantissa and an exponent;
  `3.32` + `e` + `-28` is the number a reader wants. Any part null ⇒ the whole
  result is null, never a malformed `e`.
- `curie_link` — a source that names a thing in several ontologies at once
  (`MeSH:D030342,MedGen:C0950123`) has no single id; `prefer` picks the
  authority, `templates` maps prefix → URL.
- `mapped_link` — the URL *shape* depends on which source an element came from,
  and the template is filled from the element's own fields.
- `lookup` — add a field from a shipped table in `vep/data/`. This is how a bare
  ontology accession becomes a name (see below).
- `collapse` — merge elements differing *only* in the named fields, gathering
  them into a nested list. Five rows that are one classification under five
  disease names become one row.
- `split_field` — cut a field at the first `sep`, write one side to `into`, keep
  the original. MaveDB's accession is `urn:mavedb:00000045-a-1#2010`: the link
  wants the score set in the path and the whole accession in the query.

**Reference tables.** `lookup` reads a JSON table from `app/vep/data/`. There are
two: `go_namespaces.json`, and the big one, `efo_terms.json` — generated by
`scripts/generate_efo_terms.py` from one EFO release (currently **3.92.0**). EFO
is a merged ontology, importing MONDO, HP, Orphanet, OBA and GO wholesale, so one
download resolves all six prefixes:

| prefix | terms | | prefix | terms |
|---|---|---|---|---|
| EFO | 18,449 | | Orphanet | 6,213 |
| OBA | 17,825 | | HP | 2,513 |
| MONDO | 16,432 | | GO | 762 |

**62,194 terms**, plus a separate `retired` map of **9,861** obsoleted
accessions, so a source still naming a withdrawn term resolves rather than
rendering as a bare id. The file's shape is `{version, terms, retired}` — not a
flat map; code reading it must go through `terms`.

An accession the table has never heard of is **not an error** — it renders as
itself. Deriving the table once and committing it costs disk and nothing at
runtime, versus asking OLS the same handful of questions hundreds of times per
results page.

---

## 6. Recipe C — a new allele-frequency source

AF sources used to be the one hand-rendered thing in the results panel. They are
now ordinary spec-driven options, and the useful property is that **the filter
half and the metadata half derive themselves from the parse plugin**. A new
source needs no edit to `results_filters.py`.

### 6.1 What makes an AF plugin an AF plugin

Its `output` starts with `frequencies.` (`results_filters._af_source_specs`).
From that alone the backend derives, per source:

- the **overall** column — the `scalar` target whose `field` is `"overall"`;
- the **population** columns — the `pattern_map` target's `from_pattern`, split
  into a prefix and a suffix so a matched column's key is exactly what sits
  between them, which is exactly the key the parse stores the value under;
- `exclude` — columns that match the pattern but are not populations.

```jsonc
{ "plugin": "gnomad_genomes", "scope": "allele", "output": "frequencies.gnomad_genomes",
  "csq_fields": ["gnomAD_genomes_AF"],          // ONE sentinel — see the note below
  "require_any_output": ["overall", "populations"],
  "targets": [
    { "field": "overall", "from": "gnomAD_genomes_AF", "transform": "scalar", "type": "float" },
    { "field": "populations", "transform": "pattern_map",
      "from_pattern": "gnomAD_genomes_AF_{pop}", "type": "float",
      "exclude": ["gnomAD_genomes_AF"] }
  ]}
```

★ `csq_fields` names **one** column, not the per-population set. It cannot name
them: which populations exist depends on what the user selected, and
`expected_csq_columns` would then require columns a narrower selection
legitimately never produces. The `pattern_map` discovers the rest from the
header at parse time. The same sentinel discipline governs SpliceAI's filter gate
— see [§7.3](#73-a-new-results-filter).

That drives `af_columns()` and `af_source_descriptor()`, which produce the
response's `available_af_sources` — `{key, source, population, label}` per
column, gated to the populations the submission actually selected, with the
label decoded once on the backend (`form_panels.af_population_label`). The
frontend keeps **no copy** of the population vocabulary.

### 6.2 Displaying it: the `map_rows` block

The rows cannot be written down: the populations are chosen per submission. So
they come from the **vocabulary** on the response rather than from the data.

```jsonc
{ "kind": "map_rows",
  "heading": "gnomAD Genomes v4.1.1",
  "from": "gnomad_genomes.populations",     // the dict-valued field
  "overall_from": "gnomad_genomes.overall", // fills the vocabulary's "" entry ("All")
  "vocabulary": "af_populations",
  "scope": "gnomad_genomes",                // which slice of it
  "format": "num",
  "label_suffix": { "key": "max", "from": "all_of_us.max_subpopulation_label" } }
```

Taking rows from the vocabulary is what makes the two views work with no second
code path: the default view drops a population the variant has no value for, and
"Show all" lists every selected population with a dash. That is the `sub_option`
row rule applied to a row set that is discovered instead of written down.

`label_suffix` covers the one value that needs it: All of Us publishes a `max`
frequency whose subpopulation is a sibling scalar, rendered as
`0.000167 (European)`. Its `from` is deliberately **excluded** from
`field_refs()` — it names a field the backend attaches at response time, not one
the parse produces, so checking it against the parse targets would reject a
correct ref.

### 6.3 The config side

AF sources emit `custom` lines whose `fields=` is built combinatorially. Five
builders exist; pick the grammar that matches the source
([§8.4](#84-field-builders)). The codes are open data on the
builder; the builder is only the algorithm.

### 6.4 The fallback, and its deletion

For a week `VepResultsAnnotationDetail.tsx` also carried the pre-spec AF renderer
as a fallback, because jobs pinned before the change had no AF display options
and would otherwise have lost their frequencies for the seven-day retention
window. **It was deleted on 2026-08-09** — 297 lines removed (`renderFrequencies`,
`FrequencyBlock`, `StructuralFrequencyBlock`, `noDataPopulationRows`,
`structuralHasData`, `AF_SOURCE_KEY_BY_OPTION`, `populationLabel`) plus the
`panel.id === 'allele_frequencies'` escape hatch in `renderPanel`. There is now
exactly one path.

Two lessons from that deletion, both general:

- **The fallback's tests were the feature's only tests.** All six AF tests
  exercised the renderer being removed; nothing anywhere covered `map_rows` or
  the vocabulary. They were rewritten onto the spec path rather than dropped.
  Grep for coverage before assuming a migration is safe to finish.
- **Deleting a renderer strands its imports, and only `ensembl-client` says so.**
  `getAnnotation` and `num` became unreferenced; `tsc` does not flag unused
  imports and standalone has no eslint installed, so it looked clean there and
  was a failing pre-commit in the client. See
  [technical-notes.md § Porting to ensembl-client](./technical-notes.md#porting-to-ensembl-client).

---

## 7. Recipe D — options with no data, and new filters

### 7.1 A config-only option

An option can produce no annotation at all. Today exactly one does:
**`updownstream_distance`**, which has `parsed_as: []`, no parse plugin and no
display option — it only widens VEP's `distance` setting.

★ This list used to be longer, and older notes still say so. `spdi`, `protein`
and the `nearest_*` options **all have parse plugins now** — `protein` was the
last of the hand-typed tail to convert. Re-derive it rather than trusting a
written list:

```python
[e.id for e in load_merged_spec("human_grch38").config.entries if not e.parsed_as]
```

The asymmetry is still normal — the config-set and parse-set only partly overlap,
and the relation is not 1:1: `eve` feeds both `eve` and `popeve`, and `hgvs` and
`hgvsg` both feed one `hgvs` parser (`hgvsg` additionally feeds its own).

There is a second, distinct asymmetry: an entry can have a control and no
*display* option. `clinvar_sv` is one — it emits, parses and filters, but its
output is shown inside another option's blocks.

Three fields express dependencies between options:

| field | meaning |
|---|---|
| `forces_on: [...]` | selecting this option turns others on **for config emission** — ProtVar reads HGVSg to build its link, so `protvar` forces `hgvsg` to be computed without showing its row. In use today: `protvar → hgvsg`, `phenotypes → clinvar_short` |
| `requires: [...]` | this entry emits **only if** the named options are also selected — a parent gate for an entry with no control of its own. In use today: `clinvar_short` requires `phenotypes` |
| `when: { assembly: [...] }` | emit only for matching assemblies (prefix match), inside one multi-assembly spec. **Currently used by no entry** — per-assembly availability is now expressed by which genome document declares the entry, which is simpler. Kept for a param that genuinely varies within one entry |

A forced option's columns are expected too — `effective_options` is read by both
the config interpreter and `expected_csq_columns`, so they cannot disagree.

### 7.2 A hidden-but-wired option

HGVSg is the worked example: no form control and no results row, but the config
entry, the parse plugin and ProtVar's `forces_on` all stay live, because the
value is needed even though it cannot yet be shown (its genomic notation names
chromosomes in a form we cannot map). If you hide something, hide it in the form
and the display — don't delete the plumbing, and say so in a comment.

### 7.3 A new results filter

Filters are **not** spec-driven. The results filter path is a streaming scanner
over the VCF that must decide, per line, without building models. Adding a
numeric score filter is two edits:

- **backend** `results_filters.py`: a field constant and a `ScoreSpec` naming the
  CSQ column(s), plus an optional `gate` column;
- **frontend** `resultsFilterFields.ts`: an entry in `SCORE_FIELD_OPTION_GROUPS`
  (the select renders `<optgroup>`s) and `FILTER_FIELDS`.

★ **The availability gate is the trap.** Whether a filter is offered is decided
from `expected_columns`, which comes from `csq_fields`. SpliceAI declares only
*one* of its four delta columns in `csq_fields` — gate on that sentinel column,
and do **not** widen `csq_fields` to make the gate convenient. Widening it
changes what `expected_csq_columns` requires at results time, and a legitimately
absent column then fails the check.

---

## 8. Reference — the `config` section

Model: `app/vep/models/config_spec_model.py`. Interpreter:
`app/vep/utils/config_interpreter.py`.

### 8.1 The entry

```jsonc
{ "id": "…",            // the option id: the form control, the `options` map key, and what parsed_as hangs off
  "order": 41,          // position in the emitted config.ini (load-bearing for golden tests)
  "parsed_as": ["…"],   // parse plugin ids; [] for a config-only option
  "forces_on": ["…"],   // optional
  "requires": ["…"],    // optional
  "form": { … },        // optional: the control it presents (§8.5). Absent = no control at all
  "config": { … } }     // exactly one emitter
```

### 8.2 The four emitters

| `emit` | shape | produces |
|---|---|---|
| `flag` | `{ keyword }` | `keyword 1` / `keyword 0` from the entry's own boolean — `hgvs`, `hgvsg`, `spdi`, `protein` |
| `setting` | `{ keyword, value }` | `keyword <value>` — a bare VEP setting whose value comes from a `ParamValue`, e.g. `distance 5000` |
| `plugin` | `{ name, args?, params?, flags?, when? }` | `plugin Name,<arg>…,k=v,…`. `args` are positional and emitted **before** named params — `Conservation` wants `plugin Conservation,<bigwig>`, not `file=<bigwig>` |
| `custom` | `{ params, fields?, fields_after?, omit_if_no_fields?, when? }` | `custom file=…,short_name=…,fields=…,format=…` — a VCF/BED/GFF overlay |

`fields` is optional on a custom: a `gff`/`bed` overlap custom lets VEP emit the
source's attributes automatically, so no `fields=` clause is written. Such a
custom's columns are source-derived, contribute nothing to `expected_csq_columns`
and skip the custom-column check.

### 8.3 Param values

| form | shape | meaning |
|---|---|---|
| literal | `"…"` | a string; `{path}` and `{gff}` are interpolated by the backend |
| by_assembly | `{ by_assembly: {GRCh38: …, GRCh37: …}, omit_if_absent? }` | assembly-keyed. Falls back to `GRCh38` when the assembly is not a key — unless `omit_if_absent`, which drops the whole param (SpliceAI's `snv_ensembl`, GRCh38 only) |
| from_option | `{ from_option, as, equals? }` | `as: "int"` → `int(bool(option))`; with `equals` → 1 when a *select* option equals the value; `as: "value"` → the option's own value verbatim |

**Variadic sub-flags** (`plugin.flags`, IntAct-style): append `,<keyword>=1` per
selected sub-option, or one `,<all_shortcut>=1` when all are selected. None
selected leaves the base line untouched. `implicit_all` is the inverse
convention, for a plugin that does everything when told nothing (mutfunc): all
selected emits *no* flags, and none selected emits **no line at all** — because
an empty flag list is how you ask that plugin for everything.

### 8.4 Field builders

| builder | grammar |
|---|---|
| `literal` | a fixed list — `{ "literal": ["CLNSIG", …] }` |
| `gnomad_ancestry_sex` | v4: `<base>[_non_ukb][_<anc>][_XX\|_XY]` per selected ancestry × sex, with a UK-Biobank toggle |
| `gnomad_v2` | v2/GRCh37: `[<subset>_]<base>[_<anc>[_<subpop>]][_<sex>]` — the subset is a *prefix* chosen from a list, ancestries carry sub-populations, and sexes are `male`/`female` not `XX`/`XY` |
| `allofus_populations` | concatenate each selected population's code(s); no sex split (`max` contributes two) |
| `gnomad_structural` | SV/CNV: an option-gated code list — SVTYPE (gated on the master option), the overall frequency, then each selected population |

`omit_if_no_fields` drops the whole line when nothing is selected. `fields_after`
(default `short_name`) controls where the `fields=` clause lands in the arg order.

★ Each builder's **codes are open data on the builder** — the ancestry and sex
lists live inside `GnomadAncestrySexFields` and friends, carrying `label`,
`default` and `form_order` so the same table both writes the `fields=` clause and
grows the form's sub-option tree. That single-sourcing is what removed the AF
tables' third duplicate copy; before it, the same ancestry list was written out
in the builder, in the form panels and in the label decoder, and had already
drifted.

### 8.5 The `form` block

Model: `FormOption` / `FormSubOption`, `config_spec_model.py:405`. An entry with
**no** `form` block presents no control at all — which is exactly what
`clinvar_short` and `hgvsg` need, so its absence is a declaration rather than an
omission to catch.

```jsonc
"form": {
  "panel": "genes_and_transcripts",   // one of the seven panel ids in form_panels._PANELS
  "label": "pLI",
  "category": "Constraint",           // optional; groups the control, and the results rows
  "type": "boolean",                  // boolean | number | select
  "default": false,                   // bool | int | str
  "order": 150,                       // position within the panel
  "sub_options": [ … ],               // optional, see below
  "requires_any_sub_option": false    // optional
}
```

| field | notes |
|---|---|
| `panel` | must be a panel the genome actually shows. An entry naming a panel that is not shown **raises** at assembly (`_place_spec_options`) rather than silently dropping the control — the failure mode that costs afternoons elsewhere in this spec |
| `order` | **not** the entry's `order`. That one sequences the generated `config.ini`; this one sequences the controls a reader sees, and there is no reason for the two to agree. Numbered sparsely so an option can be inserted between two others without renumbering |
| `category` | drives *both* surfaces: the form groups controls by it, and the results panel groups annotation rows by it. Regrouping options is therefore a backend-only change |
| `sub_options` | nested controls that are **not** entries of their own: a sub-option is an `options` key the parent's emitter reads through `from_option` (NearestExonJB's `max_range`). `FormSubOption` adds `min` / `max` for a number |
| `requires_any_sub_option` | for a plugin that does everything when told nothing (mutfunc): "none selected" is not a state it can be asked for, so the form switches the whole option off instead |

Allele-frequency entries declare a `form` block **and** grow their sub-option
tree from their own `fields=` builder — `_af_sub_options` reads the builder's
ancestry/sex tables, so **122 of GRCh38's 169 option nodes are generated** rather
than written. Nothing else needs to know that happened.

---

## 9. Reference — the `parsing` section

Model: `app/vep/models/parsing_spec_model.py`. Interpreter:
`app/vep/utils/spec_interpreter.py`. `extra="forbid"` throughout — an unknown key
fails loudly at load, which is far cheaper than silently empty annotations.

### 9.1 The plugin

```jsonc
{ "plugin": "…",                 // the id `parsed_as` points at
  "scope": "allele" | "transcript",
  "output": "…",                 // where it attaches on the response model
  "csq_fields": ["…"],           // the columns it owns; none present ⇒ it did not run
  "applies_to": { … },           // optional RowScope — see §5.4
  "require_any_input":  ["…"],   // present but empty in all of these ⇒ no annotation
  "require_any_output": ["…"],   // built, but the payload fields came out empty ⇒ none
  "targets": [ … ],
  "joins": [ … ],                // run after every target is built
  "post_joins": [ … ] }          // a post-op over a named target, AFTER the joins
```

`require_any_input` tests *raw presence*, so a literal `NA` counts as present.

### 9.2 The eleven transforms

| transform | key params | column(s) → value |
|---|---|---|
| `scalar` | `from, type` | one column → one value |
| `list` | `from` | one column → `&`-split list; empties and `NA` dropped |
| `first` | `from` | one column → first real item of a `&`-split list |
| `zip` | `from[], as[], align` | N aligned lists → list of objects, positions preserved |
| `regex` | `from, pattern, as[], each?` | named groups → object(s); `each` applies per item; non-matches skipped |
| `pattern_map` | `from_pattern, exclude?` | columns matching `"X_{ph}"` → dict keyed by the wildcard, **discovered from the header** |
| `chunk` | `from, size, as[], record_sep?` | `size` items per object → list |
| `positional` | `from, as[], wrap?` | items assigned to `as` strictly by index; extras ignored, missing null |
| `records` | `from, as[], sep, item_sep` | two levels of separator: records, then a record's fields by index |
| `stack` | `of[]` | several column groups, each a tagged `zip`, concatenated into one list |
| `key_value` | `from, pair_delimiter, kv_delimiter` | one column → dict; order-independent by construction |

`stack` deserves a note: it exists for a source that publishes the same shape
several times over in differently-named columns, carrying the distinction only in
the *names* (ClinVar's CLNDN vs ONCDN vs SCIDN). Each group's `const` tags its
rows, turning that back into data, so one list can be filtered, joined and split
by type rather than three lists having to be kept in step. A group may set
`split: false` to read each column whole and contribute exactly one row.

### 9.3 Shared modifiers on any target

| field | meaning |
|---|---|
| `type` | `string` · `float` · `int` · `raw`. `raw` captures the element's own source text, so a value survives verbatim where the named fields misread it |
| `sep` | the item separator (default `&` — what VEP writes) |
| `decode` | percent-decode the produced value's string leaves, applied **after** every split so an encoded `%2C` can never be read as a delimiter |
| `when` | `{ field, includes, sep?, item_pattern? }` — build only when another column's split list *contains* the value (membership, not substring) |
| `drop_when` | discard produced elements — see below |
| `post` | post-ops over the produced list |
| `item_fields` | declarative: the keys each element carries, so display refs into it can be checked |
| `join_source` | built for joins to draw from, dropped from the output afterwards |

**`drop_when`** takes exactly one mode, optionally narrowed by `only_if`:

| mode | drops an element when |
|---|---|
| `all_null: true` | every field came out null |
| `null: "<field>"` | the named field came out null |
| `unless_matches: {field, equals\|equals_column}` | the field does not equal the literal / CSQ column |

A `Match` (`unless_matches` / `only_if`, and a join's `where`) also takes
**`column_pattern`** — a regex with a `key` group applied to the *column's*
value before comparing, the same device as `RowScope.item_pattern` and a join's
`right_key_pattern`. Needed whenever the two sides spell the same thing
differently: VEP writes a versioned gene id in `Gene` (`ENSG00000121879.8`)
where a plugin's payload carries the bare accession. **Narrowing against a
per-row column also widens the parse cache key** — see trap 13.

**`FieldSpec`** (each entry of `as`): `{ field, type, replace?, strip?, null_values? }`.
`replace` is applied in order after coercion — VEP escapes spaces as underscores
in free text, so undoing that is a general need. `null_values` adds tokens meaning
"absent" beyond `''` and `NA` — ClinVar writes `.`, but `.` is a real value
elsewhere, so it is declared per field.

### 9.4 Joins

`{ into, from, left_key, right_key, … }`, plus:

| field | for |
|---|---|
| `right_key_pattern` / `left_key_pattern` | a regex with a `key` group extracting the comparable part of a decorated key |
| `left_key_sep` / `right_key_sep` | when one row belongs under several — the separator its key list uses |
| `case_insensitive` | submitters write the same condition in different cases |
| `where` | consider only right-hand rows holding this value |
| `also_match` | further equalities as `{left field: right field}` — a single key is not always enough to identify a row |
| `as` **xor** `count_into` | attach the matched rows, or how many there were |
| `count_by` (+ `nest_as`) | summarise into `[{<count_by>, count}]`, optionally keeping each group's members |

### 9.5 Post-ops over the produced list

Applied in order. `post` runs on the target; `post_joins` runs on a named target
*after* the joins, for anything that needs to see what a join added.

| op | does |
|---|---|
| `dedup` | drop elements identical to an earlier one |
| `sort` | order by `by`; `nulls: first\|last` is independent of `desc` |
| `exclude` | drop elements whose `by` field is one of `values` (case-insensitive) — placeholder terms a source emits in place of real data |
| `lookup` | add `into` from `by` via a table in `vep/data/`; an unknown id writes null, not an error |
| `concat` | join `fields` with `sep` into `into`; any part null ⇒ null |
| `split_field` | cut `by` at the first `sep`, write one side (`keep: before\|after`) to `into`, keep the original |
| `curie_link` | a CURIE list → one URL: `prefer` picks the authority, `templates` maps prefix → URL, `label_into` optionally records the chosen CURIE |
| `mapped_link` | a URL whose shape depends on `by`'s value; the template is filled from the element's own fields |
| `collapse` | merge elements differing only in `fields`, gathering them into `into` |
| `derive_if_empty` | build `into` from packed field `by` via `pattern`'s named groups, **only where the list is still empty** |
| `default` | fill `by` with `value` where the source left it empty |
| `only_if_differs` | keep a nested element's `field` only where the row does not already show it; elements are copied, never mutated |

---

## 10. Reference — the `display` section

Model: `app/vep/models/display_spec_model.py`. Renderer:
`displaySpecRenderer.tsx`. Frontend types: `types/vepDisplaySpec.ts` — **a new
block kind must be mirrored there**, and must be added to `plugin_refs()` or the
option will be filtered out of every assembled spec.

The override registry is **empty**. ClinVar, once the example of what could not
be expressed declaratively, is now the largest thing described here.

### 10.1 An option

```jsonc
{ "option_id": "…",     // == the form option id
  "heading": "…",       // optional: wraps ALL of the option's blocks in one heading
  "blocks": [ … ] }     // a sequence — `eve` is a bare row plus a sibling popEVE block
```

Use an option-level `heading` **or** per-block headings, not both.

### 10.2 The five block kinds

| `kind` | renders |
|---|---|
| `rows` | a run of fixed label/value rows, optionally under a sub-heading |
| `map_rows` | one row per entry of a per-job **vocabulary** — see [§6.2](#62-displaying-it-the-map_rows-block) |
| `list` | one item per element of a list-valued field, truncated |
| `table` | a header row plus either one body row per list element (**list mode**, `from`) or explicit rows (**matrix mode**, `rows`) |
| `group` | a run of sub-blocks under one optional heading, gated as a whole |

### 10.3 The four gates every block has

| gate | question |
|---|---|
| `requires: "<plugin>"` | did that plugin produce an annotation at all? Needed where placeholder rows would otherwise render as a wall of dashes |
| `requires_selected: {id, default}` | was this sub-option chosen for this job? (dev VCFs are annotated from a full cache and carry columns the user did not pick) |
| `when: {present\|empty: "<plugin>.<field>"}` | a data condition — ClinVar flips between a bare row and a headed block on it |
| `view: "default" \| "show_all"` | which of the two views; absent = both |

### 10.4 A row

| field | meaning |
|---|---|
| `from` | `<plugin>.<field>` — the value's source |
| `compose` | `{format: "with_score", classification, score}` — "Likely benign (0.07)"; drops the row if the *classification* is absent |
| `label` | optional only for a row that stacks a list |
| `format` | one of the eight below |
| `mono` | monospace value |
| `placeholder` | unset ⇒ an absent value **drops the row**; set ⇒ keeps it and shows this |
| `help` / `help_link` | a (?) button beside the label, and a fixed citation inside its popup |
| `sub_option` | the sub-option the value comes from; affects "Show all" only (a selected-but-empty sub-option shows a dash there) |
| `link` / `link_from` | a trailing link; `link_from` reads the href from a sibling `<plugin>.<field>` |
| `item` | for a `from` that is a list: one rendered line per element, stacked under one label |
| `where` | keep only some of that stacked list, so one list can appear in two places |
| `key` | React key; absent means "use position", which is stable for these fixed lists |

A row needs exactly one of `from` or `compose` — **except** a row whose value
*is* a named builder link (the OpenTargets variant link is built from the
variant's coordinates, which no plugin parsed).

### 10.5 The eight formats

| `format` | applies to | renders |
|---|---|---|
| `text` (default) | anything | stringify |
| `num` | a numeric scalar | `toPrecision`-style number |
| `humanize` | a string scalar | a classification term as prose |
| `humanize_terms` | a string scalar | a term list as prose |
| `phenotype` | a string scalar | a normalised phenotype name |
| `join` | a list of scalars | comma-joined |
| `humanize_join` | a list of strings | humanise each, then join |
| `count` | a list, or a `&`-delimited string | the size; **absent when zero** |

Format↔type compatibility is checked at load (`_format_suits_shape`), because
applying the wrong one crashes the renderer — `num` calls `.toPrecision` on a
string, `join` calls `.join` on a non-list. The shape comes from the parse
target's transform and element type.

### 10.6 Values (cells, item lines, table columns)

`ValuePiece` is the shared base — a cell of a repeated item, a line of a
list-valued cell and a table column are the same idea, and they had drifted.

| field | meaning |
|---|---|
| `from` | a field **of the element** (not `plugin.field`); omit for a list of scalars |
| `format` / `mono` / `nowrap` | as above; `nowrap` keeps an identifier and its link icon together |
| `link` / `link_from` | a link on the value, or built from a sibling element field |
| `split` | one value packing several, each linked in its own right (a `+`-joined PMID list) |
| `link_prefix` | only link a value carrying this prefix, and strip it before filling the template (`uniprotkb:P37840` → the bare accession) |
| `stars` / `stars_from` / `stars_of` | a rating in front of the value: on a named scale, on the scale *named by an element field*, or rating a *different* field than the one shown |
| `template` | the text as a `{field}` template over the element |
| `labels` | value → what to show for it; an unmapped value keeps the data's own wording |
| `label` | a prefix before the value ("L2G 0.42") |

`split` and `link_prefix` are rejected without a link — they only change what the
reader sees if each part becomes its own link.

### 10.7 List items

```jsonc
"item": {
  "label": { "from"|"template", "format"?, "wrap"? },  // ⇒ a label/value row
  "cells": [ … ],                                      // XOR
  "rows":  [ {label, from, format?} ],                 // a stack of labelled field-rows
  "link":  { … }                                       // a trailing builder link (label layout only)
}
```

Without `label`, an item is a row of inline cells. With it, a label/value row.
`wrap` surrounds the formatted `from` value with fixed text via a single `{}`
slot. `cells` and `rows` are mutually exclusive.

### 10.8 Tables

| field | mode | meaning |
|---|---|---|
| `from` | list | the `<plugin>.<listField>` the rows come from |
| `rows` | matrix | explicit `{label, values}` — the label fills the first column, each value is a `<plugin>.<field>` scalar under a value column |
| `columns[].label` / `notes` | both | the heading, and further heading lines (`{text, muted}`) so breaks fall where the sense does |
| `columns[].align` | both | derived from `format` by house rule (numbers right); state it only where the format cannot — a number the source publishes pre-formatted as a string |
| `columns[].sub_option` | both | a column present only when its sub-option ran, so the table's width follows the selection |
| `columns[].lift_when_invariant` | list | when every row shares one value, show it once above the table instead of as a column |
| `columns[].items` | list | how to render a cell whose value is a list of objects (+ `count_from`, `expand`) |
| `group_by` | list | one headed sub-table per distinct value of an item field; headings come from the **data**, `labels` renames individual ones |
| `where` | list | `{field, equals \| not_equals}` — two tables dividing one list under a shared heading |
| `truncate` | list | defaults to the house style (3 visible, rest behind a toggle); unset for a matrix |
| `indent` | both | sit one step in, for a table subordinate to what is above it |

`ColumnExpand` gives one line a collapsed detail: a summary that opens onto
per-element lines, read from the *same* element the summary came from, so a cell
of several summaries opens one at a time. `emphasis` sets some of those lines
apart rather than hiding them.

### 10.9 Rating scales

```jsonc
"rating_scales": {
  "clinvar_aggregate":  { "out_of": 4, "ratings": { "practice guideline": 4, "reviewed by expert panel": 3, … } },
  "clinvar_submission": { "out_of": 4, "ratings": { … } },
  "clinvar_somatic":    { "out_of": 4, "ratings": { … } }
}
```

Keys match loosely (case, and `_` as a space) so a scale can be authored as the
phrases a reader would recognise while the data keeps the source's punctuation. A
term the scale does not know renders **no rating at all** rather than a wrong one
— no stars reads as "not rated here", which is true, where zero stars would be a
claim the source never made. Because of that, a *typo in the scale name* would
look like data, so unknown scale names are rejected at load.

### 10.10 Link builders (the last frontend seam)

Three named builders exist, for links a template cannot express because they need
job context:

| builder | produces |
|---|---|
| `protvar` | the variant's ProtVar page — icon + the row's own value as the link text |
| `opentargets_variant` | the variant's OpenTargets page; this **is** the row's value, there being no annotation field behind it |
| `protein_popup` | an in-app "View in" Entity Viewer popup, built from the job genome plus the consequence's gene |

Everything else should be a `template`. `interpolateUrl` deliberately does *not*
percent-encode — values carry URL-significant characters that are intended, and
blanket encoding breaks working links. **`#` is the sole exception**: inside a
value it can only be a literal, and left raw the browser treats it as a fragment
and drops the rest of the query. But when the value **is** the URL (a
`{value}`-only template, as Geno2MP uses), it must not be escaped — a
fragment-routed URL would become `/Geno2MP/%23/variant/…`.

---

## 11. What fails at load time, and what the error looks like

`MergedSpec`'s model validator runs on every load and raises
`config/parsing inconsistency: …` listing every problem at once.

**Errors:**

- a `parsed_as` id that names no parse plugin;
- a `custom` emitter whose derived columns do not line up with its mapped parse
  plugin's `csq_fields` — exact for `literal` fields, prefix-only for the
  combinatorial builders whose columns are discovered by `from_pattern`;
- a display `from` / `compose` / `when` / `link_from` that names an unknown
  plugin, or a field that plugin does not produce;
- a display ref to a target with `join_source: true` ("read it through the list
  it was joined into");
- an item-relative ref not in the list's `item_fields`, resolved **by path** so a
  column's `items` and their `expand` are checked against the nested list they
  actually read;
- a `format` whose shape does not suit the target it reads;
- a `stars` naming an unknown rating scale;
- any unknown key anywhere (`extra="forbid"`).

**Soft warning:** a parse plugin no config entry enables — it can never run, but
that is not fatal.

`plugin` and `flag` emitters are presence-checked only, since VEP derives their
CSQ column names internally and the config line never states them.

At **results** time there is a second check: `expected_columns.json` pinned at
submission versus the output header. The contract is directional — the backend
fails on *missing* expected CSQ fields and silently ignores *extra* ones.

---

## 12. Traps

Every one of these has cost real time.

1. **`parsed_as: []` silently drops the display option.** The library is selected
   by the plugins the config enables, so an option that reads a plugin nothing
   enables is filtered out with no error. Symptom: 32 options where you expected
   33. Fix it in the genome document **and** in the baseline's own copy.

2. **The baseline gate must be hand-mirrored.** `human_grch38.baseline.json` is
   not a dump. Any intentional spec change fails
   `test_assembled_grch38_matches_the_pre_split_baseline` until you make the
   identical edit there — including the config half.

3. **The display layout is pinned per job.** An existing submission keeps the old
   rendering, correctly. Reloading an old job proves nothing about a display
   change; make a new submission, or rewrite the sidecar. Say this when handing
   over a display change or it will be reported as "not fixed".

4. **The API caches sidecars per process.** After rewriting `dev-data`'s
   sidecars, **restart** the API — reloading the page does nothing.

5. **The pinned sidecar is written by `model_dump_json()` — by field name, not by
   alias, and compact.** Two consequences: an aliased model needs
   `populate_by_name=True` or the *whole spec* fails to load and every plugin
   silently produces nothing; and if you are editing a sidecar by hand the JSON
   is `"label":"X"` with **no space after the colon**, unlike the spec files.

6. **Deleting or renaming a parsing-spec field kills every existing job.** The
   models are `extra="forbid"`, `_load_pinned_spec` swallows the validation error
   and returns `None`, and the job renders with *no annotations at all* and no
   message. When a field goes: keep accepting the old spelling (an alias for a
   rename, a declared-but-unread field for a deletion), add its shape to
   `test_sidecar_compatibility.py`, and do **not** relax `extra="forbid"`.

7. **Regenerating `dev-data/` wipes its sidecars**, and with no `parsing_spec.json`
   the API returns zero annotations for every plugin — not a fallback to the live
   spec.

8. **A plugin's `cols` gaining a middle field silently kills the whole panel.**
   Positional parses are exactly as fragile as they sound; prefer reading both
   shapes when a source's layout changes, since results live seven days.

9. **The frontend fixture job fails until the backend half merges.** Not a real
   failure. Merge backend → re-run the job → merge frontend.

10. **Lint the port against `ensembl-client`'s config before merging**, not when
    porting — its React Compiler rules are errors where standalone's are
    warnings. And lint *every file the port stages*, not only the ones you edited.

11. **A misparse is silent.** A wrong `size`, a wrong separator or a wrong field
    order produces plausible numbers under the wrong names. Differential-test
    against a real dev-data VCF carrying the columns — not just fixtures. This is
    the validation that consistently pays off.

12. **Run the control.** When you believe something is fixed, break it
    deliberately and confirm the measurement moves. A test that cannot fail
    proves nothing; a spec-driven path that silently falls back to a bespoke
    renderer looks identical to one that works.

13. ★★ **Narrowing against a per-row column silently defeats the parse cache.**
    `apply_plugin_spec` caches on `(plugin, values of csq_fields)`, because a
    plugin's output is identical on every CSQ row of a variant — true while it
    depends only on its own columns, and false the moment a `drop_when` compares
    against a column that varies per row (`Gene`, `Allele`, `SYMBOL`). Two rows
    sharing a payload column then share the answer, and the first row's result is
    served to every later one. Since 2026-08-07 `compile_plugin` widens
    `key_indices` with every `equals_column` a predicate reads, so this is handled
    — but if you add a new *kind* of per-row predicate, extend `_match_columns`
    with it. `applies_to` needs no entry: it is evaluated **before** the cache,
    which is why ClinVar's row gate was always correct.

    The two halves of that fix fail in opposite directions, which is what makes
    a control mandatory: without the cache widening the neighbour keeps the wrong
    data, and without `column_pattern` *everything* drops. Both look plausible.

14. **A default you do not state is not the default you meant.** An option left
    at its default is never written into the submitted parameters, so the
    submission fills it from the spec (`_resolve_options`). Both halves now read
    the *same* declaration — the `form` block's `default` — which is what closed
    a bug where All of Us's "Maximum subpopulation" default was set on the form
    and had no effect. Do not reintroduce a second place to say it.

15. **An option id is the only seam.** The `id` on the config entry is the form
    control, the key in the submission's `options` map, and the thing `parsed_as`
    hangs off. There is no separate registry keeping those in step any more —
    which is the point, but it means a typo in one place is simply a different
    option, and an unrecognised option is **dropped and logged, not rejected**
    (a rerun of a 28-day-old submission may legitimately name a retired option).
    Check the log line if a selection appears to do nothing.

---

## Appendix — the checklist

Ordered; the joins fail loudly at load if a step is skipped.

1. Place the indexed data file where `{path}` resolves (and add a
   `_DEV_PLUGIN_SUBDIRS` entry if it needs its own directory).
2. Author the `config` entry in the genome document — emitter, `parsed_as`, and
   the `form` block (label, default, panel, category, order, sub-options).
   Declaring it in `human_grch38.json` alone is how you make it GRCh38-only.
3. Author the `parsing` plugin in `annotation_library.json` — scope,
   `csq_fields`, targets. Only if it emits columns to read.
4. Author the `display` option in `annotation_library.json`.
5. Mirror steps 2–4 into `app/tests/human_grch38.baseline.json`.
6. Regenerate the frontend fixture (`generate_display_fixture.py`).
7. Run both suites: backend pytest, frontend `tsc` + vitest + the client's
   prettier — and eslint under **ensembl-client's** config.
8. Regenerate the `dev-data` sidecar and **restart** the API.
9. Differential-test against a real VCF, and run a control.

There is no longer a step for `form_panels.py` or for `ConfigIniParams`. If you
find yourself editing either to add an option, something is wrong with the entry.
