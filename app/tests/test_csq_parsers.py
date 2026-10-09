"""Tests for the surviving CSQ field parsers and for `_get_alt_allele_details`.

Since the go-flat cutover the plugin annotations are produced by the spec
interpreter, not by a bank of hand-written parsers; only the unspecced tail
(uniprot / protein_matches / sift / polyphen) is still parsed by hand here. A
modern CSQ header (with the plugin columns) builds the index_map, and the
end-to-end tests check an allele built from a transcript row, an intergenic
row and regulatory rows.

The header fixtures below (ALL_COLS / INDEX_MAP / row_list / EMPTY) are shared
with test_spec_interpreter.
"""

from app.vep.utils.csq import get_prediction_index_map
from app.vep.utils.spec_loader import load_merged_spec
from app.vep.utils.vcf_results import (
    _get_alt_allele_details,
    _parse_prediction,
    _parse_protein_matches,
    _parse_uniprot,
)

SPEC = load_merged_spec("human_grch38").parsing

# A modern CSQ header: the columns the plugin specs read.
ALL_COLS = [
    # core / allele-level
    "Allele", "AF", "Consequence", "Feature", "Feature_type", "BIOTYPE",
    "CANONICAL", "SYMBOL", "Gene", "STRAND", "ENSP", "Existing_variation",
    "MANE", "MANE_SELECT", "MANE_PLUS_CLINICAL", "GENCODE_PRIMARY",
    # the unspecced typed tail
    "SIFT", "PolyPhen", "SWISSPROT", "TREMBL", "UNIPARC", "UNIPROT_ISOFORM",
    "DOMAINS",
    "SPDI", "HGVSg", "HGVSc", "HGVSp", "CADD_PHRED", "CADD_RAW", "LOEUF",
    # ProtVar
    "ProtVar_stability", "ProtVar_pocket", "ProtVar_int",
    # IntAct (base + six sub-option columns)
    "IntAct_feature_type", "IntAct_interaction_ac", "IntAct_feature_ac",
    "IntAct_feature_short_label", "IntAct_feature_annotation", "IntAct_ap_ac",
    "IntAct_interaction_participants", "IntAct_pmid",
    # mutfunc
    "mutfunc_motif", "mutfunc_int", "mutfunc_mod", "mutfunc_exp",
    # MaveDB
    "MaveDB_score", "MaveDB_urn", "MaveDB_doi",
    # popEVE
    "popEVE_SCORE", "popEVE_EVE", "popEVE_ESM1v", "popEVE_pop_adjusted_EVE",
    "popEVE_pop_adjusted_ESM1v", "popEVE_gene", "popEVE_protein",
    "popEVE_mutant", "popEVE_gap_frequency",
    # dosage sensitivity
    "pHaplo", "pTriplo",
    # UTRAnnotator
    "5UTR_consequence", "5UTR_annotation", "Existing_uORFs",
    "Existing_InFrame_oORFs", "Existing_OutOfFrame_oORFs",
    # Ribo-seq ORFs
    "RiboseqORFs_id", "RiboseqORFs_consequences", "RiboseqORFs_impact",
    "RiboseqORFs_protein_position", "RiboseqORFs_codons",
    "RiboseqORFs_amino_acids", "RiboseqORFs_publications",
    # SpliceAI
    "SpliceAI_pred_SYMBOL", "SpliceAI_pred_DS_AG", "SpliceAI_pred_DS_AL",
    "SpliceAI_pred_DS_DG", "SpliceAI_pred_DS_DL", "SpliceAI_pred_DP_AG",
    "SpliceAI_pred_DP_AL", "SpliceAI_pred_DP_DG", "SpliceAI_pred_DP_DL",
    # pathogenicity
    "REVEL", "am_class", "am_pathogenicity", "EVE_CLASS", "EVE_SCORE",
    # ClinVar (the bare match column carries the variation id)
    "ClinVar", "ClinVar_CLNSIG", "ClinVar_CLNSIGCONF",
    # ClinVar structural variants
    "ClinVar_SV", "ClinVar_SV_CLNSIG", "ClinVar_SV_ORIGIN",
    # NearestGene / NearestExonJB
    "NearestGene", "NearestExonJB",
]

HEADER = "Consequence annotations from Ensembl VEP. Format: " + "|".join(ALL_COLS)
INDEX_MAP = get_prediction_index_map(HEADER)


def row_list(**values):
    """A CSQ values list (aligned to ALL_COLS); unset columns are empty."""
    return [str(values.get(col, "")) for col in ALL_COLS]


