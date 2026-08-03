"""Tests for the spec-driven parsing interpreter (`apply_plugin_spec`) against
the parsing half of `specs/human_grch38.json`.

These began life as differential tests: every case compared the interpreter's
output to the corresponding hand-written `_parse_*` function, which was the
oracle that proved the spec vocabulary sufficient before anything was rewired.
The go-flat cutover deleted that bank, so the expected values below are the
frozen outputs from the last run in which both paths agreed — the equivalence
proof is now a set of pinned literals rather than a live comparison.

The fixtures are deliberately shared with test_csq_parsers.
"""

import pytest

from app.tests.test_csq_parsers import EMPTY, INDEX_MAP, row_list
from app.vep.models.parsing_spec_model import ParsingSpec, TargetSpec
from app.vep.utils.csq import get_prediction_index_map
from app.vep.utils.spec_interpreter import apply_plugin_spec
from app.vep.utils.spec_loader import load_merged_spec

SPEC: ParsingSpec = load_merged_spec("human_grch38").parsing


def index_map_for(*columns: str) -> dict[str, int]:
    return get_prediction_index_map("Format: " + "|".join(columns))


def run(plugin: str, csq_values, index_map=INDEX_MAP):
    spec = SPEC.plugin(plugin)
    assert spec is not None, f"no spec for {plugin}"
    return apply_plugin_spec(csq_values, index_map, spec)


# --- the spec document itself ------------------------------------------------


def test_bundled_spec_validates():
    """The shipped JSON round-trips through the strict model."""
    assert SPEC.spec_version
    assert {p.plugin for p in SPEC.plugins} == {
        "mutfunc",
        "mavedb",
        "clinvar",
        "clinvar_sv",
        "protvar",
        "protein",
        "opentargets",
        "go",
        "spliceai",
        "riboseq_orfs",
        "hgvs",
        "hgvsg",
        "spdi",
        "loeuf",
        "gerp",
        "nmd",
        "nearest_gene",
        "nearest_exon_jb",
        "phenotype_data",
        "dosage_sensitivity",
        "intact",
        "popeve",
        "revel",
        "clinpred",
        "alphamissense",
        "cadd",
        "eve",
        "utr_annotation",
        "gnomad_exomes",
        "gnomad_genomes",
        "all_of_us",
        "gencode_promoter",
        "gnomad_sv",
        "gnomad_cnv",
        "tss_distance",
    }


def test_unknown_key_is_rejected():
    """extra=forbid: a spec we don't understand fails at load, not at parse."""
    with pytest.raises(Exception):
        ParsingSpec.model_validate(
            {"spec_version": "x", "plugins": [], "surprise": True}
        )


def test_zip_requires_matching_as_entries():
    with pytest.raises(Exception):
        TargetSpec.model_validate(
            {
                "field": "assays",
                "from": ["a", "b"],
                "transform": "zip",
                "as": [{"field": "only_one"}],
            }
        )


def test_key_value_requires_both_delimiters():
    with pytest.raises(Exception):
        TargetSpec.model_validate(
            {"field": "x", "from": "col", "transform": "key_value", "pair_delimiter": ":"}
        )


# --- mutfunc: four scalars ---------------------------------------------------

MUTFUNC_SCORES = dict(
    mutfunc_motif="0.1", mutfunc_int="0.2", mutfunc_mod="0.3", mutfunc_exp="0.4"
)


def test_mutfunc_all_four_scores():
    assert run("mutfunc", row_list(**MUTFUNC_SCORES)) == {
        "linear_motifs": 0.1,
        "protein_interactions": 0.2,
        "protein_structure": 0.3,
        "protein_structure_experimental": 0.4,
    }


def test_mutfunc_empty_is_none():
    assert run("mutfunc", EMPTY) is None


def test_mutfunc_partial_keeps_absent_scores_as_null():
    """Only some scores present: the rest must come back None, not be dropped."""
    csq = row_list(mutfunc_motif="0.1", mutfunc_exp="0.4")
    assert run("mutfunc", csq) == {
        "linear_motifs": 0.1,
        "protein_interactions": None,
        "protein_structure": None,
        "protein_structure_experimental": 0.4,
    }


# --- MaveDB: positional zip, the hard case -----------------------------------

MAVEDB_MULTI = dict(
    MaveDB_score="1.5&2.5&NA",
    MaveDB_urn="urn:1&urn:2&urn:3",
    MaveDB_doi="10.1/a&NA&10.1/c",
    MaveDB_nt="c.1A>G&NA",
    MaveDB_pro="p.Lys1Arg&NA",
)


def test_mavedb_multi_assay_shape_is_as_expected():
    result = run("mavedb", row_list(**MAVEDB_MULTI))
    assert result["protein_variant"] == "p.Lys1Arg"
    assert [(a["urn"], a["score"]) for a in result["assays"]] == [
        ("urn:1", 1.5),
        ("urn:2", 2.5),
        ("urn:3", None),  # NA score, but a real urn -> assay kept
    ]


def test_mavedb_empty_is_none():
    assert run("mavedb", EMPTY) is None


def test_mavedb_uneven_columns_pad_rather_than_truncate():
    """Fewer scores than urns: `align: max` must pad, not truncate."""
    csq = row_list(MaveDB_score="1.5", MaveDB_urn="urn:1&urn:2")
    assert run("mavedb", csq) == {
        "protein_variant": None,
        "assays": [
            {"score": 1.5, "urn": "urn:1"},
            {"score": None, "urn": "urn:2"},
        ],
    }


def test_mavedb_protein_variant_only_is_none():
    """pro present but no score/urn -> no assays -> whole annotation is None
    (require_any_output)."""
    assert run("mavedb", row_list(MaveDB_pro="p.Lys1Arg")) is None


def test_mavedb_all_na_assay_dropped():
    """A position where both score and urn are NA is dropped entirely."""
    csq = row_list(MaveDB_score="1.5&NA", MaveDB_urn="urn:1&NA")
    assert run("mavedb", csq) == {
        "protein_variant": None,
        "assays": [{"score": 1.5, "urn": "urn:1"}],
    }


# --- ClinVar: the `when` conditional -----------------------------------------

CONFLICTING = "Conflicting_classifications_of_pathogenicity"


def test_clinvar_id_from_bare_match_column():
    """The variation id is read from the bare `ClinVar` match column (what VEP
    fills with the matched record's ID), alongside the significance."""
    csq = row_list(ClinVar="12345", ClinVar_CLNSIG="Pathogenic")
    result = run("clinvar", csq)
    assert result["id"] == "12345"
    assert result["significance"] == ["Pathogenic"]


def test_clinvar_non_conflicting_ignores_breakdown():
    """The `when` gate: CLNSIGCONF is present but must not be read, because the
    classification is not conflicting."""
    csq = row_list(
        ClinVar="12345",
        ClinVar_CLNSIG="Pathogenic",
        ClinVar_CLNSIGCONF="Likely_pathogenic_(6)",
    )
    assert run("clinvar", csq) == {
        "id": "12345",
        "significance": ["Pathogenic"],
        "conditions": [],
        "classification_summary": [
            {
                "classification": "Pathogenic",
                "review_status": None,
                "type": "Germline",
                "rating_scale": "clinvar_aggregate",
                "submissions": None,
                "supporting": None,
            }
        ],
        "submissions": [],
        "records": [],
    }


def test_clinvar_when_matches_list_membership_not_substring():
    """A value that merely embeds the conflicting term must not trigger the
    breakdown — the condition is membership of the '&'-split list."""
    csq = row_list(
        ClinVar="678",
        ClinVar_CLNSIG="Not_" + CONFLICTING,
        ClinVar_CLNSIGCONF="Benign_(2)",
    )
    assert run("clinvar", csq) == {
        "id": "678",
        "significance": ["Not_" + CONFLICTING],
        "conditions": [],
        "classification_summary": [
            {
                "classification": "Not_" + CONFLICTING + "",
                "review_status": None,
                "type": "Germline",
                "rating_scale": "clinvar_aggregate",
                "submissions": None,
                "supporting": None,
            }
        ],
        "submissions": [],
        "records": [],
    }


def test_clinvar_empty_is_none():
    assert run("clinvar", EMPTY) is None


# --- ClinVar structural variants ---------------------------------------------


def test_clinvar_sv_reports_significance_and_origin():
    result = run(
        "clinvar_sv",
        row_list(ClinVar_SV_CLNSIG="Pathogenic", ClinVar_SV_ORIGIN="germline"),
    )
    assert result == {"significance": ["Pathogenic"], "origin": ["germline"]}


def test_clinvar_sv_empty_is_none():
    # No CLNSIG (no SV overlap) -> the plugin produces nothing (require_any_input).
    assert run("clinvar_sv", EMPTY) is None


# --- NearestGene: id:distance[:direction], &-joined -------------------------


def test_nearest_gene_both_directions_splits_and_types():
    result = run(
        "nearest_gene",
        row_list(
            NearestGene="ENSG00000269981:19457:upstream&ENSG00000279928:25274:downstream"
        ),
    )
    assert result == {
        "nearest_genes": [
            {"gene_id": "ENSG00000269981", "distance": 19457, "direction": "upstream"},
            {"gene_id": "ENSG00000279928", "distance": 25274, "direction": "downstream"},
        ]
    }


def test_nearest_gene_single_without_direction():
    # Non-both_directions mode omits the direction suffix (upstream is the default).
    result = run("nearest_gene", row_list(NearestGene="ENSG00000186092:7522"))
    assert result["nearest_genes"] == [
        {"gene_id": "ENSG00000186092", "distance": 7522, "direction": None}
    ]


def test_nearest_gene_empty_is_none():
    assert run("nearest_gene", EMPTY) is None


# --- NearestExonJB: exon_id+distance+boundary_type+exon_length, &-joined ------


