"""What a submission may set, derived from the spec rather than declared.

`ConfigIniParams` used to declare 207 fields, of which 199 were options — one
per control, and none of them ever read by attribute: they arrived as
`ConfigIniParams(**payload)` and left as `.model_dump()`. They were a third
statement of what the config entries already say, after the form panels and the
`fields=` clause, and the only one that could not tell one assembly's options
from another's.

They are now a map, completed and checked against the spec. See
docs/form-panels-to-json.md.
"""

import logging
from types import SimpleNamespace

from app.vep.models.pipeline_model import ConfigIniParams
from app.vep.submission_options import submittable_options, unknown_options

def _params(assembly: str, **options) -> ConfigIniParams:
    return ConfigIniParams(
        genome_id="g",
        assembly_name=assembly,
        options=options,
    )


def test_the_model_carries_the_job_and_a_map_of_options():
    """Eight fields, not 207: seven job fields and the options map."""
    assert set(ConfigIniParams.model_fields) == {
        "genome_id",
        "assembly_name",
        "gff",
        "fasta",
        "force_overwrite",
        "transcript_version",
        "canonical",
        "options",
    }


def test_the_dead_field_went_with_them():
    """`intact_feature_annotation` had no config entry, no control and a retired
    parse, and sat on the model unnoticed because the sync test only ever
    checked form -> model. Nothing offers it, so nothing carries it."""
    assert "intact_feature_annotation" not in ConfigIniParams.model_fields
    assert "intact_feature_annotation" not in _params("GRCh38.p14").options


def test_an_unsent_option_gets_the_default_the_spec_declares():
    """"Absent" and "off" are not the same thing.

    A ProtVar sub-feature defaults to *on*, so a payload naming only `protvar`
    must still come out with its sub-flags set — which is what the 199 fields
    used to arrange, and what would quietly change if the map were passed
    through as sent.
    """
    options = _params("GRCh38.p14", protvar=True).options
    assert options["protvar"] is True
    assert options["protvar_stability"] is True
    assert options["protvar_pocket"] is True
    # ...and something not selected is off, not missing.
    assert options["gerp"] is False


def test_the_map_is_everything_this_genome_offers():
    """One entry per option the form offers, no more: the map is the contract,
    so a caller can read it without knowing what was sent."""
    for assembly in (
        "GRCh38.p14",
        "GRCh37.p13",
        "GRCm39",
    ):
        offered = submittable_options(assembly_name=assembly)
        assert set(_params(assembly).options) == set(offered), assembly


def test_the_awkward_shapes_survive_the_round_trip():
    """The four options whose value is not a boolean — a number with bounds, and
    a select whose value is a string."""
    options = _params(
        "GRCh38.p14",
        nearest_exon_jb_max_range=250,
        gnomad_sv_overlap_cutoff="80",
    ).options
    assert options["nearest_exon_jb_max_range"] == 250
    assert options["gnomad_sv_overlap_cutoff"] == "80"
    # and their declared defaults when unsent
    assert options["updownstream_distance_bp"] == 5000
    assert options["gnomad_cnv_overlap_cutoff"] == "100"


def test_an_option_belongs_to_an_assembly():
    """What the flat model could not express.

    `pli` is a real option on GRCh38 and not an option at all on GRCh37. One set
    of fields accepted it for both, so a GRCh37 submission could turn on
    something that genome has no data for and nothing said otherwise.
    """
    assert _params("GRCh38.p14", pli=True).options["pli"] is True
    assert "pli" not in _params("GRCh37.p13", pli=True).options


def test_an_unrecognised_option_is_dropped_but_said_out_loud(caplog):
    """Dropped, not rejected — and logged, which is the part that was missing.

    A submission can be rerun for 28 days, so a replayed payload may still name
    an option that has since been retired; failing that rerun would be worse
    than ignoring it. What was wrong before is that pydantic's `extra` default
    discarded it in silence, so a typo and a deliberate omission looked
    identical from every side.
    """
    with caplog.at_level(logging.WARNING):
        params = _params("GRCh38.p14", cadd=True, gerpp=True)

    assert params.options["cadd"] is True
    assert "gerpp" not in params.options
    assert "gerpp" in caplog.text


