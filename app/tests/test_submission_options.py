"""What a submission may set, derived from the spec rather than declared.

PROOF OF CONCEPT for retiring the option half of `ConfigIniParams`. That model
declares 207 fields, of which 199 are options — and those 199 are never read by
attribute: they arrive as `ConfigIniParams(**payload)` and leave as
`.model_dump()`, a flat map for the config interpreter. Nothing here changes the
submission path; these assert the spec could replace it.

See docs/form-panels-to-json.md.
"""

from app.vep.models.pipeline_model import ConfigIniParams
from app.vep.submission_options import submittable_options, unknown_options

HUMAN = "9606"
MOUSE = "10090"

# The eight fields that are genuinely the job's, not an option's. Each is read
# by attribute somewhere; the other 199 are not.
JOB_FIELDS = {
    "genome_id",
    "assembly_name",
    "species_taxonomy_id",
    "gff",
    "fasta",
    "force_overwrite",
    "transcript_version",
    "canonical",
}

# Options the model carries that no form offers, and why.
NOT_SUBMITTABLE = {
    # Phenotypes `forces_on` it; the interpreter sets it, never the client.
    "clinvar_short",
    # Hidden pending chromosome synonyms; computed for ProtVar's link.
    "hgvsg",
    # Dead: no config entry, no control, and the parse was retired (see
    # test_spec_interpreter.test_intact_feature_annotation_is_no_longer_parsed).
    # It has sat on the model unnoticed because the sync test only checks
    # form -> model, never model -> form.
    "intact_feature_annotation",
}

ALL_GENOMES = (
    {"species_taxonomy_id": HUMAN, "assembly_name": "GRCh38.p14"},
    {"species_taxonomy_id": HUMAN, "assembly_name": "GRCh37.p13"},
    {"species_taxonomy_id": MOUSE, "assembly_name": "GRCm39"},
)


def _model_option_fields() -> dict:
    return {
        name: field
        for name, field in ConfigIniParams.model_fields.items()
        if name not in JOB_FIELDS
    }


def _spec_options() -> dict:
    options: dict = {}
    for genome in ALL_GENOMES:
        options.update(submittable_options(**genome))
    return options


def test_the_spec_knows_every_option_the_model_does():
    """The whole question, in one assertion.

    If the spec declares everything the model does, the model's option half is a
    third copy of the config entries — after the panels and the `fields=`
    clause — and can go.
    """
    model = set(_model_option_fields())
    spec = set(_spec_options())

    assert not spec - model, f"spec offers options the model cannot accept: {spec - model}"
    assert model - spec == NOT_SUBMITTABLE


def test_the_spec_agrees_on_every_type_and_default():
    """Not just the names: an option's type and its value when unsent.

    Those are what the model is actually *for* — validating the payload and
    filling in what the client left out — so agreeing on the ids alone would
    prove nothing.
    """
    model = _model_option_fields()
    spec = _spec_options()

    wrong_type = {
        name: (model[name].annotation, spec[name].type)
        for name in spec
        if model[name].annotation is not spec[name].type
    }
    wrong_default = {
        name: (model[name].default, spec[name].default)
        for name in spec
        if model[name].default != spec[name].default
    }
    assert not wrong_type
    assert not wrong_default


def test_the_awkward_shapes_come_through():
    """The four options whose value is not a boolean, stated explicitly.

    A proof that only ever saw toggles would not have tested much: these are a
    number with bounds and a select whose value is a string.
    """
    options = submittable_options(
        species_taxonomy_id=HUMAN, assembly_name="GRCh38.p14"
    )
    assert options["nearest_exon_jb_max_range"].type is int
    assert options["nearest_exon_jb_max_range"].default == 10000
    assert options["updownstream_distance_bp"].type is int
    assert options["updownstream_distance_bp"].default == 5000
    assert options["gnomad_sv_overlap_cutoff"].type is str
    assert options["gnomad_sv_overlap_cutoff"].default == "100"
    assert options["gnomad_cnv_overlap_cutoff"].type is str


def test_what_is_submittable_depends_on_the_assembly():
    """The thing the static model cannot express.

    `pli` is a real option on GRCh38 and not an option at all on GRCh37, but one
    flat set of fields accepts it for both — so a GRCh37 submission can turn on
    something that genome has no data for, and nothing says otherwise.
    """
    grch38 = submittable_options(
        species_taxonomy_id=HUMAN, assembly_name="GRCh38.p14"
    )
    grch37 = submittable_options(
        species_taxonomy_id=HUMAN, assembly_name="GRCh37.p13"
    )
    assert "pli" in grch38
    assert "pli" not in grch37
    assert "pli" in ConfigIniParams.model_fields  # accepted for either, today

    # A species with almost nothing keeps only what it can actually run.
    mouse = submittable_options(species_taxonomy_id=MOUSE, assembly_name="GRCm39")
    assert "go" in mouse
    assert "cadd" not in mouse and "eve" not in mouse


def test_an_unknown_option_is_named_rather_than_dropped():
    """What moving would fix.

    `extra` is pydantic's default on `ConfigIniParams`, so an option id the
    model does not know is discarded without a word: the job runs, that
    annotation is missing, and nothing anywhere says why. A typo behaves
    exactly like a deliberate omission.
    """
    payload = {"cadd": True, "gerpp": True, "pli": True}

    accepted = ConfigIniParams(
        genome_id="x", assembly_name="GRCh38.p14", **payload
    ).model_dump()
    assert "gerpp" not in accepted  # silently gone

    assert unknown_options(
        payload, species_taxonomy_id=HUMAN, assembly_name="GRCh38.p14"
    ) == ["gerpp"]


def test_an_option_this_genome_lacks_is_unknown_to_it():
    """The same check, doing the thing the model cannot: `pli` is a typo's
    equivalent on GRCh37, because that assembly has no such option."""
    assert unknown_options(
        {"pli": True}, species_taxonomy_id=HUMAN, assembly_name="GRCh37.p13"
    ) == ["pli"]
    assert unknown_options(
        {"pli": True}, species_taxonomy_id=HUMAN, assembly_name="GRCh38.p14"
    ) == []