def test_nearest_exon_jb_parses_fields_and_types():
    result = run(
        "nearest_exon_jb", row_list(NearestExonJB="ENSE00004404283+53+start+117")
    )
    assert result == {
        "boundaries": [
            {
                "exon_id": "ENSE00004404283",
                "distance": 53,
                "boundary_type": "start",
                "exon_length": 117,
            }
        ]
    }


def test_nearest_exon_jb_intronic_two_boundaries():
    # Intronic mode reports the nearest boundary on each side, &-joined; a small
    # exon can carry boundary_type "start_end".
    result = run(
        "nearest_exon_jb",
        row_list(
            NearestExonJB="ENSE00003759395+3744+end+144&ENSE00004567867+53+start_end+107"
        ),
    )
    assert [b["boundary_type"] for b in result["boundaries"]] == ["end", "start_end"]
    assert [b["exon_length"] for b in result["boundaries"]] == [144, 107]


def test_nearest_exon_jb_empty_is_none():
    assert run("nearest_exon_jb", EMPTY) is None


# --- gnomAD / All of Us: pattern_map -----------------------------------------


def test_gnomad_exomes_pattern_map():
    index_map = index_map_for(
        "gnomAD_exomes_AF", "gnomAD_exomes_AF_afr", "gnomAD_exomes_AF_nfe_XX"
    )
    result = run("gnomad_exomes", ["0.01", "0.02", "0.03"], index_map)
    assert result["overall"] == 0.01
    # ancestry columns discovered from the header, not named in the spec
    assert result["populations"] == {"afr": 0.02, "nfe_XX": 0.03}


def test_gnomad_exomes_zero_overall_is_kept():
    """A 0.0 frequency is a real value. require_any_output must not treat it as
    absent (plain truthiness would drop the whole annotation)."""
    index_map = index_map_for("gnomAD_exomes_AF")
    result = run("gnomad_exomes", ["0.0"], index_map)
    assert result == {"overall": 0.0, "populations": {}}


def test_gnomad_exomes_absent_matches():
    index_map = index_map_for("Allele")
    assert run("gnomad_exomes", ["A"], index_map) is None


def test_gnomad_exomes_legacy_prefix_ignored():
    """The old gnomADe_ prefix must not match the pattern."""
    index_map = index_map_for("gnomADe_AF", "gnomADe_afr_AF")
    assert run("gnomad_exomes", ["0.1", "0.2"], index_map) is None


def test_gnomad_genomes_pattern_map():
    index_map = index_map_for(
        "gnomAD_genomes_AF", "gnomAD_genomes_AF_ami", "gnomAD_genomes_AF_grpmax"
    )
    result = run("gnomad_genomes", ["0.10", "0.20", "0.30"], index_map)
    assert result["overall"] == 0.1
    assert result["populations"] == {"ami": 0.20, "grpmax": 0.30}


def test_all_of_us_pattern_map_with_suffix():
    """AoU's pattern has a suffix (AoU_gvs_{pop}_af), unlike gnomAD's, plus a
    label column (AoU_gvs_max_subpop) naming which subpopulation the max
    frequency came from."""
    index_map = index_map_for(
        "AoU_gvs_all_af", "AoU_gvs_afr_af", "AoU_gvs_max_af", "AoU_gvs_max_subpop"
    )
    result = run("all_of_us", ["0.10", "0.20", "0.30", "eur"], index_map)
    assert result["overall"] == 0.10
    assert result["populations"] == {"afr": 0.20, "max": 0.30}
    assert result["max_subpopulation"] == "eur"
    # the label column is not a frequency and must not appear among populations
    assert "max_subpop" not in result["populations"]


def test_all_of_us_label_without_frequencies_is_none():
    """A max_subpop label with no frequencies is not an annotation — which is
    why max_subpopulation is deliberately absent from require_any_output."""
    index_map = index_map_for("AoU_gvs_all_af", "AoU_gvs_max_subpop")
    assert run("all_of_us", ["", "eur"], index_map) is None


# --- ProtVar: chunk + positional ---------------------------------------------

PROTVAR_FULL = dict(
    ProtVar_stability="0.42",
    ProtVar_pocket="POCKET1&-5.2&0.3&0.8&0.6&12.5&RES",
    ProtVar_int="PARTNER1&0.9&PARTNER2&0.8",
)


def test_protvar_shape_is_as_expected():
    result = run("protvar", row_list(**PROTVAR_FULL))
    assert result["structure_stability_score"] == 0.42

    pocket = result["pockets"][0]
    assert pocket["pocket_id"] == "POCKET1"
    assert pocket["energy"] == -5.2
    assert pocket["radius_of_gyration"] == 12.5
    # the trailing residues item is unnamed, so ignored -- but `raw` keeps it
    assert pocket["raw"] == PROTVAR_FULL["ProtVar_pocket"]

    assert [i["partner"] for i in result["interaction_interfaces"]] == [
        "PARTNER1",
        "PARTNER2",
    ]
    assert result["interaction_interfaces"][0]["score"] == 0.9
    assert result["interaction_interfaces"][0]["raw"] == "PARTNER1&0.9"


def test_protvar_multiple_pockets():
    """ProtVar_pocket packs one 7-field pocket after another; each must become
    its own item (chunk of 7), not just the first."""
    two = (
        "P4&897.5&83.3&0.36&0.79&7.6&res4"
        "&P12&515.8&87.7&0.33&0.75&4.3&res12"
    )
    pockets = run("protvar", row_list(ProtVar_pocket=two))["pockets"]
    assert [p["pocket_id"] for p in pockets] == ["P4", "P12"]
    assert pockets[0]["score"] == 0.36
    assert pockets[1]["score"] == 0.33
    assert pockets[1]["radius_of_gyration"] == 4.3


def test_protvar_odd_interaction_token_count():
    """A trailing partner with no score: still one interface, score null."""
    result = run("protvar", row_list(ProtVar_int="PARTNER1&0.9&PARTNER3"))
    assert result["interaction_interfaces"] == [
        {"partner": "PARTNER1", "score": 0.9, "raw": "PARTNER1&0.9"},
        {"partner": "PARTNER3", "score": None, "raw": "PARTNER3"},
    ]


def test_protvar_empty_is_none():
    assert run("protvar", EMPTY) is None


def test_protvar_pocket_missing_middle_value_does_not_shift():
    """An unparseable score empties only its own field: a pocket's fields are
    assigned strictly by index, so a bad item cannot pull the later values
    forward and have them silently reported under the wrong names."""
    raw = "POCKET1&-5.2&NA&0.8&0.6&12.5&RES"
    pocket = run("protvar", row_list(ProtVar_pocket=raw))["pockets"][0]

    assert pocket["energy"] == -5.2
    assert pocket["energy_per_volume"] is None
    assert pocket["score"] == 0.8
    assert pocket["buriedness"] == 0.6
    assert pocket["radius_of_gyration"] == 12.5


def test_protvar_interaction_na_partner_is_nulled():
    """'NA' means absent everywhere in the spec, including as a partner id."""
    interfaces = run("protvar", row_list(ProtVar_int="NA&0.9"))["interaction_interfaces"]
    assert interfaces[0]["partner"] is None


# --- OpenTargets: align:min + dedup + sort -----------------------------------

OT_COLS = [
    "OpenTargets_gwasDiseases", "OpenTargets_gwasGeneId",
    "OpenTargets_gwasLocusToGeneScore", "OpenTargets_qtlGeneId",
    "OpenTargets_qtlBiosampleName", "OpenTargets_pValueMantissa",
    "OpenTargets_pValueExponent", "OpenTargets_beta",
]
OT_INDEX = index_map_for(*OT_COLS)


def ot_row(
    diseases="",
    genes="",
    l2g="",
    qtl_genes="",
    qtl_biosamples="",
    mantissa=None,
    exponent=None,
    beta=None,
):
    """A CSQ row for the OpenTargets columns.

    The p-value and beta columns default to `NA` repeated to the width of the
    other columns, because that is what the source emits: all eight arrays are
    one table and always the same length, and `align: min` would otherwise
    truncate every association away when a test does not care about them.
    """
    width = max(
        (len(column.split("&")) for column in (diseases, genes, l2g, qtl_genes,
                                               qtl_biosamples) if column),
        default=0,
    )
    filler = "&".join(["NA"] * width)
    return [
        diseases,
        genes,
        l2g,
        qtl_genes,
        qtl_biosamples,
        filler if mantissa is None else mantissa,
        filler if exponent is None else exponent,
        filler if beta is None else beta,
    ]


def run_ot(**kwargs):
    return run("opentargets", ot_row(**kwargs), OT_INDEX)


def test_opentargets_sorts_strongest_first():
    result = run_ot(
        diseases="EFO_1&EFO_2&EFO_3",
        genes="ENSG1&ENSG2&ENSG3",
        l2g="0.1&0.9&NA",
    )
    # descending by score; the unscored association goes last
    assert [(a["disease"], a["l2g_score"]) for a in result["gwas_associations"]] == [
        ("EFO_2", 0.9),
        ("EFO_1", 0.1),
        ("EFO_3", None),
    ]


def test_opentargets_dedups_repeated_rows():
    """The plugin emits duplicate rows -- dedup fires on 93% of real records."""
    result = run_ot(diseases="EFO_1&EFO_1", genes="ENSG1&ENSG1", l2g="0.5&0.5")
    assert result["gwas_associations"] == [
        {
            "disease": "EFO_1",
            "gene_id": "ENSG1",
            "l2g_score": 0.5,
            "p_mantissa": None,
            "p_exponent": None,
            "beta": None,
            "p_value": None,
            "disease_label": None,
        }
    ]


def test_opentargets_drops_row_without_disease():
    result = run_ot(diseases="NA&EFO_2", genes="ENSG1&ENSG2", l2g="0.1&0.9")
    assert [a["disease"] for a in result["gwas_associations"]] == ["EFO_2"]


