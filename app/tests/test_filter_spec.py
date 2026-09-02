"""The results filter catalogue: which fields the query builder offers.

The backend decides what can be filtered; this says how each field is presented,
so the offered fields and the compilable ones cannot drift. Availability is
separate and already served — `available_scores` and `available_af_sources` say
what a job carries, and the frontend intersects.
"""

from app.vep.utils.results_filters import available_transcript_groups
from app.vep.utils.spec_loader import load_merged_spec
from app.vep.utils.vcf_results import _gated_filter_fields

HUMAN_COLUMNS = {
    "CANONICAL", "MANE", "MANE_SELECT", "MANE_PLUS_CLINICAL", "GENCODE_PRIMARY",
}


def _spec():
    return load_merged_spec("human_grch38")


def test_the_library_carries_a_filter_catalogue():
    spec = _spec()
    assert spec.filters is not None
    assert [f.field for f in spec.filters.fields] == [
        "consequence", "transcript", "gene_symbol", "gene_id",
        "transcript_group", "allele_frequency", "cadd_phred",
    ]


def test_every_offered_field_is_one_the_backend_can_compile():
    """The point of moving the catalogue here: a field the query builder offers
    that `results_filters` cannot compile would fail only when someone used it."""
    from app.vep.utils.results_filters import _BUILDERS

    for field in _spec().filters.fields:
        assert field.field in _BUILDERS, field.field


def test_every_score_offered_has_a_spec_behind_it():
    """The score editor's options are separate from the field id, so they need
    the same check: one the parse has no columns for could never match."""
    from app.vep.utils.results_filters import SCORE_SPECS

    scores = next(f for f in _spec().filters.fields if f.editor == "score")
    for group in scores.score_groups:
        for option in group.options:
            assert option.value in SCORE_SPECS, option.value


def test_a_text_field_carries_what_its_editor_needs():
    transcript = next(f for f in _spec().filters.fields if f.field == "transcript")
    assert transcript.editor == "text"
    assert transcript.placeholder == "e.g. ENST00000341065"
    assert "mono" not in transcript.model_dump()


def test_membership_fields_start_with_the_backend_membership_operator():
    membership_editors = {"consequence", "text", "group"}
    for field in _spec().filters.fields:
        if field.editor in membership_editors:
            assert field.initial_condition.model_dump(exclude_none=True) == {
                "operator": "in", "values": [],
            }


def test_numeric_fields_carry_their_initial_values_and_operator_choices():
    fields = {field.editor: field for field in _spec().filters.fields}

    af = fields["af"]
    assert af.initial_condition.model_dump(exclude_none=True) == {
        "operator": "le", "values": [], "threshold": 0.05, "match": "any",
    }
    assert [(option.value, option.label) for option in af.operator_options] == [
        ("le", "≤"), ("ge", "≥"),
    ]

    score = fields["score"]
    assert score.model_dump()["initial_condition"] == {
        "operator": "ge", "values": [], "include_missing": False,
    }
    assert [(option.value, option.label) for option in score.operator_options] == [
        ("le", "≤"), ("ge", "≥"),
    ]


def test_the_consequence_terms_are_grouped():
    consequence = next(f for f in _spec().filters.fields if f.field == "consequence")
    assert consequence.single_instance is True
    assert len(consequence.option_groups) == 5
    assert sum(len(g.options) for g in consequence.option_groups) == 39


def test_the_scores_are_grouped_as_the_input_form_groups_them():
    scores = next(f for f in _spec().filters.fields if f.field == "cadd_phred")
    assert [g.title for g in scores.score_groups] == [
        "Genome wide", "Missense", "Splicing"
    ]
    popeve = next(
        o for g in scores.score_groups for o in g.options if o.value == "popeve"
    )
    # popEVE is a negative log scale where the other missense scores are
    # probabilities, so its range hint is not "e.g. 0.5".
    assert popeve.placeholder == "e.g. -3"


# --- availability, from the output rather than from the species --------------


def test_transcript_groups_come_from_the_columns_the_output_has():
    assert set(available_transcript_groups(HUMAN_COLUMNS)) == {
        "canonical", "mane_select", "mane_plus_clinical", "gencode_primary",
    }
    assert available_transcript_groups({"CANONICAL"}) == ["canonical"]


def test_mane_falls_back_to_the_combined_column():
    """Depending on the run, MANE membership is either its own column or a label
    in `MANE` — either is enough to offer the group."""
    assert set(available_transcript_groups({"MANE"})) >= {
        "mane_select", "mane_plus_clinical",
    }


def test_the_served_catalogue_drops_groups_the_output_cannot_match():
    fields = _gated_filter_fields(_spec(), {"CANONICAL"})
    groups = next(f for f in fields if f.field == "transcript_group")
    assert [o.value for o in groups.options] == ["canonical"]


def test_a_group_field_with_nothing_left_is_not_offered():
    fields = _gated_filter_fields(_spec(), {"SOMETHING_ELSE"})
    assert not any(f.field == "transcript_group" for f in fields)


def test_the_other_fields_are_untouched_by_gating():
    ungated = _gated_filter_fields(_spec(), None)
    gated = _gated_filter_fields(_spec(), {"CANONICAL"})
    for field in ungated:
        if field.field == "transcript_group":
            continue
        assert field in gated, field.field


def test_a_spec_without_the_section_serves_nothing():
    """A job pinned before the catalogue existed still renders; the frontend
    falls back to what it knows."""
    spec = _spec()
    spec.filters = None
    assert _gated_filter_fields(spec, HUMAN_COLUMNS) is None
