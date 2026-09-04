# Production readiness

The API creates a job directory, writes the VEP configuration and sidecars, and
launches the configured Seqera workflow. The following work remains before a
production deployment.

## Seqera / Nextflow validation

1. Set real values for `NF_COMPUTE_ENV_ID`, `NF_WORKSPACE_ID`, `NF_TOKEN`,
   `NF_PIPELINE_URL`, `SEQERA_API`, and `NF_WORK_DIR`.
2. Validate the launch payload and `workflowId` returned by Seqera.
3. Validate the workflow-status response shape and status mapping.
4. Confirm that the API and workflow share the job directory and can locate the
   output VCF and exports.
5. Define API error responses for launch and status failures.
6. Define retention and cleanup for per-job input directories.

Add mocked tests for the launch URL, headers, workspace parameter, payload, and
status parsing when the live integration is wired.

## Coverage gaps

### Species-specific options

Human assemblies have dedicated specs. Other species use `base.json` plus
entries selected from `species_annotations.json`; they can run but expose fewer
annotations. Adding a species-specific option set requires configuration entries
and data paths, not new parsing or display grammar.

### Unspecced annotations

`uniprot`, `protein_matches`, `sift`, `polyphen`, and `colocated_variants` are
still typed result fields because representative VCF data is unavailable to
validate parsing specs. Convert them when suitable fixtures are available.

### HGVSg

HGVSg is configured and used by ProtVar but is not displayed. It needs chromosome
synonyms before it can be presented safely.

### Option help

Option-help content is hosted externally. Reconnect its client rendering as part
of the frontend integration.

## Non-blocking follow-up

| Item | Notes |
| --- | --- |
| Upstream branch changes | Recalculate the affected-file list against the intended base before merge. |
| AF no-data semantics | Decide whether entries without AF values pass, fail, or use an explicit option. |
| popEVE gap-frequency filter | Treat as a separate filter type, not a score threshold. |
| AF code placement | Move ancestry and sex codes from builders to option definitions when practical. |
| Vestigial panel placement | Remove the unused coded-option spacing branch in `form_panels.py`. |