def row_str(**values):
    """A pipe-joined CSQ string (as it appears in the VCF INFO field)."""
    return "|".join(row_list(**values))


EMPTY = row_list()


# --- the unspecced typed tail ------------------------------------------------
#
# uniprot / protein_matches / sift / polyphen are deliberately still parsed by
# hand (no sample data carries their columns, so no plugin spec could be
# validated for them). These are the only hand-written parsers left.


def test_parse_uniprot_cross_references():
    result = _parse_uniprot(
        row_list(
            SWISSPROT="P04637.1", TREMBL="A0A2X", UNIPARC="UPI000002",
            UNIPROT_ISOFORM="P04637-2",
        ),
        INDEX_MAP,
    )
    assert result.swissprot == "P04637.1"
    assert result.trembl == "A0A2X"
    assert result.uniparc == "UPI000002"
    assert result.isoform == "P04637-2"


def test_parse_uniprot_empty_is_none():
    assert _parse_uniprot(EMPTY, INDEX_MAP) is None


def test_parse_protein_matches_splits_source_and_id():
    matches = _parse_protein_matches(
        row_list(DOMAINS="AFDB-ENSP_mappings:AF-P04637-F1&PDB-ENSP_mappings:1TUP"),
        INDEX_MAP,
    )
    assert [(m.source, m.id) for m in matches] == [
        ("AFDB-ENSP_mappings", "AF-P04637-F1"),
        ("PDB-ENSP_mappings", "1TUP"),
    ]


def test_parse_protein_matches_without_a_source_keeps_the_id():
    matches = _parse_protein_matches(row_list(DOMAINS="1TUP"), INDEX_MAP)
    assert [(m.source, m.id) for m in matches] == [("", "1TUP")]


def test_parse_protein_matches_empty_is_empty_list():
    assert _parse_protein_matches(EMPTY, INDEX_MAP) == []


def test_parse_prediction_splits_score_from_term():
    result = _parse_prediction("tolerated(0.15)")
    assert (result.prediction, result.score) == ("tolerated", 0.15)


def test_parse_prediction_without_a_score_keeps_the_term():
    result = _parse_prediction("tolerated")
    assert (result.prediction, result.score) == ("tolerated", None)


def test_parse_prediction_empty_is_none():
    assert _parse_prediction("") is None
    assert _parse_prediction(None) is None


# --- end-to-end allele (modern header) ---------------------------------------


def test_get_alt_allele_details_transcript_row_populates_annotations():
    transcript = row_str(
        Allele="T",
        Consequence="missense_variant",
        Feature="ENST00000269305.9",
        Feature_type="Transcript",
        BIOTYPE="protein_coding",
        CANONICAL="YES",
        SYMBOL="TP53",
        Gene="ENSG00000141510",
        STRAND="1",
        ENSP="ENSP00000269305",
        SIFT="deleterious(0.01)",
        PolyPhen="probably_damaging(0.98)",
        SWISSPROT="P04637.1",
        DOMAINS="AFDB-ENSP_mappings:AF-P04637-F1",
        HGVSc="c.123A>G",
        HGVSp="p.Lys41Arg",
        HGVSg="17:g.7676154A>G",
        SPDI="NC_000017.11:7676153:A:G",
        CADD_PHRED="25.3",
        LOEUF="0.15",
        ProtVar_stability="0.42",
        IntAct_feature_type="mutation",
        mutfunc_motif="0.1",
        MaveDB_score="1.5",
        MaveDB_accession="urn:mavedb:00000001-a-1#7",
        am_class="likely_pathogenic",
        am_pathogenicity="0.9",
        pHaplo="0.95",
        **{"5UTR_consequence": "uORF_variant"},
        RiboseqORFs_id="c1orf1",
    )

    result = _get_alt_allele_details("C", "T", [transcript], INDEX_MAP, SPEC)
    assert len(result.predicted_molecular_consequences) == 1
    consequence = result.predicted_molecular_consequences[0]

    # compare by value: vcf_results imports the model as `vep.models...` while
    # this test imports `app.vep.models...`, so the enum *members* differ by
    # identity even though their values match (same reason test_vep.py skips it).
    assert consequence.feature_type.value == "transcript"

    # the retained typed tail
    assert consequence.uniprot.swissprot == "P04637.1"
    assert [m.id for m in consequence.protein_matches] == ["AF-P04637-F1"]
    assert (consequence.sift.prediction, consequence.sift.score) == (
        "deleterious", 0.01
    )
    assert consequence.polyphen.prediction == "probably_damaging"

    # everything else arrives as generic transcript-scope annotations
    by_plugin = {a.plugin: a.data for a in consequence.annotations}
    assert all(a.scope == "transcript" for a in consequence.annotations)
    assert by_plugin.keys() >= {
        "protvar", "intact", "mutfunc", "mavedb", "hgvs", "alphamissense",
        "loeuf", "dosage_sensitivity", "utr_annotation", "riboseq_orfs",
    }
    assert by_plugin["hgvs"]["transcript"] == "c.123A>G"
    assert by_plugin["alphamissense"] == {
        "classification": "likely_pathogenic", "score": 0.9
    }

    # ...and the allele-level ones as generic allele-scope annotations
    allele_plugins = {a.plugin: a.data for a in result.annotations}
    assert all(a.scope == "allele" for a in result.annotations)
    assert allele_plugins["spdi"] == {"spdi": "NC_000017.11:7676153:A:G"}
    assert allele_plugins["hgvsg"] == {"genomic": "17:g.7676154A>G"}
    assert allele_plugins["cadd"]["phred"] == 25.3