def test_opentargets_misaligned_columns_truncate():
    """align:min. Real data contains ragged columns (3 diseases, 2 genes), so
    the plugin's positional alignment is not guaranteed; zip drops the excess --
    with ragged input the true pairing is unknowable.
    """
    result = run_ot(diseases="EFO_1&EFO_2&EFO_3", genes="ENSG1&ENSG2", l2g="0.1&0.9")
    assert len(result["gwas_associations"]) == 2  # EFO_3 dropped


def test_opentargets_qtl_dedups_and_nulls_na_biosample():
    result = run_ot(qtl_genes="ENSG1&ENSG1&ENSG2", qtl_biosamples="liver&liver&NA")
    assert result["qtl_associations"] == [
        {
            "gene_id": "ENSG1",
            "biosample": "liver",
            "p_mantissa": None,
            "p_exponent": None,
            "beta": None,
            "p_value": None,
        },
        {
            "gene_id": "ENSG2",
            "biosample": None,
            "p_mantissa": None,
            "p_exponent": None,
            "beta": None,
            "p_value": None,
        },
    ]


def test_opentargets_empty_is_none():
    assert run_ot() is None


def test_opentargets_absent_columns_is_none():
    assert run("opentargets", ["A"], index_map_for("Allele")) is None


# --- GO: regex + replace/strip -----------------------------------------------

GO_INDEX = index_map_for("GO")


def test_go_terms_split_id_from_name():
    """The aspect is not in the plugin's output — it comes from the shipped
    `go_namespaces` table, which is what lets the display group the terms."""
    values = ["GO:0001558:regulation_of_cell_growth&GO:0005509:calcium_ion_binding"]
    assert run("go", values, GO_INDEX)["go_terms"] == [
        {
            "id": "GO:0001558",
            "name": "regulation of cell growth",
            "namespace": "biological_process",
        },
        {
            "id": "GO:0005509",
            "name": "calcium ion binding",
            "namespace": "molecular_function",
        },
    ]


def test_a_go_id_the_table_does_not_know_is_null_not_an_error():
    """GO releases and the annotation files move independently, so a term the
    shipped table has never heard of is a normal state — it groups as unknown
    rather than failing the parse."""
    parsed = run("go", ["GO:9999999:not_a_real_term"], GO_INDEX)["go_terms"]
    assert parsed == [
        {"id": "GO:9999999", "name": "not a real term", "namespace": None}
    ]


def test_go_entry_without_a_term_name_is_null_not_empty_string():
    """Real data carries ids with no name at all (38 of 368 distinct GO ids in
    dev-data/output.vcf.gz, e.g. "GO:0050911:"). An absent name is null, as
    everywhere else in the spec."""
    assert run("go", ["GO:0050911:"], GO_INDEX)["go_terms"] == [
        {"id": "GO:0050911", "name": None, "namespace": "biological_process"}
    ]


def test_go_entry_without_a_name_part_is_skipped():
    """Fewer than three ':'-parts is not a term."""
    assert run("go", ["GO:0001558"], GO_INDEX) is None


def test_go_absent_is_none():
    assert run("go", [""], GO_INDEX) is None


# --- SpliceAI: mixed float/int scalars ---------------------------------------

SPLICEAI_COLS = [
    "SpliceAI_pred_SYMBOL", "SpliceAI_pred_DS_AG", "SpliceAI_pred_DS_AL",
    "SpliceAI_pred_DS_DG", "SpliceAI_pred_DS_DL", "SpliceAI_pred_DP_AG",
    "SpliceAI_pred_DP_AL", "SpliceAI_pred_DP_DG", "SpliceAI_pred_DP_DL",
]
SPLICEAI_INDEX = index_map_for(*SPLICEAI_COLS)


def test_spliceai_all_scores():
    values = ["BRCA1", "0.01", "0.02", "0.03", "0.04", "-5", "10", "-20", "30"]
    assert run("spliceai", values, SPLICEAI_INDEX) == {
        "symbol": "BRCA1",
        "ds_acceptor_gain": 0.01,
        "ds_acceptor_loss": 0.02,
        "ds_donor_gain": 0.03,
        "ds_donor_loss": 0.04,
        "dp_acceptor_gain": -5,
        "dp_acceptor_loss": 10,
        "dp_donor_gain": -20,
        "dp_donor_loss": 30,
    }


def test_spliceai_zero_scores_are_kept():
    """0.00 is the commonest real value (170k+ entries): a real score, not
    absence. require_any_output must not discard it."""
    values = ["BRCA1", "0.00", "", "", "", "", "", "", ""]
    result = run("spliceai", values, SPLICEAI_INDEX)
    assert result is not None
    assert result["ds_acceptor_gain"] == 0.0
    assert result["ds_acceptor_loss"] is None


def test_spliceai_symbol_alone_is_not_an_annotation():
    values = ["BRCA1", "", "", "", "", "", "", "", ""]
    assert run("spliceai", values, SPLICEAI_INDEX) is None


# --- plain scalar/list plugins -----------------------------------------------
#
# No new vocabulary; all five verified against dev-data/output.vcf.gz with zero
# mismatches (hgvs 210,658 / phenotype_data 382,715 / dosage 393,079 /
# intact 25 / popeve 96,953 CSQ entries).


def test_hgvs_three_notations():
    index_map = index_map_for("HGVSg", "HGVSc", "HGVSp")
    values = ["NC_1:g.100A>G", "ENST1:c.50A>G", "ENSP1:p.Lys1Arg"]
    assert run("hgvs", values, index_map) == {
        "genomic": "NC_1:g.100A>G",
        "transcript": "ENST1:c.50A>G",
        "protein": "ENSP1:p.Lys1Arg",
    }


def test_hgvs_partial():
    """This run emits HGVSc/HGVSp but no HGVSg -- the absent one is null."""
    index_map = index_map_for("HGVSc", "HGVSp")
    assert run("hgvs", ["ENST1:c.50A>G", ""], index_map) == {
        "genomic": None,
        "transcript": "ENST1:c.50A>G",
        "protein": None,
    }


def test_hgvs_empty_is_none():
    index_map = index_map_for("HGVSg", "HGVSc", "HGVSp")
    assert run("hgvs", ["", "", ""], index_map) is None


def test_phenotype_data_splits_entries_into_their_cols():
    # The Phenotypes plugin produces a single PHENOTYPES column: '&'-separated
    # entries, each '+'-separated into the fields named by the plugin's `cols`
    # (type, source, phenotype, id, risk_allele, clinvar_clin_sig). Absent
    # trailing fields come back null. ClinVar associations go to their own
    # target, so this one carries none.
    index_map = index_map_for("Allele", "PHENOTYPES")
    gene = "Gene+GenCC+Parkinson_disease+ENSG00000145335++"
    variation = "Variation+NHGRI-EBI_GWAS_catalog+Atrial_fibrillation+rs699+A+"
    result = run("phenotype_data", ["A", f"{gene}&{variation}"], index_map)
    assert result["clinvar_phenotypes"] == []
    assert result["phenotypes"] == [
            {
                "type": "Gene",
                "source": "GenCC",
                "phenotype": "Parkinson_disease",
                "id": "ENSG00000145335",
                "risk_allele": None,
            },
            {
                "type": "Variation",
                "source": "NHGRI-EBI_GWAS_catalog",
                "phenotype": "Atrial_fibrillation",
                "id": "rs699",
                "risk_allele": "A",
            },
        ]


def test_phenotype_data_skips_entries_missing_a_required_field():
    """type / source / phenotype must all be present; an entry missing any of
    them is dropped rather than rendered half-empty. (Entries with a different
    field count are dropped for the same reason — the pattern must match.)"""
    index_map = index_map_for("PHENOTYPES")
    good = "Gene+GenCC+Parkinson_disease+ENSG00000145335++"
    result = run(
        "phenotype_data",
        [
            "Gene++Parkinson_disease+ENSG1++"  # no source
            "&Gene+GenCC++ENSG2++"  # no phenotype
            "&+GenCC+Parkinson_disease+ENSG3++"  # no type
            "&Cancer_Gene_Census+cancer+ENSG4++"  # 5 fields (pre-`type` shape)
            f"&{good}"
        ],
        index_map,
    )
    assert [p["id"] for p in result["phenotypes"]] == ["ENSG00000145335"]


def test_phenotype_data_splits_clinvar_into_its_own_target():
    """Only ClinVar associations carry a clinical significance, and they get
    their own table, so they are parsed into their own target: the `phenotypes`
    pattern excludes source "ClinVar" and the `clinvar_phenotypes` one pins it.
    Neither leaks into the other."""
    index_map = index_map_for("Allele", "PHENOTYPES")
    result = run(
        "phenotype_data",
        [
            "A",
            "Variation+ClinVar+Parkinson_disease+rs1+A+pathogenic"
            "&Variation+NHGRI-EBI_GWAS_catalog+Albumin_levels+rs2+A+"
            "&Gene+GenCC+Parkinson_disease+ENSG1++",
        ],
        index_map,
    )
    assert [(p["source"], p["clinvar_clin_sig"]) for p in result["clinvar_phenotypes"]] == [
        ("ClinVar", "pathogenic")
    ]
    assert [p["source"] for p in result["phenotypes"]] == [
        "NHGRI-EBI_GWAS_catalog",
        "GenCC",
    ]
    # the non-ClinVar target does not carry the significance field at all
    assert "clinvar_clin_sig" not in result["phenotypes"][0]


