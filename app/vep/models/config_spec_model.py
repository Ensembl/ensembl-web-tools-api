"""Static, strongly-typed model of the *config-generation* half of the merged
annotation spec.

Sibling to `parsing_spec_model.py`. Where the parsing spec says how to read a
plugin's CSQ columns, this says how a *selected option* becomes a line in the VEP
`config.ini` — replacing the hardcoded `PLUGIN_CONFIG_LINES` /
`PLUGIN_CONFIG_LINES_BY_ASSEMBLY` maps and the `create_config_ini_file` body in
`pipeline_model.py`. It is *data* (the `config` section of the merged JSON under
`specs/`, later served by the annotation API), so it is validated hard on arrival
(`extra="forbid"`).

The emitters are a **small closed set** — `{flag, plugin, custom}` — derived by
enumerating what `create_config_ini_file` actually emits, not invented, exactly
as the parsing transforms were. The always-on base config (`force_overwrite`,
`numbers`, `symbol`, … and the assembly-gated `mane`/`assembly`) is deliberately
NOT here: it is a VEP-invocation invariant that stays in the backend, next to the
per-genome `gff`/`fasta` resolution. See app/vep/docs/design/spec-and-extension-guide.md.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


# --------------------------------------------------------------------------- #
# Param values — the right-hand side of one plugin/custom kwarg.               #
# A value is a literal string, or one of these small typed forms.             #
# --------------------------------------------------------------------------- #

class ByAssembly(BaseModel):
    """A value chosen by the submission's assembly, e.g. an assembly-specific
    data file. Keys are assembly prefixes (`GRCh38`/`GRCh37`); the interpreter
    falls back to `GRCh38` when the assembly isn't listed, matching the ini
    builder's `by_assembly.get(assembly, by_assembly["GRCh38"])`.
    """

    model_config = ConfigDict(extra="forbid")

    by_assembly: dict[str, str]
    # When the submission's assembly isn't a key: fall back to `GRCh38` (mirrors
    # the ini builder's `by_assembly.get(assembly, by_assembly["GRCh38"])`)
    # unless this is set — then the whole param is dropped. For a param that
    # exists on some assemblies only (SpliceAI's `snv_ensembl`, GRCh38 only).
    omit_if_absent: bool = False


class FromOption(BaseModel):
    """A flag derived from another option. Without `equals`: `int(bool(option))`
    (ProtVar's stability/pocket/int, dosage's cover, mutfunc's sub-flags).
    With `equals`: 1 when a *select* option equals the value, else 0 (the
    TSSDistance direction radio → three upstream/downstream/both flags).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_option: str
    equals: str | None = None
    # `as` is a Python keyword.
    #   int    -> int(bool(option)), or 1 when `equals` matches (the 0/1 flags)
    #   value  -> the option's own value verbatim (NearestExonJB's max_range)
    as_type: Literal["int", "value"] = Field(alias="as")


# A literal wins the union unambiguously; the two dict forms discriminate on
# their distinct required keys (`by_assembly` vs `from_option`).
ParamValue = Union[str, ByAssembly, FromOption]


# --------------------------------------------------------------------------- #
# Variadic sub-flags (IntAct) and the genome gate.                            #
# --------------------------------------------------------------------------- #

class VariadicFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option: str   # the boolean sub-option id
    keyword: str  # the ini flag it appends when on, e.g. `feature_ac`


class VariadicFlags(BaseModel):
    """IntAct-style: append `,<keyword>=1` for each selected sub-option, or a
    single `,<all_shortcut>=1` when *all* of them are selected. None selected
    leaves the base line untouched.

    `implicit_all` is for a plugin that already does everything when told
    nothing — mutfunc. There, naming every flag is not how you ask for all of
    them; saying nothing is. So all-selected emits no flags at all, and a subset
    emits just that subset.

    It follows that such a plugin cannot be asked for *nothing*: an empty flag
    list is how you ask for everything. So with `implicit_all`, no sub-option
    selected emits no line at all, rather than a bare line meaning the opposite.
    """

    model_config = ConfigDict(extra="forbid")

    options: list[VariadicFlag]
    all_shortcut: str | None = None
    implicit_all: bool = False

    @model_validator(mode="after")
    def _shortcut_xor_implicit(self) -> "VariadicFlags":
        if self.all_shortcut and self.implicit_all:
            raise ValueError(
                "`all_shortcut` names a flag meaning all; `implicit_all` means "
                "all needs no flag — a plugin cannot want both"
            )
        return self


class GenomeGate(BaseModel):
    """Emit only for these assemblies (prefix match, like the ini builder's
    `is_human_grch38` etc.). Mirrors the parser's CSQ `when`, on the genome."""

    model_config = ConfigDict(extra="forbid")

    assembly: list[str]


# --------------------------------------------------------------------------- #
# `fields=` for custom lines — a small closed set of named builders over the   #
# open field-code data that lives on the option definitions.                   #
# --------------------------------------------------------------------------- #

class LiteralFields(BaseModel):
    """A fixed field list, e.g. ClinVar's `CLNSIG%CLNSIGCONF`."""

    model_config = ConfigDict(extra="forbid")

    literal: list[str]


class AncestryCode(BaseModel):
    """One gnomAD ancestry option and its field-code component. `code` is empty
    for "all". `sex_split=False` marks a code that takes no XX/XY suffix and is a
    plain toggle (genomes' `grpmax`).

    `label` and `default` are what the form draws. They live here so the ancestry
    is stated once: this list already had to name every ancestry to build the
    `fields=` clause, and the form used to name them all again — the two had
    already drifted (`grpmax` was in one and not the other).
    """

    model_config = ConfigDict(extra="forbid")

    option: str
    code: str
    sex_split: bool = True
    label: str = ""
    default: bool = False
    # Where the form shows it, when that is not where the `fields=` clause wants
    # it. genomes' `grpmax` is emitted last but sits directly under "All", where
    # the two frequencies useful without knowing the variant's population belong
    # together. Sparse, like FormOption.order; unset means "in list order".
    form_order: int | None = None


class SexCode(BaseModel):
    """A sex sub-option suffix and its field-code component (both="", female=XX,
    male=XY). The sub-option id is `<ancestry.option>_<suffix>`."""

    model_config = ConfigDict(extra="forbid")

    suffix: str
    code: str
    label: str = ""
    default: bool = False


class PopulationCode(BaseModel):
    """One All of Us (or gnomAD structural) population option and the field
    code(s) it contributes ("max" contributes two)."""

    model_config = ConfigDict(extra="forbid")

    option: str
    codes: list[str]
    label: str = ""
    default: bool = False
    # The code the *parser* reports for this population, which is not always the
    # one the option id carries: gnomAD SV is suffix-named lowercase on GRCh38
    # (`AF_afr` -> `afr`) and prefix-named uppercase on GRCh37 (`AFR_AF` ->
    # `AFR`), and the two assemblies share option ids. Stated rather than
    # derived, because deriving it needs a rule per source and getting one wrong
    # mislabels a frequency without failing anything.
    population: str = ""


class GnomadAncestrySexFields(BaseModel):
    """The gnomAD exomes/genomes grammar: for each selected ancestry, for each
    selected sex-of-that-ancestry, emit `<base>[_non_ukb][_<anc>][_<XX|XY>]`.

    The builder is only the combinatorial algorithm; the ancestry/sex codes are
    open data. TODO (at merge): move `ancestries`/`sexes` onto the option
    definitions (`field_code` per Q1) and reference them here rather than
    inlining — carried here for now so the config interpreter is self-contained.
    """

    model_config = ConfigDict(extra="forbid")

    builder: Literal["gnomad_ancestry_sex"]
    base: str = "AF"
    # A boolean option that, when *false*, inserts `non_ukb` after `base`
    # (exomes only; genomes has no UK Biobank subset so it omits this).
    include_ukb_option: str | None = None
    join: str = "%"
    ancestries: list[AncestryCode]
    sexes: list[SexCode]


class GnomadV2Subset(BaseModel):
    """One gnomAD v2 subset toggle and its column prefix. `prefix` is empty for
    the full dataset; otherwise it prefixes the whole code (`controls_AF_afr`)."""

    model_config = ConfigDict(extra="forbid")

    option: str
    prefix: str
    label: str = ""
    default: bool = False


class GnomadV2Subpop(BaseModel):
    """A sub-population toggle under a gnomAD v2 ancestry (no sex split): its code
    is appended to the ancestry, `AF_nfe_seu`."""

    model_config = ConfigDict(extra="forbid")

    option: str
    code: str
    label: str = ""
    default: bool = False


class GnomadV2Ancestry(BaseModel):
    """A gnomAD v2 ancestry option. `code` is empty for "all"; `sex_split=False`
    marks a plain toggle with no XX/XY (popmax). `subpops` are its no-sex
    sub-populations (NFE / EAS)."""

    model_config = ConfigDict(extra="forbid")

    option: str
    code: str
    sex_split: bool = True
    subpops: list[GnomadV2Subpop] = []
    label: str = ""
    default: bool = False


class GnomadV2Fields(BaseModel):
    """The gnomAD v2 grammar (GRCh37 exomes/genomes): for each selected subset,
    ancestry and sex / sub-population, emit
    `[<subset>_]<base>[_<anc>[_<subpop>]][_<sex>]`.

    Differs from v4's `gnomad_ancestry_sex`: the subset is a prefix chosen from a
    list (not a single UK-Biobank toggle), ancestries carry sub-populations and a
    plain popmax, and the sex codes are `male` / `female` rather than `XX` / `XY`.
    The subset/ancestry/sex codes are open data on the option definitions; the
    builder is only the combinatorial algorithm.
    """

    model_config = ConfigDict(extra="forbid")

    builder: Literal["gnomad_v2"]
    base: str = "AF"
    join: str = "%"
    subsets: list[GnomadV2Subset]
    ancestries: list[GnomadV2Ancestry]
    sexes: list[SexCode]


class AllofusPopulationFields(BaseModel):
    """All of Us: concatenate the codes of each selected population (no sex
    split; "max" contributes two). Same TODO as above — codes move to the option
    defs at merge."""

    model_config = ConfigDict(extra="forbid")

    builder: Literal["allofus_populations"]
    join: str = "%"
    populations: list[PopulationCode]


class GnomadStructuralFields(BaseModel):
    """gnomAD structural sources (SV / CNV): concatenate the codes of each
    selected field-option (SVTYPE is gated on the master option so it is always
    included, then the overall frequency and each selected population frequency).
    Same shape as `AllofusPopulationFields` — an option-gated code list — kept as
    its own builder id for clarity."""

    model_config = ConfigDict(extra="forbid")

    builder: Literal["gnomad_structural"]
    join: str = "%"
    populations: list[PopulationCode]


FieldsSpec = Union[
    LiteralFields,
    GnomadAncestrySexFields,
    GnomadV2Fields,
    AllofusPopulationFields,
    GnomadStructuralFields,
]


# --------------------------------------------------------------------------- #
# The three emitters.                                                          #
# --------------------------------------------------------------------------- #

class FlagEmitter(BaseModel):
    """`<keyword> {0|1}` from the entry's own boolean option (hgvs, hgvsg, spdi,
    protein)."""

    model_config = ConfigDict(extra="forbid")

    emit: Literal["flag"]
    keyword: str


class SettingEmitter(BaseModel):
    """`<keyword> <value>` — a bare VEP config.ini setting with a value, emitted
    only when the entry's own boolean option is on. Unlike `FlagEmitter` (which
    writes 0/1 from the option itself), the value comes from a `ParamValue` —
    typically another option's numeric field via `from_option`, e.g.
    `distance 5000` from the up/downstream-distance field."""

    model_config = ConfigDict(extra="forbid")

    emit: Literal["setting"]
    keyword: str
    value: ParamValue


class PluginEmitter(BaseModel):
    """`plugin <name>[,<arg>…][,<k>=<v>…]` when the entry's option is on. Static
    params, assembly-keyed files, and sub-flag interpolation are all
    `ParamValue`s; IntAct's variadic sub-flags use `flags`.

    `args` are positional, emitted bare and before any named `params` — for a
    plugin that takes its argument by position rather than by name (Conservation
    wants `plugin Conservation,<bigwig>`, not `file=<bigwig>`). Most plugins take
    named params; prefer `params` unless the plugin really is positional.
    """

    model_config = ConfigDict(extra="forbid")

    emit: Literal["plugin"]
    name: str
    args: list[ParamValue] = []
    params: dict[str, ParamValue] = {}
    flags: VariadicFlags | None = None
    when: GenomeGate | None = None


class CustomEmitter(BaseModel):
    """`custom file=…,short_name=…,fields=…,format=…` — gnomAD/AoU/ClinVar. When
    `omit_if_no_fields`, the whole line is dropped if `fields` resolves empty
    (nothing selected).

    `fields` is optional: a `gff`/`bed` overlap custom (GENCODE Promoters) lets
    VEP emit the source's attributes automatically and so has no `fields=` clause
    at all — leave it None and no clause is written. Such a custom's columns are
    source-derived, not statically known, so it contributes nothing to
    `expected_csq_columns` and skips the custom-column check.
    """

    model_config = ConfigDict(extra="forbid")

    emit: Literal["custom"]
    params: dict[str, ParamValue] = {}
    fields: FieldsSpec | None = None
    # `fields=` is emitted immediately after this param, matching the arg order
    # VEP's `custom` lines use (…,short_name=…,fields=…,format=…).
    fields_after: str = "short_name"
    omit_if_no_fields: bool = False
    when: GenomeGate | None = None


ConfigEmitter = Annotated[
    Union[FlagEmitter, SettingEmitter, PluginEmitter, CustomEmitter],
    Field(discriminator="emit"),
]


# --------------------------------------------------------------------------- #
# Document.                                                                    #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# The form control an entry presents — PROOF OF CONCEPT, two entries only.     #
#                                                                              #
# Every form option is already a config entry (35 of 35 for GRCh38; the only   #
# entries without one are `clinvar_short`, which Phenotypes forces on, and the #
# hidden `hgvsg`). So the option's presentation belongs on the entry it        #
# already has, rather than in a second document keyed by the same id.          #
#                                                                              #
# Two entries carry this today — `nearest_exon_jb` and `pli` — to test the     #
# model against a plain toggle and one with a number + boolean beneath it.     #
# `form_panels.py` still owns every other option, and a test asserts the       #
# panels come out identical either way. See                                    #
# docs/form-panels-to-json.md (outside the repo) for where this is going.      #
# --------------------------------------------------------------------------- #

class FormSubOption(BaseModel):
    """A control nested under an option. Not a config entry of its own: a
    sub-option is a `ConfigIniParams` field that the parent's emitter reads
    through `from_option` (NearestExonJB's max_range), so it is declared here
    rather than as a sibling entry."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    type: Literal["boolean", "number", "select"] = "boolean"
    # bool for a toggle, int for a number — the same union the form emits today.
    default: bool | int | str = False
    min: int | None = None
    max: int | None = None


class FormOption(BaseModel):
    """How an entry appears on the input form.

    `panel` and `category` say where it belongs; the rest is the control itself.
    An entry with no `form` block presents no control at all, which is exactly
    what `clinvar_short` and `hgvsg` need — so their absence is the declaration,
    not an omission to be caught.
    """

    model_config = ConfigDict(extra="forbid")

    panel: str
    label: str
    category: str | None = None
    type: Literal["boolean", "number", "select"] = "boolean"
    default: bool | int | str = False
    sub_options: list[FormSubOption] = []
    # mutfunc does everything when told nothing, so a config line naming no
    # sub-flag already means all of them: "none selected" is not a state the
    # plugin can be asked for, and the form switches the option off instead.
    requires_any_sub_option: bool = False
    # Where in its panel the control sits.
    #
    # Sparse (…, 150, 850, …) against the step `form_panels` gives the options
    # it still owns, so an entry can be placed *between* two coded ones without
    # renumbering anything. It is deliberately not the entry's `order`, which
    # sequences the generated config.ini and has no reason to agree with the
    # order a reader wants to see the controls in.
    #
    # While the migration is half done these numbers are relative to a list this
    # module still writes, so adding a coded option above one of them shifts the
    # scale — the golden-file test is what catches that. Once every option is
    # declared, the coded side goes and the numbers stand on their own.
    order: int

    def as_panel_option(self, option_id: str) -> dict:
        """The option dict `form_config` serves, in the shape the form expects.

        Keys are omitted where the hand-written panels omit them, so a
        spec-declared option is indistinguishable from a coded one — which is
        what the equivalence test checks.
        """
        option: dict = {
            "id": option_id,
            "label": self.label,
            "type": self.type,
            "default": self.default,
        }
        if self.category is not None:
            option["category"] = self.category
        if self.requires_any_sub_option:
            option["requires_any_sub_option"] = True
        if self.sub_options:
            option["sub_options"] = [
                {
                    key: value
                    for key, value in sub.model_dump().items()
                    if value is not None or key not in ("min", "max")
                }
                for sub in self.sub_options
            ]
        return option


class ConfigEntry(BaseModel):
    """One option's config rule. `id` matches the ConfigIniParams field / form
    option id, so a selected option finds its emitter. `order` is the position
    the line takes in the generated ini (the current builder's emission order is
    load-bearing for the golden-file tests, so it is explicit here)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    order: int
    # The parse-plugin id(s) this option's output is parsed by — the explicit
    # config→parsing link the consistency check uses (merged_spec_model.py).
    # Empty for config-only options (flags like spdi/protein, and loeuf,
    # geno2mp, the nearest-* plugins). The
    # relation is not 1:1: one config may feed several parse entries
    # (eve → eve + popeve) and several configs may feed one ({hgvs, hgvsg} →
    # hgvs). Kept on the config side so the parsing specs stay untouched; it is
    # also the seed of a future per-entry merge (design §3).
    parsed_as: list[str] = []
    # Other option ids to treat as on for config emission whenever this option
    # is selected — a config-only dependency. ProtVar reads HGVSg to build its
    # link, so `protvar` forces `hgvsg` to be computed; this never touches the
    # user's own HGVSg selection, which is what the results view gates the HGVSg
    # row's display on, so the value is computed without showing the row.
    forces_on: list[str] = []
    # Other option ids that must ALSO be selected for this entry to emit — a
    # parent-gate for an entry that has no control of its own, or whose control
    # is only meaningful under another. `clinvar_short` has no form control at
    # all -- Phenotypes `forces_on` it -- and additionally
    # `requires: ["phenotypes"]`, so a stale True restored by an edit/rerun
    # cannot emit the custom on its own. Unlike `forces_on` this only gates
    # emission; it never turns another option on.
    requires: list[str] = []
    # The control this option presents, where it presents one (see FormOption).
    form: FormOption | None = None
    config: ConfigEmitter

    def requirements_met(self, options: dict) -> bool:
        """Whether every `requires` dependency is selected. The extra gate the
        config interpreter and `expected_csq_columns` apply on top of the
        entry's own option, so a sub-option entry emits only with its parent."""
        return all(options.get(dependency) for dependency in self.requires)


class ConfigSpec(BaseModel):
    """The config half of the merged document, for one genome."""

    model_config = ConfigDict(extra="forbid")

    genome: dict | None = None
    entries: list[ConfigEntry]

    @model_validator(mode="after")
    def _unique_ids(self) -> "ConfigSpec":
        ids = [entry.id for entry in self.entries]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate config entry ids: {sorted(dupes)}")
        return self

    def entry(self, option_id: str) -> ConfigEntry | None:
        return next((e for e in self.entries if e.id == option_id), None)

    def effective_options(self, options: dict) -> dict:
        """`options` plus everything a selected entry `forces_on`.

        A forced option is on for every purpose — the config line it emits, and
        the CSQ columns that line is then expected to produce. Both callers read
        it from here so they cannot disagree: emitting a `custom` line whose
        columns are not expected would silence the missing-field check for
        exactly the data the user asked for.
        """
        effective = dict(options)
        for entry in self.entries:
            if options.get(entry.id):
                for forced_id in entry.forces_on:
                    effective[forced_id] = True
        return effective
