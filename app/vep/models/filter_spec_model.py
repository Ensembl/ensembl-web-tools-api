"""The results filter catalogue: which fields the query builder offers, and how
each one is presented.

The backend already decides what *can* be filtered — `results_filters` compiles
a condition per field and rejects the rest. This is the other half of that: the
labels, the editor each field needs, and the fixed option sets two of them draw
from. Serving both together means the offered fields and the compilable ones
cannot drift.

What stays on the frontend is per-row bookkeeping — which field a given row has
taken, and so what the next row may offer. That is interface state, not data.

Availability is separate again and already served: `available_scores` and
`available_af_sources` say what this job actually carries, and the frontend
intersects the catalogue with them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_serializer


class FilterOption(BaseModel):
    """One choice in a fixed option set, where the value is not its label."""

    model_config = ConfigDict(extra="forbid")

    value: str
    label: str


class FilterOptionGroup(BaseModel):
    """A titled run of options, for an editor that groups its choices."""

    model_config = ConfigDict(extra="forbid")

    label: str
    options: list[str] = []


class ScoreOption(BaseModel):
    """One impact score the score editor can filter on.

    `placeholder` is a range hint, and differs per score: most missense
    predictors are probabilities, while popEVE is a negative log scale.
    """

    model_config = ConfigDict(extra="forbid")

    value: str
    label: str
    placeholder: str


class ScoreOptionGroup(BaseModel):
    """Scores under a heading, mirroring the input form's own categories."""

    model_config = ConfigDict(extra="forbid")

    title: str
    options: list[ScoreOption] = []


class FilterField(BaseModel):
    """One field the query builder can filter on.

    `editor` names the value editor the field needs — a grouped multi-select of
    consequence terms, a free-text token list, a fixed choice of transcript
    groups, the allele-frequency editor, or the score editor. Each carries only
    what its own editor reads.
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    label: str
    # Read between the field and its value ("is any of"). Empty where the editor
    # chooses its own operator, as the allele-frequency and score editors do.
    operator_label: str = ""
    editor: Literal["consequence", "text", "group", "af", "score"]
    # Text editors: what to show in the empty input.
    placeholder: str | None = None
    mono: bool = False
    # An editor that already takes many values makes a second row redundant, so
    # the field is offered once and then withdrawn.
    single_instance: bool = False
    # Consequence and transcript-group editors: the fixed sets they choose from.
    option_groups: list[FilterOptionGroup] = []
    options: list[FilterOption] = []
    # Score editor: what a variant with no score is called, and the scores on
    # offer. Which of them this job actually carries is `available_scores`.
    missing_label: str | None = None
    score_groups: list[ScoreOptionGroup] = []

    @model_serializer(mode="wrap")
    def _only_what_this_editor_uses(self, handler) -> dict:
        """Emit the keys this field actually carries.

        Each editor reads a different few of these, so serialising all of them
        sends a text field an empty score list and forces every key optional on
        the receiving type, with nothing to say which belong together. An absent
        key and an empty one mean the same thing to the reader.
        """
        return {
            key: value
            for key, value in handler(self).items()
            if value is not None and value != [] and value != "" and value is not False
        }


class FilterSpec(BaseModel):
    """The filter half of the shared library."""

    model_config = ConfigDict(extra="forbid")

    fields: list[FilterField] = []