def test_unknown_options_names_them_without_building_a_submission():
    """The same check on its own, for a caller that wants to ask first."""
    assert unknown_options(
        {"cadd": True, "gerpp": True},
        assembly_name="GRCh38.p14",
    ) == ["gerpp"]
    # On GRCh37 a real GRCh38 option is unknown in exactly the same way.
    assert unknown_options(
        {"pli": True}, assembly_name="GRCh37.p13"
    ) == ["pli"]


def test_a_stray_option_passed_as_a_keyword_fails_loudly():
    """`extra="forbid"` on the model: an option is a map entry now, and a caller
    still passing one as a keyword would otherwise have it silently dropped —
    the failure this whole change is about."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="cadd"):
        ConfigIniParams(genome_id="g", assembly_name="GRCh38.p14", cadd=True)


def test_submitted_option_values_are_type_checked_and_bounded():
    import pytest

    with pytest.raises(ValueError, match="updownstream_distance_bp"):
        _params("GRCh38.p14", updownstream_distance_bp="5000\nfasta /etc/passwd")
    with pytest.raises(ValueError, match="at most"):
        _params("GRCh38.p14", updownstream_distance_bp=1_000_001)


def test_submission_resolves_assembly_from_genome_id(monkeypatch, tmp_path):
    """A submission never trusts assembly/taxonomy fields from the client."""
    import asyncio

    from app.vep import vep_resources

    input_path = tmp_path / "input.vcf"
    input_path.write_text("##fileformat=VCFv4.2\n")
    config_path = tmp_path / "config.ini"
    config_path.write_text("")
    calls = {}

    class FakeStreamer:
        def __init__(self, request):
            self.parameters = SimpleNamespace(value=(
                b'{"assembly_name":"Wibble_v1","species_taxonomy_id":"1","cadd":true}'
            ))
            self.genome_id = SimpleNamespace(value=b"genome-uuid")
            self.temp_dir = tmp_path
            self.filepath = input_path
            self.filename = "input.vcf"

        async def stream(self):
            return True

    class FakeMergedSpec:
        config = object()

        def expected_csq_columns(self, options):
            calls["options"] = options
            return []

    async def fake_get_genome_assembly_name(genome_id):
        calls["genome_id"] = genome_id
        return "GRCh38.p14"

    def fake_create_config(self, directory, config_spec):
        calls["assembly_name"] = self.assembly_name
        return SimpleNamespace(name=str(config_path))

    monkeypatch.setattr(vep_resources, "Streamer", FakeStreamer)
    monkeypatch.setattr(
        vep_resources, "get_genome_assembly_name", fake_get_genome_assembly_name
    )
    monkeypatch.setattr(
        vep_resources, "resolve_merged_spec", lambda _assembly: FakeMergedSpec()
    )
    monkeypatch.setattr(
        vep_resources.ConfigIniParams, "create_config_ini_file", fake_create_config
    )
    monkeypatch.setattr(vep_resources, "write_spec_sidecar", lambda *_args: None)
    monkeypatch.setattr(
        vep_resources, "write_expected_columns_sidecar", lambda *_args: None
    )
    monkeypatch.setattr(
        vep_resources, "write_display_panels_sidecar", lambda *_args: None
    )
    monkeypatch.setattr(
        vep_resources, "launch_workflow", lambda _params: "workflow-id"
    )

    assert asyncio.run(vep_resources.submit_vep(request=None)) == {
        "submission_id": "workflow-id"
    }
    assert calls["genome_id"] == "genome-uuid"
    assert calls["assembly_name"] == "GRCh38.p14"
    assert calls["options"]["cadd"] is True
    assert "species_taxonomy_id" not in calls["options"]
