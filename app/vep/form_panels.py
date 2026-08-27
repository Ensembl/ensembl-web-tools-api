"""Which option panels/options are visible on the VEP input form for a genome.

Returned by the form_config endpoint (called on species selection). For now the
set is the same for every species ("always visible"); species-conditional rules
will be layered on later by inspecting the genome metadata attributes.

Option (and sub-option) `id`s match the ConfigIniParams parameter names, so the
form's selections round-trip back into the generated config.ini. Options may
carry a `category` label which the form uses to group them within a panel.
"""

import copy

from functools import lru_cache

from vep.utils.spec_loader import load_merged_spec, resolve_merged_spec

# Every panel the form can show, in the order it shows them.
#
# Panels only; their options are declared by the config entries themselves (see
# `_place_spec_options`) apart from the allele frequencies, which are generated
# from the ancestry tables below. A panel with nothing in it for this genome is
# dropped, so this list does not need to say which species see which panel —
# that follows from which entries exist, exactly as it does for the parse
# plugins and the display options.
_PANELS: list[dict] = [
    {"id": "variant_representations", "label": "Variant representations"},
    {"id": "variant_impact_predictions", "label": "Variant impact predictions"},
    {"id": "allele_frequencies", "label": "Allele frequencies"},
    {"id": "genes_and_transcripts", "label": "Genes & transcripts"},
    {"id": "protein_and_functional", "label": "Protein & functional"},
    {"id": "regulatory", "label": "Regulatory"},
    {"id": "phenotype_and_disease_associations",
     "label": "Phenotype & disease associations"},
]

# Kept for compatibility while the final coded-panel migration is completed.
# Panels are currently initialised empty, so the placement branch has no coded
# entries to space, but leaving this undefined makes future pre-population a
# runtime NameError.
_CODED_OPTION_STEP = 100


def is_human_grch37_or_38(
    species_taxonomy_id: str | None, assembly_name: str | None
) -> bool:
    """True for human GRCh37 / GRCh38."""
    return species_taxonomy_id == "9606" and (assembly_name or "").startswith(
        ("GRCh37", "GRCh38")
    )


def is_human_grch38(
    species_taxonomy_id: str | None, assembly_name: str | None
) -> bool:
    """True for human GRCh38."""
    return species_taxonomy_id == "9606" and (assembly_name or "").startswith(
        "GRCh38"
    )


def is_human_grch37(
    species_taxonomy_id: str | None, assembly_name: str | None
) -> bool:
    """True for human GRCh37."""
    return species_taxonomy_id == "9606" and (assembly_name or "").startswith(
        "GRCh37"
    )


# --------------------------------------------------------------------------- #
# Allele frequencies — the sub-option trees, built from the config entry's own  #
# code tables.                                                                  #
#                                                                              #
# Each AF entry already had to name every ancestry/population to build its      #
# `fields=` clause. Those entries now carry the label and the default too, so   #
# the form is generated from the same list rather than a second copy of it —    #
# the two had already drifted (`grpmax` was in one and not the other).          #
#                                                                              #
# What stays here is the *shape*: which toggles nest under which group, the     #
# overlap-cutoff select, and the fact that a sex-split ancestry has three       #
# children. That is layout, not data.                                          #
# --------------------------------------------------------------------------- #


def _toggle(option_id: str, label: str, default: bool = False) -> dict:
    return {"id": option_id, "label": label, "type": "boolean", "default": default}


def _af_fields(spec, option_id: str):
    """The `fields=` builder of one AF entry, or None if this genome has no such
    option (gnomAD CNV is GRCh38-only, All of Us likewise)."""
    entry = next((e for e in spec.config.entries if e.id == option_id), None)
    return entry.config.fields if entry is not None else None


