# What must change before this leaves dev

The dev setup deliberately fakes three things — where the plugin data lives, who
runs the pipeline, and where results come from. This is the list of what has to
become real, plus the smaller debts that should not be discovered during a
deployment.

Verified 2026-08-09 against tools-api `b69b769` and standalone-web-vep `880fa38`.
Every item was re-checked against the code; each says how to re-derive it.

Companions: [dataflow.md](./dataflow.md) shows where each dev shortcut sits in
the flow; [spec-and-extension-guide.md](./spec-and-extension-guide.md) is the
grammar; [technical-notes.md](./technical-notes.md) is the reasoning.

## Contents

- [Blockers — nothing runs on real data without these](#blockers--nothing-runs-on-real-data-without-these)
- [Seqera / Nextflow wiring](#seqera--nextflow-wiring)
- [Dev-only code to remove](#dev-only-code-to-remove)
- [Coverage gaps](#coverage-gaps)
- [Debts that are not blockers](#debts-that-are-not-blockers)

---

## Blockers — nothing runs on real data without these

### 1. `PLUGIN_PATH` is a placeholder

`pipeline_model.py:76`:

```python
PLUGIN_PATH = "/[placeholder_path]"
```

Every `plugin …` / `custom …` line interpolates `{path}` from this, so in
production **no plugin can run against real data**. It carries an explicit
`TODO (pre-production, required)`.

What it needs: real **per-genome** plugin-data resolution on the compute
environment. Note the shape the dev resolver already proves is necessary — it is
a function of the config-entry id, not a constant, because a few datasets live in
their own subdirectory under the assembly root, and non-human assemblies must
resolve under a *different* tree entirely (see item 2).

### 2. Per-genome path resolution must not fall back to human

The dev resolver used to fall back to the GRCh38 root for any unrecognised
assembly, which pointed a cattle job at human data files. It now falls through to
a shared other-species tree instead. **Whatever replaces it must preserve that
property**: an unknown assembly is a different species, not a broken lookup, and
silently annotating one species with another's data is the worst failure mode
available here.

### 3. GERP's path is a hardcoded human GRCh38 filename

```jsonc
"args": ["{path}/gerp_conservation_scores.homo_sapiens.GRCh38.bw"]
```

It does no harm today because the entry is declared only in `human_grch38.json`.
But GERP is wanted for other species, and the moment it is offered anywhere else
this path must become `by_assembly` (or templated on `{production_name}`, like
the `species_annotations.json` datasets). Re-derive with:

```python
[e.config for e in load_merged_spec("human_grch38").config.entries if e.id == "gerp"]
```

---

## Seqera / Nextflow wiring

**Status: scaffolded, never run against the live API.** In dev there is no
automated end-to-end run at all — the API dumps a `config.ini`, the Nextflow/VEP
step is run manually on the HPC, and the output VCF plus sidecars are copied into
`dev-data/`.

Already built (`app/vep/models/pipeline_model.py`, `app/vep/utils/nextflow.py`):
`VEPConfigParams`, `LaunchParams`, `PipelineParams`, `launch_workflow()`,
`get_workflow_status()`, and `PipelineStatus` (`pipeline_model.py:306`), which
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
   API locates the output VCF for `get_results_from_path` and the TSV export,
   replacing the `LOCAL_RESULTS_VCF` dev path.
5. **Error surfacing** — `launch_workflow` / `get_workflow_status` re-raise with
   annotated messages; decide how those map to API responses the frontend can
   distinguish (submission failed vs transient network error).
6. **Work-dir lifecycle.** The submit path keeps the per-job `mkdtemp` dir under
   `NF_WORK_DIR` on success (it is the job's input dir: `input.vcf` +
   `config.ini`); only error paths `rmtree` it.

   ★ Re-checked 2026-08-09: `DiskCleanup.delete_old_temp_directories(days=7)`
   exists in `app/vep/utils/cleanup.py` but **nothing in the repo imports or
   calls it**, and it reads its own `UPLOAD_DIRECTORY` (default
   `/nfs/public/rw/enswbsites/`) rather than `NF_WORK_DIR`. So either it is meant
   to be driven by an external cron against the upload area — in which case job
   work dirs under `NF_WORK_DIR` have *no* reaper at all — or it needs wiring and
   repointing. Decide which.

**Testing note:** `launch_workflow` / `get_workflow_status` are untested because
they do live HTTP. When wiring, add offline tests with `requests` mocked —
asserting the URL, the `workspaceId` param, the bearer header and the payload
shape for launch; and status parsing including `UNKNOWN → FAILED` for poll.

---

## Dev-only code to remove

### The `_DEV_PLUGIN_ROOT` block

`pipeline_model.py:79–107` is marked `--- DEV ONLY ---` and says so itself:
remove the whole block **and** the `DUMP_INI` branch in `create_config_ini_file`
once real per-genome resolution lands. It exists so a dev job's dumped
`config.ini` points at the real beta data on nfs, which the manual HPC run reads
directly.

It contains three things that will be needed by whatever replaces it, so read it
before deleting: the per-assembly roots, the per-dataset subdirectory map
(`_DEV_PLUGIN_SUBDIRS`, keyed by config-entry id), and the other-species root.

### Dev modes

`DUMP_INI`, `DUMP_INI_DIR` and `LOCAL_RESULTS_VCF` (`app/core/config.py`) are all
described in their own comments as dev/testing and temporary. They should be
inert in production, not merely unset — a `LOCAL_RESULTS_VCF` set by accident
silently serves the wrong job's results to every request.

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

Option help is linked by slug to an external docs service. The plumbing for it
was stripped from the standalone repo, so the help section has to be reconnected
wherever VEP finally lands.

---

## Debts that are not blockers

| debt | detail |
|---|---|
| **No response compression** | The backend sends none at all. The largest untouched performance lever — see [technical-notes.md](./technical-notes.md#results-load-performance) |
| **Upstreaming the edits to pre-existing code** | 386 commits sit on top of pristine `13a98ef`. Most are new files, but a set of pre-existing tools-api files are genuinely edited — `vcf_results.py` (+1,299), `vep_resources.py` (+321), `pipeline_model.py` (+238), plus `test_vep.py`, `vcf_results_model.py`, `upload_vcf_files.py`, `submission_form.py`, `nextflow.py`, `web_metadata.py`, `docker-compose.yaml`, `requirements.txt`. **Regenerate before relying on this list**: `git diff --stat 13a98ef HEAD -- <path>` |
| **AF "no data" filter semantics** | Undecided; an allele with no AF data at all is currently dropped. See [technical-notes.md](./technical-notes.md#open-allele-frequency-no-data-semantics) |
| **popEVE gap-frequency filter** | Wanted, deliberately out of scope so far: it asks a different question from the score filters ("how well covered is this position" vs "how damaging is this variant") and needs its own label and place in the UI rather than a thirteenth score field. `results_filters.py:131` |
| **AF codes still inline on the builder** | `GnomadAncestrySexFields` and friends carry a `TODO (at merge)` to move ancestry/sex codes onto the option definitions and reference them, rather than inlining — carried where they are so the config interpreter stays self-contained |
| **Vestigial placement code** | `form_panels._place_spec_options` still spaces "coded options" by `_CODED_OPTION_STEP`, but panels now start empty, so that branch never runs |
| **Reintegration, not separation** | `standalone-web-vep`'s independence is a dev convenience. The destination is `ensembl-client`; work whose only value is to the standalone shell should not be started. See [technical-notes.md](./technical-notes.md#embedding-into-ensembl-client) |
