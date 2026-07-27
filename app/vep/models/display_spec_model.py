"""Static, strongly-typed model of the *display* spec: how one option's parsed
annotation is laid out in the results annotation detail.

The parsing spec says how a plugin's CSQ columns become structured data; this
says how that data is presented — the labels, order, headings, number formats
and placeholders that were, until now, twelve hand-written `case` bodies in the
frontend's `VepResultsAnnotationDetail`. Moving them here makes the backend the
single owner of the option contract end to end (which options exist, how they
are parsed, how they are shown) and lets the frontend render generically.

It is authored per genome, so unlike the per-job display *panels* it lives
inside the merged spec document as a third sibling section, under the same
content digest, and is pinned to a job for free.

Deliberately small: every field here maps 1:1 onto a rendering primitive the
frontend already has (`RowSpec` / `renderRowGroup` / `renderRowBlock`). Nothing
in this model invents new rendering behaviour, and options whose output is
interactive or derived (ClinVar, OpenTargets, ProtVar, ...) are deliberately
*not* expressible — they stay as frontend overrides.
"""

import re
from typing import Annotated, Iterator, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The value formats the frontend's `formatValue` understands. `text` is the
# default (stringify as-is); the rest are the existing formatter functions.
# `humanize_join` humanises each element of a list then joins them — ClinVar's
# significance terms, shown as one comma-separated value. `count` renders the
# size of a list, or of a `&`-delimited string (IntAct's packed columns), and is
# absent (drops / dashes) when the count is zero — ProtVar's Show-all pockets /
# interfaces counts.
RowFormat = Literal[
    "text", "num", "humanize", "phenotype", "join", "humanize_join", "count"
]

# Which view a block belongs to: the default annotation view or "Show all". A
# block without `view` renders in both (the common case). ProtVar uses it to
# show detailed pocket / interface rows by default but sub-option counts in Show
# all.
BlockView = Literal["default", "show_all"]

# `{field}` placeholders in a link template — the item fields interpolated into
# the URL (e.g. ".../term/{id}").
_TEMPLATE_FIELD = re.compile(r"\{(\w+)\}")


class ComposeSpec(BaseModel):
    """A row value built from more than one field.

    Only one shape exists today: `with_score`, the frontend's `withScore` —
    "Likely benign (0.07)" from a classification plus its score. AlphaMissense
    and EVE both need it, and both drop the row entirely when the
    *classification* is absent, whatever the score says.
    """

    model_config = ConfigDict(extra="forbid")

    format: Literal["with_score"]
    classification: str
    score: str

    def field_refs(self) -> list[str]:
        return [self.classification, self.score]


class SubOption(BaseModel):
    """The form sub-option a row's value comes from.

    Lets "Show all" list a sub-option that ran but produced nothing as a dash
    (the default view drops the empty row instead). `default` mirrors the form
    default: a sub-option left at a default-on value isn't written to the
    submitted parameters, so the frontend treats "absent" as its default (see
    `subOptionRan`). The id is a form option id — the hand-synced seam with
    `form_panels`, like the top-level `option_id`; not a `plugin.field` ref, so
    the display↔parsing check does not touch it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    default: bool = False


class HelpLink(BaseModel):
    """A citation shown inside a row's help popup.

    A fixed reference for the help text — the paper a recommended threshold
    comes from — not a per-row link built from the annotation (that is
    `LinkSpec`). `label` is the anchor's text; without one the frontend uses its
    own wording.
    """

    model_config = ConfigDict(extra="forbid")

    # `href`, not `url`, to match the form side's OptionHelpLink: the two help
    # systems should converge rather than grow a second name for one thing.
    href: str
    label: str | None = None


class WhenSpec(BaseModel):
    """A condition gating whether a block renders, tested against one field.

    `present` -> render only when the field has content; `empty` -> only when it
    is absent (null / '' / empty list). ClinVar uses it to flip between a bare
    "Clinical significance" row (no conflicting breakdown) and a headed block
    (breakdown present). The field is a `<plugin>.<field>` reference like a row's
    `from`, resolved against the parsing spec at load like the rest.
    """

    model_config = ConfigDict(extra="forbid")

    present: str | None = None
    empty: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "WhenSpec":
        if bool(self.present) == bool(self.empty):
            raise ValueError("when needs exactly one of `present` or `empty`")
        return self

    @property
    def field_ref(self) -> str:
        # exactly one is set (validated above)
        return self.present or self.empty  # type: ignore[return-value]


class SelectedGate(BaseModel):
    """Gate a block on whether a form option/sub-option was *selected* for the
    job (as opposed to `when`/`requires`, which test the annotation data).

    The ClinVar master's display renders its short and structural blocks under
    one option, so each block gates on its own sub-option: dev-data VCFs are
    annotated from a full cache and carry columns the user didn't pick, so
    gating on data alone would leak the unselected variant kind into the view.
    `id` is the sub-option id; `default` is that sub-option's default (an option
    left at its default isn't written to the submitted parameters).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    default: bool = False


