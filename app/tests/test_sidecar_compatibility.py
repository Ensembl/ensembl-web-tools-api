"""A spec pinned to a job must keep loading after the models move on.

Every job carries the merged spec it was submitted under (`parsing_spec.json`,
beside its VCF), and the results path parses that job's annotations with the
*pinned* spec rather than the current one. The parsing models are
`extra="forbid"`, which is right for an authored spec -- a typo should fail
loudly -- but it means deleting a field breaks every spec already written.

And it breaks it *silently*: `_load_pinned_spec` swallows the error and returns
None, so the job renders with no annotations at all rather than an error saying
why. Two deletions had already done this before these tests existed.

So: whenever a field goes, add its shape here.
"""

import copy
import json
import pathlib

import pytest

from app.vep.models.merged_spec_model import MergedSpec
from app.vep.utils.spec_loader import load_merged_spec

BASELINE = pathlib.Path(__file__).with_name("human_grch38.baseline.json")


def _current() -> dict:
    return json.loads(BASELINE.read_text())


def _clinvar(doc: dict) -> dict:
    return next(p for p in doc["parsing"]["plugins"] if p["plugin"] == "clinvar")


def test_the_current_spec_loads():
    """The control: everything below mutates this, so it has to pass first."""
    MergedSpec.model_validate(_current())


def test_a_join_declaring_item_fields_still_loads():
    # Pinned before `JoinSpec.item_fields` was deleted (2026-08-04).
    doc = _current()
    for join in _clinvar(doc)["joins"]:
        if join.get("as") == "records":
            join["item_fields"] = ["rcv", "classification", "review_status"]
    MergedSpec.model_validate(doc)


def test_a_column_match_spelling_its_column_the_old_way_still_loads():
    # Pinned before `ColumnMatch{field, column}` became `Match{field,
    # equals_column}` (2026-08-04).
    doc = _current()
    changed = False
    for plugin in doc["parsing"]["plugins"]:
        for target in plugin["targets"]:
            match = (target.get("drop_when") or {}).get("unless_matches")
            if match and "equals_column" in match:
                match["column"] = match.pop("equals_column")
                changed = True
    assert changed, "no `unless_matches` left to write the old way"
    spec = MergedSpec.model_validate(doc)
    # ...and it means the same thing, not merely parses.
    phenotypes = next(
        p for p in spec.parsing.plugins if p.plugin == "phenotype_data"
    )
    target = next(t for t in phenotypes.targets if t.drop_when)
    assert target.drop_when.unless_matches.equals_column == "Allele"


def test_a_target_without_join_source_still_loads():
    # Pinned before `TargetSpec.join_source` was added (2026-08-04). Additive
    # with a default, so this is the easy direction -- kept as the reminder
    # that both directions matter.
    doc = _current()
    for target in _clinvar(doc)["targets"]:
        target.pop("join_source", None)
    MergedSpec.model_validate(doc)


def test_a_whole_pre_change_sidecar_loads():
    """All of the above at once, which is what an actual pinned file looks
    like -- a spec does not drift one field at a time."""
    doc = _current()
    for join in _clinvar(doc)["joins"]:
        if join.get("as") == "records":
            join["item_fields"] = ["rcv", "classification", "review_status"]
    for target in _clinvar(doc)["targets"]:
        target.pop("join_source", None)
    for plugin in doc["parsing"]["plugins"]:
        for target in plugin["targets"]:
            match = (target.get("drop_when") or {}).get("unless_matches")
            if match and "equals_column" in match:
                match["column"] = match.pop("equals_column")
    MergedSpec.model_validate(doc)


def test_an_authored_spec_is_still_strict():
    """The leniency above is for fields that *used* to be real. A key nobody
    ever defined is still a typo, and must still fail."""
    doc = _current()
    _clinvar(doc)["targets"][0]["itemfields"] = ["oops"]
    with pytest.raises(Exception, match="[Ee]xtra"):
        MergedSpec.model_validate(doc)