def test_phenotype_data_variation_is_scoped_to_its_risk_allele():
    """A variation association belongs to the allele its risk allele names.

    VEP repeats the whole PHENOTYPES value on every alt allele's CSQ row, so a
    multi-allelic site would otherwise show every allele's associations against
    each of them (rs139548132, alts C/G/T). `drop_when.unless_matches` keeps only
    the associations whose risk allele is this row's `Allele`; an association
    with no risk allele never matches, so it drops too. A gene association
    carries no allele at all and must survive — `only_if` scopes the rule.
    """
    index_map = index_map_for("Allele", "PHENOTYPES")
    entries = (
        "Variation+ClinVar+Neurodevelopmental_disorder+rs139548132+C+pathogenic"
        "&Variation+ClinVar+Inborn_genetic_diseases+rs139548132+G+benign"
        "&Variation+ClinVar+No_risk_allele+rs139548132++pathogenic"
        "&Gene+GenCC+Parkinson_disease+ENSG00000145335++"
    )
    def kept(allele):
        out = run("phenotype_data", [allele, entries], index_map)
        return [
            (p["type"], p["risk_allele"], p["phenotype"])
            for p in out["clinvar_phenotypes"] + out["phenotypes"]
        ]
    assert kept("C") == [
        ("Variation", "C", "Neurodevelopmental_disorder"),
        ("Gene", None, "Parkinson_disease"),
    ]
    assert kept("G") == [
        ("Variation", "G", "Inborn_genetic_diseases"),
        ("Gene", None, "Parkinson_disease"),
    ]
    # an allele none of the associations name keeps only the gene one
    assert kept("T") == [("Gene", None, "Parkinson_disease")]


def test_phenotype_data_drops_placeholder_phenotypes():
    """A source's stand-in for "we have no phenotype" is not an association:
    ClinVar emits "ClinVar:_phenotype_not_specified" (and bare "not_specified" /
    "not_provided") where a real term would go, and showing those as rows tells
    the reader nothing. Dropped from both targets, whatever the casing."""
    index_map = index_map_for("Allele", "PHENOTYPES")
    result = run(
        "phenotype_data",
        [
            "A",
            "Variation+ClinVar+ClinVar:_phenotype_not_specified+rs1+A+pathogenic"
            "&Variation+ClinVar+Neurodevelopmental_disorder+rs1+A+pathogenic"
            "&Gene+GenCC+Not_provided+ENSG1++"
            "&Gene+GenCC+Parkinson_disease+ENSG1++",
        ],
        index_map,
    )
    assert [p["phenotype"] for p in result["clinvar_phenotypes"]] == [
        "Neurodevelopmental_disorder"
    ]
    assert [p["phenotype"] for p in result["phenotypes"]] == ["Parkinson_disease"]


def test_phenotype_data_all_placeholders_is_none():
    """Every association being a placeholder leaves nothing to show, which
    `require_any_output` turns into no annotation at all rather than an empty
    table."""
    index_map = index_map_for("Allele", "PHENOTYPES")
    assert (
        run(
            "phenotype_data",
            ["A", "Variation+ClinVar+ClinVar:_phenotype_not_specified+rs1+A+pathogenic"],
            index_map,
        )
        is None
    )


def test_phenotype_data_empty_is_none():
    index_map = index_map_for("PHENOTYPES")
    assert run("phenotype_data", [""], index_map) is None


def test_dosage_sensitivity_probabilities():
    index_map = index_map_for("pHaplo", "pTriplo")
    assert run("dosage_sensitivity", ["0.98", "0.12"], index_map) == {
        "phaplo": 0.98, "ptriplo": 0.12
    }


def test_dosage_sensitivity_zero_is_kept():
    """0.0 is a real probability, not absence."""
    index_map = index_map_for("pHaplo", "pTriplo")
    assert run("dosage_sensitivity", ["0.0", ""], index_map) == {
        "phaplo": 0.0, "ptriplo": None
    }


# IntAct's real maximal output: seven parallel `&`-joined columns, one entry per
# interaction. Values are a real run for P37840 p.Ala53Thr.
INTACT_AP_AC = "&".join(["uniprotkb:P37840"] * 10)
INTACT_FEATURE_AC = (
    "EBI-27104121&EBI-8841557&EBI-27092285&EBI-27092289&EBI-36480383&"
    "EBI-27101618&EBI-27104129&EBI-7778039&EBI-9214100&EBI-27092688"
)
INTACT_SHORT_LABEL = "&".join(["P37840:p.Ala53Thr"] * 10)
INTACT_FEATURE_TYPE = (
    "mutation&mutation&mutation_decreasing&mutation_decreasing&"
    "mutation_decreasing&mutation_decreasing_strength&"
    "mutation_decreasing_strength&mutation_disrupting&mutation_increasing&"
    "mutation_increasing_strength"
)
INTACT_INTERACTION_AC = (
    "EBI-27104114&EBI-8841537&EBI-27091991&EBI-27092138&EBI-36480377&"
    "EBI-27101607&EBI-27104123&EBI-7778024&EBI-9214092&EBI-27092683"
)
INTACT_PARTICIPANTS = (
    "uniprotkb:P00520_and_uniprotkb:P37840&uniprotkb:P00414_and_uniprotkb:P37840&"
    "uniprotkb:P37840_and_uniprotkb:P00441&uniprotkb:P37840_and_uniprotkb:P00441&"
    "uniprotkb:P37840_and_uniprotkb:P00441&uniprotkb:P00519_and_uniprotkb:P37840&"
    "uniprotkb:P00520_and_uniprotkb:P37840&uniprotkb:P68510_and_uniprotkb:P37840&"
    "uniprotkb:P37840_and_uniprotkb:Q9Y6H5&"
    "uniprotkb:P37840_and_uniprotkb:P00441_and_uniprotkb:P00441"
)
INTACT_PMID = (
    "27348587&12059041&26643113&26643113&26643113&27348587&27348587&"
    "16096643&10319874&26643113"
)

INTACT_COLUMNS = (
    "IntAct_interaction_ac", "IntAct_feature_type",
    "IntAct_interaction_participants", "IntAct_feature_short_label",
    "IntAct_ap_ac", "IntAct_pmid", "IntAct_feature_ac",
)
INTACT_MAXIMAL = [
    INTACT_INTERACTION_AC, INTACT_FEATURE_TYPE, INTACT_PARTICIPANTS,
    INTACT_SHORT_LABEL, INTACT_AP_AC, INTACT_PMID, INTACT_FEATURE_AC,
]


def test_intact_zips_the_parallel_columns_into_one_row_per_interaction():
    """The columns are positional: entry i of every column describes the same
    interaction. Reporting them as seven separate lists (as this used to) loses
    that correspondence entirely."""
    result = run("intact", INTACT_MAXIMAL, index_map_for(*INTACT_COLUMNS))
    interactions = result["interactions"]

    assert len(interactions) == 10
    assert interactions[0] == {
        "interaction_ac": "EBI-27104114",
        "feature_type": "mutation",
        "interaction_participants": "uniprotkb:P00520_and_uniprotkb:P37840",
        "feature_short_label": "P37840:p.Ala53Thr",
        "ap_ac": "uniprotkb:P37840",
        "pmid": "27348587",
        "feature_ac": "EBI-27104121",
    }
    # The last entry has three participants, not two — the display splits them.
    assert interactions[-1]["interaction_ac"] == "EBI-27092683"
    # underscores are the vocabulary's word separators, restored for display
    assert interactions[-1]["feature_type"] == "mutation increasing strength"
    assert interactions[-1]["interaction_participants"].count("_and_") == 2
    assert interactions[-1]["pmid"] == "26643113"


def test_intact_unselected_sub_options_come_back_null_per_interaction():
    """A run with only the always-on columns still yields one row per
    interaction; the unselected sub-options are null inside each row rather
    than collapsing the rows together."""
    result = run(
        "intact",
        [INTACT_INTERACTION_AC, INTACT_FEATURE_TYPE],
        index_map_for("IntAct_interaction_ac", "IntAct_feature_type"),
    )
    interactions = result["interactions"]

    assert len(interactions) == 10
    assert interactions[0] == {
        "interaction_ac": "EBI-27104114",
        "feature_type": "mutation",
        "interaction_participants": None,
        "feature_short_label": None,
        "ap_ac": None,
        "pmid": None,
        "feature_ac": None,
    }


def test_intact_feature_annotation_is_no_longer_parsed():
    """Dropped: sparse, of little use, and returned in a form that resisted
    parsing."""
    result = run("intact", INTACT_MAXIMAL, index_map_for(*INTACT_COLUMNS))
    assert all("feature_annotation" not in i for i in result["interactions"])


def test_popeve_scores():
    index_map = index_map_for(
        "popEVE_SCORE", "popEVE_EVE", "popEVE_ESM1v", "popEVE_gene",
        "popEVE_mutant", "popEVE_gap_frequency",
    )
    values = ["-0.5", "-1.2", "-3.4", "BRCA1", "K1R", "0.02"]
    assert run("popeve", values, index_map) == {
        "score": -0.5,
        "eve": -1.2,
        "esm1v": -3.4,
        "pop_adjusted_eve": None,
        "pop_adjusted_esm1v": None,
        "gene": "BRCA1",
        "protein": None,
        "mutant": "K1R",
        "gap_frequency": 0.02,
    }


def test_popeve_empty_is_none():
    index_map = index_map_for("popEVE_SCORE", "popEVE_EVE", "popEVE_mutant")
    assert run("popeve", ["", "", ""], index_map) is None


# --- pathogenicity, dissolved ------------------------------------------------
#
# The deleted `_parse_pathogenicity` grouped several unrelated predictors into
# one object and nested spliceai/popeve (themselves standalone plugins) inside
# it. The grouping is not what the flat annotation payload wants, so the spec
# models each member as its own plugin. Verified on real data at cutover time
# (revel 11,290 / alphamissense 62,384 / cadd 419,210 / eve 14,968 CSQ entries,
# zero mismatches against the nested object).

