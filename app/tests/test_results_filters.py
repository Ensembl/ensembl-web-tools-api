"""Tests for server-side results filtering (app/vep/utils/results_filters.py and
the filtered scan path in vcf_results.get_results_from_path).

Filtered requests can't use the BGZF page index, so they scan the whole file
with gzip.open — meaning a plain gzip VCF fixture is enough here (no BGZF/page
index needed).
"""

import gzip
import json

import pytest
from pydantic import FilePath

from app.vep.utils import results_filters as rf
from app.vep.utils import vcf_results
from app.vep.utils.vcf_results import get_results_from_path
from vep.models.display_panels_model import to_display_panels
from app.vep.utils.spec_loader import (
    load_merged_spec,
    write_display_panels_sidecar,
    write_expected_columns_sidecar,
    write_spec_sidecar,
)
from app.vep.models import vcf_results_model as model

MERGED_SPEC = load_merged_spec("human_grch38")
PARSING_SPEC = MERGED_SPEC.parsing
DISPLAY = MERGED_SPEC.display_payload()
DISPLAY_PANELS = to_display_panels(
    [{"id": "general", "label": "General", "options": []}]
)

CSQ_DESC = (
    "Consequence annotations from Ensembl VEP. Format: "
    "Allele|Consequence|IMPACT|SYMBOL|Gene|Feature_type|Feature|BIOTYPE"
)

# CSQ column -> index for the format above (Consequence is column 1).
INDEX_MAP = {
    name: i
    for i, name in enumerate(
        "Allele Consequence IMPACT SYMBOL Gene Feature_type Feature BIOTYPE".split()
    )
}

# A wider layout that also carries the canonical / MANE / GENCODE primary columns,
# for group tests.
GROUP_COLUMNS = (
    "Allele Consequence Feature CANONICAL MANE_SELECT MANE_PLUS_CLINICAL "
    "GENCODE_PRIMARY".split()
)
GROUP_INDEX_MAP = {name: i for i, name in enumerate(GROUP_COLUMNS)}


def _group_entry(
    feature: str,
    canonical: str,
    mane_select: str,
    mane_plus: str,
    gencode_primary: str = "",
) -> str:
    return "|".join(
        ["T", "missense_variant", feature, canonical, mane_select, mane_plus,
         gencode_primary]
    )


def _group_record(pos: int, entries: list[str]) -> str:
    return f"chr1\t{100 + pos}\tid_{pos:02d}\tC\tT\t.\t.\tCSQ={','.join(entries)}\n"


def _record(pos: int, consequences: list[str]) -> str:
    """One VCF data line whose CSQ carries one entry per given consequence."""
    entries = ",".join(
        f"T|{cons}|MODERATE|GENE{pos}|ENSG{pos}|Transcript|ENST{pos}|protein_coding"
        for cons in consequences
    )
    return f"chr1\t{100 + pos}\tid_{pos:02d}\tC\tT\t.\t.\tCSQ={entries}\n"


def _write_vcf(path, records: list[str]) -> str:
    text = (
        "##fileformat=VCFv4.2\n"
        f'##INFO=<ID=CSQ,Number=.,Type=String,Description="{CSQ_DESC}">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        + "".join(records)
    )
    vcf_path = path / "results.vcf.gz"
    with gzip.open(vcf_path, "wt") as handle:
        handle.write(text)
    write_spec_sidecar(path, MERGED_SPEC)
    write_expected_columns_sidecar(path, set())
    write_display_panels_sidecar(
        path,
        DISPLAY_PANELS,
    )
    return str(vcf_path)


def _consequence_filter(*values: str) -> rf.ResultsFilter:
    return rf.ResultsFilter(
        field=rf.CONSEQUENCE_FIELD, operator=rf.OPERATOR_IN, values=list(values)
    )


def _transcript_record(pos: int, features: list[tuple[str, str]]) -> str:
    """A VCF data line with one CSQ entry per (transcript_feature, consequence)."""
    entries = ",".join(
        f"T|{cons}|MODERATE|GENE|ENSG|Transcript|{feature}|protein_coding"
        for feature, cons in features
    )
    return f"chr1\t{100 + pos}\tid_{pos:02d}\tC\tT\t.\t.\tCSQ={entries}\n"


def _transcript_filter(*values: str) -> rf.ResultsFilter:
    return rf.ResultsFilter(
        field=rf.TRANSCRIPT_FIELD, operator=rf.OPERATOR_IN, values=list(values)
    )


# --- parse_filters -----------------------------------------------------------


def test_parse_filters_empty_returns_none_list():
    assert rf.parse_filters(None) == []
    assert rf.parse_filters("") == []


def test_parse_filters_valid():
    parsed = rf.parse_filters(
        '[{"field": "consequence", "operator": "in", "values": ["missense_variant"]}]'
    )
    assert len(parsed) == 1
    assert parsed[0].field == "consequence"
    assert parsed[0].values == ["missense_variant"]


def test_parse_filters_bad_json_raises():
    with pytest.raises(rf.FilterError):
        rf.parse_filters("not json")


def test_parse_filters_non_array_raises():
    with pytest.raises(rf.FilterError):
        rf.parse_filters('{"field": "consequence"}')


# --- extract_csq_entries -----------------------------------------------------


def test_extract_csq_entries_splits_entries_and_subfields():
    line = _record(1, ["missense_variant", "synonymous_variant"])
    entries = rf.extract_csq_entries(line)
    assert len(entries) == 2
    assert entries[0][INDEX_MAP["Consequence"]] == "missense_variant"
    assert entries[1][INDEX_MAP["Consequence"]] == "synonymous_variant"


def test_extract_csq_entries_no_csq():
    assert rf.extract_csq_entries("chr1\t1\t.\tC\tT\t.\t.\tAC=1\n") == []


# --- compile_filters + pipeline ----------------------------------------------


def test_compile_rejects_unknown_field():
    with pytest.raises(rf.FilterError):
        rf.compile_filters(
            [rf.ResultsFilter(field="nonsense", operator="in", values=["x"])],
            INDEX_MAP,
        )


def test_compile_rejects_unknown_operator():
    with pytest.raises(rf.FilterError):
        rf.compile_filters(
            [rf.ResultsFilter(field="consequence", operator="gt", values=["x"])],
            INDEX_MAP,
        )


def test_pipeline_keeps_matching_and_counts_removed():
    lines = [
        _record(1, ["missense_variant"]),
        _record(2, ["synonymous_variant"]),
        _record(3, ["intron_variant"]),
        _record(4, ["missense_variant"]),
    ]
    compiled = rf.compile_filters([_consequence_filter("missense_variant")], INDEX_MAP)
    kept, stats = rf.apply_filter_pipeline(lines, compiled)

    assert len(kept) == 2
    assert kept == [lines[0], lines[3]]
    assert stats[0].field == "consequence"
    assert stats[0].removed == 2


def test_pipeline_prunes_nonmatching_entries():
    lines = [
        # kept, pruned to just the synonymous entry
        _record(1, ["missense_variant", "synonymous_variant"]),
        # kept intact: its single &-joined entry intersects the selection
        _record(2, ["splice_region_variant&intron_variant"]),
        # removed: neither term selected
        _record(3, ["upstream_gene_variant"]),
    ]
    compiled = rf.compile_filters(
        [_consequence_filter("synonymous_variant", "intron_variant")], INDEX_MAP
    )
    kept, stats = rf.apply_filter_pipeline(lines, compiled)

    assert len(kept) == 2
    ci = INDEX_MAP["Consequence"]
    # record 1 lost its non-matching missense entry
    assert [e[ci] for e in rf.extract_csq_entries(kept[0])] == ["synonymous_variant"]
    # record 2 kept as-is
    assert [e[ci] for e in rf.extract_csq_entries(kept[1])] == [
        "splice_region_variant&intron_variant"
    ]
    assert stats[0].removed == 1


