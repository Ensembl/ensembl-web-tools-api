# VEP docs

Everything about how the VEP annotation system works, how to extend it, and what
it still owes before production — four documents, plus the rendered diagrams.

They cover all three repos (`ensembl-web-tools-api`, `standalone-web-vep`,
`ensembl-client`) but **live here**, in the backend repo, so they are versioned
and reviewed with the code they describe. A change to them goes through a branch
and a PR like anything else.

**History:** these began as 16 loose notes outside the repos, were collapsed into
four themed documents on 2026-08-09, and moved here the same day — absorbing the
three design docs that used to occupy this folder. Everything was re-verified
against tools-api `b69b769` and standalone-web-vep `880fa38`: counts, file:line
references and status lines were read out of the code, not carried forward.

## The four documents

| doc | what it is |
|---|---|
| **[spec-and-extension-guide.md](./spec-and-extension-guide.md)** | **The JSON specifications, and how to add new data, options and output.** The full grammar of all three spec sections plus the `form` block — config emitters, the 11 parse transforms, the 12 post-ops, the 5 display block kinds, the 8 formats — with worked recipes from a simple plugin to a new allele-frequency source, what fails at load time, and 15 accumulated traps |
| **[technical-notes.md](./technical-notes.md)** | **How the surrounding machinery works, and why.** The submission contract, the form-options migration, pagination, filtering, results-load performance, output checking, what the specs replaced, the test suite, and porting to `ensembl-client` — each with the measurements and the dead ends already ruled out |
| **[dataflow.md](./dataflow.md)** | **What calls what, end to end**, with three worked examples (a pLI score, an allele frequency, a filtered page) that link into the guide's reference sections. Plus the three SVG diagrams, species selection, the metadata API, and the dev server's modes and toggles |
| **[production-readiness.md](./production-readiness.md)** | **What must change before this leaves dev.** The blockers (nothing runs on real data without them), the Seqera wiring, the dev-only code to remove, the coverage gaps, and the debts that are not blockers |

Start with the guide if you are adding an annotation; with dataflow if you are
trying to find where something happens; with production-readiness if you are
planning a deployment.

## Where to start for common tasks