PATH_COLS = ["REVEL", "am_class", "am_pathogenicity", "CADD_PHRED", "CADD_RAW",
             "EVE_CLASS", "EVE_SCORE"]
PATH_INDEX = index_map_for(*PATH_COLS)
PATH_VALUES = ["0.7", "likely_pathogenic", "0.9", "25.1", "3.2", "Pathogenic", "0.85"]


def test_flat_plugins_carry_the_former_pathogenicity_members():
    assert run("revel", PATH_VALUES, PATH_INDEX) == {"score": 0.7}
    assert run("alphamissense", PATH_VALUES, PATH_INDEX) == {
        "classification": "likely_pathogenic", "score": 0.9
    }
    assert run("cadd", PATH_VALUES, PATH_INDEX) == {"phred": 25.1, "raw": 3.2}
    assert run("eve", PATH_VALUES, PATH_INDEX) == {
        "classification": "Pathogenic", "score": 0.85
    }


def test_flat_pathogenicity_members_are_independent():
    """Only REVEL present: revel is an annotation, the others are absent.

    The old nested object could not express this -- it returned one object
    carrying a revel score and six nulls.
    """
    values = ["0.7", "", "", "", "", "", ""]
    assert run("revel", values, PATH_INDEX) == {"score": 0.7}
    assert run("alphamissense", values, PATH_INDEX) is None
    assert run("cadd", values, PATH_INDEX) is None
    assert run("eve", values, PATH_INDEX) is None


def test_flat_pathogenicity_members_absent_are_none():
    values = ["", "", "", "", "", "", ""]
    for plugin in ("revel", "alphamissense", "cadd", "eve"):
        assert run(plugin, values, PATH_INDEX) is None


def test_cadd_zero_is_kept():
    values = ["", "", "", "0.0", "0.0", "", ""]
    assert run("cadd", values, PATH_INDEX) == {"phred": 0.0, "raw": 0.0}


# --- the plugins added by the go-flat cutover --------------------------------


def test_loeuf_is_a_transcript_scoped_score():
    spec = SPEC.plugin("loeuf")
    assert spec.scope == "transcript"
    index_map = index_map_for("LOEUF")
    assert run("loeuf", ["0.15"], index_map) == {"score": 0.15}
    assert run("loeuf", [""], index_map) is None


def test_spdi_and_hgvsg_are_allele_scoped():
    """Both are allele-scoped because intergenic variants have no transcript
    rows and must still carry their variant representations."""
    assert SPEC.plugin("spdi").scope == "allele"
    assert SPEC.plugin("hgvsg").scope == "allele"

    spdi_map = index_map_for("SPDI")
    assert run("spdi", ["1:79106:T:C"], spdi_map) == {"spdi": "1:79106:T:C"}
    assert run("spdi", [""], spdi_map) is None

    hgvsg_map = index_map_for("HGVSg")
    assert run("hgvsg", ["1:g.79107T>C"], hgvsg_map) == {"genomic": "1:g.79107T>C"}
    assert run("hgvsg", [""], hgvsg_map) is None


# --- UTRAnnotator ------------------------------------------------------------

UTR_COLS = ["5UTR_consequence", "5UTR_annotation", "Existing_uORFs",
            "Existing_InFrame_oORFs", "Existing_OutOfFrame_oORFs"]
UTR_INDEX = index_map_for(*UTR_COLS)
# A real value from dev-data/has_utr.vcf.gz.
UTR_ANNOTATION = (
    "alt_type=uORF:ref_StartDistanceToCDS=324:ref_type=uORF:KozakStrength=Moderate"
    ":KozakContext=GCGATGC:ref_type_length=15:Evidence=False:alt_type_length=189"
)
UTR_VALUES = ["5_prime_UTR_uORF_frameshift_variant", UTR_ANNOTATION, "5", "0", "0"]


def test_utr_annotation_parses_the_detail_string_into_a_dict():
    """The deleted parser copied `annotation` verbatim as a ':'-delimited
    string; the spec parses it into a dict via `key_value`, which is the point
    of the transform (see the ordering test below)."""
    result = run("utr_annotation", UTR_VALUES, UTR_INDEX)
    assert result["consequence"] == "5_prime_UTR_uORF_frameshift_variant"
    assert result["existing_uorfs"] == "5"
    assert result["existing_inframe_oorfs"] == "0"
    assert result["existing_outofframe_oorfs"] == "0"
    assert result["annotation"] == {
        "alt_type": "uORF",
        "ref_StartDistanceToCDS": "324",
        "ref_type": "uORF",
        "KozakStrength": "Moderate",
        "KozakContext": "GCGATGC",
        "ref_type_length": "15",
        "Evidence": "False",
        "alt_type_length": "189",
    }


def test_utr_annotation_key_value_is_order_independent():
    """The actual bug this fixes: UTRAnnotator emits the same pairs in a
    different order every record (all 9 in has_utr.vcf.gz are one identical
    annotation shuffled 9 ways). The raw string is 9 different values; parsed
    as key_value, all 9 must be the same dict."""
    shuffled = "ref_type=uORF:alt_type=uORF:Evidence=False:KozakStrength=Moderate"
    original = "alt_type=uORF:KozakStrength=Moderate:ref_type=uORF:Evidence=False"
    assert shuffled != original  # different raw strings

    def annotation_of(value):
        row = ["", value, "", "", ""]
        return run("utr_annotation", row, UTR_INDEX)["annotation"]

    assert annotation_of(shuffled) == annotation_of(original)  # same parsed value


def test_utr_annotation_malformed_piece_is_dropped_not_raised():
    """A piece without '=' does not break parsing of the rest of the value."""
    row = ["", "alt_type=uORF:garbage:Evidence=False", "", "", ""]
    result = run("utr_annotation", row, UTR_INDEX)
    assert result["annotation"] == {"alt_type": "uORF", "Evidence": "False"}


def test_utr_annotation_empty_is_none():
    assert run("utr_annotation", ["", "", "", "", ""], UTR_INDEX) is None


def test_lookup_needs_all_three_of_by_into_and_table():
    """A half-specified lookup would silently write nothing on every row, so it
    fails at load rather than at results time."""
    from pydantic import ValidationError

    from app.vep.models.parsing_spec_model import PostOp

    with pytest.raises(ValidationError, match="lookup requires"):
        PostOp.model_validate({"op": "lookup", "by": "id", "into": "namespace"})
    with pytest.raises(ValidationError, match="`table` belongs to lookup"):
        PostOp.model_validate({"op": "dedup", "table": "go_namespaces"})
    # `into` is shared with concat and curie_link now, so it is rejected only for
    # the ops that write no field at all.
    with pytest.raises(ValidationError, match="belongs to lookup, concat or curie_link"):
        PostOp.model_validate({"op": "dedup", "into": "namespace"})


def test_tss_distance_keeps_the_sign():
    """`both_direction=1` makes the plugin measure downstream variants too, as a
    negative distance — so the value is a signed int, not a magnitude."""
    index_map = index_map_for("Allele", "TSSDistance")
    assert apply_plugin_spec(["A", "-13864"], index_map, SPEC.plugin("tss_distance")) == {
        "distance": -13864
    }
    assert apply_plugin_spec(["A", "988"], index_map, SPEC.plugin("tss_distance")) == {
        "distance": 988
    }


def test_tss_distance_absent_is_no_annotation():
    index_map = index_map_for("Allele", "TSSDistance")
    assert apply_plugin_spec(["A", ""], index_map, SPEC.plugin("tss_distance")) is None


def test_phenotype_rows_identical_in_every_field_are_collapsed():
    """The source repeats an association verbatim — rs699 carries "Systolic
    blood pressure / NHGRI-EBI GWAS catalog" twice — and the table showed it
    twice. `dedup` compares whole rows, so an association differing in any
    field (a different source, say) is still its own row."""
    index_map = index_map_for("Allele", "PHENOTYPES")
    # PHENOTYPES packs `+`-separated fields into `&`-separated entries.
    row = "Variation+{source}+Systolic_blood_pressure+rs699+G+"
    entry = "&".join(
        [
            row.format(source="NHGRI-EBI_GWAS_catalog"),
            row.format(source="NHGRI-EBI_GWAS_catalog"),  # the source's own repeat
            row.format(source="OtherSource"),
        ]
    )
    parsed = apply_plugin_spec(["G", entry], index_map, SPEC.plugin("phenotype_data"))
    rows = parsed["phenotypes"]
    assert len(rows) == 2, rows
    assert {r["source"] for r in rows} == {"NHGRI-EBI_GWAS_catalog", "OtherSource"}


def test_target_sep_splits_on_a_delimiter_vep_leaves_alone():
    """VEP rewrites both ',' and '|' to '&' in everything it emits, so a source
    that needs structure *below* the entry level has to carry a delimiter VEP
    does not touch. The enriched ClinVar VCF uses '+' between repeats; `sep`
    is what lets a target read it."""
    index_map = index_map_for("Allele", "Thing")
    spec = ParsingSpec(
        plugins=[
            {
                "plugin": "probe",
                "scope": "allele",
                "output": "probe",
                "csq_fields": ["Thing"],
                "require_any_output": ["items"],
                "targets": [
                    {
                        "field": "items",
                        "from": "Thing",
                        "transform": "list",
                        "sep": "+",
                    }
                ],
            }
        ]
    )
    plugin = spec.plugin("probe")
    assert apply_plugin_spec(["A", "one+two+three"], index_map, plugin) == {
        "items": ["one", "two", "three"]
    }
    # '&' is now just a character in the value, not a separator.
    assert apply_plugin_spec(["A", "a&b+c"], index_map, plugin) == {
        "items": ["a&b", "c"]
    }