def _ancestry_options(fields) -> list[dict]:
    """One toggle per ancestry, each with Combined / XX / XY beneath it unless
    the ancestry takes no sex split (genomes' grpmax)."""
    sexes = fields.sexes
    placed: list[tuple[int, dict]] = []
    for index, ancestry in enumerate(fields.ancestries):
        option = _toggle(ancestry.option, ancestry.label, ancestry.default)
        if ancestry.sex_split:
            option["sub_options"] = [
                _toggle(f"{ancestry.option}_{sex.suffix}", sex.label, sex.default)
                for sex in sexes
            ]
            # A sex-split ancestry emits one field per *selected sex*, so with
            # none of them ticked it contributes nothing at all (see
            # build_fields). Left to itself the form would show the ancestry
            # checked while submitting no column for it; this tells the form to
            # switch it off with its last sex.
            option["requires_any_sub_option"] = True
        # `form_order` moves an ancestry to where the form wants it, which is not
        # always where the emitted clause wants it (see AncestryCode).
        placed.append(
            (ancestry.form_order if ancestry.form_order is not None else index * 100,
             option)
        )
    placed.sort(key=lambda pair: pair[0])
    return [option for _order, option in placed]


def _gnomad_ancestry_sex_option(fields) -> list[dict]:
    """The sub-options of a gnomAD v4 exomes/genomes toggle: the UK Biobank
    switch where the source has one, then the ancestry group."""
    sub_options = []
    if fields.include_ukb_option:
        sub_options.append(
            _toggle(fields.include_ukb_option, "Include UK BioBank samples", True)
        )
    sub_options.append(
        {"type": "group", "label": "Genetic ancestry group",
         "options": _ancestry_options(fields)}
    )
    return sub_options


def _allofus_sub_options(fields) -> list[dict]:
    """All of Us: a flat list of population toggles, no sex split — and no group
    heading, since there is only the one group to name."""
    return [
        {"type": "group",
         "options": [
             _toggle(population.option, population.label, population.default)
             for population in fields.populations
         ]}
    ]


def _overlap_cutoff(option_id: str) -> dict:
    """How much of the variant an SV/CNV must cover to count as overlapping."""
    return {
        "id": f"{option_id}_overlap_cutoff",
        "label": "Overlap cutoff",
        "type": "select",
        "default": "100",
        "options": [
            {"label": "80%", "value": "80"},
            {"label": "90%", "value": "90"},
            {"label": "100%", "value": "100"},
        ],
    }


def _structural_sub_options(fields, option_id: str) -> list[dict]:
    """gnomAD SV / CNV: an overlap-cutoff select, then the per-population
    frequency toggles.

    The first population is the master option's own code — SVTYPE, which rides
    along whenever the option is on — so it is emitted by the entry rather than
    as a control of its own.
    """
    return [
        _overlap_cutoff(option_id),
        {"type": "group",
         "options": [
             _toggle(population.option, population.label, population.default)
             for population in fields.populations
             if population.option != option_id
         ]},
    ]


def _gnomad_v2_sub_options(fields) -> list[dict]:
    """gnomAD v2: a subset group, then ancestries — each with its sub-populations
    and sexes beneath it."""
    ancestry_options = []
    for ancestry in fields.ancestries:
        option = _toggle(ancestry.option, ancestry.label, ancestry.default)
        if not ancestry.sex_split:
            # popmax: a plain row, no sexes and no sub-populations.
            ancestry_options.append(option)
            continue
        option["sub_options"] = [
            _toggle(f"{ancestry.option}_{sex.suffix}", sex.label, sex.default)
            for sex in fields.sexes
        ]
        if ancestry.subpops:
            # NFE and EAS divide further, in a group of their own beneath the
            # sexes rather than alongside them.
            option["sub_options"].append({
                "type": "group",
                "label": "Sub-populations",
                "options": [
                    _toggle(subpop.option, subpop.label, subpop.default)
                    for subpop in ancestry.subpops
                ],
            })
        # As in `_ancestry_options`: nothing selected beneath it means no field.
        # ★ For v2 that means neither a sex *nor* a sub-population — a subpop
        # emits `<base>_<anc>_<subpop>` on its own, keeping the ancestry alive
        # with every sex unticked, so the form must count both.
        option["requires_any_sub_option"] = True
        ancestry_options.append(option)
    return [
        {"type": "group", "label": "Subset",
         "options": [
             _toggle(subset.option, subset.label, subset.default)
             for subset in fields.subsets
         ]},
        {"type": "group", "label": "Genetic ancestry group",
         "options": ancestry_options},
    ]