# --- filter_records (streaming, page-bounded) --------------------------------


def test_filter_records_retains_only_the_page_window():
    lines = [_record(i, ["missense_variant"]) for i in range(1, 8)]  # 7 matches
    compiled = rf.compile_filters([_consequence_filter("missense_variant")], INDEX_MAP)

    outcome = rf.filter_records(lines, compiled, start=2, count=3)

    # Full counts are tallied regardless of which window is asked for...
    assert outcome.scanned_total == 7
    assert outcome.matched_total == 7
    # ...but only the [2, 5) slice of survivors is materialised.
    assert outcome.page == [lines[2], lines[3], lines[4]]
    assert outcome.stats[0].removed == 0


def test_filter_records_counts_all_scanned_including_dropped():
    lines = [
        _record(1, ["missense_variant"]),
        _record(2, ["synonymous_variant"]),  # dropped
        _record(3, ["missense_variant"]),
    ]
    compiled = rf.compile_filters([_consequence_filter("missense_variant")], INDEX_MAP)

    outcome = rf.filter_records(lines, compiled, start=0, count=10)

    assert outcome.scanned_total == 3
    assert outcome.matched_total == 2
    assert outcome.page == [lines[0], lines[2]]
    assert outcome.stats[0].removed == 1


def test_filter_records_page_stays_bounded_below_match_count():
    # 100 matches but a page of 5: only 5 lines are ever held, and a lazy
    # iterator source is consumed without materialising the input.
    lines = [_record(i, ["missense_variant"]) for i in range(1, 101)]
    compiled = rf.compile_filters([_consequence_filter("missense_variant")], INDEX_MAP)

    outcome = rf.filter_records(iter(lines), compiled, start=0, count=5)

    assert outcome.matched_total == 100
    assert len(outcome.page) == 5


def test_apply_filter_pipeline_wrapper_keeps_every_survivor():
    lines = [
        _record(1, ["missense_variant"]),
        _record(2, ["intron_variant"]),
        _record(3, ["missense_variant"]),
    ]
    compiled = rf.compile_filters([_consequence_filter("missense_variant")], INDEX_MAP)

    kept, stats = rf.apply_filter_pipeline(lines, compiled)

    assert kept == [lines[0], lines[2]]
    assert stats[0].removed == 1


# --- raw-line pre-filter (fast reject before splitting the CSQ) ---------------


def test_membership_filters_carry_a_line_prefilter_gene_symbol_does_not():
    cases = [
        (_consequence_filter("missense_variant"), True),
        (_transcript_filter("ENST00000341065"), True),
        (rf.ResultsFilter(field=rf.GENE_ID_FIELD, operator=rf.OPERATOR_IN, values=["ENSG001"]), True),
        # Gene symbol matching is case-insensitive, so a case-sensitive substring
        # test could false-negative — no prefilter.
        (rf.ResultsFilter(field=rf.GENE_SYMBOL_FIELD, operator=rf.OPERATOR_IN, values=["BRCA1"]), False),
    ]
    for filt, has_prefilter in cases:
        (cf,) = rf.compile_filters([filt], INDEX_MAP)
        assert (cf.line_prefilter is not None) is has_prefilter


def test_prefilter_substring_false_positive_is_still_excluded_by_exact_check():
    # The selected term appears in the line only as the SYMBOL, not as a
    # Consequence: the cheap substring prefilter admits the line, but the exact
    # per-entry check must still drop it (the prefilter is necessary, not sufficient).
    line = (
        "chr1\t100\tv\tC\tT\t.\t.\t"
        "CSQ=T|synonymous_variant|MODERATE|missense_variant|ENSG|Transcript|ENST|protein_coding\n"
    )
    compiled = rf.compile_filters([_consequence_filter("missense_variant")], INDEX_MAP)

    assert compiled[0].line_prefilter(line) is True  # prefilter alone would admit it
    outcome = rf.filter_records([line], compiled)
    assert outcome.matched_total == 0  # ...but the exact check drops it
    assert outcome.stats[0].removed == 1


def test_prefilter_rejects_without_error_when_no_token_present():
    lines = [_record(1, ["synonymous_variant"]), _record(2, ["intron_variant"])]
    compiled = rf.compile_filters([_consequence_filter("missense_variant")], INDEX_MAP)
    outcome = rf.filter_records(lines, compiled)
    assert outcome.matched_total == 0
    assert outcome.scanned_total == 2
    assert outcome.stats[0].removed == 2


def test_transcript_group_filter_has_no_prefilter():
    # Transcript-group tests read CANONICAL/MANE columns, not literal values.
    (cf,) = rf.compile_filters([_transcript_group_filter("canonical")], GROUP_INDEX_MAP)
    assert cf.line_prefilter is None


def test_transcript_filter_matches_ignoring_version():
    lines = [
        _transcript_record(
            1, [("ENST00000341065.8", "missense_variant"), ("ENST00000999.2", "intron_variant")]
        ),
        _transcript_record(2, [("ENST00000111.1", "missense_variant")]),
    ]
    fi = INDEX_MAP["Feature"]
    # user supplies the id without a version; the file has versioned ids
    compiled = rf.compile_filters([_transcript_filter("ENST00000341065")], INDEX_MAP)
    kept, stats = rf.apply_filter_pipeline(lines, compiled)

    assert len(kept) == 1
    kept_features = [e[fi] for e in rf.extract_csq_entries(kept[0])]
    # only the matching transcript survives; the other transcript is pruned
    assert kept_features == ["ENST00000341065.8"]
    assert stats[0].removed == 1


def test_transcript_filter_matches_with_version_supplied():
    lines = [_transcript_record(1, [("ENST00000341065.8", "missense_variant")])]
    # a versioned id supplied by the user still matches (version ignored)
    compiled = rf.compile_filters([_transcript_filter("ENST00000341065.3")], INDEX_MAP)
    kept, _ = rf.apply_filter_pipeline(lines, compiled)
    assert len(kept) == 1


def test_consequence_and_transcript_combined():
    # transcript A is missense, transcript B (same variant) is intron.
    lines = [
        _transcript_record(
            1,
            [
                ("ENST_A.1", "missense_variant"),
                ("ENST_B.1", "intron_variant"),
            ],
        )
    ]
    fi = INDEX_MAP["Feature"]
    # consequence=missense AND transcript in {A, B}: only A satisfies both
    compiled = rf.compile_filters(
        [_consequence_filter("missense_variant"), _transcript_filter("ENST_A", "ENST_B")],
        INDEX_MAP,
    )
    kept, _ = rf.apply_filter_pipeline(lines, compiled)
    assert len(kept) == 1
    assert [e[fi] for e in rf.extract_csq_entries(kept[0])] == ["ENST_A.1"]


def _gene_record(pos: int, genes: list[tuple[str, str]]) -> str:
    """A VCF data line with one CSQ entry per (SYMBOL, Gene) pair."""
    entries = ",".join(
        f"T|missense_variant|MODERATE|{symbol}|{gene_id}|Transcript|ENST_{i}|protein_coding"
        for i, (symbol, gene_id) in enumerate(genes)
    )
    return f"chr1\t{100 + pos}\tid_{pos:02d}\tC\tT\t.\t.\tCSQ={entries}\n"


