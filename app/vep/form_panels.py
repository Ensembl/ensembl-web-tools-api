"""Which option panels/options are visible on the VEP input form for a genome.

Returned by the form_config endpoint (called on species selection). For now the
set is the same for every species ("always visible"); species-conditional rules
will be layered on later by inspecting the genome metadata attributes.

Option (and sub-option) `id`s match the ConfigIniParams parameter names, so the
form's selections round-trip back into the generated config.ini. Options may
carry a `category` label which the form uses to group them within a panel.
"""

import copy

from vep.utils.spec_loader import resolve_merged_spec

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


# Human GRCh38-only sub-options.


# gnomAD exomes v4.1 (human GRCh38): a master toggle revealing an "Include UK
# Biobank samples" switch and a "Genetic ancestry group" of ancestry toggles,
# each with Both / Female / Male sub-options. Option/sub-option ids match the
# ConfigIniParams parameter names, so selections round-trip into the ini.
_GNOMAD_EXOMES_ANCESTRIES = [
    ("all", "All"),
    ("afr", "African & African-American"),
    ("amr", "Admixed American"),
    ("asj", "Ashkenazi Jewish"),
    ("eas", "East Asian"),
    ("fin", "Finnish"),
    ("mid", "Middle Eastern"),
    ("nfe", "Non-Finnish European"),
]


def _gnomad_sex_suboptions(option_id: str) -> list[dict]:
    """Both / Female / Male toggles for one ancestry option (Both on = combined
    sexes). `option_id` is the ancestry option's id, e.g. `gnomad_exomes_afr`."""
    return [
        {"id": f"{option_id}_both", "label": "Combined", "type": "boolean", "default": True},
        {"id": f"{option_id}_female", "label": "XX", "type": "boolean", "default": False},
        {"id": f"{option_id}_male", "label": "XY", "type": "boolean", "default": False},
    ]


def _gnomad_exomes_option() -> dict:
    """The gnomAD Exomes v4.1.1 option (freshly built so callers can mutate it)."""
    ancestry_options = [
        {
            "id": f"gnomad_exomes_{anc}",
            "label": label,
            "type": "boolean",
            "default": anc == "all",  # "All" pre-selected -> fields=AF baseline
            "sub_options": _gnomad_sex_suboptions(f"gnomad_exomes_{anc}"),
        }
        for anc, label in _GNOMAD_EXOMES_ANCESTRIES
    ]
    return {
        "id": "gnomad_exomes",
        "label": "gnomAD Exomes v4.1.1",
        "type": "boolean",
        "default": False,
        "sub_options": [
            {"id": "gnomad_exomes_include_ukb", "label": "Include UK BioBank samples", "type": "boolean", "default": True},
            {"type": "group", "label": "Genetic ancestry group", "options": ancestry_options},
        ],
    }


# gnomAD genomes v4.1 (human GRCh38): as exomes but no UK Biobank toggle, plus
# Amish / Remaining, and "Maximum across all groups" (grpmax) which has no sex
# split (a plain toggle).
_GNOMAD_GENOMES_ANCESTRIES = [
    ("all", "All"),
    ("afr", "African & African-American"),
    ("amr", "Admixed American"),
    ("asj", "Ashkenazi Jewish"),
    ("eas", "East Asian"),
    ("fin", "Finnish"),
    ("mid", "Middle Eastern"),
    ("nfe", "Non-Finnish European"),
    ("ami", "Amish"),
    ("remaining", "Remaining"),
]