def _af_sub_options(fields, option_id: str) -> list[dict]:
    """The sub-option tree for one allele-frequency option, chosen by the same
    `fields=` builder that writes its config line.

    Every code these draw on — ancestry, population, subset, sex — comes from
    that builder's own tables, which now carry the label and the default beside
    the field code. One list, two consumers.
    """
    builder = fields.builder
    if builder == "gnomad_ancestry_sex":
        return _gnomad_ancestry_sex_option(fields)
    if builder == "allofus_populations":
        return _allofus_sub_options(fields)
    if builder == "gnomad_structural":
        return _structural_sub_options(fields, option_id)
    if builder == "gnomad_v2":
        return _gnomad_v2_sub_options(fields)
    raise ValueError(f"no form sub-options known for builder {builder!r}")


# --------------------------------------------------------------------------- #
# AF population-code -> form-label decoders
#
# The results parser emits the same population codes these option ids are built
# from (see results_filters.af_source_descriptor), so a served AF column can be
# labelled by decoding its code back to the form label. That decode lives here,
# beside the option tuples it reuses, so the label vocabulary is defined exactly
# once — the frontend reads the decoded label off the response rather than
# keeping its own copy of these tables.
# --------------------------------------------------------------------------- #

# Built from the same tables the form is: each AF entry's `fields=` builder
# names every ancestry/population and now carries its label, so there is one
# vocabulary rather than a decode-side copy of it.
#
# Keyed by the *population code the parser reports* (see
# `results_filters.af_source_descriptor`), which each source spells its own way:
# a v4 ancestry's `code` is already it, while the flat sources encode it in the
# option id after a per-source prefix.
@lru_cache(maxsize=1)
def _af_label_tables() -> dict[str, dict[str, str]]:
    """population code -> label, per AF source, across both human assemblies.

    Both, because a source's codes differ by assembly and the decode has only
    the code to go on: gnomAD SV is suffix-named lowercase on GRCh38 and
    prefix-named uppercase on GRCh37, which is why they can share one table.
    """
    tables: dict[str, dict[str, str]] = {
        "gnomad_ancestry": {}, "allofus": {}, "gnomad_sv": {}, "gnomad_cnv": {},
        "gnomad_v2_ancestry": {}, "gnomad_v2_subpop": {}, "gnomad_v2_subset": {},
    }
    for genome in ("human_grch38", "human_grch37"):
        for entry in load_merged_spec(genome).config.entries:
            fields = getattr(entry.config, "fields", None)
            builder = getattr(fields, "builder", None)
            if builder is None:
                continue
            if builder == "gnomad_ancestry_sex":
                for ancestry in fields.ancestries:
                    if ancestry.code and ancestry.label:
                        tables["gnomad_ancestry"][ancestry.code] = ancestry.label
            if builder == "gnomad_v2":
                # A separate table: v2 codes are decoded by their own function
                # (the grammar differs), and `popmax` would otherwise shadow a
                # v4 ancestry of the same name.
                for ancestry in fields.ancestries:
                    if ancestry.code and ancestry.label:
                        tables["gnomad_v2_ancestry"][ancestry.code] = ancestry.label
                    for subpop in ancestry.subpops:
                        if subpop.label:
                            tables["gnomad_v2_subpop"][subpop.code] = subpop.label
                for subset in fields.subsets:
                    if subset.prefix and subset.label:
                        tables["gnomad_v2_subset"][subset.prefix] = subset.label
            if builder in ("allofus_populations", "gnomad_structural"):
                for population in fields.populations:
                    if population.population and population.label:
                        tables[entry.id][population.population] = population.label
    return tables


def _labels_for(source: str) -> dict[str, str]:
    return _af_label_tables()[source]