def test_target_sep_defaults_to_amp():
    index_map = index_map_for("Allele", "Thing")
    spec = ParsingSpec(
        plugins=[
            {
                "plugin": "probe",
                "scope": "allele",
                "output": "probe",
                "csq_fields": ["Thing"],
                "require_any_output": ["items"],
                "targets": [
                    {"field": "items", "from": "Thing", "transform": "list"}
                ],
            }
        ]
    )
    assert apply_plugin_spec(["A", "one&two"], index_map, spec.plugin("probe")) == {
        "items": ["one", "two"]
    }


def test_field_null_values_blank_a_placeholder_token():
    """ClinVar writes '.' where a condition has no ontology ids. It must read as
    absent, but only where it is declared: '.' is a real value in other fields,
    so this is per-field rather than global."""
    index_map = index_map_for("Allele", "Names", "Ids")
    spec = ParsingSpec(
        plugins=[
            {
                "plugin": "probe",
                "scope": "allele",
                "output": "probe",
                "csq_fields": ["Names", "Ids"],
                "require_any_output": ["conditions"],
                "targets": [
                    {
                        "field": "conditions",
                        "from": ["Names", "Ids"],
                        "transform": "zip",
                        "sep": "+",
                        "align": "max",
                        "as": [
                            {"field": "name", "type": "string"},
                            {
                                "field": "ids",
                                "type": "string",
                                "null_values": ["."],
                            },
                        ],
                    }
                ],
            }
        ]
    )
    result = apply_plugin_spec(
        ["A", "Disease_one+Disease_two", "MeSH:D1,MedGen:C1+."],
        index_map,
        spec.plugin("probe"),
    )
    assert result == {
        "conditions": [
            {"name": "Disease_one", "ids": "MeSH:D1,MedGen:C1"},
            {"name": "Disease_two", "ids": None},
        ]
    }


def test_decode_happens_after_every_split():
    """An escaped separator must survive as data.

    ClinVar escapes ',' inside disease names and CURIE lists, and the enriched
    VCF then uses '+' as its own separator. Decoding first would turn a '%2C'
    back into a live comma before the splits ran; decoding last, as the
    interpreter does, keeps it inside the value it belongs to.
    """
    index_map = index_map_for("Allele", "Names", "Ids")
    spec = ParsingSpec(
        plugins=[
            {
                "plugin": "probe",
                "scope": "allele",
                "output": "probe",
                "csq_fields": ["Names", "Ids"],
                "require_any_output": ["conditions"],
                "targets": [
                    {
                        "field": "conditions",
                        "from": ["Names", "Ids"],
                        "transform": "zip",
                        "sep": "+",
                        "decode": True,
                        "as": [
                            {"field": "name", "type": "string"},
                            {"field": "ids", "type": "string", "null_values": ["."]},
                        ],
                    }
                ],
            }
        ]
    )
    result = apply_plugin_spec(
        [
            "A",
            # one name containing an escaped comma, then a second name
            "Neurodevelopmental_disorder%2C_mitochondrial+Inborn_disease",
            "MONDO:MONDO:0060578%2CMedGen:C4540192+.",
        ],
        index_map,
        spec.plugin("probe"),
    )
    assert result == {
        "conditions": [
            {
                "name": "Neurodevelopmental_disorder,_mitochondrial",
                "ids": "MONDO:MONDO:0060578,MedGen:C4540192",
            },
            {"name": "Inborn_disease", "ids": None},
        ]
    }


def test_decode_is_off_by_default():
    """A '%' that is genuinely part of a value must not be mangled."""
    index_map = index_map_for("Allele", "Thing")
    spec = ParsingSpec(
        plugins=[
            {
                "plugin": "probe",
                "scope": "allele",
                "output": "probe",
                "csq_fields": ["Thing"],
                "require_any_output": ["value"],
                "targets": [
                    {"field": "value", "from": "Thing", "transform": "scalar"}
                ],
            }
        ]
    )
    assert apply_plugin_spec(["A", "100%2C"], index_map, spec.plugin("probe")) == {
        "value": "100%2C"
    }


def _joined(joins, **columns):
    """A two-list plugin with `joins` applied, over the given raw columns."""
    index_map = index_map_for("Allele", "Names", "Recs")
    spec = ParsingSpec(
        plugins=[
            {
                "plugin": "probe",
                "scope": "allele",
                "output": "probe",
                "csq_fields": ["Names", "Recs"],
                "require_any_output": ["conditions"],
                "targets": [
                    {
                        "field": "conditions",
                        "from": "Names",
                        "transform": "records",
                        "sep": "+",
                        "item_sep": "~",
                        "decode": True,
                        "as": [
                            {"field": "name", "type": "string"},
                            # Only the `also_match` test fills this; the rest
                            # pass bare names, so it comes out null.
                            {"field": "kind", "type": "string"},
                        ],
                    },
                    {
                        "field": "records",
                        "from": "Recs",
                        "transform": "records",
                        "sep": "&",
                        "item_sep": "~",
                        "decode": True,
                        "as": [
                            {"field": "acc", "type": "string"},
                            {"field": "verdict", "type": "string"},
                            {"field": "condition", "type": "string"},
                        ],
                    },
                ],
                "joins": joins,
            }
        ]
    )
    return apply_plugin_spec(
        ["A", columns["names"], columns["recs"]], index_map, spec.plugin("probe")
    )


def test_join_attaches_matching_rows_by_key():
    result = _joined(
        [{"into": "conditions", "from": "records", "left_key": "name",
          "right_key": "condition", "as": "records"}],
        names="Disease_one+Disease_two",
        recs="R1~Pathogenic~Disease_one&R2~Benign~Disease_two",
    )
    assert [c["name"] for c in result["conditions"]] == ["Disease_one", "Disease_two"]
    assert [r["acc"] for r in result["conditions"][0]["records"]] == ["R1"]
    assert [r["acc"] for r in result["conditions"][1]["records"]] == ["R2"]


def test_join_matches_case_insensitively_when_asked():
    """ClinVar submitters write the same condition in different cases; an exact
    match would drop them from their own condition's counts."""
    joins = [{"into": "conditions", "from": "records", "left_key": "name",
              "right_key": "condition", "as": "records"}]
    exact = _joined(joins, names="Disease_one", recs="R1~Pathogenic~DISEASE_ONE")
    assert exact["conditions"][0]["records"] == []

    joins[0]["case_insensitive"] = True
    loose = _joined(joins, names="Disease_one", recs="R1~Pathogenic~DISEASE_ONE")
    assert [r["acc"] for r in loose["conditions"][0]["records"]] == ["R1"]


def test_join_key_pattern_extracts_the_comparable_part():
    """The two lists key on the same condition, but one writes it decorated —
    ClinVar's RCV condition is `MedGen:C4540192:<name>`."""
    result = _joined(
        [{"into": "conditions", "from": "records", "left_key": "name",
          "right_key": "condition", "as": "records",
          "right_key_pattern": r"^(?:[^:]+:[^:]+:)?(?P<key>.*)$"}],
        names="Disease_one",
        recs="R1~Pathogenic~MedGen:C123:Disease_one",
    )
    assert [r["acc"] for r in result["conditions"][0]["records"]] == ["R1"]


def test_join_places_a_row_under_every_condition_it_names():
    """One ClinVar record can be filed against several conditions at once. It
    belongs under each of them — without the split it matched none, because the
    whole '+'-joined string was the key."""
    result = _joined(
        [{"into": "conditions", "from": "records", "left_key": "name",
          "right_key": "condition", "as": "records", "right_key_sep": "+",
          "right_key_pattern": r"^(?:[^:]+:[^:]+:)?(?P<key>.*)$"}],
        names="Disease_one+Disease_two",
        recs="R1~Pathogenic~MedGen:C1:Disease_one+MedGen:C2:Disease_two",
    )
    assert [r["acc"] for r in result["conditions"][0]["records"]] == ["R1"]
    assert [r["acc"] for r in result["conditions"][1]["records"]] == ["R1"]


def test_join_count_by_summarises_the_matches():
    """"How many submitters said what", grouped in first-seen order, so the
    display renders counts rather than counting."""
    result = _joined(
        [{"into": "conditions", "from": "records", "left_key": "name",
          "right_key": "condition", "as": "classifications",
          "count_by": "verdict"}],
        names="Disease_one",
        recs=("R1~Pathogenic~Disease_one&R2~Pathogenic~Disease_one"
              "&R3~Benign~Disease_one"),
    )
    assert result["conditions"][0]["classifications"] == [
        {"verdict": "Pathogenic", "count": 2},
        {"verdict": "Benign", "count": 1},
    ]


def test_join_nest_as_keeps_each_group_beside_its_count():
    """A count the reader can open needs the rows it was made of, grouped the
    same way -- otherwise opening "Pathogenic (2)" shows every submitter of
    every classification."""
    result = _joined(
        [{"into": "conditions", "from": "records", "left_key": "name",
          "right_key": "condition", "as": "classifications",
          "count_by": "verdict", "nest_as": "members"}],
        names="Disease_one",
        recs=("R1~Pathogenic~Disease_one&R2~Pathogenic~Disease_one"
              "&R3~Benign~Disease_one"),
    )
    groups = result["conditions"][0]["classifications"]
    assert [g["verdict"] for g in groups] == ["Pathogenic", "Benign"]
    assert [[m["acc"] for m in g["members"]] for g in groups] == [
        ["R1", "R2"],
        ["R3"],
    ]
    assert [g["count"] for g in groups] == [2, 1]


def test_join_nest_as_needs_a_grouping_to_nest_under():
    from pydantic import ValidationError

    from app.vep.models.parsing_spec_model import JoinSpec

    with pytest.raises(ValidationError, match="nest_as"):
        JoinSpec(**{"into": "conditions", "from": "records", "left_key": "name",
                    "right_key": "condition", "as": "classifications",
                    "nest_as": "members"})


