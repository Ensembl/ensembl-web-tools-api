# VEP data flow

How variant data and metadata move through the VEP stack — what calls what, in
what order, and where each piece of the JSON specification takes effect.

Verified 2026-08-09 against tools-api `ad15cda` and standalone-web-vep `880fa38`.

Companions: [spec-and-extension-guide.md](./spec-and-extension-guide.md) (the
grammar), [technical-notes.md](./technical-notes.md) (why the machinery is shaped
this way), [production-readiness.md](./production-readiness.md) (what is still
dev-only in the flow below).

## The rendered diagrams

Three self-contained, theme-aware SVG views live beside this document — no
runtime, no mermaid — in increasing detail. Each has a `.py` generator: edit the
data at the top and re-run, rather than hand-editing the output.

| file | shows | generator |
|---|---|---|
| `concept-map.html` / `.jpg` | **the shape of the thing** — four boxes and the traffic between them. Start here | `concept-map.py` |
| `dataflow-diagram.html` / `.jpg` | **the per-request sequence**, dev and prod branches inline, with the contract points tagged | `dataflow-diagram.py` (edit `EVENTS`) |
| `repo-overview.html` / `.jpg` | **the two-repo overview** — what lives where, the path a submission takes, and every hop that leaves the repos. VEP slice only; the tools API also serves BLAST, not drawn | `repo-overview.py` (edit `NODES` / `EDGES` / `CONTRACTS`) |

