# dev-data-10k — scaled VEP results fixture

A drop-in replacement for `dev-data/`, holding **10,038 records / 155,589
consequence entries** instead of the 42-record sample. Generated from
`dev-data/output.vcf.gz` by `../../make_scaled_dev_data.py`.

| file | what it is |
|---|---|
| `input.vcf` | the submission — the same 10,038 variants, no CSQ |
| `output.vcf.gz` (+ `.csi`, `.tbi`) | the annotated results |
| `output.vcf.gz.pageidx.json` | BGZF page index — **19× faster paging, see below** |
| `parsing_spec.json`, `display_panels.json`, `expected_columns.json` | copied from `dev-data/`, unchanged |
| `manifest.json` | what was generated and how |

`results_meta.json` is deliberately absent: the backend writes it on first read
(`vcf_meta._get_vcf_meta`) and regenerates it when stale.

## Use it

The sidecars are resolved per-**directory** (`Path.with_name`), so point the
whole directory at the API rather than dropping a second VCF into `dev-data/`:

```bash
DEV_DATA_DIR=./dev-data-10k docker compose up
```

## Regenerate

```bash
python ../../make_scaled_dev_data.py --outdir /tmp/out --copies 239 --seed 1
```

Deterministic for a given `--seed`. `--copies N` gives `42 × N` records.

## Check it

```bash
python ../../check_scaled_dev_data.py output.vcf.gz input.vcf
```

Verifies sort order, contig bounds, SV/BND integrity, that SPDI and HGVSg track
each record's shifted POS, and that the annotation spread still matches the
source sample field-for-field. After a *real* pipeline run, the question is
narrower — use:

```bash
python ../../check_scaled_dev_data.py --roundtrip <pipeline-output>.vcf.gz input.vcf
```

## How it was built

Each of the 42 real records is a **template** replayed 239 times. A replay keeps
the template's REF/ALT, INFO keys and complete CSQ entry list verbatim, and
changes only:

- **POS**, shifted downstream per copy — and every coordinate derived from it:
  INFO `END`/`END2`, CSQ `SPDI` and `HGVSg`, and BND mate coordinates;
- a **format-preserving numeric jitter** on the scalar score fields, so filters
  see realistic value cardinality (`CADD_PHRED` 31 distinct values → 6,330)
  instead of 239 identical copies. Allele-frequency families share one factor
  per entry, so `grpmax ≥ every population AF` still holds.

Because each replay carries a whole real CSQ entry list, these are reproduced
*exactly*, not approximately: the per-record consequence-count distribution
(min 1, max 95, mean 15.5), the per-field fill rates across all 254 CSQ columns,
the consequence-term and biotype mix, and the SVTYPE mix
(DEL/DUP/INS/INV/BND, including 3 reciprocal BND mate pairs per copy).
Feature IDs stay unique within a record.

## Limitations — read before trusting a result

1. **Transcript-relative fields are not re-derived.** `EXON`, `INTRON`, `HGVSc`,
   `HGVSp`, `cDNA_position`, `CDS_position`, `Protein_position`, `Amino_acids`,
   `Codons`, `DISTANCE` and `NearestExonJB` are carried over verbatim. They stay
   mutually consistent *within* an entry, but a replayed variant is not
   biologically true at its new coordinate. This is a volume/shape fixture, not
   a correct call set.
2. **Gene cardinality is the sample's**, 43 symbols / 46 genes / 475
   transcripts, so each gene recurs ~239×. Real IDs were kept rather than minted
   so UI link-outs still resolve; the cost is that a `gene_symbol` filter
   returns a multiple of 239. Widening this needs a larger source sample.
3. **IDs repeat.** An rsID is replayed with its template (239× each), which
   preserves the ID-present/ID-absent mix. Match input to output on
   `(CHROM, POS, REF, ALT)`, never on ID. BND IDs are suffixed per copy so mate
   pairs stay identifiable.

## Measured on this fixture

```
page fetch (page 90, page_size 100)   0.29 s   with pageidx sidecar
                                      5.70 s   without  ← 19× slower
filtered scan, consequence=missense   1.04 s   3,585 records
filtered scan, gnomAD exomes AF≤0.01  2.27 s   4,063 records
peak RSS across the filter suite       227 MB
```

Note the first row: `dev-data/copy_remote.sh` fetches the sidecar as
`output.vcf.pageidx.json`, but `vcf_results.PAGE_INDEX_SUFFIX` expects
`output.vcf.gz.pageidx.json` — so in dev the seek path is silently off. Invisible
at 42 records; a 19× page-load regression here.