class LinkSpec(BaseModel):
    """How to turn a value into a link.

    `external` -> a plain anchor (`target=_blank`). `template` is a full URL with
    `{field}` placeholders filled from the item's fields (e.g. a GO term or
    MaveDB URN); `builder` names a frontend link builder for URLs that aren't a
    simple template (ProtVar's algorithmic URL). `app_popup` -> an in-app
    "View in" popup, which is always a named `builder` (it needs the job's genome
    and the consequence, not just the annotation field) — e.g. the protein id.

    On a `CellSpec` the link wraps that cell's value; on a `DisplayRow` or a
    `DisplayItemSpec` it is a trailing link on the row's value (ProtVar's icon).
    A `template` only makes sense where item fields exist to fill it (cells);
    row/item-level links use a `builder`.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["external", "app_popup"]
    template: str | None = None
    builder: str | None = None

    @model_validator(mode="after")
    def _template_xor_builder(self) -> "LinkSpec":
        if bool(self.template) == bool(self.builder):
            raise ValueError("link needs exactly one of `template` or `builder`")
        if self.kind == "app_popup" and not self.builder:
            raise ValueError("an app_popup link must use a `builder`")
        return self

    def template_fields(self) -> list[str]:
        """The item field names a `template` interpolates; empty for a builder."""
        return _TEMPLATE_FIELD.findall(self.template) if self.template else []


class DisplayRow(BaseModel):
    """One label/value row.

    `from` is a `<plugin>.<field>` reference into the *parsing* spec — the
    plugin id and one of its declared target fields. Which entity that plugin is
    read from (allele or transcript consequence) is deliberately not stated
    here: it already lives on the parsing plugin's `scope`, and is derived at
    serve time (see `MergedSpec.plugin_scopes`).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # React list key. Optional: absent means "use the row's position", which is
    # stable for these fixed lists.
    key: str | None = None
    label: str
    # `from` is a Python keyword, hence the alias (as in TargetSpec).
    source: str | None = Field(default=None, alias="from")
    compose: ComposeSpec | None = None
    format: RowFormat | None = None
    mono: bool = False
    # What to show when the value is absent. Unset drops the row entirely; set
    # keeps it and shows this (SpliceAI's deltas always read as a set of eight).
    placeholder: str | None = None
    # Help text for a (?) button beside the label. The text is data; the button
    # is a frontend primitive.
    help: str | None = None
    # A source to cite inside that help popup — popEVE's threshold is the
    # authors' recommendation, so the help says where to read it. Deliberately
    # not a `LinkSpec`: those build a URL per row from the annotation's own
    # values, whereas this is one fixed reference belonging to the help text.
    help_link: HelpLink | None = None
    # The sub-option this row's value comes from. Only affects "Show all": a
    # selected-but-empty sub-option shows a dash there; the default view still
    # drops it. Rows without one behave exactly as before.
    sub_option: SubOption | None = None
    # A trailing link on the value (a named `builder` — ProtVar's link icon on
    # each row). Builder links contribute no field refs.
    link: LinkSpec | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "DisplayRow":
        if bool(self.source) == bool(self.compose):
            raise ValueError("row needs exactly one of `from` or `compose`")
        return self

    def field_refs(self) -> list[str]:
        return [self.source] if self.source else self.compose.field_refs()


