"""Help text for a form option: the sentence and links behind its (?) button.

Lives in the shared library, keyed by option id, so one entry serves the option
in every genome that offers it — eighteen options are declared by both
human_grch38.json and human_grch37.json.

`{version}` in a description and `majorVersion` on a link are both resolved by
the frontend against the option's rendered label, so both travel as authored.
"""

from pydantic import BaseModel, ConfigDict, Field


class OptionHelpLink(BaseModel):
    """A resource link rendered after the description."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    href: str
    # Visible link text. The frontend supplies a generic label when unset.
    label: str | None = None
    # Shows the link only for the major version the option's label carries, so
    # an assembly cites its own release rather than the other one's. camelCase
    # on the wire: the payload is handed straight to the frontend, whose
    # OptionHelpLink names the field that way.
    major_version: str | None = Field(default=None, alias="majorVersion")


class OptionHelp(BaseModel):
    """One option's help, keyed by the id the form and results both use."""

    model_config = ConfigDict(extra="forbid")

    option_id: str
    # A `*span*` renders emphasised — a small markdown subset, so the text stays
    # a plain string rather than markup the backend has to escape.
    description: str
    links: list[OptionHelpLink] = []

    def as_payload(self) -> dict:
        """The `help` object served on a form option.

        `option_id` is the key, not part of the value, so it is dropped; unset
        fields are dropped too, keeping a two-key link two keys wide rather than
        padding every one of them with nulls.
        """
        return self.model_dump(
            mode="json", by_alias=True, exclude_none=True, exclude={"option_id"}
        )


class HelpSpec(BaseModel):
    """The help half of the shared library."""

    model_config = ConfigDict(extra="forbid")

    options: list[OptionHelp] = []

    def payload_for(self, option_id: str) -> dict | None:
        """This option's help payload, or None when it has none.

        An option without help is ordinary — nothing is offered for
        `updownstream_distance` or the ClinVar sub-entries — so a miss is not an
        error and the key is simply omitted from the served option.
        """
        for option in self.options:
            if option.option_id == option_id:
                return option.as_payload()
        return None