def test_new_plugins_surface_at_their_declared_scope():
    """loeuf / spdi / hgvsg were added by the go-flat cutover: loeuf is
    transcript-scoped, spdi and hgvsg are allele-scoped (intergenic variants
    have no transcript rows, so they must be readable off the allele)."""
    transcript = row_str(
        Allele="T",
        Consequence="missense_variant",
        Feature="ENST00000269305.9",
        Feature_type="Transcript",
        BIOTYPE="protein_coding",
        CANONICAL="YES",
        SYMBOL="TP53",
        Gene="ENSG00000141510",
        STRAND="1",
        LOEUF="0.15",
        SPDI="NC_000017.11:7676153:A:G",
        HGVSg="17:g.7676154A>G",
    )

    result = _get_alt_allele_details("C", "T", [transcript], INDEX_MAP, SPEC)
    consequence = result.predicted_molecular_consequences[0]

    transcript_scoped = {a.plugin: a for a in consequence.annotations}
    allele_scoped = {a.plugin: a for a in result.annotations}

    assert transcript_scoped["loeuf"].scope == "transcript"
    assert transcript_scoped["loeuf"].data == {"score": 0.15}
    assert "loeuf" not in allele_scoped

    assert allele_scoped["spdi"].scope == "allele"
    assert allele_scoped["spdi"].data == {"spdi": "NC_000017.11:7676153:A:G"}
    assert allele_scoped["hgvsg"].scope == "allele"
    assert allele_scoped["hgvsg"].data == {"genomic": "17:g.7676154A>G"}
    assert "spdi" not in transcript_scoped
    assert "hgvsg" not in transcript_scoped


def test_get_alt_allele_details_intergenic_surfaces_allele_level_annotations():
    intergenic = row_str(
        Allele="A",
        Consequence="intergenic_variant",
        Feature_type="",
        SPDI="NC_000017.11:7676153:T:A",
        HGVSg="17:g.7676154T>A",
        CADD_PHRED="8.2",
        Existing_variation="rs123&rs456",
    )

    result = _get_alt_allele_details("T", "A", [intergenic], INDEX_MAP, SPEC)
    assert len(result.predicted_molecular_consequences) == 1
    # no transcript consequence for an intergenic variant
    assert result.predicted_molecular_consequences[0].feature_type is None
    # ...but the allele-scope annotations (and colocated variants) still surface
    by_plugin = {a.plugin: a.data for a in result.annotations}
    assert by_plugin["spdi"] == {"spdi": "NC_000017.11:7676153:T:A"}
    assert by_plugin["hgvsg"] == {"genomic": "17:g.7676154T>A"}
    assert by_plugin["cadd"]["phred"] == 8.2
    assert result.colocated_variants == ["rs123", "rs456"]