def test_gene_symbol_filter_case_insensitive_and_prunes():
    lines = [
        _gene_record(1, [("TP53", "ENSG00000141510"), ("BRCA1", "ENSG00000012048")]),
        _gene_record(2, [("EGFR", "ENSG00000146648")]),
    ]
    si = INDEX_MAP["SYMBOL"]
    # lower-case query still matches TP53
    compiled = rf.compile_filters(
        [rf.ResultsFilter(field=rf.GENE_SYMBOL_FIELD, operator=rf.OPERATOR_IN, values=["tp53"])],
        INDEX_MAP,
    )
    kept, stats = rf.apply_filter_pipeline(lines, compiled)

    assert len(kept) == 1
    # only the TP53 entry survives; the BRCA1 entry on the same record is pruned
    assert [e[si] for e in rf.extract_csq_entries(kept[0])] == ["TP53"]
    assert stats[0].removed == 1


def test_gene_id_filter_version_insensitive():
    lines = [
        _gene_record(1, [("TP53", "ENSG00000141510.17")]),
        _gene_record(2, [("EGFR", "ENSG00000146648")]),
    ]
    compiled = rf.compile_filters(
        [rf.ResultsFilter(field=rf.GENE_ID_FIELD, operator=rf.OPERATOR_IN, values=["ENSG00000141510"])],
        INDEX_MAP,
    )
    kept, _ = rf.apply_filter_pipeline(lines, compiled)
    assert len(kept) == 1
    gi = INDEX_MAP["Gene"]
    assert [e[gi] for e in rf.extract_csq_entries(kept[0])] == ["ENSG00000141510.17"]


def _transcript_group_filter(*values: str) -> rf.ResultsFilter:
    return rf.ResultsFilter(
        field=rf.TRANSCRIPT_GROUP_FIELD, operator=rf.OPERATOR_IN, values=list(values)
    )


def test_transcript_group_canonical():
    lines = [
        _group_record(
            1,
            [
                _group_entry("ENST_A", "YES", "", ""),  # canonical
                _group_entry("ENST_B", "", "", ""),  # neither
            ],
        )
    ]
    fi = GROUP_INDEX_MAP["Feature"]
    compiled = rf.compile_filters([_transcript_group_filter("canonical")], GROUP_INDEX_MAP)
    kept, _ = rf.apply_filter_pipeline(lines, compiled)
    assert len(kept) == 1
    assert [e[fi] for e in rf.extract_csq_entries(kept[0])] == ["ENST_A"]


def test_transcript_group_mane_any_of():
    lines = [
        _group_record(
            1,
            [
                _group_entry("ENST_A", "", "NM_1.1", ""),  # MANE Select (refseq present)
                _group_entry("ENST_B", "YES", "", ""),  # canonical only
                _group_entry("ENST_C", "", "", "NM_2.1"),  # MANE Plus Clinical
            ],
        )
    ]
    fi = GROUP_INDEX_MAP["Feature"]
    # select the two MANE groups; canonical-only transcript B is pruned
    compiled = rf.compile_filters(
        [_transcript_group_filter("mane_select", "mane_plus_clinical")], GROUP_INDEX_MAP
    )
    kept, _ = rf.apply_filter_pipeline(lines, compiled)
    assert len(kept) == 1
    assert [e[fi] for e in rf.extract_csq_entries(kept[0])] == ["ENST_A", "ENST_C"]


def test_transcript_group_gencode_primary():
    lines = [
        _group_record(
            1,
            [
                _group_entry("ENST_A", "", "", "", "1"),  # GENCODE primary
                _group_entry("ENST_B", "YES", "", "", ""),  # canonical only
            ],
        )
    ]
    fi = GROUP_INDEX_MAP["Feature"]
    compiled = rf.compile_filters(
        [_transcript_group_filter("gencode_primary")], GROUP_INDEX_MAP
    )
    kept, _ = rf.apply_filter_pipeline(lines, compiled)
    assert len(kept) == 1
    assert [e[fi] for e in rf.extract_csq_entries(kept[0])] == ["ENST_A"]


def test_transcript_group_rejects_unknown_group():
    with pytest.raises(rf.FilterError):
        rf.compile_filters([_transcript_group_filter("nonsense")], GROUP_INDEX_MAP)


# --- allele frequency ---------------------------------------------------------

AF_COLUMNS = (
    "Allele Consequence Feature "
    "gnomAD_exomes_AF gnomAD_exomes_AF_nfe AoU_gvs_all_af AoU_gvs_max_subpop"
).split()
AF_INDEX_MAP = {name: i for i, name in enumerate(AF_COLUMNS)}


def _af_entry(exomes: str, nfe: str, aou: str) -> str:
    return "|".join(["T", "missense_variant", "ENST_1", exomes, nfe, aou, "eur"])


def _af_record(pos: int, entries: list[str]) -> str:
    return f"chr1\t{100 + pos}\tid_{pos:02d}\tC\tT\t.\t.\tCSQ={','.join(entries)}\n"


def _af_filter(operator, threshold, match="any", values=None) -> rf.ResultsFilter:
    return rf.ResultsFilter(
        field=rf.ALLELE_FREQUENCY_FIELD,
        operator=operator,
        values=values or [],
        threshold=threshold,
        match=match,
    )


def test_af_columns_discovery_excludes_subpop_label():
    assert rf.af_columns(AF_INDEX_MAP, PARSING_SPEC) == [
        "gnomAD_exomes_AF",
        "gnomAD_exomes_AF_nfe",
        "AoU_gvs_all_af",
    ]


def test_af_source_descriptor():
    # Each descriptor carries a decoded population `label` (from form_panels): the
    # overall AF is "All", a compound gnomAD code decodes to its form label.
    def descriptor(column):
        return rf.af_source_descriptor(column, PARSING_SPEC)
    assert descriptor("gnomAD_exomes_AF") == {
        "key": "gnomAD_exomes_AF",
        "source": "gnomad_exomes",
        "population": "",
        "label": "All",
    }
    assert descriptor("gnomAD_genomes_AF_grpmax") == {
        "key": "gnomAD_genomes_AF_grpmax",
        "source": "gnomad_genomes",
        "population": "grpmax",
        "label": "Maximum across all groups",
    }
    assert descriptor("AoU_gvs_all_af") == {
        "key": "AoU_gvs_all_af",
        "source": "all_of_us",
        "population": "",
        "label": "All",
    }
    assert descriptor("AoU_gvs_afr_af")["population"] == "afr"
    assert descriptor("AoU_gvs_afr_af")["label"] == "African"
    assert descriptor("gnomAD_exomes_AF_nfe_XX")["label"] == (
        "Non-Finnish European · XX"
    )
    # gnomAD SV: the AF columns are AF sources; the SV id / SVTYPE columns are not.
    assert descriptor("gnomAD_SV_AF") == {
        "key": "gnomAD_SV_AF",
        "source": "gnomad_sv",
        "population": "",
        "label": "All",
    }
    assert descriptor("gnomAD_SV_AF_rmi")["label"] == "Remaining"
    assert descriptor("gnomAD_SV") is None
    assert descriptor("gnomAD_SV_SVTYPE") is None
    # gnomAD CNV: sample frequencies (SF prefix), "remaining" spelled out.
    assert descriptor("gnomAD_CNV_SF") == {
        "key": "gnomAD_CNV_SF",
        "source": "gnomad_cnv",
        "population": "",
        "label": "All",
    }
    assert descriptor("gnomAD_CNV_SF_remaining")["label"] == "Remaining"
    assert descriptor("gnomAD_CNV") is None
    assert descriptor("SYMBOL") is None