class CellSpec(BaseModel):
    """One cell of a repeated item (see `DisplayListBlock`).

    `from` is a field *of the list element* (not `plugin.field`) — e.g. `score`
    on a MaveDB assay. Omit it for a scalar list whose elements are the value
    themselves (phenotype strings). `link` makes the cell an anchor. An optional
    `label` prefixes the value ("L2G 0.42").
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    label: str | None = None
    # `from` is a Python keyword, hence the alias.
    source: str | None = Field(default=None, alias="from")
    format: RowFormat | None = None
    mono: bool = False
    link: LinkSpec | None = None

    def item_field_refs(self) -> Iterator[str]:
        """Every item field this cell reads: its `from` plus any `{field}`
        placeholders in a link template. Builder links contribute nothing (the
        frontend builder owns its inputs)."""
        if self.source:
            yield self.source
        if self.link:
            yield from self.link.template_fields()


# House style for the results display: a block that repeats — a list, or a table
# in list mode — shows three rows and puts the rest behind a show-more toggle.
# An annotation panel is a summary, and a variant can carry a hundred phenotype
# rows or a dozen interactions; without a cap one option pushes every other
# option off the screen. Applied as the *default* rather than asked of each
# block, so a new one inherits it and only has to say something when it wants a
# different number.
DEFAULT_TRUNCATE_VISIBLE_COUNT = 3


class TruncateSpec(BaseModel):
    """Show the first `visible_count` items with the rest behind a show-more
    toggle (the frontend's `TruncatedList`)."""

    model_config = ConfigDict(extra="forbid")

    visible_count: int = Field(gt=0)


def _default_truncate() -> TruncateSpec:
    return TruncateSpec(visible_count=DEFAULT_TRUNCATE_VISIBLE_COUNT)


class DisplayItemLabel(BaseModel):
    """The label of a list element rendered as a label/value row (see
    `DisplayItemSpec.label`).

    `from` reads one item field (ClinVar's per-class significance); `template`
    interpolates item fields into text ("Pocket {pocket_id}"). `format` applies
    to a `from` value (e.g. humanize).

    `wrap` surrounds the *formatted* `from` value with fixed text via a single
    `{}` slot — ClinVar's conflicting counts read `Submitters reporting
    "Pathogenic"` from the humanised class. It only combines with `from` (there
    is a value to wrap), never `template` (already free text).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: str | None = Field(default=None, alias="from")
    template: str | None = None
    format: RowFormat | None = None
    wrap: str | None = None

    @model_validator(mode="after")
    def _source_xor_template(self) -> "DisplayItemLabel":
        if bool(self.source) == bool(self.template):
            raise ValueError(
                "item label needs exactly one of `from` or `template`"
            )
        if self.wrap is not None:
            if not self.source:
                raise ValueError("item label `wrap` needs `from`")
            if "{}" not in self.wrap:
                raise ValueError("item label `wrap` needs a `{}` placeholder")
        return self

    def item_field_refs(self) -> Iterator[str]:
        """The item fields this label reads: its `from`, or the `{field}`
        placeholders in its `template`."""
        if self.source:
            yield self.source
        if self.template:
            yield from _TEMPLATE_FIELD.findall(self.template)


class DisplayItemFieldRow(BaseModel):
    """One labelled field-row of a list element rendered as a stack of rows (see
    `DisplayItemSpec.rows`): a fixed `label` and a value read from one item field
    (NearestExonJB's Exon / Distance / Boundary type / Exon length)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    label: str
    source: str = Field(alias="from")  # an item field, not `plugin.field`
    format: RowFormat | None = None

    def item_field_refs(self) -> Iterator[str]:
        yield self.source


class DisplayItemSpec(BaseModel):
    """How one element of a list renders.

    Without `label`, a row of one or more inline cells (a GO id + name). With
    `label`, a label/value row instead: `label` is the row's label and the
    `cells` render as its value — ClinVar's per-class counts, ProtVar's pockets.

    With `rows` instead of `cells`, the element renders as a stack of labelled
    field-rows (one `label: value` row per field) — a repeated structured record
    like NearestExonJB's exon boundaries. `cells` and `rows` are mutually
    exclusive; `label`/`link` don't apply to the `rows` layout.
    """

    model_config = ConfigDict(extra="forbid")

    label: DisplayItemLabel | None = None
    cells: list[CellSpec] | None = Field(default=None, min_length=1)
    rows: list[DisplayItemFieldRow] | None = Field(default=None, min_length=1)
    # A trailing link on a label/value item's value (ProtVar's per-pocket icon).
    # Only meaningful with `label` (the row layout); a named builder, no refs.
    link: LinkSpec | None = None

    @model_validator(mode="after")
    def _cells_xor_rows(self) -> "DisplayItemSpec":
        if bool(self.cells) == bool(self.rows):
            raise ValueError("list item needs exactly one of `cells` or `rows`")
        return self

    def item_field_refs(self) -> Iterator[str]:
        """Every item field this element reads, across its label, cells and rows."""
        if self.label:
            yield from self.label.item_field_refs()
        for cell in self.cells or []:
            yield from cell.item_field_refs()
        for row in self.rows or []:
            yield from row.item_field_refs()


class _GatedBlock(BaseModel):
    """What every display block has, however it renders.

    A block is a thing that may or may not appear, and four gates decide:
    `requires_selected` (was the sub-option chosen for this job), `when` (does
    the data satisfy a condition), `view` (default panel or "Show all"), and —
    for the block kinds that carry it — `requires` (did a plugin produce anything
    at all).

    Declared once so a new block kind cannot arrive missing one. Before this,
    each of the four kinds redeclared the same five fields, and `group_by` had
    already been added to two of them separately.
    """

    model_config = ConfigDict(extra="forbid")

    heading: str | None = None
    # Render only when this sub-option was selected (ClinVar short/structural).
    requires_selected: SelectedGate | None = None
    # A data condition: render only when the named field is present / empty
    # (ClinVar's bare vs headed shapes).
    when: WhenSpec | None = None
    # Restrict this block to the default view or "Show all" (ProtVar / IntAct).
    view: BlockView | None = None


class DisplayRowsBlock(_GatedBlock):
    """A run of fixed rows, optionally under the option's own sub-heading.

    `heading` present -> the frontend's `renderRowBlock` (an `OptionBlock` whose
    heading only appears if a row survived); absent -> `renderRowGroup` (the
    rows on their own).

    `requires` names a plugin that must have produced an annotation at all for
    the block to render. It exists for SpliceAI, whose delta rows carry a
    placeholder: without it, a variant with no SpliceAI annotation would render
    eight dashes instead of nothing (the hand-written case returned early).
    """

    kind: Literal["rows"] = "rows"
    requires: str | None = None
    rows: list[DisplayRow]


class RowFilter(BaseModel):
    """Keep only the list elements whose `field` equals `value`.

    Lets two tables split one list between them so both can sit under a single
    heading — the phenotypes option shows variant-associated rows and ClinVar's
    own rows as two tables under one "Variant associated" group. `group_by`
    cannot do that: it builds a heading per table, so a second table repeats the
    heading rather than joining it.

    Equality only. Anything richer belongs in the parsing spec, which already
    has `drop_when` and can express it once rather than per display block.
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    equals: str | None = None
    # The complement, so a pair of tables can divide a list exhaustively. Without
    # it the second table names the values it wants, and a value the pipeline
    # starts emitting matches neither and vanishes -- worse than the missing
    # heading this was built to fix.
    not_equals: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "RowFilter":
        if bool(self.equals) == bool(self.not_equals):
            raise ValueError("where needs exactly one of `equals` or `not_equals`")
        return self


class GroupBy(BaseModel):
    """Split the rows into one sub-section per distinct value of an item field.

    The sub-headings come from the *data* — the distinct values in first-seen
    order — rather than being written into the spec, so a value the pipeline
    starts emitting appears on its own without a spec change. Phenotype entries
    carry a `type` ("Gene" / "Variation"), and each kind gets its own headed
    table.

    `labels` renames individual headings for display where the pipeline's own
    word is not the one to show ("Variation" -> "Variant associated"). Values
    with no entry keep the data's own wording, so the data-driven default holds.
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    labels: dict[str, str] | None = None


class DisplayListBlock(_GatedBlock):
    """A variable-length list: one item (a row of cells) per element of a
    list-valued field, optionally truncated. Covers the options whose output is
    a repeat rather than a fixed set of rows — phenotypes, GO terms, MaveDB
    assays, ...

    `from` is the `<plugin>.<listField>` the elements come from; that field must
    be a parse-plugin target declaring the element's `item_fields`, which the
    cells' `from`/link templates reference.

    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: Literal["list"]
    requires: str | None = None
    source: str = Field(alias="from")
    # Split the items into a headed sub-section per distinct value of an item
    # field — GO terms by aspect. Same semantics as a table's: headings come from
    # the data, `labels` renames them, and `truncate` then applies per section.
    group_by: GroupBy | None = None
    # Defaults to the house style (see DEFAULT_TRUNCATE_VISIBLE_COUNT); set an
    # explicit `visible_count` to show a different number.
    truncate: TruncateSpec = Field(default_factory=_default_truncate)
    item: DisplayItemSpec

    def list_ref(self) -> tuple[str, str]:
        """The `(plugin, listField)` this block iterates."""
        plugin, _, field = self.source.partition(".")
        return plugin, field


class TableColumn(BaseModel):
    """One column of a `table` block: a header `label`.

    In list mode the value comes from the list element's `from` field. In fixed
    (matrix) mode the columns are headers only — the first names the row-label
    column, the rest are value columns filled from each `TableMatrixRow.values`,
    with this column's `format` applied to that value."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    label: str
    # `from` is a Python keyword, hence the alias. Omit for a scalar list whose
    # elements are the value themselves (list mode), or in fixed mode (headers).
    source: str | None = Field(default=None, alias="from")
    format: RowFormat | None = None
    mono: bool = False
    # A column present only when its sub-option ran, so a table's width follows
    # what the user selected. Same gate the rows use.
    sub_option: SubOption | None = None
    # Link the cell value out. `{value}` in the template is the cell's own text
    # (after `split` and `link_prefix` have been applied).
    link: LinkSpec | None = None
    # Some sources pack several values into one column — IntAct joins interaction
    # participants with `_and_`. Splitting here renders them as separate items,
    # each linked in its own right, rather than one link over the whole string.
    split: str | None = None
    # Only link a value that carries this prefix, and strip it before filling the
    # template: IntAct writes `uniprotkb:P37840`, and UniProt's URL wants the bare
    # accession. A value without the prefix is not a UniProt accession at all, so
    # it renders as plain text rather than becoming a broken link.
    link_prefix: str | None = None
    # When every row of the table shares one value for this column, show it once
    # above the table instead of repeating it down a column. IntAct's affected
    # protein and feature short label are usually the same for every interaction
    # a variant takes part in — a column of ten identical values costs width the
    # columns that do vary need. If the value does vary, it stays a column.
    lift_when_invariant: bool = False

    @model_validator(mode="after")
    def _prefix_and_split_need_a_link(self) -> "TableColumn":
        if (self.split or self.link_prefix) and self.link is None:
            raise ValueError(
                "`split`/`link_prefix` only apply to a linked column; "
                f"column {self.label!r} has neither a link nor a reason for them"
            )
        return self

    def item_field_refs(self) -> Iterator[str]:
        if self.source:
            yield self.source


class TableMatrixRow(BaseModel):
    """One row of a fixed `table` (matrix mode): a text `label` for the first
    column, then a `<plugin>.<field>` scalar ref per value column — SpliceAI's
    "Acceptor gain" | ds_acceptor_gain | dp_acceptor_gain."""

    model_config = ConfigDict(extra="forbid")

    label: str
    values: list[str] = Field(default_factory=list)


class DisplayTableBlock(_GatedBlock):
    """A small table with a header row of column labels. Two shapes:

    * list mode (`from`): one body row per element of a `<plugin>.<listField>`,
      each column reading that element's `from` item field — ClinVar's
      conflicting classifications (Classification | Submitters reporting).
    * fixed / matrix mode (`rows`): explicit rows of `{label, values}`, the label
      filling the first column and each value a `<plugin>.<field>` scalar under a
      value column — SpliceAI's splicing events (Splicing event | ΔS | ΔP).

    Exactly one of `from` / `rows` is set.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: Literal["table"]
    requires: str | None = None
    # Sit one indent step in, as if under a heading. For a table with no heading
    # standing beside headed siblings: the ClinVar phenotype table names its
    # source in a column rather than a heading, but still belongs at the depth of
    # the "Gene associated" / "Variant associated" tables it sits with, not a step
    # out from them.
    indent: bool = False
    # list mode: the `<plugin>.<listField>` the rows come from.
    source: str | None = Field(default=None, alias="from")
    columns: list[TableColumn] = Field(min_length=1)
    # list mode: split the rows into a headed table per distinct value.
    group_by: GroupBy | None = None
    # list mode: keep only the rows matching this, so two tables can divide one
    # list between them under a shared heading (see RowFilter).
    where: RowFilter | None = None
    # list mode: show this many rows, the rest behind a show-more toggle (per
    # section when grouped). Defaults to the house style — see
    # DEFAULT_TRUNCATE_VISIBLE_COUNT — and is left unset for a fixed matrix,
    # whose height is known and small.
    truncate: TruncateSpec | None = None
    # fixed mode: explicit rows.
    rows: list[TableMatrixRow] | None = None

    @model_validator(mode="after")
    def _from_xor_rows(self) -> "DisplayTableBlock":
        if bool(self.source) == bool(self.rows):
            raise ValueError("table needs exactly one of `from` or `rows`")
        # List mode repeats, so it takes the house-style cap unless the spec
        # named its own. A fixed matrix does not repeat and is left alone.
        if self.source is not None and self.truncate is None:
            self.truncate = _default_truncate()
        if self.rows is not None:
            # Fixed matrix: columns are headers, the first is the row-label
            # column and the rest are value columns filled from each row.
            for column in self.columns:
                if column.source is not None:
                    raise ValueError("a fixed table's columns take no `from`")
            value_columns = len(self.columns) - 1
            for row in self.rows:
                if len(row.values) != value_columns:
                    raise ValueError(
                        f"table row {row.label!r} has {len(row.values)} value(s) "
                        f"but there are {value_columns} value column(s)"
                    )
        return self

    def list_ref(self) -> tuple[str, str]:
        """The `(plugin, listField)` this block iterates (list mode only)."""
        plugin, _, field = (self.source or "").partition(".")
        return plugin, field

    def column_field_refs(self) -> Iterator[str]:
        """The item fields the columns read, plus the fields the rows group on
        or are filtered by (list mode)."""
        for column in self.columns:
            yield from column.item_field_refs()
        if self.group_by:
            yield self.group_by.field
        if self.where:
            # Checked like any other item ref: a typo would silently keep no
            # rows, and the block would just vanish.
            yield self.where.field

    def matrix_value_refs(self) -> Iterator[str]:
        """Every `<plugin>.<field>` a fixed table's rows read."""
        for row in self.rows or []:
            yield from row.values

    def value_column_formats(self) -> Iterator[tuple[str, str]]:
        """(ref, format) pairs for a fixed table: each row value paired with its
        value column's format (the columns after the label column), where set."""
        value_columns = self.columns[1:]
        for row in self.rows or []:
            for column, ref in zip(value_columns, row.values):
                if column.format:
                    yield ref, column.format


class DisplayGroupBlock(_GatedBlock):
    """A run of sub-blocks under one optional heading, gated as a whole by `when`.

    Lets a heading span more than one block conditionally: ClinVar's conflicting
    case is a "Classification" row plus a per-class breakdown list under one
    "Clinical significance" heading, shown only when the breakdown is present.
    Distinct from `DisplayOptionSpec.heading`, which spans *every* block of the
    option unconditionally.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["group"] = "group"
    heading: str | None = None
    requires_selected: SelectedGate | None = None
    when: WhenSpec | None = None
    view: BlockView | None = None
    blocks: list["DisplayBlock"]


# A block is a fixed set of rows, a repeated list, a table, or a group of
# sub-blocks, discriminated on `kind`.
DisplayBlock = Annotated[
    Union[
        DisplayRowsBlock,
        DisplayListBlock,
        DisplayTableBlock,
        DisplayGroupBlock,
    ],
    Field(discriminator="kind"),
]

# `DisplayGroupBlock.blocks` refers to the union defined just above it.
DisplayGroupBlock.model_rebuild()


class DisplayOptionSpec(BaseModel):
    """How one form option renders: a sequence of blocks.

    A sequence, not a single block, because an option can legitimately emit more
    than one: `eve` is a bare EVE row *plus* a sibling popEVE heading block.
    """

    model_config = ConfigDict(extra="forbid")

    option_id: str
    # An option-level heading wrapping *all* the option's blocks in one
    # `OptionBlock`, shown whenever the option renders anything. For an option
    # whose output spans more than one block under a single heading — MaveDB's
    # "Variant" row plus its assays list — where a per-block heading can't reach
    # across blocks. Distinct from a block's own `heading` (use one or the other).
    heading: str | None = None
    blocks: list[DisplayBlock]

    def iter_blocks(self) -> Iterator[DisplayBlock]:
        """Every block in the option, groups flattened. The group block itself is
        yielded (so its own `when` gets checked) as well as its children, so the
        consistency check can treat the tree as a flat list of blocks."""

        def walk(blocks: list[DisplayBlock]) -> Iterator[DisplayBlock]:
            for block in blocks:
                yield block
                if isinstance(block, DisplayGroupBlock):
                    yield from walk(block.blocks)

        yield from walk(self.blocks)

    def plugin_refs(self) -> set[str]:
        """The parse plugins this option reads — the `<plugin>` half of every
        scalar `plugin.field` ref plus each block's `requires`. Used to select
        which options a genome offers: an option belongs in an assembled spec
        only when every plugin it reads is present. Mirrors the scalar refs the
        display↔parsing consistency check resolves (item-relative cell/column
        refs are element fields, not plugins, so they are not counted)."""
        refs: set[str] = set()
        for block in self.iter_blocks():
            if block.when:
                refs.add(block.when.field_ref.partition(".")[0])
            if isinstance(block, DisplayGroupBlock):
                continue
            if block.requires:
                refs.add(block.requires)
            if isinstance(block, DisplayRowsBlock):
                for row in block.rows:
                    for ref in row.field_refs():
                        refs.add(ref.partition(".")[0])
            elif isinstance(block, DisplayListBlock):
                refs.add(block.list_ref()[0])
            elif isinstance(block, DisplayTableBlock):
                if block.rows is not None:
                    for ref in block.matrix_value_refs():
                        refs.add(ref.partition(".")[0])
                else:
                    refs.add(block.list_ref()[0])
        return refs


class DisplaySpec(BaseModel):
    """The display half of the merged document: every laid-out option."""

    model_config = ConfigDict(extra="forbid")

    options: list[DisplayOptionSpec]


class DisplayPayload(BaseModel):
    """What the results response carries: the display spec plus the plugin ->
    scope map derived from `parsing`, which the frontend needs to know whether
    to read a row's plugin from the allele or the transcript consequence.

    The scopes are derived rather than authored so there is only ever one place
    that states them (the parsing plugin), and no hand-synced copy to drift.
    """

    model_config = ConfigDict(extra="forbid")

    options: list[DisplayOptionSpec]
    plugin_scopes: dict[str, str]