The contract markers in those diagrams are the C1–C8 points, listed and
re-verified in
[technical-notes § The contract points](./technical-notes.md#the-contract-points).
Keep the two in step.

The three `dataflow-*.svg` files are the older, simpler views embedded inline
below.

## Contents

- [The whole flow in one picture](#the-whole-flow-in-one-picture)
- [Worked example — a variant with a pLI score](#worked-example--a-variant-with-a-pli-score)
- [Worked example — an allele frequency](#worked-example--an-allele-frequency)
- [Worked example — a filtered results page](#worked-example--a-filtered-results-page)
- [Original VEP vs beta-vep](#original-vep-vs-beta-vep)
- [Species selection](#species-selection)
- [Metadata API reference](#metadata-api-reference)
- [Dev server modes and toggles](#dev-server-modes-and-toggles)

---

## The whole flow in one picture

```
 ┌── FORM ────────────┐   ┌── SUBMIT ──────────┐   ┌ PIPELINE ┐   ┌── RESULTS ───────────┐
 │                    │   │                    │   │          │   │                      │
 │ GET /form_config   │   │ POST /submissions  │   │ VEP runs │   │ GET /…/results       │
 │        ↓           │   │        ↓           │   │    ↓     │   │        ↓             │
 │ get_visible_panels │   │ ConfigIniParams    │   │ output   │   │ parse with the PINNED │
 │        ↑           │   │  .options (map)    │   │ .vcf.gz  │   │ spec, not the live one│
 │ every option from  │   │        ↓           │   │ (one CSQ │   │        ↓             │
 │ its entry's `form` │   │ emit_config_lines  │   │ column   │   │ lay out with the      │
 │ block              │   │        ↓           │   │ per      │   │ PINNED display+panels │
 │                    │   │   config.ini       │   │ field)   │   │                      │
 └────────────────────┘   └────────┬───────────┘   └──────────┘   └──────────────────────┘
                                   │
                    pins 3 sidecars beside the job:
                      parsing_spec.json      the whole merged document
                      expected_columns.json  the CSQ columns these options must produce
                      display_panels.json    the panel/category layout as submitted
```

**The one idea to hold on to:** the spec is *pinned per job*. Results are parsed
and laid out with the document that existed at submission, so a job's options,
its parsing and its layout are provably one ruleset — and a spec change is
correctly invisible to jobs already submitted. Reloading an old job proves
nothing about a display change; make a new submission.

Where each spec section acts:

| section | acts at | reference |
|---|---|---|
| `config` | submit — turns selected options into `config.ini` lines | [guide §8](./spec-and-extension-guide.md#8-reference--the-config-section) |
| `form` (on a config entry) | form — the control itself, its panel, category and order | [guide §8.5](./spec-and-extension-guide.md#85-the-form-block) |
| `parsing` | results — CSQ columns → structured annotation | [guide §9](./spec-and-extension-guide.md#9-reference--the-parsing-section) |
| `display` | results — annotation → the rendered panel | [guide §10](./spec-and-extension-guide.md#10-reference--the-display-section) |

---

## Worked example — a variant with a pLI score

pLI is the simplest possible end-to-end case: one plugin, one column, one row.
It is also GRCh38-only, which shows how availability works.

**1 · The form.** `human_grch38.json` carries an entry whose `form` block names
the panel and category:

```jsonc
{ "id": "pli", "order": 46, "parsed_as": ["pli"],
  "form": { "panel": "genes_and_transcripts", "label": "pLI",
            "category": "Constraint", "type": "boolean",
            "default": false, "order": 150 },
  "config": { "emit": "plugin", "name": "pLI",
              "args": ["{path}/pli_transcript.txt", "transcript"] } }
```

`get_visible_panels` reads the *assembled* spec, so this control exists for
GRCh38 and simply is not there for GRCh37 — no branch anywhere says so.

**2 · Submit.** The browser posts `{options: {pli: true, …}}`.
`ConfigIniParams._resolve_options` completes the map from the spec (every option
this genome offers, at the sent value or the declared default) and
`emit_config_lines` writes:

```
plugin pLI,/…/pli_transcript.txt,transcript
```

Meanwhile `expected_csq_columns` records that this run must produce
`pLI_transcript_value`, and all three sidecars are pinned.

**3 · The pipeline** runs VEP, which appends `pLI_transcript_value` to each CSQ
entry.

**4 · Results.** The parse plugin — `scope: "transcript"`, so the value attaches
per consequence — reads that column into `pli.score`, and the display option
renders one row under the Constraint category of Genes & transcripts.

★ **The trap this example exists to record:** the plugin names its CSQ column
after its *argument*, so the column is `pLI_transcript_value`, not `pLI`. Find
the real name in the dev VCF's header — a wrong `csq_fields` produces no error,
just an option that never appears.

---

## Worked example — an allele frequency

Allele frequencies are the awkward case, because **the row set is a property of
the job, not of the variant**.

**1 · The form.** A single entry declares the control, and its sub-option tree
(ancestries × sexes) is *generated* from the same `fields=` builder table that
writes its config line — 122 of GRCh38's 169 option nodes come from there.

**2 · Submit.** The `custom` emitter builds a combinatorial `fields=` clause from
exactly the populations selected:

```
custom file=…/gnomad.genomes.v4.1.1.sites.vcf.gz,short_name=gnomAD_genomes,
       fields=AF%AF_afr%AF_nfe%AF_afr_XX,format=vcf,type=exact,coords=0
```

**3 · Results, the parse.** The `scalar` target reads the overall column; a
`pattern_map` target discovers the per-population columns **from the header** at
parse time, keyed by whatever sits between the pattern's prefix and suffix.

★ `csq_fields` names **one** sentinel column, not the per-population set. It
cannot name them: which populations exist depends on what the user selected, and
`expected_csq_columns` would then demand columns a narrower selection
legitimately never produces.

**4 · Results, the display.** A `map_rows` block takes its rows from the job's
**vocabulary** (`available_af_sources` on the response) rather than from the
data. That single fact is what makes both views work with no second code path:
the default view drops a population the variant has no value for, and "Show all"
lists every selected population with a dash.

See [guide §6](./spec-and-extension-guide.md#6-recipe-c--a-new-allele-frequency-source)
for the full recipe. The hand-written AF renderer that used to draw this was
deleted on 2026-08-09; there is now one path.

---

## Worked example — a filtered results page

Filters are the one part of the results path that is **not** spec-driven, because
it must decide per line, without building models.

```
GET /…/results?page=3&filters=[{"field":"cadd_phred","operator":">=","values":["20"]}]
   ↓
results_filters compiles each filter to a predicate over raw CSQ fields
   ↓
line_prefilter (literal-membership filters only): a cheap substring test on the
   UNSPLIT line — a necessary condition, so no false negatives
   ↓
full CSQ split only for lines that survive; per-entry evaluation
   ↓
a record is kept iff ≥1 of its CSQ entries matches, rewritten to just those entries
   ↓
page window assembled and parsed into the response model
```

An unfiltered request skips all of this and takes the BGZF page-index seek path
instead. A filtered one always full-scans — bounded in memory, but a scan.

See [technical-notes.md § Results filtering](./technical-notes.md#results-filtering)
for the measurements and the open question about no-data semantics.

---

## Original VEP vs beta-vep

![Original VEP data flow](./dataflow-original-vep.svg)

The tools API orchestrates everything. External calls (orange):

- **Ensembl Web Metadata API** — genome metadata for the form config, and
  resolving the `gff` / `fasta` reference paths while building `config.ini`.
- **Seqera Platform** (Nextflow Tower) — launch the workflow, then poll status.
- **VEP reference data** — VEP reads the **GFF + FASTA** the tools API writes into
  `config.ini`. This is GFF-based custom annotation, **not** the VEP cache, and
  the original `config.ini` contains **no `plugin` lines**.

The client separately calls Ensembl search / metadata / variation APIs for species
selection and example variants.

> The exact `vep` command is assembled by the external Nextflow pipeline
> (`NF_PIPELINE_URL`), which is not in this repo. But the `config.ini` the tools
> API supplies provides `gff` + `fasta` (no `cache` / `dir_cache` / `offline`), so
> annotation is GFF-based — consistent with output whose MANE designation appears
> in the `MANE` label column.

![beta-vep data flow](./dataflow-beta-vep.svg)

The client/API surface is identical, but the Seqera round-trip is replaced by a
**manual step** (violet band):

1. Submit runs in `DUMP_INI` mode — the tools API still resolves `gff`/`fasta`
   and builds the same `config.ini`, but **writes it to `data/output`** and
   returns a `dump-…` id instead of launching Seqera.
2. **Manual gap** — the operator takes that `config.ini`, runs the Nextflow VEP
   pipeline on the HPC (reading the GFF + FASTA + plugin data files), and drops
   `output.vcf.gz` back into `data/output`.
3. Results run in `LOCAL_RESULTS_VCF` mode — the endpoint parses that local VCF
   into the structured annotations.

Submission + status are **dev-mocked** so the UI's submit → poll → results flow
still completes, and species search is proxied to Ensembl staging via the split
dev proxy (`TOOLS_API_TARGET` vs `ENSEMBL_API_TARGET`).

**Net difference:** the original is a fully-automated `client ↔ API ↔ Seqera`
loop; beta-vep keeps the same client/API surface but swaps the Seqera round-trip
for dump-to-disk → run manually → parse-from-disk. Closing that gap is
[production-readiness.md § Seqera](./production-readiness.md#seqera--nextflow-wiring).

---

## Species selection

Selecting a species fires two request chains, plus some no-API side effects.

![API calls on species selection](./dataflow-species-selection.svg)

**Trigger** — `setSelectedSpecies({ species })` (`VepAppBar.tsx:59` or
`VepSpeciesSelector.tsx:102`); the reducer (`vepFormSlice.ts`) sets the species
**and resets `parameters = {}`**, which is what un-gates chain A.

**Chain A — form config** (`useVepFormConfig.ts`):

1. `GET /api/tools/vep/form_config/{genome_id}` (`vepApiSlice.ts:38`).
2. The tools API calls the **metadata API**:
   `GET …/genome/{genome_id}/dataset/genebuild/attributes?attribute_names=genebuild.provider_name&…provider_version&…last_geneset_update`.
3. The response builds the **Transcript set** dropdown (+ static
   `symbol`/`biotype`); the option panels come from the assembled spec.
4. `setDefaultParameters()` seeds `parameters`, so the call will not re-fire until
   the species changes again.

**Chain B — example input** (`VepFormVariantsSection.tsx:58` →
`vepApiSlice.ts:41`):

1. `GET /api/metadata/genome/{genome_id}/example_objects` → `[{id, type}]`.
2. For the `type === 'variant'` entry: `POST /api/graphql/variation` with
   `{ genomeId, variantId }` → variant detail → `vcfString` (the "Example data").

**No-API side effects** — `parameters` reset to `{}`; the Variants section
auto-expands (`VepFormVariantsSection.tsx:65`).

In the dev server, chain A is mocked unless `LIVE_FORM_CONFIG=1`, and chain B is
mocked unless `LIVE_VARIATION=1`.

---

## Metadata API reference

Three distinct upstreams are easy to conflate; only one is the **metadata API**:

| Upstream | Server-side (tools API) | Client-side (browser) |
|---|---|---|
| Metadata API (form config) | `GENOME_METADATA_API` — **staging** by default; `GENOME_METADATA_LIVE=1` → `beta.ensembl.org` | `metadataApiBaseUrl` = `/api/metadata` → `ENSEMBL_API_TARGET` |
| Metadata API (gff/fasta) | `WEB_METADATA_API` = `https://beta.ensembl.org/api/metadata/` | — |
| Search API (separate) | — | `searchApiBaseUrl` = `/api/search` |
| Variation GraphQL (separate) | — | `/api/graphql/variation` |

The form-config metadata call (`get_genome_metadata`) defaults to **staging**,
matching the browser's species search so genome ids resolve consistently; the
gff/fasta lookup (`get_vep_support_location`) uses `WEB_METADATA_API` (beta)
independently.

**Server-side, stage 1 — form config.** `get_genome_metadata()`
(`app/vep/utils/web_metadata.py:39`), called from `get_form_config`
(`app/vep/vep_resources.py:484`).

- `GET …/genome/{genome_id}/dataset/genebuild/attributes?attribute_names=genebuild.provider_name&attribute_names=genebuild.provider_version&attribute_names=genebuild.last_geneset_update`
- Returns `{"attributes": [{"name","value"}, …]}`; the code reads
  `genebuild.provider_name`, `genebuild.provider_version`,
  `genebuild.last_geneset_update`.
- Builds the **"Transcript set"** dropdown label/value (e.g. `GENCODE 50`).

**Server-side, stage 2 — submission.** `get_vep_support_location()`
(`app/vep/utils/web_metadata.py:8`), called from `create_config_ini_file`.

- `GET …/genome/{genome_id}/vep/file_paths` → `{"faa_location","gff_location"}`;
  each prefixed with `VEP_SUPPORT_PATH` (default `/tmpdir`) to form the `fasta` /
  `gff` lines in `config.ini`.

**Client-side — species selection**
(`speciesSelectorApiSlice.ts`): `GET /api/metadata/popular_species`,
`GET /api/metadata/genome_group_categories`. Species *search* is
`GET /api/search/genomes/v2?…` — the **Search API**, not metadata.

**Client-side — example input** (optional):
`GET /api/metadata/genome/{genome_id}/example_objects` → `[{id, type}]`, then a
`POST /api/graphql/variation` for the variant.

★ Verified: the shared `genomeApiSlice` also defines `/genome/{slug}/explain` and
`/genome/{id}/karyotype`, but the VEP flow invokes neither.

★ `/genomeid` returns the **partial** genome, and staging is a release ahead of
live — both have caused confusion when ids fail to resolve.

---

## Dev server modes and toggles

The webpack dev server (`mocks/devServerMocks.cjs`) intercepts `/api/*` and
serves fixtures, so the whole flow works with no real backend. Individual groups
switch to **live** (the mock is not registered, so the request falls through the
dev proxy to the real upstream).

**Frontend toggles** (`LIVE` in `mocks/devServerMocks.cjs`; restart `npm start`
after changing):

| Toggle | Env var | When live, proxies to | Affects |
|---|---|---|---|
| `speciesSearch` | _(hard-coded `true`)_ | `ENSEMBL_API_TARGET` | `popular_species`, `genome_group_categories`, `search/genomes/v2` |
| `formConfig` | `LIVE_FORM_CONFIG=1` | `TOOLS_API_TARGET` (local fork) | `GET /vep/form_config/:genomeId` |
| `submission` | `LIVE_SUBMISSION=1` | `TOOLS_API_TARGET` | `POST /vep/submissions` |
| `results` | `LIVE_RESULTS=1` | `TOOLS_API_TARGET` | `GET /vep/submissions/:id/results` |
| `variation` | `LIVE_VARIATION=1` | `ENSEMBL_API_TARGET` | `example_objects` + `POST /graphql/variation` |

Submission `status` is always mocked (returns `SUCCEEDED` after a couple of polls
so the Results button enables).

**Proxy targets** (`webpack.config.js`): `TOOLS_API_TARGET` for `/api/tools`,
`ENSEMBL_API_TARGET` for `/api/metadata`, `/api/search`, `/api/graphql` (both
default to staging).

**Backend modes** (`app/core/config.py`):

| Env var | Effect |
|---|---|
| `DUMP_INI=1` | `submit_vep` writes the generated `config.ini` to `DUMP_INI_DIR` (default the repo `data/output`) and returns a fake id, instead of launching Seqera. Also switches `{path}` to the real beta data layout |
| `LOCAL_RESULTS_VCF=<path>` | the results endpoint parses that VCF directly, skipping the Seqera status lookup |
| `GENOME_METADATA_LIVE=1` | form-config genome metadata uses the live API instead of staging |

Typical combined run for the manual loop:

```bash
DUMP_INI=1 LOCAL_RESULTS_VCF=/…/data/output/output.vcf.gz uvicorn main:app --reload --port 8013
```

```bash
LIVE_SUBMISSION=1 LIVE_RESULTS=1 LIVE_VARIATION=1 TOOLS_API_TARGET=http://localhost:8013 npm start
```

★ **The API caches each job's sidecars per process.** After regenerating
`dev-data`'s sidecars, **restart** the API — reloading the page does nothing.
And regenerating `dev-data/` wipes the sidecars: with no `parsing_spec.json` the
API returns zero annotations for every plugin, with no fallback to the live spec
and no message.
