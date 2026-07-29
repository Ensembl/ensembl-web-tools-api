"""The EFO table generator's parsing rules.

The script itself is run by hand, but its three judgement calls are not
self-evident from the OBO and would be easy to "tidy" back into a bug, so they
are pinned here: which id shapes yield an accession, which ontologies are kept,
and how a retired term is recognised.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "vep" / "scripts" / "generate_efo_terms.py"
)


def _load_script():
    """Import the generator by path — `vep/scripts` is not a package."""
    spec = importlib.util.spec_from_file_location("generate_efo_terms", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = _load_script()


def obo(*stanzas: str) -> list[str]:
    return "\n".join(stanzas).split("\n")


def test_efo_ids_are_curies_carrying_the_accession():
    """EFO's own terms are `efo:EFO_0001645` — the accession is the local part,
    not the prefix plus a number. Reading them as `PREFIX:number` was what made
    a first pass report every EFO id missing."""
    table = generator.parse_obo(
        obo("[Term]", "id: efo:EFO_0006336", "name: diastolic blood pressure")
    )
    assert table["terms"] == {"EFO_0006336": "diastolic blood pressure"}


def test_imported_ids_use_the_ordinary_curie_form():
    table = generator.parse_obo(
        obo(
            "[Term]",
            "id: GO:0036273",
            "name: response to statin",
            "",
            "[Term]",
            "id: OBA:2050068",
            "name: serum albumin amount",
        )
    )
    assert table["terms"] == {
        "GO_0036273": "response to statin",
        "OBA_2050068": "serum albumin amount",
    }


def test_url_ids_are_skipped():
    """A handful of terms are identified by bare URL with no accession to
    recover; they cannot be looked up by an OpenTargets id anyway."""
    table = generator.parse_obo(
        obo("[Term]", "id: http://www.ebi.ac.uk/efo/something", "name: whatever")
    )
    assert table["terms"] == {}


def test_out_of_scope_ontologies_are_dropped():
    """A third of the release describes proteins, chemicals and taxa — things a
    GWAS trait is not."""
    table = generator.parse_obo(
        obo(
            "[Term]",
            "id: PR:000001",
            "name: some protein",
            "",
            "[Term]",
            "id: CHEBI:12345",
            "name: some chemical",
            "",
            "[Term]",
            "id: MONDO:0005148",
            "name: type 2 diabetes mellitus",
        )
    )
    assert table["terms"] == {"MONDO_0005148": "type 2 diabetes mellitus"}


@pytest.mark.parametrize("marker", ["obsolete_", "obsolete "])
def test_the_obsolete_prefix_is_stripped_from_the_name(marker):
    """Both spellings occur — 9093 with the underscore, 752 with a space."""
    table = generator.parse_obo(
        obo(
            "[Term]",
            "id: efo:EFO_1000627",
            f"name: {marker}thyroid disease",
            "is_obsolete: true",
        )
    )
    assert table["terms"] == {"EFO_1000627": "thyroid disease"}
    assert table["retired"] == ["EFO_1000627"]


def test_retired_comes_from_the_flag_not_the_name():
    """EFO_0002302 is named `obsolete_H720` while not being flagged obsolete.
    Trusting the name would retire a live term; trusting the flag alone keeps
    the claim honest, and the prefix is still stripped as the artefact it is."""
    table = generator.parse_obo(
        obo("[Term]", "id: efo:EFO_0002302", "name: obsolete_H720")
    )
    assert table["terms"] == {"EFO_0002302": "H720"}
    assert table["retired"] == []


def test_retired_terms_are_kept_not_dropped():
    """Annotation sources lag ontology releases, so retired accessions are
    exactly the ones still arriving in real output."""
    table = generator.parse_obo(
        obo(
            "[Term]",
            "id: efo:EFO_0001645",
            "name: obsolete_coronary artery disease",
            "is_obsolete: true",
        )
    )
    assert table["terms"]["EFO_0001645"] == "coronary artery disease"
    assert "EFO_0001645" in table["retired"]


def test_non_term_stanzas_are_ignored():
    """A [Typedef] carries an id and a name too, and is not a term."""
    table = generator.parse_obo(
        obo(
            "[Typedef]",
            "id: part_of",
            "name: part of",
            "",
            "[Term]",
            "id: efo:EFO_0004468",
            "name: glucose measurement",
        )
    )
    assert table["terms"] == {"EFO_0004468": "glucose measurement"}


def test_output_is_sorted_so_a_no_op_regeneration_has_no_diff():
    table = generator.parse_obo(
        obo(
            "[Term]",
            "id: efo:EFO_0009",
            "name: b",
            "is_obsolete: true",
            "",
            "[Term]",
            "id: efo:EFO_0001",
            "name: a",
            "is_obsolete: true",
        )
    )
    assert list(table["terms"]) == ["EFO_0001", "EFO_0009"]
    assert table["retired"] == ["EFO_0001", "EFO_0009"]


def test_the_committed_table_resolves_the_accessions_in_dev_data():
    """A guard on the shipped file rather than the parser: these eleven are what
    the dev-data VCF actually carries."""
    import json

    path = Path(__file__).resolve().parents[1] / "vep" / "data" / "efo_terms.json"
    table = json.loads(path.read_text())
    expected = {
        "EFO_0001645": "coronary artery disease",
        "EFO_0004468": "glucose measurement",
        "EFO_0005763": "pulse pressure measurement",
        "EFO_0006335": "systolic blood pressure",
        "EFO_0006336": "diastolic blood pressure",
        "EFO_0006340": "mean arterial pressure",
        "EFO_0008111": "diet measurement",
        "EFO_1000627": "thyroid disease",
        "GO_0036273": "response to statin",
        "OBA_2050068": "serum albumin amount",
        "OBA_VT0000188": "blood glucose amount",
    }
    for accession, name in expected.items():
        assert table["terms"].get(accession) == name
    retired = set(table["retired"])
    assert {"EFO_0001645", "EFO_1000627"} <= retired
    assert retired <= set(table["terms"])
