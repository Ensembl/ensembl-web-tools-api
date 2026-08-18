# What must change before this is deployed

The API now resolves plugin data from the configured support-data mount and
always launches the Seqera workflow. This is the remaining deployment work and
the smaller debts that should not be discovered during a deployment.

Each item is tied to the current code path and says how to re-derive it.

Companions: [dataflow.md](./dataflow.md) shows the workflow; [spec-and-extension-guide.md](./spec-and-extension-guide.md) is the
grammar; [technical-notes.md](./technical-notes.md) is the reasoning.

## Contents

- [Seqera / Nextflow wiring](#seqera--nextflow-wiring)
- [Coverage gaps](#coverage-gaps)
- [Debts that are not blockers](#debts-that-are-not-blockers)

---

## Seqera / Nextflow wiring

**Status: configured in the API; requires live integration validation.** The API
creates a per-job directory, launches the configured workflow, and reads that
workflow's output from the same shared filesystem.

Already built (`app/vep/models/pipeline_model.py`, `app/vep/utils/nextflow.py`):
`VEPConfigParams`, `LaunchParams`, `PipelineParams`, `launch_workflow()`,
`get_workflow_status()`, and `PipelineStatus` (`pipeline_model.py`), which
reads status from `status.workflow.status` and maps `UNKNOWN → FAILED`.

Outstanding:

1. **Real credentials and IDs in `.env`** — `NF_COMPUTE_ENV_ID`,
   `NF_WORKSPACE_ID`, `NF_TOKEN`, `NF_PIPELINE_URL`, `SEQERA_API`. All are
   placeholders copied from `.env.sample`. `NF_WORK_DIR` currently points at a
   local path and must point at the managed Nextflow work area.
2. **Validate the launch payload against the live API** — confirm
   `pipeline_params.model_dump()` matches what `/workflow/launch` expects
   (compute env id, pipeline/revision, `configProfiles`, and `paramsText` as a
   JSON *string*), and that `workflowId` is the field returned.
3. **Validate the status shape** — confirm the live `GET /workflow/{id}` really
   nests status at `status.workflow.status`; adjust the alias if not. Check the
   full status value set and whether `UNKNOWN → FAILED` is still right.
4. **Results retrieval** — confirm where the pipeline writes `outdir` and how the
   API locates the output VCF for `get_results_from_path` and the TSV export.
5. **Error surfacing** — `launch_workflow` / `get_workflow_status` re-raise with
   annotated messages; decide how those map to API responses the frontend can
   distinguish (submission failed vs transient network error).
6. **Work-dir lifecycle.** The submit path keeps the per-job `mkdtemp` dir under
   `NF_WORK_DIR` on success (it is the job's input dir: `input.vcf` +
   `config.ini`); only error paths `rmtree` it.

**Testing note:** `launch_workflow` / `get_workflow_status` are untested because
they do live HTTP. When wiring, add offline tests with `requests` mocked —
asserting the URL, the `workspaceId` param, the bearer header and the payload
shape for launch; and status parsing including `UNKNOWN → FAILED` for poll.

---

## Coverage gaps

### Only human has a spec of its own

`app/vep/specs/` holds `human_grch38.json` and `human_grch37.json` and nothing
else. Every other species assembles from `base.json` plus whatever
`species_annotations.json` grants it (GO for all 50, Phenotypes for 15, CADD for
3). That works — VEP needs only a GFF and a FASTA, so an unlisted species still
runs, simply offered fewer options — but the per-species documents that would
give other genomes their own option sets have not been written.

The split that would guide it: parsing and display are **species-agnostic**; a
genome document is purely *availability plus file paths*. So a new species
document is a list of which entries apply and where their data files are — no
new parse or display work.

### The unspecced tail

`uniprot`, `protein_matches`, `sift`, `polyphen` (`vcf_results_model.py:102`) and
`colocated_variants` (`vcf_results_model.py:201`) are still hand-typed pydantic
fields rather than parse plugins. **Blocked on data**, deliberately: no sample
VCF carries their columns, so no spec could be validated. `ensembl_protein_id`
was the last of this tail to convert and is the model for the rest.

### HGVSg is hidden, not finished

HGVSg has a config entry, a parse plugin and ProtVar's `forces_on` dependency —
all live — but no form control and no results row, because its genomic notation
names chromosomes in a form that cannot yet be mapped. It needs **chromosome
synonyms** before it can be shown.

★ Do not delete the plumbing as dead code. ProtVar reads it to build its link.

### Help text is linked out, not in-repo

Option help is linked by slug to an external docs service. The client integration
needs to reconnect the help section where it renders VEP options.

---

## Debts that are not blockers

| debt | detail |
|---|---|
| **Upstreaming the edits to pre-existing code** | The branch contains a large VEP change set on top of pristine `13a98ef`. Regenerate the affected-file list and size before relying on it: `git diff --stat 13a98ef HEAD -- <path>` |
| **AF "no data" filter semantics** | Undecided; an allele with no AF data at all is currently dropped. See [technical-notes.md](./technical-notes.md#open-allele-frequency-no-data-semantics) |
| **popEVE gap-frequency filter** | Wanted, deliberately out of scope so far: it asks a different question from the score filters ("how well covered is this position" vs "how damaging is this variant") and needs its own label and place in the UI rather than a thirteenth score field. `results_filters.py:131` |
| **AF codes still inline on the builder** | `GnomadAncestrySexFields` and friends carry a `TODO (at merge)` to move ancestry/sex codes onto the option definitions and reference them, rather than inlining — carried where they are so the config interpreter stays self-contained |
| **Vestigial placement code** | `form_panels._place_spec_options` still spaces "coded options" by `_CODED_OPTION_STEP`, but panels now start empty, so that branch never runs |