def _gnomad_genomes_option() -> dict:
    """The gnomAD Genomes v4.1.1 option (freshly built so callers can mutate it)."""
    ancestry_options = [
        {
            "id": f"gnomad_genomes_{anc}",
            "label": label,
            "type": "boolean",
            "default": anc == "all",  # "All" pre-selected -> fields=AF baseline
            "sub_options": _gnomad_sex_suboptions(f"gnomad_genomes_{anc}"),
        }
        for anc, label in _GNOMAD_GENOMES_ANCESTRIES
    ]
    # grpmax (max across groups) has no XX/XY split -> a plain toggle. On by
    # default and placed directly under "All", the same pairing All of Us makes
    # with its maximum subpopulation: the overall frequency plus the highest any
    # group reaches are the two that are useful without knowing which population
    # matters for a given variant, so they belong together at the top rather
    # than with the individual ancestries.
    #
    # Display order only. The `fields=` order in the config line comes from the
    # spec's `ancestries` list, where grpmax stays last.
    ancestry_options.insert(1, {
        "id": "gnomad_genomes_grpmax",
        "label": "Maximum across all groups",
        "type": "boolean",
        "default": True,
    })
    return {
        "id": "gnomad_genomes",
        "label": "gnomAD Genomes v4.1.1",
        "type": "boolean",
        "default": False,
        "sub_options": [
            {"type": "group", "label": "Genetic ancestry group", "options": ancestry_options},
        ],
    }


# NIH All of Us (human GRCh38): a flat list of population toggles (no sex split).
# "Maximum subpopulation" contributes two fields (gvs_max_af + gvs_max_subpop);
# that is handled by the ini builder, not the form.
_ALLOFUS_POPULATIONS = [
    ("all", "All"),
    ("max", "Maximum subpopulation"),
    ("afr", "African"),
    ("amr", "Latino/Ad Mixed American"),
    ("eas", "East Asian"),
    ("eur", "European"),
    ("mid", "Middle Eastern"),
    ("sas", "South Asian"),
    ("oth", "Other"),
]


def _allofus_option() -> dict:
    """The NIH All of Us option (freshly built so callers can mutate it)."""
    population_options = [
        {
            "id": f"allofus_{pop}",
            "label": label,
            "type": "boolean",
            # Suggested defaults: the overall AF, plus the maximum subpopulation
            # — the two that are useful without knowing which population matters
            # for a given variant.
            "default": pop in ("all", "max"),
        }
        for pop, label in _ALLOFUS_POPULATIONS
    ]
    return {
        "id": "allofus",
        "label": "NIH All of Us",
        "type": "boolean",
        "default": False,
        # A label-less group keeps the population list full-width (reusing the
        # nested-group renderer) without adding a heading.
        "sub_options": [
            {"type": "group", "options": population_options},
        ],
    }


# gnomAD SV v4.1 (human GRCh38): a flat list of AF toggles (no sex split). The
# SV id (`gnomAD_SV`) and `gnomAD_SV_SVTYPE` are always returned; these gate the
# per-population AF columns. Population code -> label; "" is the overall AF.
_GNOMAD_SV_POPULATIONS = [
    ("", "All"),
    ("afr", "African & African-American"),
    ("ami", "Amish"),
    ("amr", "Admixed American"),
    ("asj", "Ashkenazi Jewish"),
    ("eas", "East Asian"),
    ("fin", "Finnish"),
    ("mid", "Middle Eastern"),
    ("nfe", "Non-Finnish European"),
    ("rmi", "Remaining"),
    ("sas", "South Asian"),
]

# gnomAD SV v2.1 (human GRCh37): 5 continental populations, PREFIX-named in the
# VCF (`AFR_AF`, not v4's suffix `AF_afr`) and broader (EUR = all Europeans, not
# NFE). (form-option suffix [lowercase], VCF column code [uppercase], label).
_GNOMAD_SV_V2_POPULATIONS = [
    ("afr", "AFR", "African"),
    ("amr", "AMR", "Admixed American"),
    ("eas", "EAS", "East Asian"),
    ("eur", "EUR", "European"),
    ("oth", "OTH", "Other"),
]


# The allele-frequency sources split into two kinds of data, so the form groups
# them under these category headings (see `groupByCategory` on the frontend)
# rather than listing all of them in one column.
_AF_SHORT_VARIANTS = "Short variants"
_AF_STRUCTURAL_VARIANTS = "Structural variants"


