"""The generic spec-driven `annotations` emitted on alleles and transcript
consequences (the additive go-flat wire format).

Checks the *wiring*: that _get_alt_allele_details drives the pinned parsing
spec's plugins through apply_plugin_spec and attaches the results at the right
scope. Since the go-flat cutover these are the only annotation data on the
response; apply_plugin_spec's own correctness is covered by
test_spec_interpreter.
"""

import os

from pydantic import FilePath

from app.vep.utils import vcf_results
from app.vep.utils.spec_interpreter import apply_plugin_spec
from app.vep.utils.spec_loader import (
    SPEC_SIDECAR_FILE,
    load_merged_spec,
    write_spec_sidecar,
)
from app.vep.utils.vcf_results import _gate_af_columns, _get_alt_allele_details

SPEC = load_merged_spec("human_grch38").parsing

# A CSQ header layout with structural columns plus one allele-scope frequency
# (gnomad_exomes, incl. a per-population column to exercise the pattern_map
# flat-frequency shape), and two transcript-scope plugins: a simple one (revel)
# and a custom whose rows are narrowed by gene (clinvar).
COLUMNS = [
    "Allele", "Feature_type", "Consequence", "Feature", "Gene", "BIOTYPE",
    "CANONICAL", "STRAND", "SYMBOL",
    "REVEL", "gnomAD_exomes_AF", "gnomAD_exomes_AF_nfe", "ClinVar_CLNSIG",
    "ClinVar_GENEINFO",
]
INDEX_MAP = {column: i for i, column in enumerate(COLUMNS)}
ROW = "|".join([
    "T", "Transcript", "missense_variant", "ENST001", "ENSG001", "protein_coding",
    "YES", "1", "BRCA2",
    "0.9", "0.01", "0.02", "Pathogenic", "BRCA2:675",
])
CSQ_VALUES = ROW.split("|")

# The same variant against a neighbouring gene's transcript: VEP repeats the
# custom's columns here too, but ClinVar's record is about BRCA2.
OTHER_GENE_ROW = "|".join([
    "T", "Transcript", "missense_variant", "ENST002", "ENSG002", "protein_coding",
    "", "1", "ZAR1L",
    "0.9", "0.01", "0.02", "Pathogenic", "BRCA2:675",
])


def _expected(plugin_name):
    return apply_plugin_spec(CSQ_VALUES, INDEX_MAP, SPEC.plugin(plugin_name))


def test_allele_scope_annotations_attached():
    allele = _get_alt_allele_details("A", "T", [ROW], INDEX_MAP, SPEC)
    by_plugin = {a.plugin: a for a in allele.annotations}

    assert by_plugin.keys() >= {"gnomad_exomes"}
    assert all(a.scope == "allele" for a in allele.annotations)
    assert by_plugin["gnomad_exomes"].data == _expected("gnomad_exomes")
    # ClinVar is about a gene, so it hangs off the consequence, not the allele.
    assert "clinvar" not in by_plugin
    # the flat frequency shape carries the per-population column
    assert by_plugin["gnomad_exomes"].data["populations"] == {"nfe": 0.02}


def test_transcript_scope_annotations_attached():
    allele = _get_alt_allele_details("A", "T", [ROW], INDEX_MAP, SPEC)
    consequence = allele.predicted_molecular_consequences[0]
    by_plugin = {a.plugin: a for a in consequence.annotations}

    assert by_plugin.keys() >= {"revel", "clinvar"}
    assert all(a.scope == "transcript" for a in consequence.annotations)
    assert by_plugin["revel"].data == _expected("revel")
    assert by_plugin["clinvar"].data == _expected("clinvar")


def test_clinvar_is_attached_only_to_the_gene_it_names():
    """VEP repeats a custom's columns on every CSQ row of the variant, so
    without narrowing ClinVar's record for one gene is served against every gene
    the variant touches -- 22:23834143 showed SMARCB1's classification under
    DERL3, whose transcripts merely overlap the position."""
    allele = _get_alt_allele_details("A", "T", [ROW, OTHER_GENE_ROW], INDEX_MAP, SPEC)
    by_gene = {
        c.gene_symbol: {a.plugin for a in c.annotations}
        for c in allele.predicted_molecular_consequences
    }
    assert "clinvar" in by_gene["BRCA2"]
    assert "clinvar" not in by_gene["ZAR1L"]
    # The neighbour keeps everything that really is about it.
    assert "revel" in by_gene["ZAR1L"]


def test_annotations_are_the_only_annotation_data():
    allele = _get_alt_allele_details("A", "T", [ROW], INDEX_MAP, SPEC)
    # What used to be the typed `clinvar` / `frequencies` fields now arrives
    # only as generic annotations, at allele scope.
    by_plugin = {a.plugin: a.data for a in allele.annotations}
    assert by_plugin["gnomad_exomes"]["overall"] == 0.01
    consequence = allele.predicted_molecular_consequences[0]
    by_consequence = {a.plugin: a.data for a in consequence.annotations}
    assert by_consequence["clinvar"]["significance"] == ["Pathogenic"]


def test_no_spec_means_no_generic_annotations():
    allele = _get_alt_allele_details("A", "T", [ROW], INDEX_MAP, None)
    assert allele.annotations == []
    assert allele.predicted_molecular_consequences[0].annotations == []
    # the envelope is unaffected by the absence of a spec
    assert allele.allele_sequence == "T"
    assert allele.predicted_molecular_consequences[0].gene_symbol == "BRCA2"


