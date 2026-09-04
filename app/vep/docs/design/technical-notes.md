# VEP technical notes

This document records runtime behaviour and decisions around the VEP specs. See
[the extension guide](./spec-and-extension-guide.md) for the spec grammar and
[data flow](./dataflow.md) for request sequencing.

## The submission contract (`ConfigIniParams`: 207 fields → 8)

`ConfigIniParams` holds job fields plus an `options` map. At submission, the map
is completed from the selected assembly's spec, defaults are applied, and
unknown or retired option ids are logged and omitted. Keyword option fields are
rejected so callers cannot silently lose a misspelled option.

The emitted `config.ini` is the compatibility oracle: tests compare it with
captured outputs for representative option selections. Form defaults and
submission defaults are tested independently, because both otherwise read the
same declaration.

## Form options

Config entries own options and their `form` blocks. `form_panels.py` owns panel
layout and generated allele-frequency trees. Allele-frequency code tables carry
the field code, label, and default so the form, config generator, and response
label decoder share one vocabulary.

`app/tests/form_panels.golden.json` captures served panels for representative
assemblies. Update it only after confirming an intentional form change.

## Results pagination

The workflow writes a BGZF virtual-offset page index beside the VCF. Unfiltered
requests use it to seek directly to a page. Outputs without the index use the
`bcftools` scan fallback. The index must be produced by the workflow, which
already streams every output record.

## Results filtering

Filters operate on CSQ entries. A record remains when at least one entry matches
all filters, and the response includes only matching entries. Filtered requests
scan the VCF because filtering invalidates page-index offsets; the scan retains
only the requested page window in memory.

Literal membership filters use a raw-line prefilter before splitting CSQ fields.
It must be a necessary condition: false positives are acceptable, but false
negatives would change results. Filter removal counts are returned for future
ordering work.

### Allele-frequency no-data semantics

Missing, empty, and non-numeric AF values are ignored during comparison. An
entry with no usable AF value currently fails the AF filter. Decide whether this
should remain the default or become an explicit user choice before changing the
frontend behaviour.

## Results-load performance

Parsing work is compiled once per VCF header. Plugin plans skip plugins whose
columns are absent and cache row-independent outputs. Results caches use file
identity so a regenerated output does not reuse stale metadata or a stale spec.

## Checking output against the submission

Submission writes three sidecars beside the VCF:

| Sidecar | Purpose |
| --- | --- |
| `parsing_spec.json` | Complete merged spec used to parse and display results. |
| `expected_columns.json` | CSQ columns expected from selected options. |
| `display_panels.json` | Form layout shown when the job was submitted. |

Results load these sidecars rather than the live spec. Missing expected CSQ
columns are logged; they do not currently fail a result request.

## Allele-frequency labels

Frequency plugin definitions describe their source, column pattern, and
population codes. The backend derives response metadata from the job's pinned
spec and decodes labels with the same form vocabulary. This prevents the client
from maintaining a second population-code map.

## The contract points

The request flow relies on these contracts:

| Point | Contract |
| --- | --- |
| C1 | Form options are derived from the assembled spec for the selected assembly. |
| C2 | Submitted options are completed and validated against that same spec. |
| C3 | Config lines and expected CSQ columns are derived from selected options. |
| C4 | The merged spec, expected columns, and display panels are pinned with the job. |
| C5 | The workflow writes the VCF and optional page index into the job output. |
| C6 | Results parse the VCF using the pinned merged spec. |
| C7 | Filter availability is gated by the VCF header and pinned expected columns. |
| C8 | The client renders display metadata supplied by the API. |

## Unspecced annotations

`uniprot`, `protein_matches`, `sift`, `polyphen`, and `colocated_variants` are
still typed result fields. Convert them to parsing specs only when representative
VCF data is available to validate the expected columns and output shape.

## Tests

Tests cover spec validation, config generation, form-panel snapshots, parsing,
display validation, filtering, sidecar loading, and page-index pagination. For
changes that replace code with data, test the externally visible output rather
than implementation details.

## Porting to ensembl-client

The client consumes form panels, result display metadata, filter metadata, and
option-help links from the API. Keep renderer primitives generic; a new option
should normally be a spec change rather than a client component.
