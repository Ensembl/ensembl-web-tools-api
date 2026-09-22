"""The #CHROM, #POS, #REF and #ALT pseudo-columns, and the parsing targets and
display entries built on them."""

from io import StringIO

import pytest
from pydantic import ValidationError

from app.vep.models.display_panels_model import to_display_panels
from app.vep.models.parsing_spec_model import ParsingSpec, TargetSpec
from app.vep.utils.spec_interpreter import apply_plugin_spec, compile_plugin
from app.vep.utils.spec_loader import (
    load_merged_spec,
    write_display_panels_sidecar,
    write_expected_columns_sidecar,
    write_spec_sidecar,
)
from app.vep.utils.vcf_results import get_results_from_path, get_results_from_stream

MERGED = load_merged_spec("human_grch38")
SPEC = MERGED.parsing
DISPLAY = MERGED.display_payload()

OPENTARGETS_COLUMNS = [
    "OpenTargets_gwasDiseases", "OpenTargets_gwasGeneId",
    "OpenTargets_gwasLocusToGeneScore", "OpenTargets_qtlGeneId",
    "OpenTargets_qtlBiosampleName", "OpenTargets_pValueMantissa",
    "OpenTargets_pValueExponent", "OpenTargets_beta",
]
COLUMNS = [
    "Allele", "Consequence", "Feature_type", "Feature", "HGVSg",
    "ProtVar_stability", "ProtVar_pocket", "ProtVar_int", *OPENTARGETS_COLUMNS,
]
OPENTARGETS_VALUES = ["EFO_1", "ENSG1", "0.5", "", "", "3.2", "-8", "0.1"]

PROBE = ParsingSpec.model_validate({
    "plugins": [{
        "plugin": "probe",
        "scope": "allele",
        "output": "probe",
        "csq_fields": ["Consequence"],
        "targets": [{
            "field": "site",
            "transform": "template",
            "template": "{#CHROM}|{#POS}|{#REF}|{#ALT}",
        }],
    }]
})


def _row(allele, hgvsg):
    return "|".join([
        allele, "missense_variant", "Transcript", "ENST1", hgvsg,
        "0.7", "", "", *OPENTARGETS_VALUES,
    ])