def test_join_leaves_an_unmatched_left_row_empty():
    result = _joined(
        [{"into": "conditions", "from": "records", "left_key": "name",
          "right_key": "condition", "as": "records"}],
        names="Disease_one+Orphan_disease",
        recs="R1~Pathogenic~Disease_one",
    )
    assert result["conditions"][1]["records"] == []


def _curie_link(ids, **overrides):
    """A one-row list carrying `ids`, with the ClinVar curie_link post-op."""
    index_map = index_map_for("Allele", "Names", "Ids")
    post = {
        "op": "curie_link", "by": "ids", "into": "id_url", "label_into": "id_curie",
        "prefer": ["MedGen", "OMIM", "MONDO"],
        "templates": {
            "MedGen": "https://www.ncbi.nlm.nih.gov/medgen/{id}",
            "OMIM": "https://www.omim.org/entry/{id}",
            "MONDO": "https://purl.obolibrary.org/obo/MONDO_{id}",
            "MeSH": "https://meshb.nlm.nih.gov/record/ui?ui={id}",
        },
        **overrides,
    }
    spec = ParsingSpec(
        plugins=[
            {
                "plugin": "probe", "scope": "allele", "output": "probe",
                "csq_fields": ["Names", "Ids"], "require_any_output": ["conditions"],
                "targets": [
                    {
                        "field": "conditions", "from": ["Names", "Ids"],
                        "transform": "zip", "sep": "+", "decode": True,
                        "as": [
                            {"field": "name", "type": "string"},
                            {"field": "ids", "type": "string", "null_values": ["."]},
                        ],
                        "post": [post],
                    }
                ],
            }
        ]
    )
    out = apply_plugin_spec(["A", "Disease", ids], index_map, spec.plugin("probe"))
    return out["conditions"][0]


def test_curie_link_prefers_medgen():
    row = _curie_link("MeSH:D030342%2CMedGen:C0950123")
    assert row["id_url"] == "https://www.ncbi.nlm.nih.gov/medgen/C0950123"
    assert row["id_curie"] == "MedGen:C0950123"


def test_curie_link_falls_back_through_the_preference_order():
    assert _curie_link("OMIM:617710%2CMONDO:MONDO:0060578")["id_url"] == (
        "https://www.omim.org/entry/617710"
    )
    assert _curie_link("MONDO:MONDO:0060578")["id_url"] == (
        # MONDO writes itself as `MONDO:MONDO:0060578` — the tag plus a
        # self-prefixing CURIE. The bare accession is what the URL wants.
        "https://purl.obolibrary.org/obo/MONDO_0060578"
    )


def test_curie_link_takes_an_unpreferred_source_rather_than_nothing():
    assert _curie_link("MeSH:D030342")["id_url"] == (
        "https://meshb.nlm.nih.gov/record/ui?ui=D030342"
    )


def test_curie_link_writes_null_when_there_is_no_usable_id():
    # ClinVar writes '.' for a condition it has no ontology id for; the name
    # then renders as plain text rather than a dead link.
    row = _curie_link(".")
    assert row["ids"] is None
    assert row["id_url"] is None
    assert row["id_curie"] is None


def test_curie_link_ignores_a_source_it_has_no_template_for():
    assert _curie_link("Nonesuch:12345")["id_url"] is None


# --- the `stack` transform --------------------------------------------------


def _stacked(groups, **columns):
    """A one-target plugin whose target stacks `groups` over the given columns."""
    index_map = index_map_for("Allele", "GermDN", "GermIDs", "SomDN", "SomIDs")
    spec = ParsingSpec(
        plugins=[
            {
                "plugin": "probe",
                "scope": "allele",
                "output": "probe",
                "csq_fields": ["GermDN", "SomDN"],
                "targets": [
                    {
                        "field": "conditions",
                        "transform": "stack",
                        "of": groups,
                        "item_fields": ["name", "ids", "type"],
                    }
                ],
            }
        ]
    )
    return apply_plugin_spec(
        [
            "A",
            columns.get("germ_dn", ""),
            columns.get("germ_ids", ""),
            columns.get("som_dn", ""),
            columns.get("som_ids", ""),
        ],
        index_map,
        spec.plugin("probe"),
    )


_STACK_GROUPS = [
    {
        "from": ["GermDN", "GermIDs"],
        "as": [{"field": "name", "type": "string"}, {"field": "ids", "type": "string"}],
        "const": {"type": "Germline"},
        "sep": "+",
    },
    {
        "from": ["SomDN", "SomIDs"],
        "as": [{"field": "name", "type": "string"}, {"field": "ids", "type": "string"}],
        "const": {"type": "Somatic"},
        "sep": "+",
    },
]


def test_stack_concatenates_its_groups_in_order():
    result = _stacked(
        _STACK_GROUPS,
        germ_dn="Disease_one+Disease_two",
        germ_ids="MedGen:C1+MedGen:C2",
        som_dn="Tumour_one",
        som_ids="MedGen:C3",
    )
    assert [(c["name"], c["ids"]) for c in result["conditions"]] == [
        ("Disease_one", "MedGen:C1"),
        ("Disease_two", "MedGen:C2"),
        ("Tumour_one", "MedGen:C3"),
    ]


def test_stack_tags_every_row_with_its_group():
    """The tag is the only record of which columns a row came from -- ClinVar
    carries the classification type in the column *names* (CLNDN vs SCIDN), and
    nowhere in the values."""
    result = _stacked(
        _STACK_GROUPS,
        germ_dn="Disease_one+Disease_two",
        germ_ids=".+.",
        som_dn="Tumour_one",
        som_ids=".",
    )
    assert [c["type"] for c in result["conditions"]] == [
        "Germline",
        "Germline",
        "Somatic",
    ]


def test_stack_keeps_a_name_that_appears_under_two_types():
    """The same condition can be both germline and somatic; it is two rows, not
    one, because the classifications behind them are different claims."""
    result = _stacked(
        _STACK_GROUPS,
        germ_dn="Shared_disease",
        germ_ids="MedGen:C1",
        som_dn="Shared_disease",
        som_ids="MedGen:C1",
    )
    assert [(c["name"], c["type"]) for c in result["conditions"]] == [
        ("Shared_disease", "Germline"),
        ("Shared_disease", "Somatic"),
    ]


def test_stack_skips_a_group_whose_columns_are_empty():
    result = _stacked(
        _STACK_GROUPS, germ_dn="Disease_one", germ_ids="MedGen:C1", som_dn="", som_ids=""
    )
    assert [c["type"] for c in result["conditions"]] == ["Germline"]


def test_stack_over_scalar_columns_yields_one_row_per_group():
    """A group of scalar columns is a zip of one-element lists -- which is how
    three aggregate classifications become a three-row list."""
    result = _stacked(
        [
            {
                "from": ["GermDN", "GermIDs"],
                "as": [
                    {"field": "name", "type": "string"},
                    {"field": "ids", "type": "string"},
                ],
                "const": {"type": "Germline"},
            },
            {
                "from": ["SomDN", "SomIDs"],
                "as": [
                    {"field": "name", "type": "string"},
                    {"field": "ids", "type": "string"},
                ],
                "const": {"type": "Somatic"},
            },
        ],
        germ_dn="Pathogenic",
        germ_ids="reviewed_by_expert_panel",
        som_dn="Tier_I",
        som_ids="criteria_provided",
    )
    assert [(c["name"], c["type"]) for c in result["conditions"]] == [
        ("Pathogenic", "Germline"),
        ("Tier_I", "Somatic"),
    ]


def test_stack_rejects_a_group_whose_as_does_not_match_its_columns():
    from pydantic import ValidationError

    from app.vep.models.parsing_spec_model import StackGroup

    with pytest.raises(ValidationError, match="one `as` entry per `from` column"):
        StackGroup.model_validate(
            {"from": ["A", "B"], "as": [{"field": "name", "type": "string"}]}
        )


# --- join refinements -------------------------------------------------------


def test_join_also_match_disambiguates_a_shared_key():
    """One condition name under two classification types: without the extra
    equality the somatic record files itself under the germline condition."""
    joins = [{"into": "conditions", "from": "records", "left_key": "name",
              "right_key": "condition", "as": "records"}]
    loose = _joined(
        joins,
        names="Shared_disease~Germline+Shared_disease~Somatic",
        recs="R1~Germline~Shared_disease&R2~Somatic~Shared_disease",
    )
    # Both records land under both conditions -- the leak.
    assert [[r["acc"] for r in c["records"]] for c in loose["conditions"]] == [
        ["R1", "R2"],
        ["R1", "R2"],
    ]

    joins[0]["also_match"] = {"kind": "verdict"}
    tight = _joined(
        joins,
        names="Shared_disease~Germline+Shared_disease~Somatic",
        recs="R1~Germline~Shared_disease&R2~Somatic~Shared_disease",
    )
    assert [[r["acc"] for r in c["records"]] for c in tight["conditions"]] == [
        ["R1"],
        ["R2"],
    ]


def test_join_count_into_writes_the_number_of_matches():
    """A row with no candidates at all counts as nothing, not as zero: "0 of 0
    submissions contribute" is a sentence about nothing, while a real zero —
    none of several qualifying — is worth saying."""
    result = _joined(
        [{"into": "conditions", "from": "records", "left_key": "name",
          "right_key": "condition", "count_into": "n"}],
        names="Disease_one+Orphan_disease",
        recs=("R1~Pathogenic~Disease_one&R2~Pathogenic~Disease_one"
              "&R3~Benign~Disease_one"),
    )
    assert [c["n"] for c in result["conditions"]] == [3, None]


def test_join_where_counts_zero_when_candidates_all_fail_it():
    """The distinction the null depends on: these conditions *have* records,
    none of which qualify, so the count is a real 0."""
    result = _joined(
        [{"into": "conditions", "from": "records", "left_key": "name",
          "right_key": "condition", "where": {"field": "verdict", "equals": "1"},
          "count_into": "n"}],
        names="Has_records+Has_none",
        recs="R1~0~Has_records&R2~0~Has_records",
    )
    assert [c["n"] for c in result["conditions"]] == [0, None]