def test_af_source_descriptor_grch37_v2_grammar():
    # gnomAD v2 (GRCh37): the population code is the whole field after the source
    # prefix (subset included) — the same key the parse stores it under — and
    # decodes to a compound label.
    spec = load_merged_spec("human_grch37").parsing
    assert rf.af_source_descriptor("gnomAD_exomes_controls_AF_afr_male", spec) == {
        "key": "gnomAD_exomes_controls_AF_afr_male",
        "source": "gnomad_exomes",
        "population": "controls_AF_afr_male",
        "label": "African & African-American · XY · Controls",
    }
    assert rf.af_source_descriptor("gnomAD_exomes_AF", spec)["population"] == ""
    assert rf.af_source_descriptor("gnomAD_exomes_AF_nfe_seu", spec)["label"] == (
        "Non-Finnish European › Southern European"
    )
    assert rf.af_source_descriptor("gnomAD_exomes_AF_popmax", spec)["label"] == (
        "Maximum across populations"
    )
    # CNV / All of Us aren't in the GRCh37 spec, so their columns are unrecognised.
    assert rf.af_source_descriptor("gnomAD_CNV_SF", spec) is None


def test_af_source_descriptor_grch37_sv_v2_prefix_grammar():
    # gnomAD SV v2 (GRCh37) populations are PREFIX-named (`gnomAD_SV_AFR_AF`, not
    # v4's suffix `gnomAD_SV_AF_afr`); the population code is the bare uppercase
    # continental code, matching the parse key.
    spec = load_merged_spec("human_grch37").parsing
    assert rf.af_source_descriptor("gnomAD_SV_AFR_AF", spec) == {
        "key": "gnomAD_SV_AFR_AF",
        "source": "gnomad_sv",
        "population": "AFR",
        "label": "African",
    }
    assert rf.af_source_descriptor("gnomAD_SV_AF", spec)["population"] == ""  # overall
    assert rf.af_source_descriptor("gnomAD_SV_EUR_AF", spec)["label"] == "European"
    # the id / SVTYPE columns are not AF sources
    assert rf.af_source_descriptor("gnomAD_SV", spec) is None
    assert rf.af_source_descriptor("gnomAD_SV_SVTYPE", spec) is None


def test_af_columns_discovers_v2_subset_columns():
    # v2's subset-prefixed AF columns come from the pinned spec's grammar.
    spec = load_merged_spec("human_grch37").parsing
    index_map = {
        name: i
        for i, name in enumerate((
            "Allele", "gnomAD_exomes_AF", "gnomAD_exomes_controls_AF_afr",
            "gnomAD_exomes_AF_popmax", "SYMBOL",
        ))
    }
    expected = [
        "gnomAD_exomes_AF", "gnomAD_exomes_controls_AF_afr", "gnomAD_exomes_AF_popmax",
    ]
    assert rf.af_columns(index_map, spec) == expected


def test_af_le_any_keeps_when_one_meets():
    lines = [
        _af_record(1, [_af_entry("0.3", "0.01", "0.5")]),  # nfe 0.01 <= 0.05 -> keep
        _af_record(2, [_af_entry("0.3", "0.2", "0.5")]),  # none <= 0.05 -> drop
    ]
    compiled = rf.compile_filters([_af_filter("le", 0.05, "any")], AF_INDEX_MAP, PARSING_SPEC)
    kept, stats = rf.apply_filter_pipeline(lines, compiled)
    assert len(kept) == 1
    assert kept[0] == lines[0]
    assert stats[0].removed == 1


def test_af_le_all_requires_every_value():
    lines = [
        _af_record(1, [_af_entry("0.3", "0.01", "0.5")]),  # not all <= 0.05 -> drop
        _af_record(2, [_af_entry("0.01", "0.02", "0.03")]),  # all <= 0.05 -> keep
    ]
    compiled = rf.compile_filters([_af_filter("le", 0.05, "all")], AF_INDEX_MAP, PARSING_SPEC)
    kept, _ = rf.apply_filter_pipeline(lines, compiled)
    assert len(kept) == 1
    assert kept[0] == lines[1]


def test_af_ge():
    line = _af_record(1, [_af_entry("0.3", "0.01", "0.5")])
    kept_ge, _ = rf.apply_filter_pipeline(
        [line], rf.compile_filters([_af_filter("ge", 0.4, "any")], AF_INDEX_MAP, PARSING_SPEC)
    )
    assert len(kept_ge) == 1  # aou 0.5 >= 0.4


def test_af_rejects_equality():
    """`==` is gone: these are floats, so equality is a question the data can
    rarely answer, and it was never the useful test for a frequency."""
    with pytest.raises(rf.FilterError):
        rf.compile_filters([_af_filter("eq", 0.01, "any")], AF_INDEX_MAP, PARSING_SPEC)


def test_af_specific_columns_only():
    lines = [_af_record(1, [_af_entry("0.3", "0.3", "0.5")])]
    # test only the exomes overall column; 0.3 > 0.05 -> drop
    compiled = rf.compile_filters(
        [_af_filter("le", 0.05, "any", values=["gnomAD_exomes_AF"])], AF_INDEX_MAP, PARSING_SPEC
    )
    kept, _ = rf.apply_filter_pipeline(lines, compiled)
    assert kept == []


def test_af_no_data_is_kept():
    """No data in any tested column keeps the allele. Absence of a frequency is
    not evidence of a high one -- a variant gnomAD has never seen is unknown, not
    common -- and dropping it hid exactly the novel variants a rare-variant
    filter is usually hunting for."""
    lines = [_af_record(1, [_af_entry("", "", "")])]
    compiled = rf.compile_filters([_af_filter("le", 0.05, "any")], AF_INDEX_MAP, PARSING_SPEC)
    kept, _ = rf.apply_filter_pipeline(lines, compiled)
    assert len(kept) == 1


def test_af_no_data_is_kept_whatever_the_comparison():
    """Keeping is about having nothing to compare, not about which way the
    comparison points -- a `ge` filter must not start dropping them again."""
    lines = [_af_record(1, [_af_entry(".", "", "")])]
    for operator in ("le", "ge"):
        compiled = rf.compile_filters([_af_filter(operator, 0.05, "any")], AF_INDEX_MAP, PARSING_SPEC)
        kept, _ = rf.apply_filter_pipeline(lines, compiled)
        assert len(kept) == 1, operator


def test_af_present_data_still_decides_even_with_no_data_alongside():
    """The change is only about having nothing at all: a column with data still
    excludes the allele when it fails."""
    lines = [_af_record(1, [_af_entry("0.9", "", "")])]
    compiled = rf.compile_filters([_af_filter("le", 0.05, "any")], AF_INDEX_MAP, PARSING_SPEC)
    kept, _ = rf.apply_filter_pipeline(lines, compiled)
    assert kept == []


def test_af_ignores_missing_but_tests_present():
    # exomes empty (ignored), nfe 0.01 present and <= 0.05 -> keep
    lines = [_af_record(1, [_af_entry("", "0.01", "")])]
    compiled = rf.compile_filters([_af_filter("le", 0.05, "any")], AF_INDEX_MAP, PARSING_SPEC)
    kept, _ = rf.apply_filter_pipeline(lines, compiled)
    assert len(kept) == 1