def _in_category(option: dict, category: str) -> dict:
    """The option, tagged with the category heading it sits under."""
    return {**option, "category": category}


def _gnomad_sv_af_option_id(code: str) -> str:
    """Form option id for a gnomAD SV AF population (`""` = overall)."""
    return "gnomad_sv_af" if code == "" else f"gnomad_sv_af_{code}"


def _gnomad_sv_option_from(label: str, populations: list[tuple[str, str]]) -> dict:
    """A gnomAD SV option: an overlap-cutoff select plus per-population AF toggles
    (overall AF pre-selected). SVTYPE + the SV id ride along always. `populations`
    is (option-code, label), option-code "" = the overall AF. Shared by the v4.1
    (GRCh38) and v2.1 (GRCh37) options — they differ only in label + population
    set (the differing VCF column codes live in each assembly's config entry)."""
    population_options = [
        {
            "id": _gnomad_sv_af_option_id(code),
            "label": pop_label,
            "type": "boolean",
            "default": code == "",  # overall AF pre-selected
        }
        for code, pop_label in populations
    ]
    return {
        "id": "gnomad_sv",
        "label": label,
        "type": "boolean",
        "default": False,
        "sub_options": [
            {
                "id": "gnomad_sv_overlap_cutoff",
                "label": "Overlap cutoff",
                "type": "select",
                "default": "100",
                "options": [
                    {"label": "80%", "value": "80"},
                    {"label": "90%", "value": "90"},
                    {"label": "100%", "value": "100"},
                ],
            },
            {"type": "group", "options": population_options},
        ],
    }


def _gnomad_sv_option() -> dict:
    return _gnomad_sv_option_from("gnomAD SV v4.1", _GNOMAD_SV_POPULATIONS)


def _gnomad_sv_v2_option() -> dict:
    populations = [("", "All")] + [
        (code, label) for code, _col, label in _GNOMAD_SV_V2_POPULATIONS
    ]
    return _gnomad_sv_option_from("gnomAD SV v2.1", populations)


# gnomAD CNV v4.1 (human GRCh38): like gnomAD SV, but *sample* frequencies (SF)
# and a slightly different population set (no Amish; "remaining" spelled out).
_GNOMAD_CNV_POPULATIONS = [
    ("", "All"),
    ("afr", "African & African-American"),
    ("amr", "Admixed American"),
    ("asj", "Ashkenazi Jewish"),
    ("eas", "East Asian"),
    ("fin", "Finnish"),
    ("mid", "Middle Eastern"),
    ("nfe", "Non-Finnish European"),
    ("sas", "South Asian"),
    ("remaining", "Remaining"),
]


def _gnomad_cnv_sf_option_id(code: str) -> str:
    """Form option id for a gnomAD CNV SF population (`""` = overall)."""
    return "gnomad_cnv_sf" if code == "" else f"gnomad_cnv_sf_{code}"


def _gnomad_cnv_option() -> dict:
    """The gnomAD CNV v4.1 option: an overlap-cutoff select plus per-population
    SF toggles (overall SF pre-selected). SVTYPE + the CNV id ride along always."""
    population_options = [
        {
            "id": _gnomad_cnv_sf_option_id(code),
            "label": label,
            "type": "boolean",
            "default": code == "",  # overall SF pre-selected
        }
        for code, label in _GNOMAD_CNV_POPULATIONS
    ]
    return {
        "id": "gnomad_cnv",
        "label": "gnomAD CNV v4.1",
        "type": "boolean",
        "default": False,
        "sub_options": [
            {
                "id": "gnomad_cnv_overlap_cutoff",
                "label": "Overlap cutoff",
                "type": "select",
                "default": "100",
                "options": [
                    {"label": "80%", "value": "80"},
                    {"label": "90%", "value": "90"},
                    {"label": "100%", "value": "100"},
                ],
            },
            {"type": "group", "options": population_options},
        ],
    }


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