# --- AF-population emission gate ---------------------------------------------
# A full-cache VCF carries every ancestry; a job that selected only some AF
# populations must still show only those. The parser's pattern_map reads every
# column present, so the gate (in _with_display_panels) trims the served
# annotation to the pinned expected columns.

_GATE_COLUMNS = [
    "Allele", "Feature_type", "Consequence", "Feature", "Gene", "BIOTYPE",
    "CANONICAL", "STRAND", "SYMBOL",
    "gnomAD_exomes_AF",
    "gnomAD_exomes_AF_nfe", "gnomAD_exomes_AF_eas", "gnomAD_exomes_AF_afr",
]
_GATE_INDEX = {column: i for i, column in enumerate(_GATE_COLUMNS)}
_GATE_ROW = "|".join([
    "T", "Transcript", "missense_variant", "ENST001", "ENSG001", "protein_coding",
    "YES", "1", "BRCA2",
    "0.01", "0.02", "0.03", "0.04",
])


def test_af_columns_gated_to_selected_populations_only():
    allele = _get_alt_allele_details("A", "T", [_GATE_ROW], _GATE_INDEX, SPEC)
    gnomad = {a.plugin: a for a in allele.annotations}["gnomad_exomes"]
    # every ancestry in the (full-cache) VCF is parsed before gating
    assert set(gnomad.data["populations"]) == {"nfe", "eas", "afr"}
    assert gnomad.data["overall"] == 0.01

    # the submission selected only the nfe population column — not the overall
    _gate_af_columns([allele], SPEC, {"gnomAD_exomes_AF_nfe"})

    assert gnomad.data["populations"] == {"nfe": 0.02}
    # the overall's column wasn't selected, so it is gated too (no "All" row)
    assert gnomad.data["overall"] is None


def test_af_columns_keeps_the_overall_when_its_column_is_selected():
    allele = _get_alt_allele_details("A", "T", [_GATE_ROW], _GATE_INDEX, SPEC)
    gnomad = {a.plugin: a for a in allele.annotations}["gnomad_exomes"]
    _gate_af_columns(
        [allele], SPEC, {"gnomAD_exomes_AF", "gnomAD_exomes_AF_eas"}
    )
    assert gnomad.data["overall"] == 0.01
    assert gnomad.data["populations"] == {"eas": 0.03}


def test_af_columns_gate_is_a_no_op_without_a_spec():
    allele = _get_alt_allele_details("A", "T", [_GATE_ROW], _GATE_INDEX, SPEC)
    gnomad = {a.plugin: a for a in allele.annotations}["gnomad_exomes"]
    _gate_af_columns([allele], None, {"gnomAD_exomes_AF_nfe"})
    assert set(gnomad.data["populations"]) == {"nfe", "eas", "afr"}
    assert gnomad.data["overall"] == 0.01


# --- the pinned spec is cached per file ---------------------------------------


def _pin(tmp_path, spec):
    """A stand-in results VCF with `spec` pinned beside it."""
    write_spec_sidecar(tmp_path, spec)
    path = tmp_path / "input_VEP.vcf.gz"
    path.write_bytes(b"")
    return FilePath(path)


def test_the_pinned_spec_is_read_once_per_file(tmp_path, monkeypatch):
    """Reading it means parsing and validating a large JSON document, and a
    single request goes through this twice (`_load_pinned_spec` calls it) before
    paging asks again for every page."""
    vcf_results.clear_spec_cache()
    merged = load_merged_spec("human_grch38")
    path = _pin(tmp_path, merged)

    reads = []
    real = vcf_results.load_spec_sidecar
    monkeypatch.setattr(
        vcf_results, "load_spec_sidecar",
        lambda p: (reads.append(p), real(p))[1],
    )

    first = vcf_results._load_pinned_merged_spec(path)
    again = vcf_results._load_pinned_merged_spec(path)
    parsing = vcf_results._load_pinned_spec(path)

    assert len(reads) == 1, f"sidecar read {len(reads)} times, expected 1"
    assert again is first
    assert parsing is first.parsing


def test_a_rewritten_output_is_never_served_a_stale_spec(tmp_path, monkeypatch):
    """The key is the file's identity *now*. The dev harness rewrites one fixed
    path, so a cache that missed a rewrite would serve annotations parsed to the
    wrong shape — the whole reason the scan cache keys the same way."""
    vcf_results.clear_spec_cache()
    merged = load_merged_spec("human_grch38")
    path = _pin(tmp_path, merged)
    assert vcf_results._load_pinned_merged_spec(path) is not None

    # The job is regenerated: same path, no sidecar this time.
    (tmp_path / SPEC_SIDECAR_FILE).unlink()
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    assert vcf_results._load_pinned_merged_spec(path) is None


def test_an_unreadable_sidecar_is_not_cached(tmp_path):
    """A fault that can be repaired without the output changing: caching the
    failure would keep serving no annotations until the file was touched."""
    vcf_results.clear_spec_cache()
    (tmp_path / SPEC_SIDECAR_FILE).write_text("{ not json")
    path = tmp_path / "input_VEP.vcf.gz"
    path.write_bytes(b"")
    path = FilePath(path)

    assert vcf_results._load_pinned_merged_spec(path) is None
    write_spec_sidecar(tmp_path, load_merged_spec("human_grch38"))
    assert vcf_results._load_pinned_merged_spec(path) is not None