def test_af_rejects_in_operator():
    with pytest.raises(rf.FilterError):
        rf.compile_filters(
            [rf.ResultsFilter(field=rf.ALLELE_FREQUENCY_FIELD, operator="in", values=[])],
            AF_INDEX_MAP,
            PARSING_SPEC,
        )


def test_empty_values_is_noop():
    lines = [_record(1, ["missense_variant"])]
    compiled = rf.compile_filters([_consequence_filter()], INDEX_MAP)
    assert compiled == []
    kept, stats = rf.apply_filter_pipeline(lines, compiled)
    assert kept == lines
    assert stats == []


# --- end to end via get_results_from_path ------------------------------------


def test_get_results_filtered_totals_and_metadata(tmp_path):
    records = [
        _record(1, ["missense_variant"]),
        _record(2, ["synonymous_variant"]),
        _record(3, ["missense_variant"]),
        _record(4, ["intron_variant"]),
        _record(5, ["missense_variant"]),
    ]
    vcf_path = _write_vcf(tmp_path, records)

    result = get_results_from_path(
        page_size=10,
        page=1,
        vcf_path=FilePath(vcf_path),
        filters=[_consequence_filter("missense_variant")],
    )

    # Three missense records survive; pagination total reflects the filtered set.
    assert result.metadata.pagination.total == 3
    assert len(result.variants) == 3
    assert result.metadata.filters is not None
    assert result.metadata.filters.unfiltered_total == 5
    assert result.metadata.filters.filtered_total == 3
    assert result.metadata.filters.stats[0].field == "consequence"
    assert result.metadata.filters.stats[0].removed == 2


def test_get_results_prunes_nonmatching_transcripts(tmp_path):
    # One variant with two transcripts: one missense, one upstream. Filtering on
    # missense must keep the variant but drop the upstream transcript.
    csq = (
        "T|missense_variant|MODERATE|GENE|ENSG|Transcript|ENST_A|protein_coding,"
        "T|upstream_gene_variant|MODIFIER|GENE|ENSG|Transcript|ENST_B|protein_coding"
    )
    records = [f"chr1\t200\tv1\tC\tT\t.\t.\tCSQ={csq}\n"]
    vcf_path = _write_vcf(tmp_path, records)

    result = get_results_from_path(
        page_size=10,
        page=1,
        vcf_path=FilePath(vcf_path),
        filters=[_consequence_filter("missense_variant")],
    )

    assert len(result.variants) == 1
    all_consequences = [
        consequence
        for allele in result.variants[0].alternative_alleles
        for prediction in allele.predicted_molecular_consequences
        for consequence in prediction.consequences
    ]
    assert "missense_variant" in all_consequences
    assert "upstream_gene_variant" not in all_consequences


def test_get_results_filtered_pagination_slices(tmp_path):
    records = [_record(i, ["missense_variant"]) for i in range(1, 8)]
    # add some non-matching noise interleaved
    records += [_record(i, ["intron_variant"]) for i in range(8, 11)]
    vcf_path = _write_vcf(tmp_path, records)

    page1 = get_results_from_path(
        page_size=5,
        page=1,
        vcf_path=FilePath(vcf_path),
        filters=[_consequence_filter("missense_variant")],
    )
    page2 = get_results_from_path(
        page_size=5,
        page=2,
        vcf_path=FilePath(vcf_path),
        filters=[_consequence_filter("missense_variant")],
    )

    assert page1.metadata.pagination.total == 7
    assert len(page1.variants) == 5
    assert len(page2.variants) == 2  # remainder of the 7 filtered records


# --- available_af_sources gated to what the submission selected --------------


def _response_with_af_sources() -> model.VepResultsResponse:
    return model.VepResultsResponse(
        metadata=model.Metadata(
            pagination=model.PaginationMetadata(page=1, per_page=10, total=0),
            display_panels=DISPLAY_PANELS,
            display=DISPLAY,
            available_af_sources=[
                model.AfSource(key="gnomAD_exomes_AF", source="gnomad_exomes", population="", label="All"),
                model.AfSource(key="gnomAD_genomes_AF", source="gnomad_genomes", population="", label="All"),
            ],
        ),
        variants=[],
    )


def test_af_sources_gated_to_the_expected_columns():
    # The output VCF carries both, but only exomes was selected (in the pin).
    gated = vcf_results._with_display_panels(
        _response_with_af_sources(), DISPLAY_PANELS, DISPLAY,
        spec=PARSING_SPEC,
        expected_columns={"gnomAD_exomes_AF", "CADD_PHRED"},
    )
    assert [s.key for s in gated.metadata.available_af_sources] == ["gnomAD_exomes_AF"]


def test_af_sources_all_dropped_when_no_af_was_selected():
    # AF columns are in the VCF but none is in the pinned expected set -> the AF
    # filter is offered nothing (so the frontend hides it).
    gated = vcf_results._with_display_panels(
        _response_with_af_sources(), DISPLAY_PANELS, DISPLAY,
        spec=PARSING_SPEC,
        expected_columns={"CADD_PHRED", "CLIN_SIG"},
    )
    assert gated.metadata.available_af_sources == []


# --- All of Us max_subpopulation decoded to a label at serve time -----------


def _allele_with_aou_data(data: dict) -> model.AlternativeVariantAllele:
    return model.AlternativeVariantAllele(
        allele_sequence="T",
        allele_type="SNV",
        predicted_molecular_consequences=[],
        annotations=[
            model.Annotation(plugin="all_of_us", scope="allele", data=data)
        ],
    )


def test_label_af_max_subpopulation_decodes_amp_joined_codes():
    allele = _allele_with_aou_data(
        {"populations": {"max": 0.2}, "max_subpopulation": "eur&afr"}
    )
    vcf_results._label_af_max_subpopulation([allele])
    assert (
        allele.annotations[0].data["max_subpopulation_label"]
        == "European / African"
    )


def test_label_af_max_subpopulation_skips_when_null_or_absent():
    nulled = _allele_with_aou_data(
        {"populations": {}, "max_subpopulation": None}
    )
    absent = _allele_with_aou_data({"populations": {}})
    vcf_results._label_af_max_subpopulation([nulled, absent])
    assert "max_subpopulation_label" not in nulled.annotations[0].data
    assert "max_subpopulation_label" not in absent.annotations[0].data


def test_with_display_panels_labels_max_subpopulation():
    # The serve path (any job) decodes the max-subpopulation code to a label.
    variant = model.Variant(
        allele_type="SNV",
        location=model.Location(region_name="1", start=1, end=2),
        reference_allele=model.ReferenceVariantAllele(allele_sequence="C"),
        alternative_alleles=[
            _allele_with_aou_data(
                {"populations": {"max": 0.2}, "max_subpopulation": "eur"}
            )
        ],
    )
    response = model.VepResultsResponse(
        metadata=model.Metadata(
            pagination=model.PaginationMetadata(page=1, per_page=10, total=1),
            display_panels=DISPLAY_PANELS,
            display=DISPLAY,
        ),
        variants=[variant],
    )
    out = vcf_results._with_display_panels(
        response,
        DISPLAY_PANELS,
        DISPLAY,
        spec=PARSING_SPEC,
        expected_columns={"AoU_gvs_max_subpop"},
    )
    data = out.variants[0].alternative_alleles[0].annotations[0].data
    assert data["max_subpopulation_label"] == "European"


# --- bounded CSQ splitting ---------------------------------------------------