def test_join_where_counts_only_the_rows_a_source_vouches_for():
    """Counting the terms that match the aggregate verbatim breaks on the ones a
    source derives -- nobody submits "Pathogenic/Likely pathogenic", so the count
    came out zero. ClinVar flags which submissions produced the aggregate, and
    `where` counts those."""
    result = _joined(
        [{"into": "conditions", "from": "records", "left_key": "name",
          "right_key": "condition", "where": {"field": "verdict", "equals": "1"},
          "count_into": "counted"},
         {"into": "conditions", "from": "records", "left_key": "name",
          "right_key": "condition", "count_into": "total"}],
        names="Disease_one",
        recs="R1~1~Disease_one&R2~0~Disease_one&R3~1~Disease_one",
    )
    assert result["conditions"][0]["counted"] == 2
    assert result["conditions"][0]["total"] == 3


def test_a_join_must_write_exactly_one_thing():
    from pydantic import ValidationError

    from app.vep.models.parsing_spec_model import JoinSpec

    base = {"into": "conditions", "from": "records", "left_key": "name",
            "right_key": "condition"}
    with pytest.raises(ValidationError, match="not both or neither"):
        JoinSpec(**base)
    with pytest.raises(ValidationError, match="not both or neither"):
        JoinSpec(**base, **{"as": "records", "count_into": "n"})


# --- narrowing a plugin to the rows it is about -----------------------------


def _scoped(applies_to, symbol, geneinfo, sig="Pathogenic"):
    """One plugin gated by `applies_to`, over a row with these columns."""
    index_map = index_map_for("Allele", "SYMBOL", "Probe_SIG", "Probe_GENEINFO")
    spec = ParsingSpec(
        plugins=[
            {
                "plugin": "probe",
                "scope": "transcript",
                "output": "probe",
                "csq_fields": ["Probe_SIG", "Probe_GENEINFO"],
                "applies_to": applies_to,
                "targets": [
                    {
                        "field": "significance",
                        "from": "Probe_SIG",
                        "transform": "scalar",
                        "type": "string",
                    }
                ],
            }
        ]
    )
    return apply_plugin_spec(
        ["A", symbol, sig, geneinfo], index_map, spec.plugin("probe")
    )


_GENE_SCOPE = {
    "column": "SYMBOL",
    "listed_in": "Probe_GENEINFO",
    "item_pattern": "^(?P<key>[^:]+)",
}


def test_a_plugin_is_dropped_on_a_row_it_is_not_about():
    """VEP repeats a custom's columns on every CSQ row of the variant, so
    ClinVar's record for SMARCB1 was also being served under DERL3, whose
    transcripts merely overlap the same position."""
    assert _scoped(_GENE_SCOPE, "SMARCB1", "SMARCB1:6598") is not None
    assert _scoped(_GENE_SCOPE, "DERL3", "SMARCB1:6598") is None


def test_every_gene_the_annotation_names_keeps_it():
    """A record can name several genes; each of them is one it is about."""
    listed = "WARS2:10352&WARS2-AS1:101929147&LOC129931299:129931299"
    assert _scoped(_GENE_SCOPE, "WARS2", listed) is not None
    assert _scoped(_GENE_SCOPE, "WARS2-AS1", listed) is not None
    assert _scoped(_GENE_SCOPE, "SMARCB1", listed) is None


def test_nothing_to_narrow_by_keeps_the_annotation():
    """Dropping here would trade a wrong attribution for a missing one: an
    intergenic row has no symbol to match, and the annotation is still true of
    the variant."""
    assert _scoped(_GENE_SCOPE, "", "SMARCB1:6598") is not None
    assert _scoped(_GENE_SCOPE, "SMARCB1", "") is not None


def test_an_escaped_separator_is_not_read_as_one():
    """Split before decoding: a name carrying an encoded '&' is one name."""
    assert _scoped(_GENE_SCOPE, "A&B", "A%26B:1") is not None


def test_post_joins_can_order_by_what_a_join_added():
    """A target's own `post` runs before the joins, so ordering by a joined-in
    value needs the later pass: whether a condition has a submission behind the
    aggregate is only known once the submissions have been matched to it."""
    index_map = index_map_for("Allele", "Names", "Recs")
    spec = ParsingSpec(
        plugins=[
            {
                "plugin": "probe",
                "scope": "allele",
                "output": "probe",
                "csq_fields": ["Names", "Recs"],
                "targets": [
                    {"field": "conditions", "from": "Names", "transform": "records",
                     "sep": "+", "item_sep": "~",
                     "as": [{"field": "name", "type": "string"}]},
                    {"field": "records", "from": "Recs", "transform": "records",
                     "sep": "&", "item_sep": "~",
                     "as": [{"field": "acc", "type": "string"},
                            {"field": "verdict", "type": "string"},
                            {"field": "condition", "type": "string"}]},
                ],
                "joins": [
                    {"into": "conditions", "from": "records", "left_key": "name",
                     "right_key": "condition",
                     "where": {"field": "verdict", "equals": "1"},
                     "count_into": "counted"}
                ],
                "post_joins": [
                    {"target": "conditions", "op": "sort", "by": "counted",
                     "desc": True, "nulls": "last"}
                ],
            }
        ]
    )
    result = apply_plugin_spec(
        ["A", "Quiet_one+Loud_one+Other_quiet", "R1~1~Loud_one&R2~0~Quiet_one"],
        index_map,
        spec.plugin("probe"),
    )
    # The one with a counted record leads; the rest keep their source order.
    assert [c["name"] for c in result["conditions"]] == [
        "Loud_one",
        "Quiet_one",
        "Other_quiet",
    ]


def test_a_gated_out_list_transform_yields_a_list():
    """A `when` that does not hold must leave the target *empty*, not null: a
    join tests `isinstance(left, list)` before it runs, so a null here silently
    skips every join into that target -- and a `post_joins` sort by a field the
    join was meant to write then has nothing to sort by."""
    index_map = index_map_for("Allele", "Flag", "Recs")
    spec = ParsingSpec(plugins=[{
        "plugin": "probe", "scope": "allele", "output": "probe",
        "csq_fields": ["Recs"],
        "targets": [
            {"field": "recs", "from": "Recs", "transform": "records",
             "item_sep": "~", "as": [{"field": "a", "type": "string"}],
             "when": {"field": "Flag", "includes": "on"}},
            {"field": "stacked", "transform": "stack",
             "of": [{"from": ["Recs"], "as": [{"field": "a", "type": "string"}]}],
             "when": {"field": "Flag", "includes": "on"}},
        ],
    }])
    off = apply_plugin_spec(["A", "off", "x"], index_map, spec.plugin("probe"))
    assert off == {"recs": [], "stacked": []}


def test_sort_survives_a_row_that_lacks_the_key():
    """A sentinel has to be comparable with the real keys, so a missing field
    raised KeyError and a string column with one null raised TypeError — both at
    request time, on data no spec could forbid."""
    index_map = index_map_for("Allele", "Recs")
    spec = ParsingSpec(plugins=[{
        "plugin": "probe", "scope": "allele", "output": "probe",
        "csq_fields": ["Recs"],
        "targets": [{
            "field": "rows", "from": "Recs", "transform": "records",
            "item_sep": "~",
            "as": [{"field": "name", "type": "string"},
                   {"field": "rank", "type": "string"}],
            "post": [{"op": "sort", "by": "rank", "desc": True, "nulls": "last"}],
        }],
    }])
    # "Bare" has no second field at all, so `rank` comes out null.
    result = apply_plugin_spec(["A", "Low~a&Bare&High~b"], index_map, spec.plugin("probe"))
    assert [r["name"] for r in result["rows"]] == ["High", "Low", "Bare"]


def test_dedup_survives_a_row_holding_a_list():
    """A tuple containing a list is unhashable, so `dedup` in `post_joins` —
    where every row may carry joined-in rows — raised at request time."""
    index_map = index_map_for("Allele", "Names", "Recs")
    spec = ParsingSpec(plugins=[{
        "plugin": "probe", "scope": "allele", "output": "probe",
        "csq_fields": ["Names", "Recs"],
        "targets": [
            {"field": "conditions", "from": "Names", "transform": "records",
             "sep": "+", "item_sep": "~", "as": [{"field": "name", "type": "string"}]},
            {"field": "recs", "from": "Recs", "transform": "records",
             "item_sep": "~", "as": [{"field": "acc", "type": "string"},
                                     {"field": "cond", "type": "string"}]},
        ],
        "joins": [{"into": "conditions", "from": "recs", "left_key": "name",
                   "right_key": "cond", "as": "hits"}],
        "post_joins": [{"target": "conditions", "op": "dedup"}],
    }])
    result = apply_plugin_spec(
        ["A", "One+One+Two", "R1~One"], index_map, spec.plugin("probe")
    )
    assert [c["name"] for c in result["conditions"]] == ["One", "Two"]


def test_a_join_splits_before_the_value_is_decoded():
    """The whole reason decoding is one step at the end. A condition literally
    named `Foo+Bar` arrives as `Foo%2BBar`; if the target decodes as it is built,
    the join then splits on the '+' the source had escaped and the condition
    matches nothing — silently, since a join drops evidence rather than erroring."""
    result = _joined(
        [{"into": "conditions", "from": "records", "left_key": "name",
          "right_key": "condition", "right_key_sep": "+", "as": "records"}],
        names="Foo%2BBar",
        recs="R1~Pathogenic~Foo%2BBar",
    )
    condition = result["conditions"][0]
    assert condition["name"] == "Foo+Bar"
    assert [r["acc"] for r in condition["records"]] == ["R1"]