| task | go to |
|---|---|
| add a new annotation option | [guide §4](./spec-and-extension-guide.md#4-recipe-a--a-simple-plugin-end-to-end), then the [checklist](./spec-and-extension-guide.md#appendix--the-checklist) |
| add a new allele-frequency source | [guide §6](./spec-and-extension-guide.md#6-recipe-c--a-new-allele-frequency-source) |
| add a results filter | [guide §7.3](./spec-and-extension-guide.md#73-a-new-results-filter) — filters are **not** spec-driven |
| change where an option appears on the form | [guide §8.5](./spec-and-extension-guide.md#85-the-form-block) — backend-only, it moves the results grouping too |
| work out why an option vanished | [guide §12 trap 1](./spec-and-extension-guide.md#12-traps) — `parsed_as: []` drops it silently |
| understand why a display change "didn't work" | the spec is pinned per job; [dataflow](./dataflow.md#the-whole-flow-in-one-picture) |
| run the dev loop locally | [dataflow](./dataflow.md#dev-server-modes-and-toggles) |
| port frontend work to the client | [technical-notes](./technical-notes.md#porting-to-ensembl-client) |

## What happened to the other twelve documents

Their durable content was folded into the four above; the rest was premise that
had gone out of date. Superseded originals are **not** kept here — the reasoning
worth keeping was carried across, and a banner-topped stale doc still gets opened
from a search result and believed.

| former doc | where it went |
|---|---|
| `extending-vep-annotations.md` | became **spec-and-extension-guide.md**, corrected |
| `form-panels-to-json.md` | design note whose proposal shipped → technical-notes § Moving the form options out of code |
| `pagination-design.md` | technical-notes § Results pagination |
| `results-filtering-notes.md` | technical-notes § Results filtering, including its open AF no-data question |
| `page-parsing-speedups.md` | technical-notes § Results-load performance — kept as the record that its ranked ideas were *not* the win |
| `results-parse-schema-check-note.md` | technical-notes § Checking the output against the submission |
| `shared-config-labels-note.md` | technical-notes § Allele-frequency labels |
| `annotation-output-spec.md` | technical-notes § What the specs replaced (the CSQ-field research and the VEP `&`-rewriting rule) |
| `model-trim-notes.md` | technical-notes § The unspecced tail — its own subject (`PopEve`, `_parse_popeve`) no longer exists |
| `backend-test-plan.md` | technical-notes § Tests — it was a plan for a suite that now has 727 tests |
| `embedding-audit.md` | technical-notes § Embedding into ensembl-client |
| `seqera-wiring-todo.md` | production-readiness § Seqera / Nextflow wiring |
| `phenotypes-species-todo.md` | production-readiness § Only human has a spec of its own; the per-species work it described is now one table row |
| `tools-api-existing-code-changes.md` | production-readiness § Debts — as a regenerate-this-first pointer, since its file list had drifted badly |

And the three design docs that used to live in this folder, folded in the same
day (they are in git history if something turns out to have been dropped):

| former doc | where it went |
|---|---|
| `merged-annotation-spec.md` | technical-notes § What the specs replaced — the 2026-07-18 decisions and the "display does not fully close" call, with a note that the prediction was **beaten** — and § The contract points (C1–C8, with C1/C2 rewritten: they described the pre-migration model) |
| `adding-an-annotation-plugin.md` | fully superseded by spec-and-extension-guide.md, which was already the longer version of it |
| `option-tiers-by-species.md` | guide §2.3 "What each genome is offered", re-derived — it had GRCh38 at 35 entries (now 37) and listed the **v4** gnomAD trio for GRCh37, which gets **v2** |

## ★ The standing rule: update these docs *with* the change

**After any change to VEP, check whether it invalidated something here, and fix
it as part of that change — not as a follow-up.**

The 2026-08-09 restructure found **nine wrong claims** in a document that called
itself current, and every one was a by-product of work "finished" weeks earlier.
A wrong doc is worse than a missing one: it gets opened from a search result and
believed. Living in the repo helps — the diff is reviewable — but nothing
*checks* these files, so the habit is still what holds.

Most changes need no edit. The check is meant to take seconds, not a re-read —
ask *did this invalidate a specific claim?*, then look at the one doc that owns
it:

| a change to… | check |
|---|---|
| a config entry, `form` block, parse plugin, display option, or a spec model | [spec-and-extension-guide.md](./spec-and-extension-guide.md) — the §1 counts table, the §8–§10 reference, the recipe steps |
| a **new** transform / post-op / block kind / format / emitter | the guide's vocabulary tables — they state exact counts ("the eleven transforms") |
| `form_panels.py`, `pipeline_model.py`, `submission_options.py` | guide §2.5 "what is still code", and [technical-notes](./technical-notes.md#the-submission-contract-configiniparams-207-fields--9) |
| filters, pagination, performance, the test suite, the port process | [technical-notes.md](./technical-notes.md) |
| a route, an env var, a dev-server mock, the metadata API | [dataflow.md](./dataflow.md) |
| anything dev-only, placeholder, or `TODO (pre-production)` | [production-readiness.md](./production-readiness.md) |
| **deleting** a fallback, shim or dated obligation | grep the docs for its deletion date — a "can be deleted from `<date>`" note left standing is exactly how one claim went stale |

Two things that rot fastest, so check them by reflex:

- **Counts.** Three of the nine stale claims were numbers someone had adjusted by
  hand. Every count here ships with the expression that re-derives it — run that
  instead of incrementing.
- **The "Verified `<date>` against `<commit>`" line** at the top of each doc.
  Update it on any doc you touch.

**These docs are tracked in the repo**, so an update rides along in the same
branch and PR as the change that caused it — which is the point of moving them
here. A PR that changes documented behaviour and touches nothing in this folder
should prompt the question of whether it should have.

★ Code comments point here by path (`app/vep/docs/design/…`). If you rename or
remove a document, grep for it:

```bash
grep -rn "app/vep/docs/design" --include='*.py' app/
```

## Conventions

- **Put the status in the file, not only here.** A doc opened directly from a
  search result must say for itself whether it is still true.
- **Date the status, and say what it was verified against.** "Current" without a
  commit is unfalsifiable.
- **Re-derive counts, don't copy them.** Every number in these docs comes with the
  expression that produces it, because they all drift.
- **Delete a superseded doc; don't band it.** The reasoning worth keeping gets
  folded into one of the four, and the table above records where it went.
- **Prefer folding a note into a themed doc over adding a fifth file.** The last
  restructure existed because the folder had grown one note per afternoon.