def test_bounded_split_round_trips():
    """The safety property the optimisation rests on: an entry split only as far
    as the filters read still rejoins byte for byte, because split(sep, maxsplit)
    leaves the remainder whole. Without this, narrowing a record's CSQ on the
    download path would silently truncate every entry."""
    entry = "|".join(str(i) for i in range(135))
    for bound in (0, 1, 71, 134):
        parts = entry.split("|", bound + 1)
        assert len(parts) <= bound + 2
        assert "|".join(parts) == entry


def test_csq_split_bound_is_the_highest_column_any_filter_reads():
    consequence = rf.compile_filters(
        [_consequence_filter("missense_variant")], INDEX_MAP
    )
    assert rf.csq_split_bound(consequence) == INDEX_MAP["Consequence"]

    both = rf.compile_filters(
        [
            _consequence_filter("missense_variant"),
            rf.ResultsFilter(
                field=rf.GENE_SYMBOL_FIELD, operator=rf.OPERATOR_IN, values=["GENE1"]
            ),
        ],
        INDEX_MAP,
    )
    # the pipeline must split as far as the *deepest* reader, not the first
    assert rf.csq_split_bound(both) == max(
        INDEX_MAP["Consequence"], INDEX_MAP["SYMBOL"]
    )


def test_a_bounded_scan_matches_an_unbounded_one():
    """End to end: bounding the split must not change which records survive, nor
    the exact lines they rebuild to."""
    lines = [
        _record(1, ["missense_variant", "synonymous_variant"]),
        _record(2, ["synonymous_variant"]),
        _record(3, ["missense_variant"]),
    ]
    compiled = rf.compile_filters([_consequence_filter("missense_variant")], INDEX_MAP)
    bounded = rf.filter_records(iter(lines), compiled)

    # the pre-optimisation behaviour: no declared bound -> split everything
    unbounded_filters = [
        rf.CompiledFilter(
            field=cf.field,
            keep_entry=cf.keep_entry,
            line_prefilter=cf.line_prefilter,
            max_csq_index=None,
        )
        for cf in compiled
    ]
    unbounded = rf.filter_records(iter(lines), unbounded_filters)

    assert rf.csq_split_bound(unbounded_filters) is None  # the full-split path
    assert bounded.matched_total == unbounded.matched_total == 2
    assert bounded.page == unbounded.page


# --- filtered-scan cache -----------------------------------------------------


def _filtered_names(vcf_path, page, page_size=2):
    response = get_results_from_path(
        page_size, page, FilePath(vcf_path), [_consequence_filter("missense_variant")]
    )
    return [variant.name for variant in response.variants], response


def test_a_warm_page_is_identical_to_a_cold_one(tmp_path):
    """The cache must change how long a page takes, never what it contains."""
    records = [
        _record(i, ["missense_variant" if i % 2 else "synonymous_variant"])
        for i in range(1, 21)
    ]
    vcf_path = _write_vcf(tmp_path, records)

    for page in (1, 2, 5):
        vcf_results.clear_scan_cache()
        cold_names, cold = _filtered_names(vcf_path, page)
        warm_names, warm = _filtered_names(vcf_path, page)  # cache now warm
        assert cold_names == warm_names
        assert cold.metadata.filters.filtered_total == warm.metadata.filters.filtered_total
        assert cold.metadata.filters.unfiltered_total == warm.metadata.filters.unfiltered_total
        assert [s.removed for s in cold.metadata.filters.stats] == [
            s.removed for s in warm.metadata.filters.stats
        ]


def test_a_rewritten_file_is_not_served_from_the_old_scan(tmp_path):
    """The dev harness rewrites one fixed output path, so a cache keyed on the
    path alone would serve a stale match set. The key carries mtime and size."""
    vcf_results.clear_scan_cache()
    first = [_record(i, ["missense_variant"]) for i in range(1, 6)]
    vcf_path = _write_vcf(tmp_path, first)
    names_before, before = _filtered_names(vcf_path, 1, page_size=10)
    assert before.metadata.filters.filtered_total == 5

    # regenerate the same path with different content
    import os
    import time as _time

    _time.sleep(0.01)
    rewritten = [_record(i, ["synonymous_variant"]) for i in range(1, 6)]
    _write_vcf(tmp_path, rewritten)
    os.utime(vcf_path, None)

    _, after = _filtered_names(vcf_path, 1, page_size=10)
    assert after.metadata.filters.filtered_total == 0, "served a stale match set"


def test_two_filter_sets_do_not_share_a_cache_entry(tmp_path):
    vcf_results.clear_scan_cache()
    records = [
        _record(1, ["missense_variant"]),
        _record(2, ["synonymous_variant"]),
        _record(3, ["stop_gained"]),
    ]
    vcf_path = _write_vcf(tmp_path, records)

    missense = get_results_from_path(
        10, 1, FilePath(vcf_path), [_consequence_filter("missense_variant")]
    )
    stop = get_results_from_path(
        10, 1, FilePath(vcf_path), [_consequence_filter("stop_gained")]
    )
    assert missense.metadata.filters.filtered_total == 1
    assert stop.metadata.filters.filtered_total == 1
    assert missense.variants[0].name != stop.variants[0].name


def test_the_cache_is_bounded(tmp_path):
    """It holds one int per matching record; unbounded, a long-lived process
    accumulating filter sets would grow without limit."""
    vcf_results.clear_scan_cache()
    vcf_path = _write_vcf(tmp_path, [_record(1, ["missense_variant"])])
    for i in range(vcf_results._SCAN_CACHE_MAX_ENTRIES + 3):
        get_results_from_path(
            10, 1, FilePath(vcf_path), [_consequence_filter(f"term_{i}")]
        )
    assert len(vcf_results._scan_cache) <= vcf_results._SCAN_CACHE_MAX_ENTRIES


# --- Variant impact score filters ---------------------------------------------
#
# Every numeric impact prediction the job can carry is one field. Each score is
# its own field because the scales differ wildly — CADD PHRED is ~0-99, CADD RAW
# is unbounded around -7 to +35, the protein/splice predictors are 0-1
# probabilities and popEVE is normally negative — so a threshold means nothing
# without knowing which scale it is on.

SCORE_COLUMNS_HEADER = [
    "Allele",
    "Consequence",
    "Feature",
    "CADD_PHRED",
    "CADD_RAW",
    "am_pathogenicity",
    "REVEL",
    "ClinPred",
    "EVE_SCORE",
    "popEVE_SCORE",
    "SpliceAI_pred_DS_AG",
    "SpliceAI_pred_DS_AL",
    "SpliceAI_pred_DS_DG",
    "SpliceAI_pred_DS_DL",
]
SCORE_INDEX_MAP = {name: i for i, name in enumerate(SCORE_COLUMNS_HEADER)}
# The pre-generalisation name, kept for the CADD tests below.
CADD_INDEX_MAP = SCORE_INDEX_MAP


def _score_entry(**values: str) -> str:
    """A CSQ entry carrying the named score columns; every other score empty."""
    entry = ["T", "missense_variant", "ENST_1"] + [""] * (
        len(SCORE_COLUMNS_HEADER) - 3
    )
    for column, value in values.items():
        entry[SCORE_INDEX_MAP[column]] = value
    return "|".join(entry)


def _cadd_entry(phred: str, raw: str) -> str:
    return _score_entry(CADD_PHRED=phred, CADD_RAW=raw)


def _spliceai_entry(ag: str, al: str, dg: str, dl: str) -> str:
    return _score_entry(
        SpliceAI_pred_DS_AG=ag,
        SpliceAI_pred_DS_AL=al,
        SpliceAI_pred_DS_DG=dg,
        SpliceAI_pred_DS_DL=dl,
    )