# gnomAD ancestry codes -> labels. Genomes is a superset of exomes, so its list
# covers both sources; grpmax (genomes-only, added separately as a plain toggle)
# is folded in. The form's "all" ancestry is the overall AF, which the parser
# reports as an empty population code, so it is left out of the map.
_GNOMAD_ANCESTRY_LABELS = {
    code: label for code, label in _GNOMAD_GENOMES_ANCESTRIES if code != "all"
} | {"grpmax": "Maximum across all groups"}

# All of Us population codes -> labels ("all" is the overall AF -> empty code).
_ALLOFUS_POPULATION_LABELS = {
    code: label for code, label in _ALLOFUS_POPULATIONS if code != "all"
}

# gnomAD SV population codes -> labels ("" is the overall AF -> "All"). Both the
# v4.1 (GRCh38, suffix-named, lowercase codes) and v2.1 (GRCh37, prefix-named,
# UPPERCASE column codes) sets — disjoint by case, so they coexist in one map.
# The v2 keys are the VCF column codes (AFR/AMR/…), which is what the parse and
# `af_source_descriptor` derive from the columns.
_GNOMAD_SV_POPULATION_LABELS = {
    code: label for code, label in _GNOMAD_SV_POPULATIONS if code != ""
} | {col: label for _code, col, label in _GNOMAD_SV_V2_POPULATIONS}

# gnomAD CNV population codes -> labels ("" is the overall SF -> "All").
_GNOMAD_CNV_POPULATION_LABELS = {
    code: label for code, label in _GNOMAD_CNV_POPULATIONS if code != ""
}

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

    ancestry = "All" if rest == "" else _GNOMAD_ANCESTRY_LABELS.get(rest, rest)
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
        return _ALLOFUS_POPULATION_LABELS.get(code, code)
    if source == "gnomad_sv":
        return _GNOMAD_SV_POPULATION_LABELS.get(code, code)
    if source == "gnomad_cnv":
        return _GNOMAD_CNV_POPULATION_LABELS.get(code, code)
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


def _add_grch38_allele_frequencies(panels: dict[str, dict]) -> None:
    """The GRCh38 allele-frequency options.

    The last options still built here rather than declared: each is an ancestry
    (or population) table crossed with a sex split, ~110 nodes for this
    assembly. Expanding them into the spec would be a fourth copy of tables the
    config entries already carry — see docs/form-panels-to-json.md; the move is
    to give those a label and generate both from one list.
    """
    panels["allele_frequencies"]["options"].extend([
        _in_category(_gnomad_exomes_option(), _AF_SHORT_VARIANTS),
        _in_category(_gnomad_genomes_option(), _AF_SHORT_VARIANTS),
        _in_category(_allofus_option(), _AF_SHORT_VARIANTS),
        _in_category(_gnomad_sv_option(), _AF_STRUCTURAL_VARIANTS),
        _in_category(_gnomad_cnv_option(), _AF_STRUCTURAL_VARIANTS),
    ])