# gnomAD sex-split suffixes — shown as the chromosomal notation (matching the
# form's XX/XY sub-option labels).
_SEX_LABELS = {"XX": "XX", "XY": "XY"}


def _gnomad_population_label(code: str) -> str:
    """Decode a compound gnomAD population code, e.g. `nfe_XX` -> 'Non-Finnish
    European · Female', `non_ukb_afr` -> 'African & African-American · excl. UK
    Biobank'. A code is an optional `non_ukb` subset prefix, then an ancestry (or
    a bare sex code = all ancestries), then an optional `_XX`/`_XY` sex suffix."""
    rest = code

    exclude_ukb = False
    if rest == "non_ukb" or rest.startswith("non_ukb_"):
        exclude_ukb = True
        rest = rest[len("non_ukb"):].lstrip("_")

    sex = None
    if rest.endswith(("_XX", "_XY")):
        sex = _SEX_LABELS[rest[-2:]]
        rest = rest[:-3]
    elif rest in ("XX", "XY"):
        sex = _SEX_LABELS[rest]
        rest = ""

    ancestry = "All" if rest == "" else _labels_for("gnomad_ancestry").get(rest, rest)
    parts = [ancestry]
    if sex:
        parts.append(sex)
    if exclude_ukb:
        parts.append("excl. UK Biobank")
    return " · ".join(parts)


def af_population_label(source: str, code: str) -> str:
    """The form label for an AF population `code` within an AF `source`
    (`gnomad_exomes` / `gnomad_genomes` / `all_of_us`). The empty code is the
    source's overall AF ("All"); an unrecognised code falls back to itself.

    Reused by the results metadata (each `AfSource.label`) and the All of Us
    `max_subpopulation` decode, so the label vocabulary stays defined once."""
    if code == "":
        return "All"
    if source == "all_of_us":
        return _labels_for("allofus").get(code, code)
    if source == "gnomad_sv":
        return _labels_for("gnomad_sv").get(code, code)
    if source == "gnomad_cnv":
        return _labels_for("gnomad_cnv").get(code, code)
    # gnomAD v2 (GRCh37) codes carry the `AF` token (the parse captures the whole
    # field, subset prefix and all); v4 codes never do.
    if source in ("gnomad_exomes", "gnomad_genomes") and "AF" in code.split("_"):
        return _gnomad_v2_population_label(code)
    return _gnomad_population_label(code)


def af_max_subpopulation_label(raw: str) -> str:
    """Decode All of Us `max_subpopulation` — the subpopulation(s) the max AF came
    from, given as `&`-joined population codes — to ` / `-joined labels."""
    return " / ".join(
        af_population_label("all_of_us", part) for part in raw.split("&")
    )


def _gnomad_v2_population_label(code: str) -> str:
    """Decode a gnomAD v2 (GRCh37) population code — the raw AF field name the
    parse captures, e.g. `AF_afr`, `controls_AF_afr_male`, `AF_nfe_seu`,
    `AF_popmax`, `AF_male` — to a ` · `-joined label. Grammar:
    `[<subset>_]AF[_<anc>[_<subpop>]][_<sex>]`; `AF_popmax` is a single field."""
    rest = code
    subset = None
    for prefix, lbl in _labels_for("gnomad_v2_subset").items():
        if rest.startswith(f"{prefix}_AF"):
            subset = lbl
            rest = rest[len(prefix) + 1:]
            break
    rest = rest[len("AF"):].lstrip("_")  # drop the AF token
    sex = None
    if rest in ("male", "female"):
        sex, rest = ("XY" if rest == "male" else "XX"), ""
    elif rest.endswith(("_male", "_female")):
        sex = "XY" if rest.endswith("_male") else "XX"
        rest = rest.rsplit("_", 1)[0]
    if rest == "popmax":
        ancestry = "Maximum across populations"
    elif rest == "":
        ancestry = "All"
    elif "_" in rest:
        anc, subpop = rest.split("_", 1)
        ancestry_label = _labels_for("gnomad_v2_ancestry").get(anc, anc)
        subpop_label = _labels_for("gnomad_v2_subpop").get(subpop, subpop)
        ancestry = f"{ancestry_label} › {subpop_label}"
    else:
        ancestry = _labels_for("gnomad_v2_ancestry").get(rest, rest)
    parts = [ancestry]
    if sex:
        parts.append(sex)
    if subset:
        parts.append(subset)
    return " · ".join(parts)