def _score_record(pos: int, entries: list[str]) -> str:
    return f"chr1\t{100 + pos}\tid_{pos:02d}\tC\tT\t.\t.\tCSQ={','.join(entries)}\n"


# The pre-generalisation names, still used by the scan-cache tests below.
_cadd_record = _score_record


def _score_filter(field, operator, threshold, include_missing=True):
    return rf.ResultsFilter(
        field=field,
        operator=operator,
        threshold=threshold,
        include_missing=include_missing,
    )


_cadd_filter = _score_filter


def _run_score(entries, *filters):
    lines = [_score_record(1, entries)]
    kept, _ = rf.apply_filter_pipeline(
        lines, rf.compile_filters(list(filters), SCORE_INDEX_MAP)
    )
    return kept


_run_cadd = _run_score


def test_cadd_phred_ge_keeps_only_scores_at_or_above():
    assert _run_cadd([_cadd_entry("25.3", "3.1")],
                     _cadd_filter(rf.CADD_PHRED_FIELD, "ge", 20))
    assert _run_cadd([_cadd_entry("12.0", "3.1")],
                     _cadd_filter(rf.CADD_PHRED_FIELD, "ge", 20)) == []


def test_cadd_phred_le_keeps_only_scores_at_or_below():
    assert _run_cadd([_cadd_entry("12.0", "3.1")],
                     _cadd_filter(rf.CADD_PHRED_FIELD, "le", 20))
    assert _run_cadd([_cadd_entry("25.3", "3.1")],
                     _cadd_filter(rf.CADD_PHRED_FIELD, "le", 20)) == []


def test_cadd_raw_is_its_own_scale():
    """The reason these are two fields: a threshold of 3 means one thing on the
    raw scale and something else entirely on PHRED."""
    entries = [_cadd_entry("25.3", "3.1")]
    assert _run_cadd(entries, _cadd_filter(rf.CADD_RAW_FIELD, "ge", 3))
    assert _run_cadd(entries, _cadd_filter(rf.CADD_RAW_FIELD, "ge", 20)) == []


def test_cadd_missing_score_is_kept_by_default():
    """A missing CADD score usually means the variant type is not scored at all
    rather than that it scored low, so the filter does not hide it unasked."""
    for empty in ("", "."):
        assert _run_cadd([_cadd_entry(empty, "3.1")],
                         _cadd_filter(rf.CADD_PHRED_FIELD, "ge", 20))


def test_cadd_missing_score_can_be_excluded():
    assert _run_cadd(
        [_cadd_entry("", "3.1")],
        _cadd_filter(rf.CADD_PHRED_FIELD, "ge", 20, include_missing=False),
    ) == []


def test_cadd_unparseable_score_counts_as_missing():
    """Whatever it is, it is not a number to compare against — so it follows the
    same choice the user made about absent scores rather than a third rule."""
    assert _run_cadd([_cadd_entry("NA", "3.1")],
                     _cadd_filter(rf.CADD_PHRED_FIELD, "ge", 20))
    assert _run_cadd(
        [_cadd_entry("NA", "3.1")],
        _cadd_filter(rf.CADD_PHRED_FIELD, "ge", 20, include_missing=False),
    ) == []


def test_cadd_filter_is_a_no_op_when_cadd_was_not_run():
    """No column means the plugin never ran; that must not empty the results."""
    without = {"Allele": 0, "Consequence": 1, "Feature": 2}
    assert rf.compile_filters(
        [_cadd_filter(rf.CADD_PHRED_FIELD, "ge", 20)], without
    ) == []


def test_cadd_rejects_operators_other_than_ge_and_le():
    for operator in ("eq", "in"):
        with pytest.raises(rf.FilterError):
            rf.compile_filters(
                [_cadd_filter(rf.CADD_PHRED_FIELD, operator, 20)], CADD_INDEX_MAP
            )


# --- the other single-column scores ------------------------------------------
#
# One parameterised pass over every score that reads exactly one column: they
# share `_compile_score`, so this pins that each field id is wired to the right
# column rather than re-testing the comparison logic eleven times.

_SINGLE_COLUMN_SCORES = [
    (rf.ALPHAMISSENSE_FIELD, "am_pathogenicity"),
    (rf.REVEL_FIELD, "REVEL"),
    (rf.CLINPRED_FIELD, "ClinPred"),
    (rf.EVE_FIELD, "EVE_SCORE"),
    (rf.POPEVE_FIELD, "popEVE_SCORE"),
    (rf.SPLICEAI_AG_FIELD, "SpliceAI_pred_DS_AG"),
    (rf.SPLICEAI_AL_FIELD, "SpliceAI_pred_DS_AL"),
    (rf.SPLICEAI_DG_FIELD, "SpliceAI_pred_DS_DG"),
    (rf.SPLICEAI_DL_FIELD, "SpliceAI_pred_DS_DL"),
]


@pytest.mark.parametrize("field,column", _SINGLE_COLUMN_SCORES)
def test_each_score_filters_on_its_own_column(field, column):
    high = [_score_entry(**{column: "0.9"})]
    low = [_score_entry(**{column: "0.1"})]
    assert _run_score(high, _score_filter(field, "ge", 0.5))
    assert _run_score(low, _score_filter(field, "ge", 0.5)) == []
    assert _run_score(low, _score_filter(field, "le", 0.5))
    assert _run_score(high, _score_filter(field, "le", 0.5)) == []


@pytest.mark.parametrize("field,column", _SINGLE_COLUMN_SCORES)
def test_each_score_reads_no_other_score_column(field, column):
    """A score set only in some *other* column leaves this field's entry
    unscored — the wiring mistake this catches is a field pointed at the wrong
    column, which would silently filter on a neighbouring predictor."""
    others = [c for _, c in _SINGLE_COLUMN_SCORES if c != column]
    entry = [_score_entry(**{c: "0.9" for c in others})]
    assert _run_score(
        entry, _score_filter(field, "ge", 0.5, include_missing=False)
    ) == []


@pytest.mark.parametrize("field,column", _SINGLE_COLUMN_SCORES)
def test_each_score_is_a_no_op_when_its_plugin_was_not_run(field, column):
    without = {
        name: i
        for name, i in SCORE_INDEX_MAP.items()
        if name not in {c for _, c in _SINGLE_COLUMN_SCORES}
    }
    assert rf.compile_filters([_score_filter(field, "ge", 0.5)], without) == []


def test_popeve_handles_negative_thresholds():
    """Real popEVE scores run about -5.5 to -2.5, so this is the scale the field
    is actually used on; a positive threshold would prove nothing about it."""
    damaging = [_score_entry(popEVE_SCORE="-2.6")]
    tolerated = [_score_entry(popEVE_SCORE="-5.4")]
    # "at least -3.0" keeps the (less negative) damaging end.
    assert _run_score(damaging, _score_filter(rf.POPEVE_FIELD, "ge", -3.0))
    assert _run_score(tolerated, _score_filter(rf.POPEVE_FIELD, "ge", -3.0)) == []
    # And the comparison is a real numeric one, not a sign-blind magnitude test.
    assert _run_score(tolerated, _score_filter(rf.POPEVE_FIELD, "le", -3.0))
    assert _run_score(damaging, _score_filter(rf.POPEVE_FIELD, "le", -3.0)) == []


# --- spliceai_any: one threshold against all four delta scores ----------------


