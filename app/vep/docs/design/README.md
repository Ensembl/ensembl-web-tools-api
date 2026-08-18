# VEP docs

Everything about how the VEP annotation system works, how to extend it, and what
it still owes before production — four documents, plus the rendered diagrams.

They cover the tools API and `ensembl-client`, but live here, in the backend
repository, so they are versioned and reviewed with the code they describe.
A change to them goes through a branch and a PR like anything else.

The documents are maintained with the current implementation; re-derive counts,
file references, and status from the code when changing a documented behavior.

## Documents list

| doc | what it is |
|---|---|
| **[spec-and-extension-guide.md](./spec-and-extension-guide.md)** | **The JSON specifications, and how to add new data, options and output.** The full grammar of all three spec sections plus the `form` block — config emitters, the 11 parse transforms, the 12 post-ops, the 5 display block kinds, the 8 formats — with worked recipes from a simple plugin to a new allele-frequency source, what fails at load time, and 15 accumulated traps |
| **[technical-notes.md](./technical-notes.md)** | **How the surrounding machinery works, and why.** The submission contract, form options, pagination, filtering, results-load performance, output checking, and tests |
| **[dataflow.md](./dataflow.md)** | **What calls what, end to end**, with worked examples, rendered diagrams, species selection, and metadata API behavior |
| **[production-readiness.md](./production-readiness.md)** | **What remains before deployment.** Seqera wiring, coverage gaps, and operational debts |

Start with the guide if you are adding an annotation; with dataflow if you are
trying to find where something happens; with production-readiness if you are
planning a deployment.

Previous documents and notes have been folded to the documents above and can be recovered from git history in case some details have gone lost.

## Where to start for common tasks

| task | go to |
|---|---|
| add a new annotation option | [guide §4](./spec-and-extension-guide.md#4-recipe-a--a-simple-plugin-end-to-end), then the [checklist](./spec-and-extension-guide.md#appendix--the-checklist) |
| add a new allele-frequency source | [guide §6](./spec-and-extension-guide.md#6-recipe-c--a-new-allele-frequency-source) |
| add a results filter | [guide §7.3](./spec-and-extension-guide.md#73-a-new-results-filter) — filters are **not** spec-driven |
| change where an option appears on the form | [guide §8.5](./spec-and-extension-guide.md#85-the-form-block) — backend-only, it moves the results grouping too |
| work out why an option vanished | [guide §12 trap 1](./spec-and-extension-guide.md#12-traps) — `parsed_as: []` drops it silently |
| understand why a display change "didn't work" | the spec is pinned per job; [dataflow](./dataflow.md#the-whole-flow-in-one-picture) |
| validate a live submission flow | [dataflow](./dataflow.md#workflow-execution) |
| integrate frontend work | `ensembl-client` |


## Update these docs together with changes

**After any change to VEP, check whether it invalidated something here, and fix
it as part of that change.**

A wrong doc is worse than a missing one: it gets opened from a search result and
believed. Most changes need no edit. Start by asking: *did this invalidate a specific claim?*, then look at the doc that owns
it:

| a change to… | check |
|---|---|
| a config entry, `form` block, parse plugin, display option, or a spec model | [spec-and-extension-guide.md](./spec-and-extension-guide.md) — the §1 counts table, the §8–§10 reference, the recipe steps |
| a **new** transform / post-op / block kind / format / emitter | the guide's vocabulary tables — they state exact counts ("the eleven transforms") |
| `form_panels.py`, `pipeline_model.py`, `submission_options.py` | guide §2.5 "what is still code", and [technical-notes](./technical-notes.md#the-submission-contract-configiniparams-207-fields--9) |
| filters, pagination, performance, the test suite, the port process | [technical-notes.md](./technical-notes.md) |
| a route, an env var, or metadata API behavior | [dataflow.md](./dataflow.md) |
| an operational gap or deferred design | [production-readiness.md](./production-readiness.md) |
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