def _spec_form_options(
    assembly_name: str | None,
) -> list[tuple[str, int, dict]]:
    """Every option the form shows: `(panel id, order, option)`.

    All of them come from here now — the config entry declares the control, and
    an allele-frequency entry additionally grows its sub-option tree from the
    same `fields=` tables that write its config line (see `_af_sub_options`).

    Read through the *assembled* spec rather than the raw documents, so an
    option is offered exactly where its entry is: `pli` and All of Us are
    declared only by `human_grch38.json`, so GRCh37 has nothing to place and
    nothing here says so. That is already how the parse plugin and the display
    option are selected (see `_select_library`), and it is the per-assembly
    branching this module used to spell out.
    """
    spec = resolve_merged_spec(assembly_name or "")
    placed = []
    for entry in spec.config.entries:
        if entry.form is None:
            continue
        option = entry.form.as_panel_option(entry.id)
        fields = getattr(entry.config, "fields", None)
        if fields is not None and getattr(fields, "builder", None):
            option["sub_options"] = _af_sub_options(fields, entry.id)
        placed.append((entry.form.panel, entry.form.order, option))
    return placed


def _place_spec_options(panels: list[dict], assembly_name: str | None) -> None:
    """Place each declared option into its panel, at the order it states.

    The coded options keep their relative order and are spaced by
    `_CODED_OPTION_STEP`; a declared option sorts in among them by its own
    `order`. Nothing here knows what the options *are* — only where they go.
    """
    declared = _spec_form_options(assembly_name)
    if not declared:
        return

    by_panel: dict[str, list[tuple[int, dict]]] = {}
    for panel_id, order, option in declared:
        by_panel.setdefault(panel_id, []).append((order, option))

    for panel in panels:
        extra = by_panel.pop(panel["id"], None)
        if not extra:
            continue
        placed = [
            (index * _CODED_OPTION_STEP, option)
            for index, option in enumerate(panel["options"])
        ]
        placed += [(order, copy.deepcopy(option)) for order, option in extra]
        placed.sort(key=lambda pair: pair[0])
        panel["options"] = [option for _order, option in placed]

    if by_panel:
        # An entry naming a panel this genome does not show would otherwise
        # drop its control silently — the failure mode that keeps costing
        # afternoons elsewhere in this spec.
        raise ValueError(
            "form options declare panels that are not shown for "
            f"{assembly_name!r}: {sorted(by_panel)}"
        )


def get_visible_panels(
    attributes: dict | None = None,
    *,
    species_taxonomy_id: str | None = None,
    assembly_name: str | None = None,
) -> list[dict]:
    """Return the panels/options to show for a genome.

    `attributes` is the genome metadata (genebuild.* etc.). `species_taxonomy_id`
    and `assembly_name` are passed by the client (from the selected species) so
    visibility can depend on species/assembly — e.g. human GRCh37/38.

    Almost nothing here decides *what* a genome is offered any more: the options
    come from the config entries the genome's assembled spec carries, so an
    option exists for exactly the genomes that declare it. What is left is the
    panel list, the allele frequencies (still generated), and dropping a panel
    that ended up with nothing in it.
    """
    panels = [dict(panel, options=[]) for panel in _PANELS]

    # Every option, placed where its `form` block says — allele frequencies
    # included, their sub-option trees grown from the same tables that write
    # their config lines.
    _place_spec_options(panels, assembly_name)

    # A panel with nothing to show is not shown. This is what used to be said
    # three times over — "these panels are human-only", "create the panel if the
    # species has CADD" — and it now follows from the options themselves.
    return [panel for panel in panels if panel["options"]]