def test_spliceai_any_keeps_an_entry_when_only_one_of_the_four_passes():
    """SpliceAI's four deltas are read as a set — a variant that scores high for
    donor loss alone is a splice candidate, so one passing column is enough."""
    for position in range(4):
        scores = ["0.01"] * 4
        scores[position] = "0.85"
        assert _run_score(
            [_spliceai_entry(*scores)],
            _score_filter(rf.SPLICEAI_ANY_FIELD, "ge", 0.5),
        ), f"column {position} alone should keep the entry"


def test_spliceai_any_drops_an_entry_when_none_of_the_four_passes():
    assert _run_score(
        [_spliceai_entry("0.01", "0.02", "0.03", "0.04")],
        _score_filter(rf.SPLICEAI_ANY_FIELD, "ge", 0.5),
    ) == []


def test_spliceai_any_partial_data_is_scored_not_missing():
    """The crux of the multi-column rule: an entry counts as unscored only when
    EVERY tested column is absent. A variant scored on three of the four deltas
    is scored, so it must be judged on the values it has — treating "one column
    absent" as no-data would hand it to `include_missing` and either hide a real
    hit or keep a variant that clearly fails."""
    partial_high = [_spliceai_entry("", "0.9", "0.01", ".")]
    partial_low = [_spliceai_entry("", "0.1", "0.01", ".")]
    # include_missing=False must not drop the scored-on-three entry that passes.
    assert _run_score(
        partial_high,
        _score_filter(rf.SPLICEAI_ANY_FIELD, "ge", 0.5, include_missing=False),
    )
    # ...and include_missing=True must not rescue the one that fails on the
    # data it does have.
    assert _run_score(
        partial_low,
        _score_filter(rf.SPLICEAI_ANY_FIELD, "ge", 0.5, include_missing=True),
    ) == []


def test_spliceai_any_with_no_data_at_all_follows_include_missing():
    empty = [_spliceai_entry("", ".", "", "NA")]
    assert _run_score(
        empty, _score_filter(rf.SPLICEAI_ANY_FIELD, "ge", 0.5, include_missing=True)
    )
    assert _run_score(
        empty, _score_filter(rf.SPLICEAI_ANY_FIELD, "ge", 0.5, include_missing=False)
    ) == []


def test_include_missing_defaults_to_dropping_unscored_entries():
    """A payload that omits `include_missing` drops the unscored entries.

    The wire default, which nothing else covers: every other test constructs the
    model with the flag set explicitly. It is False rather than True because a
    missing impact score means the variant was never scored, which says nothing
    about how damaging it is — the opposite of a missing allele frequency, which
    is itself evidence of rarity and so is always kept.
    """
    parsed = rf.parse_filters(
        json.dumps([{"field": rf.CADD_PHRED_FIELD, "operator": "ge", "threshold": 20}])
    )
    assert parsed[0].include_missing is False

    unscored = [_score_entry(CADD_PHRED="")]
    assert _run_score(unscored, parsed[0]) == []
    # ...and the flag is what decides it, not the threshold.
    assert _run_score(
        unscored, _score_filter(rf.CADD_PHRED_FIELD, "ge", 20, include_missing=True)
    )


def test_spliceai_any_reads_only_the_present_columns():
    """A header carrying just the AG column still compiles (the bound is the max
    over the columns actually present), and filters on what is there."""
    partial_map = {
        name: i
        for name, i in SCORE_INDEX_MAP.items()
        if not name.startswith("SpliceAI_") or name == "SpliceAI_pred_DS_AG"
    }
    compiled = rf.compile_filters(
        [_score_filter(rf.SPLICEAI_ANY_FIELD, "ge", 0.5)], partial_map
    )
    assert len(compiled) == 1
    assert compiled[0].max_csq_index == partial_map["SpliceAI_pred_DS_AG"]


# --- available_scores: the two-stage availability gate ------------------------


def _response_with_scores(fields: list[str]) -> model.VepResultsResponse:
    return model.VepResultsResponse(
        metadata=model.Metadata(
            pagination=model.PaginationMetadata(page=1, per_page=10, total=0),
            display_panels=DISPLAY_PANELS,
            display=DISPLAY,
            available_scores=list(fields),
        ),
        variants=[],
    )


def test_spliceai_fields_stay_available_on_the_sentinel_column_alone():
    """The regression this whole design exists to prevent. The `spliceai` parse
    plugin declares only `SpliceAI_pred_DS_AG` in its `csq_fields`, so that is
    the only SpliceAI column the pinned expected-columns sidecar carries — even
    though the VCF holds all four. Gating each field on its own column would
    hide three of the five options with the data present in the file."""
    spliceai_fields = [
        rf.SPLICEAI_AG_FIELD,
        rf.SPLICEAI_AL_FIELD,
        rf.SPLICEAI_DG_FIELD,
        rf.SPLICEAI_DL_FIELD,
        rf.SPLICEAI_ANY_FIELD,
    ]
    gated = vcf_results._with_display_panels(
        _response_with_scores(spliceai_fields), DISPLAY_PANELS, DISPLAY,
        spec=PARSING_SPEC,
        expected_columns={"SpliceAI_pred_DS_AG"},
    )
    assert gated.metadata.available_scores == spliceai_fields


def test_scores_the_submission_did_not_select_are_dropped():
    """The full-cache leak: the VCF may carry columns this job never asked for."""
    gated = vcf_results._with_display_panels(
        _response_with_scores(
            [rf.CADD_PHRED_FIELD, rf.REVEL_FIELD, rf.SPLICEAI_ANY_FIELD]
        ),
        DISPLAY_PANELS, DISPLAY,
        spec=PARSING_SPEC,
        expected_columns={"CADD_PHRED", "gnomAD_exomes_AF"},
    )
    assert gated.metadata.available_scores == [rf.CADD_PHRED_FIELD]


def test_every_score_field_has_a_builder():
    """A score added to SCORE_SPECS without a builder entry would 4xx at request
    time rather than fail here."""
    assert set(rf.SCORE_SPECS) <= set(rf._BUILDERS)


def test_categorical_predictions_are_not_offered_as_numeric_scores():
    """`am_class` and `EVE_CLASS` are categorical calls, not thresholds."""
    tested = {column for spec in rf.SCORE_SPECS.values() for column in spec.columns}
    assert "am_class" not in tested
    assert "EVE_CLASS" not in tested


def test_scan_cache_key_separates_filters_that_only_differ_by_no_score_choice(tmp_path):
    """Two CADD filters alike but for `include_missing` select different records,
    so they must not share a cached scan. They did: the key was built from
    field/operator/values/threshold/match, and the second request was served the
    first's match set — 13 variants either way, where the real answers are 13
    and 31."""
    vcf_path = _write_vcf(tmp_path, [_cadd_record(1, [_cadd_entry("25", "3")])])
    keys = {
        vcf_results._scan_cache_key(
            vcf_path,
            [_cadd_filter(rf.CADD_PHRED_FIELD, "ge", 20, include_missing=include)],
        )
        for include in (True, False)
    }
    assert len(keys) == 2


def test_scan_cache_key_separates_filters_that_only_differ_by_match_mode(tmp_path):
    """The same hazard for allele frequency's any/all, which was already in the
    key — pinned so it stays there."""
    vcf_path = _write_vcf(tmp_path, [_af_record(1, [_af_entry("0.3", "0.01", "0.5")])])
    keys = {
        vcf_results._scan_cache_key(vcf_path, [_af_filter("le", 0.01, match)])
        for match in ("any", "all")
    }
    assert len(keys) == 2
