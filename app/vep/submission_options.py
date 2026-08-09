"""What a submission is allowed to set, according to the spec.

PROOF OF CONCEPT. `ConfigIniParams` (pipeline_model) declares 207 fields, of
which 199 are options: they are never read by attribute — they arrive as
`ConfigIniParams(**payload)` and leave as `.model_dump()`, a flat
`{option_id: value}` map for the config interpreter. The model is a third copy
of what the config entries already say, and the one copy that cannot tell one
assembly's options from another's.

This derives the same contract from the spec instead. Nothing calls it on the
submission path yet; the tests assert it agrees with the model, which is what
has to be true before the model's option half can go.

See docs/form-panels-to-json.md for the migration this completes.
"""

from vep.form_panels import get_visible_panels

# `type` as the form states it -> the type a submitted value must have.
_VALUE_TYPES: dict[str, type] = {
    "boolean": bool,
    "number": int,
    "select": str,
}


class SubmittableOption:
    """One option a submission may set: what type its value is, and what it is
    when the client does not send it."""

    __slots__ = ("id", "type", "default")

    def __init__(self, option_id: str, value_type: type, default) -> None:
        self.id = option_id
        self.type = value_type
        self.default = default

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"SubmittableOption({self.id!r}, {self.type.__name__}, {self.default!r})"


def submittable_options(
    *, species_taxonomy_id: str | None = None, assembly_name: str | None = None
) -> dict[str, SubmittableOption]:
    """Every option id this genome's form offers, with its type and default.

    Read off the panels rather than walked out of the entries directly, because
    the panels are already entirely spec-driven — including the allele
    frequencies, whose sub-options are grown from each entry's own ancestry and
    population tables rather than written down. Deriving from anywhere else
    would be a second way of saying the same thing, which is the problem this
    is here to remove.

    Per assembly, which is the part the static model cannot do: `pli` is a real
    option on GRCh38 and not an option at all on GRCh37.
    """
    options: dict[str, SubmittableOption] = {}

    def walk(option: dict) -> None:
        option_id = option.get("id")
        if option_id is not None:
            value_type = _VALUE_TYPES[option["type"]]
            options[option_id] = SubmittableOption(
                option_id, value_type, option.get("default")
            )
        # A `group` has `options`; everything else nests under `sub_options`.
        for child in option.get("sub_options", []) + option.get("options", []):
            # A select's choices are {label, value} — values, not controls.
            if isinstance(child, dict) and ("id" in child or "options" in child
                                            or "sub_options" in child):
                walk(child)

    for panel in get_visible_panels(
        species_taxonomy_id=species_taxonomy_id, assembly_name=assembly_name
    ):
        for option in panel["options"]:
            walk(option)
    return options


def unknown_options(
    payload: dict, *, species_taxonomy_id: str | None = None,
    assembly_name: str | None = None
) -> list[str]:
    """The keys of `payload` this genome has no option for.

    `ConfigIniParams` drops these silently — `extra` is pydantic's default, so a
    mistyped option id simply does not run and the job comes back without that
    annotation and without a word. Naming them is the point of moving.
    """
    known = submittable_options(
        species_taxonomy_id=species_taxonomy_id, assembly_name=assembly_name
    )
    return sorted(key for key in payload if key not in known)
