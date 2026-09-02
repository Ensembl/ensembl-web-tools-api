# VEP technical notes

How the machinery around the specs works, and **why it is shaped that way** —
the decisions, the measurements that drove them, and the dead ends already ruled
out. The grammar itself is in
[spec-and-extension-guide.md](./spec-and-extension-guide.md); the request paths
are in [dataflow.md](./dataflow.md); what is still owed before production is in
[production-readiness.md](./production-readiness.md).

Every status line below is derived from the current code rather than carried
forward from the prototype implementation.

## Contents

- [The submission contract](#the-submission-contract-configiniparams-207-fields--9)
- [Moving the form options out of code](#moving-the-form-options-out-of-code)
- [Results pagination](#results-pagination)
- [Results filtering](#results-filtering)
- [Results-load performance](#results-load-performance)
- [Checking the output against the submission](#checking-the-output-against-the-submission)
- [Allele-frequency labels](#allele-frequency-labels)
- [What the specs replaced](#what-the-specs-replaced)
- [The unspecced tail](#the-unspecced-tail)
- [Tests](#tests)
- [Porting to ensembl-client](#porting-to-ensembl-client)
- [Embedding into ensembl-client](#embedding-into-ensembl-client)

---

## The submission contract (`ConfigIniParams`: 207 fields → 8)

**Status: done, 2026-08-09.**

`ConfigIniParams` used to declare **207 fields**, 199 of them one per form
control. None of the 199 was ever read by attribute: they arrived as
`ConfigIniParams(**payload)` and left as `.model_dump()`. They were a third
statement of what the config entries already say — after the form panels and the
`fields=` clause — and the only one that could not tell one assembly's options
from another's.

It is now **eight** fields: seven job fields, each genuinely read, plus

```python
options: dict[str, bool | int | str] = {}
```

completed and validated against the spec for *this submission's* assembly by a
model validator (`_resolve_options` → `vep/submission_options.py`).

**What that fixed, concretely.** A flat model accepted `pli=True` for GRCh37,
which has no pLI data and no such option; nothing said otherwise. The map is now
exactly what the genome offers, so `"pli" in params.options` is False on GRCh37
and True on GRCh38.

**Three decisions inside it worth not re-litigating:**

- **`extra="forbid"`.** A caller still passing an option as a keyword now fails
  loudly instead of having it silently dropped — that silent drop being the whole
  failure this change was about.
- **Unknown options are dropped and logged, not rejected.** A submission can be
  rerun for 28 days, so a replayed payload may still name an option since
  retired; failing that rerun would be worse than ignoring it. What was wrong
  before is that pydantic's `extra` default discarded them *in silence*, so a
  typo and a deliberate omission looked identical from every side.
- **Defaults must be completed, not passed through.** An option left at its
  default is never written into the submitted parameters, so a payload naming
  only `protvar` must still come out with `protvar_stability` and
  `protvar_pocket` set. Absent and off are not the same thing.

**How it was verified**, because this is the pattern for any risky migration
here: capture the emitted `config.ini` for a matrix of option selections from the
*pre-change* code (stashed, then imported from git), run the same matrix after,
and diff. 12/12 byte-identical. Comparing `config.ini` output is the real oracle;
the tests are not.

★ **One casualty, now repaired.** `test_form_defaults_match_the_config_parameter_defaults`
compared the form's defaults against `ConfigIniParams`' boolean-defaulted fields.
There were no longer any, so it built an empty dict and **could not fail** — on
GRCh38 it walked 158 form options and checked them against nothing.

Rewritten rather than deleted, as
`test_an_unsent_option_comes_back_at_the_form_s_declared_default`: it reads the
defaults off `get_visible_panels`, submits an **empty** option map, and requires
the result to reproduce them exactly — comparing type alongside value, since
`True == 1` would otherwise hide a boolean widened to an int. It covers GRCh38,
GRCh37 and GRCm39, and asserts the walk found something, which is precisely what
the old test had stopped doing. It is the complement of
`test_option_ids_round_trip_into_a_submission`, which sends every option; this
one sends none.

★ **Note what the control has to break.** Flipping a default in the spec proves
nothing here — form and submission read the *same* declaration, so both sides
move together and the test stays green. The control that matters breaks the
**mechanism**: make `submission_options.option_values` ignore
`option.default`, and the test fails naming each option and both sides of the
disagreement. Verified 2026-08-09.

---

## Moving the form options out of code

**Status: done, 2026-08-09, in four steps.** `form_panels.py` 1,081 → 492 lines.

The design question was "can the form options be served as data?", and the
answer that mattered was *not* "copy `form_panels.py` into a JSON file". The
finding that decided it:

**Every form option is already a config entry.** Checked exhaustively for human
GRCh38 — 35 of 35 top-level form options had a config entry of the same id, with
exactly two deliberate exceptions the other way (`clinvar_short` and `hgvsg`,
which must present no control). So the presentation belongs *on the entry it
already has*, not in a parallel document that would need its own tier-layering,
its own override rules and its own way to stay in step.

That is why there is a `form` block on `ConfigEntry` and no `form.json`.

**The duplication it removed.** The allele-frequency ancestry tables were written
out **three times** — in the `fields=` builder, in the form panels, and in the
label decoder — and had already drifted. They are now one table on the builder,
carrying `label`, `default` and `form_order` alongside the code, feeding all
three uses.

★ **The trap that migration hit**, worth knowing because it is invisible: the two
gnomAD **SV** generators share option ids but not labels. A harvest keyed on
option id therefore merged them and silently gave GRCh38 v2.1's wording. The fix
was to harvest per assembly and add an explicit `population` field rather than
deriving the code from the option id. When single-sourcing anything here, check
whether the ids are unique *across assemblies* before keying on them.

**The oracle used throughout:** `app/tests/form_panels.golden.json`, a frozen
capture of the served panels for four cases (human GRCh38, human GRCh37, mouse,
an unlisted species), taken **before** any change. Four successive steps moved 47
literal option nodes, then the AF tables, and the golden file never moved.

---

## Results pagination

**Status: implemented.**

A **BGZF virtual-offset record-checkpoint index**, generated by the *pipeline*
(not the API), written as a sidecar next to the output VCF. The API seeks to a
page instead of scanning from the top.

- Generator: `build_page_index.py` → `bin/` + `modules/generate_index.nf` in
  ensembl-vep/nextflow.
- Seek path: `get_results_from_path` in `vcf_results.py` — sidecar fast path,
  with the bcftools scan kept as a fallback.
- Covered by `tests/test_page_index.py`.

Generating it in the pipeline rather than the API is the load-bearing choice: the
pipeline already streams every record once, so the index costs nothing extra
there, where the API would pay a full scan per job to build it.

★ `copy_remote.sh` misnames the page index for scaled test fixtures, so the seek
path silently falls back to scanning and is ~19× slower. If a test page feels
slow, check the sidecar's filename before profiling anything.

---

## Results filtering

**Status: implemented and since extended.** Server-side, applied across all
pages.

- **Transport:** a `filters` query param — a JSON array of
  `{field, operator, values}`, omitted entirely when nothing is active so
  unfiltered requests keep the fast path.
- **Backend:** `app/vep/utils/results_filters.py` + `get_results_from_path`.
- **Entry-level semantics:** filters act at the CSQ-entry (per-transcript) level.
  A record is kept iff ≥1 entry matches, and the kept record is rewritten with
  only its matching entries — so a filtered variant shows only the transcripts
  carrying a selected consequence. Allele-level annotations are identical across
  an allele's rows, so they survive as long as one entry does.
- **12 score filters** today: AlphaMissense, CADD (phred + raw), ClinPred, EVE,
  popEVE, REVEL and SpliceAI's four delta scores plus an "any" variant.

**Filters run in order and short-circuit**, so ordering is a real lever; the
per-filter `removed` counts in metadata and logs exist to gather numbers before
ranking them. That ranking has still not been done.

**The prefilter, which is the interesting measurement.** Profiling showed
**14.6 s of a 22 s filtered scan was `str.split`** — `_find_csq` fully split all
~6.6 M CSQ entries though only 3.3 % matched. The fix is a raw-line
`line_prefilter` on literal-membership filters: a record can only match if a
selected value appears as a substring of the *unsplit* line, a cheap C-level `in`
run before any splitting. It is a **necessary condition**, so false positives
fall through to the exact check and there are no false negatives. Result:
**22 s → 6.3 s**, RSS 75 → 56 MB, identical output. Gene symbol gets no prefilter
(case-insensitive); allele-frequency and transcript-group have no literal token.

★ **The availability gate is where new filters go wrong.** Whether a filter is
offered is decided from `expected_columns`, which comes from `csq_fields`.
SpliceAI declares only *one* of its four delta columns there — gate on that
sentinel, and do **not** widen `csq_fields` to make the gate convenient. Widening
it changes what `expected_csq_columns` requires at results time, and a
legitimately absent column then fails the check.

### Open: allele-frequency "no data" semantics

Unresolved, and flagged deliberately. The AF filter currently ignores no-data
(missing / empty / non-numeric) values when evaluating a comparison, and an
allele with *no* AF data at all for the tested columns is **dropped**
(`_compile_allele_frequency` returns False when there are no numeric values).

- Under "any ≤ x", an all-no-data allele contributes nothing and is dropped — is
  that intended, or should no-data pass through, or be shown separately?
- Under "all ≤ x", dropping avoids a vacuous `all([]) == True`, but the intent
  for *partially* missing sets may differ (currently judged only on the present
  values).
- The results view shows selected-but-empty AF sources as "no data"; the filter
  and that display should end up telling one story.

A decision is needed (a toggle, or an explicit pass/fail policy), then backend
and frontend aligned.

### Also open: a filter-set index cache

The filtered path always full-scans. It was made streaming and bounded-memory,
which was the correctness/robustness fix; caching a filter-set index was
considered and deferred.

---

## Results-load performance

**Status: the wins landed; they were not where the notes predicted.**

An earlier note in this folder was a ranked list of *page-parsing* speedups —
pydantic construction, CSQ splitting, model reuse. Worth recording that **none of
them was the win**:

| change | effect |
|---|---|
| FastAPI's `jsonable_encoder` on the response | **490 ms → 62 ms** |
| annotation **dedup** on the payload | **7.87 MB → 1.17 MB** |

Both merged; the deployment is confirmed significantly faster. A purpose-built
VCF reader replacing vcfpy also exists but is **parked and unpushed**.

Earlier, real but smaller: column-presence gating (`_has_any_column`) so optional
parsers short-circuit when their plugin was not in the run — ~68 ms → ~42 ms on a
sample page.

★ Two things to carry forward:

- **`by_alias=True` is load-bearing and omitting it fails silently.**
  `jsonable_encoder` applies aliases where `model_dump_json` does not.
- **Dedup identity is the payload, not the plugin.** Annotations repeat across a
  variant's ~43 transcript consequences; deduplicating by *value* is what shrank
  it (744 distinct of 864 in the sample).

Responses are compressed with level-1 gzip, except downloads that are already
gzip-compressed. See `app/main.py` for the middleware and its benchmarked level.

**Method note, hard-won:** bench wall-clock, not cProfile — the profiler's
overhead dominates this workload and reorders the ranking. Set
`PYTHONDONTWRITEBYTECODE=1` or a stale `.pyc` will make a control run lie.

---

## Checking the output against the submission

**Status: implemented.** Results parsing used to be purely header-driven — it
read whatever CSQ columns were present and never checked them against what the
job asked for, so a silently-missing plugin looked like a variant with no
annotation.

Each job now pins an `expected_columns.json` sidecar at submission — the CSQ
columns its selected options must produce, derived by
`MergedSpec.expected_csq_columns` from the same config entries that wrote the
`config.ini` — and results time checks the output header against it.

**The contract is directional:** the backend fails on *missing* expected columns
and silently ignores *extra* ones. That asymmetry is deliberate. Workflow output
can legitimately carry columns the user never
selected; a missing column, by contrast, means the run did not do what was asked.

Two sibling sidecars pin the rest of the ruleset: `parsing_spec.json` (the whole
merged document) and `display_panels.json` (the panel layout as submitted).

---

## Allele-frequency labels

**Status: resolved.**

The AF population code↔label mapping used to exist on both sides — the backend
built the form labels, and the frontend kept its own copy to render results.
Labels are now decoded once, on the backend (`form_panels.af_population_label`),
and read off the response via `available_af_sources`
(`{key, source, population, label}` per column, gated to the populations the
submission actually selected).

The frontend keeps **no** copy of the population vocabulary; its only remaining
copies are test fixtures. That is what lets a new AF source need no frontend
change at all — see the guide's Recipe C.

---

## The contract points

Each of these is a place where two sides must agree, and where a change on one
breaks the other unless made in step. Most are enforced in code; the rest are
load-time or runtime checks. Re-verified 2026-08-09.

| # | contract | enforced by |
|---|---|---|
| C1 | An option id **is** its key in the submission's `options` map | `test_option_ids_round_trip_into_a_submission` — every form option and sub-option id survives a submission |
| C2 | A submitted option is one this genome actually offers | `ConfigIniParams._resolve_options` → `submission_options.option_values`, checked against the assembled spec. Unknown keys are **dropped and logged**; `extra="forbid"` catches a caller passing an option as a keyword |
| C3 | The fields a config line emits are the CSQ columns VEP writes | `expected_csq_columns` is derived from the *same* `build_fields` that wrote the line |
| C4 | Config ⇄ parsing ⇄ display refer to things that exist | the `MergedSpec` model validator at load: `parsed_as` names real plugins, display refs resolve to parse targets, formats suit the parsed types |
| C5 | A job is read with the ruleset it was built with | the content digest plus the three pinned sidecars |
| C6 | The output carries the expected columns | the runtime check at results — missing fails, extra is ignored |
| C7 | An annotation's shape matches what the display expects | `item_fields` on a list target vs the cells/columns that read them (load-time) |
| C8 | Per-allele annotation metadata matches the parsed keys | `af_source_descriptor` derives its population code from the same `from_pattern` the parse uses, so the frontend can join on it |

★ **C1 and C2 used to say something different, and the older phrasing is still
quoted in places.** The contract was once "every form option id must be a
`ConfigIniParams` **field**", policed by a test of that name, with C2 noting that
pydantic's default **silently dropped** an unknown key — so an option the form
offered but the model did not declare reached the emitter as "not selected" and
its config line simply never appeared. Both halves of that are gone: options are
a spec-validated map, and an unrecognised one is now said out loud.

---

## What the specs replaced

Kept because knowing the shape of the old system explains several things that
otherwise look arbitrary.

Before the merged spec, adding an annotation meant a **four-layer hand-synced
edit**: a `TARGET_COLUMNS` allow-list in `vcf_results.py`, a hardcoded
`PLUGIN_CONFIG_LINES` / `PLUGIN_CONFIG_LINES_BY_ASSEMBLY` map, a typed pydantic
model per annotation, and a frontend override registry keyed by option id. Every
one of those is gone: `TARGET_COLUMNS` survives only as a fixture in
`test_vep.py`, and **the frontend override registry is empty**. ClinVar — once
the standing example of what could not be expressed declaratively — is now the
largest thing described in the display spec.

### The decisions that shaped it (settled in review, 2026-07-18)

- **The spec owns the option→`config.ini` mapping**, not just parse and display.
  Splitting them would have left the drift the project existed to remove.
- **One merged document, one content digest.** The pinning machinery already
  existed for parsing; merging both halves means one digest pins the whole
  front↔back contract for a job.
- **Panel *activation* stays in the backend; option *definitions* move to JSON** —
  data in JSON, conditional logic in code. ★ This one has since gone further than
  designed: the definitions moved onto the config entry, and the activation logic
  dissolved with them, because an option now exists for exactly the genomes whose
  spec declares it.
- **Always-on config lines stay in the backend** — VEP invocation invariants, not
  options.
- ★ **"Display does not fully close like parsing, and that is fine."** Parsing is
  a finite set of structural transforms; presentation is open-ended. The design
  deliberately aimed at *generic renderer primitives the JSON composes* plus a
  small shared interactive kit — **not** a per-plugin override registry — and
  accepted that a tail of judgment calls would keep needing frontend code.

That last prediction is worth keeping because it was **beaten**: the tail it
expected to persist (ClinVar's two shapes, IntAct's derived count, All of Us's
`max` bracket, OpenTargets' compound rows) was all eventually expressed
declaratively, and the override registry is empty. What genuinely remains is
much smaller than forecast — three named link builders and the formatter
functions. The lesson is not that the caution was wrong, but that the vocabulary
kept absorbing cases that looked like judgment calls right up until someone
tried.

★ **What the design also predicted correctly:** it identified the frequency
population labels as "a hand-synced copy of `form_panels.py` labels — the exact
drift this project removes". That copy is indeed gone.

Durable from that era:

- **The CSQ-field research.** VEP's `Consequence_type` column naming, which
  plugins emit which columns, and the `&`-escaping behaviour, all still hold.
- **VEP rewrites both `,` and `|` to `&`.** Any source carrying structure *below*
  that level must use a delimiter VEP leaves alone — the enriched ClinVar VCF
  uses `~` between subfields and `+` between repeats. Split **before**
  percent-decoding, and use `unquote`, never `unquote_plus`.

---

## The unspecced tail

**Status: open, blocked on data.**

A few annotations were never converted to plugin specs and remain hand-typed
pydantic fields:

| field | where |
|---|---|
| `uniprot`, `protein_matches`, `sift`, `polyphen` | `vcf_results_model.py:102` |
| `colocated_variants` | `vcf_results_model.py:201` |

They are left typed **deliberately**: no sample data carries their columns, so no
spec could be validated for them. `ensembl_protein_id` was the last of this tail
to convert — it is now the `protein` parse plugin — which is the model for the
rest, once data exists.

★ An older note in this folder proposed trimming unused `PopEve` model fields.
That note is now fully obsolete: `class PopEve` and `_parse_popeve` no longer
exist, and neither does the frontend's `case 'eve'`. EVE and popEVE are ordinary
spec-driven options. Nothing to trim.

---

## Tests

**732 passing**, 1 skipped, and **one environment-specific failure** in the
current checkout: `test_blast.py::test_read_config` reads
`/data/blast_config.json`, which is absent outside the container runtime. The
failure is unrelated to VEP and should not be treated as a regression.

```bash
PYTHONPATH=app .venv/bin/python -m pytest app/tests -q
```

Use a **python3.11** venv; 3.12 cannot build vcfpy.

Run the VEP frontend checks from the `ensembl-client` checkout using that
repository's TypeScript, test, formatting, and lint commands.

Coverage baseline (2026-07-20): backend 79 %, frontend VEP utils 92.7 %.

★ **The recurring finding worth internalising:** more than once, the only test
coverage for a feature turned out to be testing the code being deleted — the AF
renderer's six tests were allele frequencies' *entire* coverage, and the
phenotype source link had none at all. Grep for coverage before finishing a
migration, and rewrite tests onto the real path rather than dropping them.

---

## ensembl-client integration

`ensembl-client` owns the VEP user experience and consumes the tools API's form,
submission, status, results, and download contracts. Client changes should be
validated with that repository's TypeScript, test, formatting, and lint
configuration before integration.

The API remains responsible for assembling form options, pinning the submitted
specification beside each job, launching the workflow, and parsing the workflow
output. Keep browser-specific concerns out of these server-side contracts.