def _vcf(records):
    header = (
        "##fileformat=VCFv4.2\n"
        '##INFO=<ID=CSQ,Number=.,Type=String,Description="Consequence '
        f'annotations from Ensembl VEP. Format: {"|".join(COLUMNS)}">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    )
    lines = [
        f"{chrom}\t{pos}\t.\t{ref}\t{alt}\t.\tPASS\tCSQ={','.join(rows)}\n"
        for chrom, pos, ref, alt, rows in records
    ]
    return header + "".join(lines)


RECORDS = [
    ("chr19", 82664, "C", "T", [_row("T", "19:g.82664C>T")]),
    ("1", 1000, "AT", "A", [_row("-", "1:g.1001del")]),
    ("2", 500, "CA", "C,CAA", [
        _row("-", "2:g.501del"), _row("A", "2:g.501dup"),
    ]),
]


def _results(spec):
    return get_results_from_stream(
        100, 1, len(RECORDS), StringIO(_vcf(RECORDS)), spec, [], DISPLAY
    )


def _data(annotations, plugin):
    return next(a.data for a in annotations if a.plugin == plugin)


def test_pseudo_columns_carry_the_responses_own_values():
    variants = _results(PROBE).variants

    seen = []
    for variant in variants:
        for allele in variant.alternative_alleles:
            expected = "|".join([
                variant.location.region_name,
                str(variant.location.start),
                variant.reference_allele.allele_sequence,
                allele.allele_sequence,
            ])
            assert _data(allele.annotations, "probe") == {"site": expected}
            seen.append(expected)

    assert seen == [
        "19|82664|C|T",
        "1|1000|AT|-",
        "2|500|CA|-",
        "2|500|CA|A",
    ]


def test_opentargets_variant_id_and_protvar_url_for_a_substitution():
    allele = _results(SPEC).variants[0].alternative_alleles[0]
    consequence = allele.predicted_molecular_consequences[0]

    assert _data(allele.annotations, "opentargets")["variant_id"] == "19_82664_C_T"
    assert _data(consequence.annotations, "protvar")["url"] == (
        "https://www.ebi.ac.uk/ProtVar/g/19/82664/C/T?annotation=fun"
    )


def test_protvar_url_is_absent_for_an_indel():
    allele = _results(SPEC).variants[1].alternative_alleles[0]
    consequence = allele.predicted_molecular_consequences[0]

    assert _data(allele.annotations, "opentargets")["variant_id"] == "1_1000_AT_-"
    assert _data(consequence.annotations, "protvar")["url"] is None


def test_a_results_call_ships_both_fields(tmp_path):
    vcf_path = tmp_path / "input_VEP.vcf"
    vcf_path.write_text(_vcf(RECORDS))
    write_spec_sidecar(tmp_path, MERGED)
    write_expected_columns_sidecar(tmp_path, set())
    panels = [{"id": "general", "label": "General", "options": []}]
    write_display_panels_sidecar(tmp_path, to_display_panels(panels))

    response = get_results_from_path(100, 1, vcf_path).model_dump()
    pool = response["variants"][0]["annotation_pool"]
    by_plugin = {entry["plugin"]: entry["data"] for entry in pool}

    assert by_plugin["opentargets"]["variant_id"] == "19_82664_C_T"
    assert by_plugin["protvar"]["url"] == (
        "https://www.ebi.ac.uk/ProtVar/g/19/82664/C/T?annotation=fun"
    )


def test_variant_id_is_absent_without_an_alt():
    index_map = {column: i for i, column in enumerate(COLUMNS)}
    values = _row("T", "").split("|")
    opentargets = SPEC.plugin("opentargets")

    data = apply_plugin_spec(
        values, index_map, opentargets, site=("1", "10", "C", "")
    )

    assert data["variant_id"] is None


def test_the_cache_keys_on_the_site():
    index_map = {column: i for i, column in enumerate(COLUMNS)}
    values = _row("T", "").split("|")
    opentargets = SPEC.plugin("opentargets")
    cache: dict = {}

    first = apply_plugin_spec(
        values, index_map, opentargets, cache, site=("1", "10", "C", "T")
    )
    second = apply_plugin_spec(
        values, index_map, opentargets, cache, site=("1", "10", "C", "G")
    )

    assert (first["variant_id"], second["variant_id"]) == ("1_10_C_T", "1_10_C_G")


def test_only_plugins_reading_the_site_extend_the_row():
    index_map = {column: i for i, column in enumerate(COLUMNS)}

    assert compile_plugin(index_map, SPEC.plugin("protvar")).site_index_map is None
    assert compile_plugin(index_map, SPEC.plugin("revel")).site_index_map is None
    assert compile_plugin(index_map, SPEC.plugin("opentargets")).site_index_map


def test_a_template_placeholder_must_be_a_pattern_group():
    with pytest.raises(ValidationError, match=r"\['alt'\] are not groups"):
        TargetSpec.model_validate({
            "field": "url",
            "from": "HGVSg",
            "transform": "template",
            "pattern": "^(?P<ref>[ACGT])$",
            "template": "x/{ref}/{alt}",
        })


def test_a_template_pattern_needs_a_source():
    with pytest.raises(ValidationError, match="`pattern` needs `from`"):
        TargetSpec.model_validate({
            "field": "url",
            "transform": "template",
            "pattern": "^(?P<ref>[ACGT])$",
            "template": "x/{ref}",
        })


def _option(option_id):
    return next(o for o in MERGED.display.options if o.option_id == option_id)


def test_protvar_and_opentargets_links_are_templates():
    protvar = _option("protvar").model_dump(by_alias=True, exclude_none=True)
    opentargets = _option("opentargets").model_dump(by_alias=True, exclude_none=True)

    assert protvar["blocks"][0]["rows"][0]["link"] == {
        "kind": "external", "template": "{value}",
    }
    assert protvar["blocks"][0]["rows"][0]["link_from"] == "protvar.url"
    for block in (protvar["blocks"][1], protvar["blocks"][3]):
        assert block["item"]["link"] == {"kind": "external", "template": "{value}"}
        assert block["item"]["link_from"] == "protvar.url"
    assert opentargets["blocks"][0]["rows"][0] == {
        "label": "",
        "from": "opentargets.variant_id",
        "link": {
            "kind": "external",
            "template": "https://platform.opentargets.org/variant/{value}",
        },
    }