def test_transcript_flags_mane_gencode_primary_canonical():
    """The transcript-level tags (canonical / MANE / GENCODE primary) are parsed
    off their CSQ columns onto the typed consequence, independent of the spec."""
    tagged = row_str(
        Allele="T",
        Consequence="missense_variant",
        Feature="ENST00000269305.9",
        Feature_type="Transcript",
        BIOTYPE="protein_coding",
        CANONICAL="YES",
        Gene="ENSG00000141510",
        STRAND="1",
        MANE_SELECT="NM_000546.6",
        GENCODE_PRIMARY="1",
    )
    plain = row_str(
        Allele="T",
        Consequence="missense_variant",
        Feature="ENST00000000001.1",
        Feature_type="Transcript",
        BIOTYPE="protein_coding",
        Gene="ENSG00000141510",
        STRAND="1",
    )

    result = _get_alt_allele_details("C", "T", [tagged, plain], INDEX_MAP, SPEC)
    tagged_cons, plain_cons = result.predicted_molecular_consequences

    assert tagged_cons.is_canonical is True
    assert tagged_cons.is_mane_select is True
    assert tagged_cons.is_gencode_primary is True

    # empty GENCODE_PRIMARY column -> not flagged
    assert plain_cons.is_canonical is False
    assert plain_cons.is_mane_select is False
    assert plain_cons.is_gencode_primary is False


# --- feature types with no consequence model ---------------------------------


def test_an_unmodelled_feature_type_is_counted_rather_than_lost():
    from collections import Counter

    dropped: Counter = Counter()
    allele = _get_alt_allele_details(
        "G",
        "A",
        [row_str(Allele="A", Feature_type="FutureFeature", Feature="X1",
                 Consequence="future_variant")],
        INDEX_MAP,
        SPEC,
        unhandled_feature_types=dropped,
    )
    assert allele.predicted_molecular_consequences == []
    assert dropped == Counter({"FutureFeature": 1})


def test_the_counter_is_optional():
    allele = _get_alt_allele_details(
        "G", "A",
        [row_str(Allele="A", Feature_type="FutureFeature",
                 Consequence="future_variant")],
        INDEX_MAP,
        SPEC,
    )
    assert allele.predicted_molecular_consequences == []


def test_modelled_rows_are_not_counted():
    from collections import Counter

    dropped: Counter = Counter()
    _get_alt_allele_details(
        "G", "A",
        [
            row_str(Allele="A", Feature_type="Transcript", Feature="ENST1",
                    BIOTYPE="protein_coding", Consequence="missense_variant",
                    STRAND="1"),
            row_str(Allele="A", Feature_type="RegulatoryFeature",
                    Feature="ENSR1_D37Q", BIOTYPE="enhancer",
                    Consequence="regulatory_region_variant"),
            row_str(Allele="A", Feature_type="MotifFeature",
                    Feature="ENSM00000018397",
                    Consequence="TF_binding_site_variant"),
            row_str(Allele="A", Feature_type="", Consequence="intergenic_variant"),
        ],
        INDEX_MAP,
        SPEC,
        unhandled_feature_types=dropped,
    )
    assert dropped == Counter()


# --- regulatory rows ---------------------------------------------------------


def test_a_regulatory_feature_row_becomes_a_regulatory_consequence():
    allele = _get_alt_allele_details(
        "C", "T",
        [row_str(Allele="T", Feature_type="RegulatoryFeature",
                 Feature="ENSR1_D37Q", BIOTYPE="enhancer",
                 Consequence="regulatory_region_variant")],
        INDEX_MAP,
        SPEC,
    )
    [consequence] = allele.predicted_molecular_consequences
    assert consequence.feature_type == "regulatory"
    assert consequence.stable_id == "ENSR1_D37Q"
    assert consequence.biotype == "enhancer"
    assert consequence.consequences == ["regulatory_region_variant"]


def test_a_motif_row_is_a_regulatory_consequence_without_a_biotype():
    allele = _get_alt_allele_details(
        "G", "C",
        [row_str(Allele="C", Feature_type="MotifFeature",
                 Feature="ENSM00000018397",
                 Consequence="TF_binding_site_variant")],
        INDEX_MAP,
        SPEC,
    )
    [consequence] = allele.predicted_molecular_consequences
    assert consequence.feature_type == "regulatory"
    assert consequence.stable_id == "ENSM00000018397"
    assert consequence.biotype is None
    assert consequence.consequences == ["TF_binding_site_variant"]