_GNOMAD_V2_EXOMES_SUBSETS = [
    ("full", "Full dataset"), ("controls", "Controls"), ("non_neuro", "Non-neuro"),
    ("non_topmed", "Non-TOPMed"), ("non_cancer", "Non-cancer"),
]
_GNOMAD_V2_GENOMES_SUBSETS = [
    ("full", "Full dataset"), ("controls", "Controls"),
    ("non_neuro", "Non-neuro"), ("non_topmed", "Non-TOPMed"),
]
_GNOMAD_V2_EXOMES_ANCESTRIES = [
    ("all", "All", []),
    ("popmax", "Maximum across populations", []),
    ("afr", "African & African-American", []),
    ("amr", "Admixed American", []),
    ("asj", "Ashkenazi Jewish", []),
    ("eas", "East Asian", [("kor", "Korean"), ("jpn", "Japanese"), ("oea", "Other East Asian")]),
    ("fin", "Finnish", []),
    ("nfe", "Non-Finnish European",
     [("seu", "Southern European"), ("bgr", "Bulgarian"), ("onf", "Other non-Finnish European"),
      ("swe", "Swedish"), ("nwe", "North-Western European"), ("est", "Estonian")]),
    ("oth", "Other / uncertain", []),
    ("sas", "South Asian", []),
]
_GNOMAD_V2_GENOMES_ANCESTRIES = [
    ("all", "All", []),
    ("popmax", "Maximum across populations", []),
    ("afr", "African & African-American", []),
    ("amr", "Admixed American", []),
    ("asj", "Ashkenazi Jewish", []),
    ("eas", "East Asian", []),
    ("fin", "Finnish", []),
    ("nfe", "Non-Finnish European",
     [("seu", "Southern European"), ("onf", "Other non-Finnish European"),
      ("nwe", "North-Western European"), ("est", "Estonian")]),
    ("oth", "Other / uncertain", []),
]

# gnomAD v2 code -> label vocabularies, derived from the form data above so the
# results labels and the form sub-options read the same. Subset prefixes exclude
# `full` (empty prefix); ancestry excludes the synthetic `all`/`popmax` rows.
_GNOMAD_V2_SUBSET_LABELS = {
    code: lbl for code, lbl in _GNOMAD_V2_EXOMES_SUBSETS if code != "full"
}
_GNOMAD_V2_ANCESTRY_LABELS = {
    code: lbl for code, lbl, _ in _GNOMAD_V2_EXOMES_ANCESTRIES
    if code not in ("all", "popmax")
}
_GNOMAD_V2_SUBPOP_LABELS = {
    sp: splbl
    for _code, _lbl, subpops in _GNOMAD_V2_EXOMES_ANCESTRIES
    for sp, splbl in subpops
}


def _gnomad_v2_population_label(code: str) -> str:
    """Decode a gnomAD v2 (GRCh37) population code — the raw AF field name the
    parse captures, e.g. `AF_afr`, `controls_AF_afr_male`, `AF_nfe_seu`,
    `AF_popmax`, `AF_male` — to a ` · `-joined label. Grammar:
    `[<subset>_]AF[_<anc>[_<subpop>]][_<sex>]`; `AF_popmax` is a single field."""
    rest = code
    subset = None
    for prefix, lbl in _GNOMAD_V2_SUBSET_LABELS.items():
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
        ancestry = (f"{_GNOMAD_V2_ANCESTRY_LABELS.get(anc, anc)} › "
                    f"{_GNOMAD_V2_SUBPOP_LABELS.get(subpop, subpop)}")
    else:
        ancestry = _GNOMAD_V2_ANCESTRY_LABELS.get(rest, rest)
    parts = [ancestry]
    if sex:
        parts.append(sex)
    if subset:
        parts.append(subset)
    return " · ".join(parts)


def _gnomad_v2_option(prefix: str, label: str, subsets, ancestries) -> dict:
    """A gnomAD v2 master option with a Subset group and a Genetic-ancestry group
    (each ancestry carrying Combined/XX/XY, NFE/EAS also sub-population toggles;
    popmax is a plain row)."""
    subset_options = [
        {"id": f"{prefix}_subset_{code}", "label": lbl, "type": "boolean",
         "default": code == "full"}
        for code, lbl in subsets
    ]
    ancestry_options = []
    for code, lbl, subpops in ancestries:
        option_id = f"{prefix}_{code}"
        if code == "popmax":  # no sex split, no sub-pops
            ancestry_options.append(
                {"id": option_id, "label": lbl, "type": "boolean", "default": False}
            )
            continue
        option = {
            "id": option_id, "label": lbl, "type": "boolean",
            "default": code == "all",  # All pre-selected -> fields=AF baseline
            "sub_options": _gnomad_sex_suboptions(option_id),
        }
        if subpops:
            option["sub_options"].append({
                "type": "group", "label": "Sub-populations",
                "options": [
                    {"id": f"{prefix}_{code}_{sp}", "label": splbl,
                     "type": "boolean", "default": False}
                    for sp, splbl in subpops
                ],
            })
        ancestry_options.append(option)
    return {
        "id": prefix, "label": label, "type": "boolean", "default": False,
        "sub_options": [
            {"type": "group", "label": "Subset", "options": subset_options},
            {"type": "group", "label": "Genetic ancestry group", "options": ancestry_options},
        ],
    }


