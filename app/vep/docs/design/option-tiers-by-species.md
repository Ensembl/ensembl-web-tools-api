# Option tiers by species

> **Snapshot of the shipped state, 2026-07-26.** Derived from the spec files,
> not written by hand — where this and the code disagree, **the code is
> authoritative**. Regenerate with the snippet in [§6](#6-regenerating-this-document)
> after adding a species or an option.
>
> Sources: `vep/specs/base.json`, `vep/specs/species_annotations.json`,
> `vep/specs/human_grch37.json`, `vep/specs/human_grch38.json`.

The tiers **nest strictly**: base ⊂ GRCh37 ⊂ GRCh38, with no entry dropping out
along the way (asserted by the regeneration snippet). The one exception is
CADD — see [§4](#4-tier-3--cadd--3-species).

| Tier | Who gets it | Entries |
|---|---|---|
| 0 | every species | 8 |
| 1 | 50 table species | +1 (GO) |
| 2 | 15 of those | +1 (Phenotypes) |
| 3 | 3 of those | +1 (CADD) |
| 4 | human GRCh37 | 26 |
| 5 | human GRCh38 | 35 |

## 1. Tier 0 — ubiquitous, every species

The eight entries in `base.json`. Offered to any genome with a GFF+FASTA,
including assemblies in no table at all: `resolve_merged_spec` falls back to
this set rather than raising, because **gating decides which extra options a
species is offered, never whether it can run**.

| Panel | Options |
|---|---|
| Variant representations | HGVS, SPDI, *(HGVSg — wired but hidden pending chromosome synonyms)* |
| Genes & transcripts | Up/downstream distance, Distance to TSS, Nearest gene, Nearest exon junction boundary |
| Protein & functional | Protein ID |

These need no data file beyond the genome itself, which is what makes them
universal.

## 2. Tier 1 — + Gene Ontology · 50 species

Every row in `species_annotations.json`. GO needs one per-species file
(`GO.pm_<production_name>_116.gff.gz`), so it is the widest data-backed option.

The 34 species at this tier and no higher:

`anas_platyrhynchos`, `anas_platyrhynchos_platyrhynchos`, `bison_bison_bison`,
`bos_grunniens`, `callithrix_jacchus`, `camelus_dromedarius`, `cavia_porcellus`,
`chlorocebus_sabaeus`, `ciona_intestinalis`, `clupea_harengus`,
`coturnix_japonica`, `dicentrarchus_labrax`, `drosophila_melanogaster`,
`ficedula_albicollis`, `macaca_fascicularis`, `macaca_mulatta`,
`manacus_vitellinus`, `microcebus_murinus`, `microtus_ochrogaster`,
`neovison_vison`, `nomascus_leucogenys`, `oncorhynchus_mykiss`,
`oreochromis_niloticus`, `ornithorhynchus_anatinus`, `oryctolagus_cuniculus`,
`pan_troglodytes`, `parus_major`, `peromyscus_maniculatus_bairdii`,
`pongo_abelii`, `saccharomyces_cerevisiae`, `salmo_salar`, `sander_lucioperca`,
`seriola_dumerili`, `taeniopygia_guttata`

## 3. Tier 2 — + Phenotypes · 15 species

`bos_taurus`, `canis_lupus_familiaris`, `canis_lupus_familiarisboxer`,
`capra_hircus`, `danio_rerio`, `equus_caballus`, `felis_catus`,
`felis_catus_abyssinian`, `gallus_gallus`, `gallus_gallus_gca000002315v5`,
`mus_musculus`, `ovis_aries`, `ovis_aries_texel`, `rattus_norvegicus`,
`sus_scrofa`

## 4. Tier 3 — + CADD · 3 species

**Not a clean superset of tier 2.** Chicken red junglefowl
(`gallus_gallus_gca000002315v5`, GRCg6a) and pig (`sus_scrofa`) have all three
datasets; **turkey (`meleagris_gallopavo`) has GO + CADD but no Phenotypes
file**. So CADD is a sibling of Phenotypes, not a step above it — the table
expresses per-dataset availability, not a ladder.

Unlike human, these species get a single `snv=` file (no indels), and pig and
chicken never score `CADD_RAW` — it arrives as the VCF null `.`, which reads as
absent, so the RAW row drops itself. Both columns are still emitted and still
expected.

## 5. Tiers 4 & 5 — human

Human's GO, Phenotypes and CADD come from its **own spec documents, not the
species table** (its GO file carries an assembly suffix the table's filename
rule does not produce).

### 5.1 GRCh37 — 26 entries

Base + 18:

| Panel | Adds |
|---|---|
| Pathogenicity predictions | CADD, REVEL, SpliceAI, AlphaMissense, ClinPred |
| Genes & transcripts | Gene Ontology, NMD, UTRAnnotator |
| Conservation & constraint | Dosage sensitivity, LOEUF |
| Variant associations | Phenotypes, Geno2MP, ClinVar *(master option: Short variants + Structural variants sub-options)* |
| Protein & functional | IntAct |
| Allele frequencies | gnomAD Exomes v4.1.1, gnomAD Genomes v4.1.1, gnomAD SV v4.1 |

### 5.2 GRCh38 — 35 entries

Everything in GRCh37, plus 9 GRCh38-only:

| Panel | Adds |
|---|---|
| Allele frequencies | NIH All of Us, gnomAD CNV v4.1 |
| Pathogenicity predictions | EVE & popEVE |
| Protein & functional | MaveDB, mutfunc, ProtVar |
| Variant associations | OpenTargets |
| Genes & transcripts | RiboSeqORFs |
| Regulatory | GENCODE promoter |

## 6. The shape worth noticing

Tiers 1–3 are **one table** where a species is a row and a dataset is a flag;
tiers 4–5 are **hand-written spec documents**. That asymmetry is why adding a
species is a one-line change while adding a new *kind* of data to human is not —
and why turkey could break the nesting without needing anything special to
express it.

Adding a species means one row: `assembly`, `production_name`,
`species_taxonomy_id`, `datasets` — plus `files` when the file name does not
follow from the production name, as CADD's do not. `form_panels` reads the same
table, so the options offered and the config submitted cannot drift.

**Resolve the assembly name from the metadata API**
(`/api/metadata/genome/{accession}/explain`), never from classic Ensembl REST:
the two disagree for several species, and a submission carries the metadata
API's name. A wrong name fails silently — the species drops to tier 0 with no
error.

## 7. Regenerating this document

```python
# from app/, with PYTHONPATH=. and the py3.11 venv
from vep.utils.spec_loader import load_merged_spec, _species_annotations
from vep.form_panels import get_visible_panels
from collections import Counter

ids = lambda n: [e.id for e in load_merged_spec(n).config.entries]
base, g37, g38 = ids("base"), ids("human_grch37"), ids("human_grch38")
assert set(base) <= set(g37) <= set(g38), "tiers no longer nest"

for combo, n in Counter(
    tuple(sorted(r["datasets"])) for r in _species_annotations()["species"]
).most_common():
    print(n, "+".join(combo))

# labels/panels for a tier's ids
panels = get_visible_panels(species_taxonomy_id="9606", assembly_name="GRCh38.p14")
print({o["id"]: (p["id"], o.get("label")) for p in panels for o in p.get("options", [])})
```

An option showing as `(hidden)` is either deliberately hidden (HGVSg) or a
**sub-option** rather than a top-level one (`clinvar_short`, `clinvar_sv` sit
under the `clinvar` master).

Related: `merged-annotation-spec.md` (the spec design),
`adding-an-annotation-plugin.md` (the end-to-end recipe).