def test_an_allele_keeps_its_transcript_and_regulatory_rows():
    allele = _get_alt_allele_details(
        "C", "G",
        [
            row_str(Allele="G", Feature_type="Transcript",
                    Feature="ENST00000367313.5", BIOTYPE="protein_coding",
                    Consequence="intron_variant", STRAND="1", CADD_PHRED="5.579"),
            row_str(Allele="G", Feature_type="RegulatoryFeature",
                    Feature="ENSR1_94XXBC", BIOTYPE="enhancer",
                    Consequence="regulatory_region_variant", CADD_PHRED="5.579"),
            row_str(Allele="G", Feature_type="MotifFeature",
                    Feature="ENSM00000071889",
                    Consequence="TF_binding_site_variant", CADD_PHRED="5.579"),
        ],
        INDEX_MAP,
        SPEC,
    )
    rows = [
        (type(c).__name__, c.stable_id)
        for c in allele.predicted_molecular_consequences
    ]
    assert rows == [
        ("PredictedTranscriptConsequence", "ENST00000367313.5"),
        ("PredictedRegulatoryConsequence", "ENSR1_94XXBC"),
        ("PredictedRegulatoryConsequence", "ENSM00000071889"),
    ]
    assert {a.plugin: a.data for a in allele.annotations}["cadd"]["phred"] == 5.579


def test_a_regulatory_scoped_plugin_attaches_to_the_regulatory_row_only():
    loeuf = next(p for p in SPEC.plugins if p.plugin == "loeuf")
    probe = type(loeuf).model_validate(
        {**loeuf.model_dump(), "plugin": "regulatory_probe",
         "output": "regulatory_probe", "scope": "regulatory"}
    )
    spec = SPEC.model_copy(update={"plugins": [*SPEC.plugins, probe]})
    allele = _get_alt_allele_details(
        "C", "G",
        [
            row_str(Allele="G", Feature_type="Transcript", Feature="ENST1",
                    BIOTYPE="protein_coding", Consequence="intron_variant",
                    STRAND="1", LOEUF="0.5"),
            row_str(Allele="G", Feature_type="RegulatoryFeature",
                    Feature="ENSR1_94XXBC", BIOTYPE="enhancer",
                    Consequence="regulatory_region_variant", LOEUF="0.7"),
        ],
        INDEX_MAP,
        spec,
    )
    transcript, regulatory = allele.predicted_molecular_consequences
    on_transcript = {a.plugin: a for a in transcript.annotations}
    on_regulatory = {a.plugin: a for a in regulatory.annotations}

    assert on_regulatory["regulatory_probe"].scope == "regulatory"
    assert on_regulatory["regulatory_probe"].data == {"score": 0.7}
    assert "loeuf" not in on_regulatory
    assert on_transcript["loeuf"].data == {"score": 0.5}
    assert "regulatory_probe" not in on_transcript
    assert "regulatory_probe" not in {a.plugin for a in allele.annotations}


def test_a_motif_rows_details_attach_to_that_row():
    # HIGH_INF_POS and MOTIF_SCORE_CHANGE are filled here, although VEP leaves
    # them empty because the regulation GFFs carry no weight matrix.
    motif_cols = [
        "MOTIF_NAME", "MOTIF_POS", "HIGH_INF_POS", "MOTIF_SCORE_CHANGE",
        "TRANSCRIPTION_FACTORS",
    ]
    cols = ALL_COLS + motif_cols
    index_map = get_prediction_index_map(
        "Consequence annotations from Ensembl VEP. Format: " + "|".join(cols)
    )

    def row(**values):
        return "|".join(str(values.get(col, "")) for col in cols)

    allele = _get_alt_allele_details(
        "G", "C",
        [
            row(Allele="C", Feature_type="MotifFeature", Feature="ENSM00000018397",
                Consequence="TF_binding_site_variant", MOTIF_NAME="ENSPFM0015",
                MOTIF_POS="11", HIGH_INF_POS="N", MOTIF_SCORE_CHANGE="-0.021",
                TRANSCRIPTION_FACTORS="FOS&ATF7&JUN"),
            row(Allele="C", Feature_type="RegulatoryFeature", Feature="ENSR1_D37Q",
                BIOTYPE="enhancer", Consequence="regulatory_region_variant"),
        ],
        index_map,
        SPEC,
    )
    motif_row, enhancer_row = allele.predicted_molecular_consequences
    motif = {a.plugin: a for a in motif_row.annotations}["motif"]
    assert motif.scope == "regulatory"
    assert motif.data["name"] == "ENSPFM0015"
    assert motif.data["transcription_factors"] == ["FOS", "ATF7", "JUN"]
    assert motif.data["position"] == 11
    assert motif.data["high_information_position"] == "N"
    assert motif.data["score_change"] == -0.021
    assert "motif" not in {a.plugin for a in enhancer_row.annotations}
    assert "motif" not in {a.plugin for a in allele.annotations}