def _gnomad_v2_exomes_option() -> dict:
    return _gnomad_v2_option(
        "gnomad_exomes", "gnomAD Exomes v2.1.1",
        _GNOMAD_V2_EXOMES_SUBSETS, _GNOMAD_V2_EXOMES_ANCESTRIES,
    )


def _gnomad_v2_genomes_option() -> dict:
    return _gnomad_v2_option(
        "gnomad_genomes", "gnomAD Genomes v2.1",
        _GNOMAD_V2_GENOMES_SUBSETS, _GNOMAD_V2_GENOMES_ANCESTRIES,
    )


def _add_grch37_allele_frequencies(panels: dict[str, dict]) -> None:
    """The GRCh37 allele-frequency options — gnomAD v2, whose grammar differs
    from v4's (a subset prefix before `AF`, sub-populations under an ancestry,
    male/female rather than XX/XY)."""
    panels["allele_frequencies"]["options"].extend([
        _in_category(_gnomad_v2_exomes_option(), _AF_SHORT_VARIANTS),
        _in_category(_gnomad_v2_genomes_option(), _AF_SHORT_VARIANTS),
        _in_category(_gnomad_sv_v2_option(), _AF_STRUCTURAL_VARIANTS),
    ])


# The step between two options this module still writes out. A `form.order`
# lands between them (150 sits between the 2nd and 3rd), so an entry can place
# itself without the coded list being renumbered.
_CODED_OPTION_STEP = 100


def _spec_form_options(
    assembly_name: str | None,
) -> list[tuple[str, int, dict]]:
    """Options declared by their own config entry: `(panel id, order, option)`.

    Two entries carry a `form` block today — `nearest_exon_jb` and `pli`;
    everything else still comes from the literals above. See
    docs/form-panels-to-json.md for where this goes.

    Read through the *assembled* spec rather than the raw documents, so an
    option is offered exactly where its entry is: `pli` is declared only by
    `human_grch38.json`, so GRCh37 has nothing to place and nothing here says
    so. That is already how the parse plugin and display option are selected
    (see `_select_library`), and it is the per-assembly branching this module
    exists to do.
    """
    spec = resolve_merged_spec(assembly_name or "")
    return [
        (entry.form.panel, entry.form.order, entry.form.as_panel_option(entry.id))
        for entry in spec.config.entries
        if entry.form is not None
    ]


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
    by_id = {panel["id"]: panel for panel in panels}

    # Every non-AF option, placed where its `form` block says.
    _place_spec_options(panels, assembly_name)

    # The allele frequencies are the one set still built rather than declared,
    # and the two assemblies publish different grammars.
    #
    # Keyed on the assembly alone, as `resolve_merged_spec` keys the options
    # above — otherwise a call without `species_taxonomy_id` would get every
    # human option and no frequencies, which is worse than either answer. The
    # spec has always been per-assembly (only `assembly_name` is available at
    # submission), so this makes the form agree with the thing it configures.
    assembly = assembly_name or ""
    if assembly.startswith("GRCh38"):
        _add_grch38_allele_frequencies(by_id)
    elif assembly.startswith("GRCh37"):
        _add_grch37_allele_frequencies(by_id)

    # A panel with nothing to show is not shown. This is what used to be said
    # three times over — "these panels are human-only", "create the panel if the
    # species has CADD" — and it now follows from the options themselves.
    return [panel for panel in panels if panel["options"]]
