"""Tests for spec_loader: content-digest versioning, assembly -> merged-spec
resolution, and the sidecar that pins the merged document to a job.
"""

import json
from pathlib import Path

import pytest
from pydantic import FilePath

from app.vep.utils.spec_loader import (
    _is_same_assembly,
    _species_annotations,
    species_annotation_entry,
    EXPECTED_COLUMNS_SIDECAR_FILE,
    SPEC_SIDECAR_FILE,
    _content_digest,
    load_expected_columns_sidecar,
    load_merged_spec,
    load_merged_spec_file,
    load_spec_sidecar,
    resolve_merged_spec,
    write_expected_columns_sidecar,
    write_spec_sidecar,
)
from app.vep.utils.csq import get_prediction_index_map
from app.vep.utils.spec_interpreter import apply_plugin_spec
from app.vep.utils.vcf_results import _load_pinned_spec

SAMPLE = {
    "genome": {"assembly": "GRCh38"},
    "config": {"entries": []},
    "parsing": {"plugins": []},
}


# --- content digest -----------------------------------------------------


def test_digest_is_independent_of_key_order():
    reordered = {
        "parsing": {"plugins": []},
        "config": {"entries": []},
        "genome": {"assembly": "GRCh38"},
    }
    assert _content_digest(SAMPLE) == _content_digest(reordered)


def test_digest_ignores_any_spec_version_already_present():
    """spec_version can't affect its own value -- it must be excluded before
    hashing, or the digest would depend on whatever was there before it."""
    with_version = {**SAMPLE, "spec_version": "sha256:whatever"}
    assert _content_digest(SAMPLE) == _content_digest(with_version)


def test_digest_changes_with_real_content():
    changed = {**SAMPLE, "genome": {"assembly": "GRCh37"}}
    assert _content_digest(SAMPLE) != _content_digest(changed)


# --- load_merged_spec_file: version is computed, not authored ------------


def test_load_merged_spec_file_computes_version_ignoring_file_placeholder(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({**SAMPLE, "spec_version": "sha256:0000"}))
    spec = load_merged_spec_file(path)
    assert spec.spec_version.startswith("sha256:")
    assert spec.spec_version != "sha256:0000"
    # deterministic: the same content computes the same digest on a second load
    assert load_merged_spec_file(path).spec_version == spec.spec_version
    # and the digest is mirrored onto the nested parsing view
    assert spec.parsing.spec_version == spec.spec_version


def test_load_merged_spec_file_works_with_no_version_in_the_file(tmp_path):
    """The bundled spec files don't carry a spec_version at all -- it is purely
    computed at load time."""
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(SAMPLE))
    spec = load_merged_spec_file(path)
    assert spec.spec_version.startswith("sha256:")


def test_bundled_human_grch38_spec_loads_and_has_a_real_digest():
    spec = load_merged_spec("human_grch38")
    assert spec.spec_version.startswith("sha256:")
    assert spec.spec_version != "sha256:" + "0" * 64
    assert len(spec.config_entries()) > 0
    assert len(spec.parse_plugins()) > 0


# --- Phase 0: shared-library assembly equivalence --------------------------


def test_assembled_grch38_matches_the_pre_split_baseline():
    """The library-split refactor gate: assembling human_grch38 from the shared
    `annotation_library` + its thin config document must reproduce the pre-split
    monolith *exactly* — same content digest, so no job's pinned spec, expected
    columns or parsing changes. `human_grch38.baseline.json` is a byte copy of the
    monolith taken before the split; loading it as a self-contained document must
    match the assembled result."""
    baseline = load_merged_spec_file(
        Path(__file__).parent / "human_grch38.baseline.json"
    )
    assembled = load_merged_spec("human_grch38")
    assert assembled.spec_version == baseline.spec_version
    assert assembled.model_dump(mode="json", by_alias=True) == baseline.model_dump(
        mode="json", by_alias=True
    )


# --- Phase 1: library selection (the subset a genome offers) ----------------


def _rows_option(option_id: str, *plugins: str) -> dict:
    """A minimal valid display option that reads `<plugin>.score` for each of
    `plugins`, so its plugin_refs are exactly those plugins."""
    return {
        "option_id": option_id,
        "blocks": [
            {
                "kind": "rows",
                "rows": [{"label": p, "from": f"{p}.score"} for p in plugins],
            }
        ],
    }


def test_select_library_keeps_the_configs_plugins_and_covered_options():
    from app.vep.utils.spec_loader import _select_library

    library = {
        "parsing": {"plugins": [{"plugin": "revel"}, {"plugin": "cadd"}, {"plugin": "eve"}]},
        "display": {
            "options": [
                _rows_option("revel", "revel"),
                _rows_option("cadd", "cadd"),
                _rows_option("combo", "revel", "eve"),
            ]
        },
    }
    # config offers revel + eve, not cadd
    config = [
        {"id": "revel", "parsed_as": ["revel"]},
        {"id": "eve", "parsed_as": ["eve"]},
    ]
    selected = _select_library(library, config)

    assert sorted(p["plugin"] for p in selected["parsing"]["plugins"]) == ["eve", "revel"]
    # revel kept; cadd dropped (plugin absent); combo kept (revel + eve both present)
    assert sorted(o["option_id"] for o in selected["display"]["options"]) == [
        "combo",
        "revel",
    ]


def test_select_library_drops_an_option_missing_one_of_its_plugins():
    from app.vep.utils.spec_loader import _select_library

    library = {
        "parsing": {"plugins": [{"plugin": "revel"}, {"plugin": "cadd"}]},
        "display": {"options": [_rows_option("combo", "revel", "cadd")]},
    }
    config = [{"id": "revel", "parsed_as": ["revel"]}]  # cadd not offered
    selected = _select_library(library, config)

    assert [p["plugin"] for p in selected["parsing"]["plugins"]] == ["revel"]
    assert selected["display"]["options"] == []  # combo needs cadd -> dropped


# --- resolve_merged_spec -------------------------------------------------


def test_resolve_grch38_returns_the_human_spec():
    resolved = resolve_merged_spec("GRCh38.p14")
    bundled = load_merged_spec("human_grch38")
    assert resolved.spec_version == bundled.spec_version
    assert {p.plugin for p in resolved.parse_plugins()} == {
        p.plugin for p in bundled.parse_plugins()
    }


def test_resolve_matches_by_prefix_not_exact_string():
    """Real assembly_name values carry a patch suffix, e.g. "GRCh38.p14" -- an
    exact-match lookup would never resolve anything."""
    assert (
        resolve_merged_spec("GRCh38.p14").spec_version
        == load_merged_spec("human_grch38").spec_version
    )


def test_resolve_grch37_returns_the_human_grch37_spec():
    resolved = resolve_merged_spec("GRCh37.p13")
    bundled = load_merged_spec("human_grch37")
    assert resolved.spec_version == bundled.spec_version


def test_grch37_is_the_reuse_tier_without_gnomad_or_grch38_only():
    """GRCh37 assembles a subset of the shared library: the reuse tier, with no
    gnomAD v2 AF sources (their own overrides come later) and none of the
    GRCh38-only datasets (opentargets, protvar, eve, ...)."""
    spec = load_merged_spec("human_grch37")
    plugins = {p.plugin for p in spec.parse_plugins()}
    options = {o.option_id for o in spec.display.options}
    assert {
        "revel", "cadd", "spliceai", "clinvar", "clinvar_sv", "go", "phenotype_data"
    } <= plugins
    assert plugins.isdisjoint(
        {
            "gnomad_exomes", "gnomad_genomes", "gnomad_sv", "gnomad_cnv",
            "all_of_us", "opentargets", "protvar", "eve", "mavedb",
            "mutfunc", "gencode_promoter",
        }
    )
    assert options.isdisjoint(
        {"opentargets", "protvar", "eve", "mavedb", "gencode_promoters"}
    )


# The ubiquitous options — the only ids the base spec and a human spec share.
BASE_IDS = {
    "updownstream_distance", "hgvs", "hgvsg", "spdi", "protein",
    "tss_distance", "nearest_gene", "nearest_exon_jb",
}


def test_an_assembly_with_no_spec_of_its_own_still_resolves():
    """VEP needs only a GFF and a FASTA, both of which the metadata API serves
    for every genome it knows, so an unlisted species must still be submittable
    — it is simply offered fewer options. It used to raise, which meant the form
    showed a usable panel and Run then returned a 500."""
    spec = resolve_merged_spec("Wibble_v1")
    assert [e.id for e in spec.config.entries] == [
        e.id for e in load_merged_spec("base").config.entries
    ]


def test_the_fallback_is_the_base_spec_never_a_human_one():
    """The original reason this raised: never silently annotate a mouse
    submission with human data files. The base spec carries no data files at
    all, so the fallback cannot do that."""
    spec = resolve_merged_spec("Wibble_v1")  # matches nothing in the table
    assert {e.id for e in spec.config.entries} == BASE_IDS
    for entry in spec.config.entries:
        # no data files at all, so nothing species-specific can leak in
        params = getattr(entry.config, "params", {}) or {}
        assert not [v for v in params.values() if isinstance(v, str) and "{path}" in v]


def test_resolve_empty_assembly_falls_back_rather_than_raising():
    assert resolve_merged_spec("").config.entries


def test_a_species_with_data_gets_its_own_files():
    spec = resolve_merged_spec("ARS-UCD2.0")  # cattle
    files = {
        e.id: e.config.params["file"]
        for e in spec.config.entries
        if e.id in ("go", "phenotypes")
    }
    assert files == {
        "go": "{path}/GO.pm_bos_taurus_116.gff.gz",
        "phenotypes": "{path}/Phenotypes.pm_bos_taurus_116.gvf.gz",
    }


def test_a_species_with_only_some_data_gets_only_that():
    spec = resolve_merged_spec("mOrnAna1.p.v1")  # platypus: GO, no phenotypes
    ids = {e.id for e in spec.config.entries}
    assert "go" in ids and "phenotypes" not in ids


def test_every_species_in_the_table_resolves_and_names_its_own_files():
    """The table is the single source of the file names; this walks all of it."""
    for row in _species_annotations()["species"]:
        spec = resolve_merged_spec(row["assembly"])
        ids = {e.id for e in spec.config.entries}
        assert set(row["datasets"]) <= ids, row["assembly"]
        for entry in spec.config.entries:
            if entry.id in ("go", "phenotypes"):
                assert row["production_name"] in entry.config.params["file"]


def test_a_short_assembly_name_does_not_swallow_an_unrelated_genome():
    """Ciona's assembly is literally `KH`. Under a bare prefix match any genome
    whose name merely started with those letters would be handed Ciona's GO
    file, so the match requires a separator after the table's name."""
    assert species_annotation_entry("KH")["production_name"] == "ciona_intestinalis"
    assert species_annotation_entry("KHv2") is None
    assert species_annotation_entry("ARS12_Fake") is None  # vs goat's ARS1


def test_a_patch_suffix_still_matches_its_assembly():
    """The tolerance the separator rule preserves: a patched assembly is still
    the same assembly and keeps its data."""
    row = species_annotation_entry("GRCm39.p1")
    assert row and row["production_name"] == "mus_musculus"


def test_no_table_assembly_is_a_prefix_of_another():
    """First match wins, so one row prefixing another would shadow it — and
    which one is shadowed would depend on table order."""
    names = [row["assembly"] for row in _species_annotations()["species"]]
    assert len(names) == len(set(names))
    overlaps = [
        (short, long)
        for short in names
        for long in names
        if short != long and _is_same_assembly(long, short)
    ]
    assert not overlaps


# --- sidecar ---------------------------------------------------------------


def test_write_and_load_spec_sidecar_round_trip(tmp_path):
    """The digest must survive a write -> reload of the pinned document. Both
    spec_version fields are stamped when written; the loader must exclude them
    again before hashing or the reloaded digest would differ from the original
    (the bug this test guards)."""
    spec = load_merged_spec("human_grch38")
    written_path = write_spec_sidecar(tmp_path, spec)
    assert written_path == tmp_path / SPEC_SIDECAR_FILE
    assert written_path.exists()

    (tmp_path / "output.vcf.gz").write_bytes(b"")
    loaded = load_spec_sidecar(FilePath(tmp_path / "output.vcf.gz"))
    assert loaded is not None
    assert loaded.spec_version == spec.spec_version
    assert len(loaded.parse_plugins()) == len(spec.parse_plugins())
    assert len(loaded.config_entries()) == len(spec.config_entries())


def test_load_spec_sidecar_missing_is_none(tmp_path):
    (tmp_path / "output.vcf.gz").write_bytes(b"")
    assert load_spec_sidecar(FilePath(tmp_path / "output.vcf.gz")) is None


# --- expected-columns sidecar (the per-job missing-field check) --------------


def test_expected_columns_sidecar_round_trip(tmp_path):
    columns = {"REVEL", "ClinVar_CLNSIG", "gnomAD_exomes_AF"}
    written = write_expected_columns_sidecar(tmp_path, columns)
    assert written == tmp_path / EXPECTED_COLUMNS_SIDECAR_FILE
    (tmp_path / "output.vcf.gz").write_bytes(b"")
    loaded = load_expected_columns_sidecar(FilePath(tmp_path / "output.vcf.gz"))
    assert loaded == columns


def test_load_expected_columns_sidecar_missing_is_none(tmp_path):
    (tmp_path / "output.vcf.gz").write_bytes(b"")
    assert load_expected_columns_sidecar(FilePath(tmp_path / "output.vcf.gz")) is None


def test_write_spec_sidecar_overwrites_the_previous_one(tmp_path):
    """Writing a sidecar again for the same job replaces its previous pin."""
    write_spec_sidecar(tmp_path, load_merged_spec("human_grch38"))
    write_spec_sidecar(tmp_path, load_merged_spec("human_grch38"))
    assert (tmp_path / SPEC_SIDECAR_FILE).exists()
    # still exactly one sidecar file, not two
    assert len(list(tmp_path.glob("*spec*"))) == 1


# --- _load_pinned_spec: the results-time seam (vcf_results) -----------------
# The defensive wrapper get_results_from_path uses to load the pinned spec at
# results time. It must never let a missing or corrupt pin break parsing, and it
# returns the parsing half of the merged document.


def test_load_pinned_spec_returns_the_sidecar_parsing_when_present(tmp_path):
    write_spec_sidecar(tmp_path, load_merged_spec("human_grch38"))
    (tmp_path / "output.vcf.gz").write_bytes(b"")
    spec = _load_pinned_spec(FilePath(tmp_path / "output.vcf.gz"))
    assert spec is not None
    assert spec.spec_version == load_merged_spec("human_grch38").spec_version
    assert len(spec.plugins) > 0


def test_load_pinned_spec_missing_sidecar_is_none(tmp_path):
    (tmp_path / "output.vcf.gz").write_bytes(b"")
    assert _load_pinned_spec(FilePath(tmp_path / "output.vcf.gz")) is None


def test_load_pinned_spec_unreadable_sidecar_is_none_not_raised(tmp_path):
    """A corrupt pin must fall back, not 500 the results endpoint."""
    (tmp_path / SPEC_SIDECAR_FILE).write_text("{ not valid json")
    (tmp_path / "output.vcf.gz").write_bytes(b"")
    assert _load_pinned_spec(FilePath(tmp_path / "output.vcf.gz")) is None


def test_species_cadd_uses_a_named_file_and_only_snv():
    """Other-species CADD is a single SNV file with a per-project name, not the
    production-name pattern GO and Phenotypes follow, and not human's
    snv+indels pair."""
    expected = {
        "GRCg6a": "chCADD_updated.tsv.gz",              # chicken, red junglefowl
        "Sscrofa11.1": "ALL_pCADD-PHRED-scores.tsv.gz",  # pig reference
        "Turkey_5.1": "tCADD.tsv.gz",
    }
    for assembly, filename in expected.items():
        entry = next(
            e for e in resolve_merged_spec(assembly).config.entries if e.id == "cadd"
        )
        assert entry.config.params == {"snv": "{path}/" + filename}, assembly


def test_human_cadd_is_untouched_by_the_species_table():
    entry = next(
        e for e in load_merged_spec("human_grch38").config.entries if e.id == "cadd"
    )
    assert set(entry.config.params) == {"snv", "indels"}


def test_a_phred_only_species_still_expects_both_cadd_columns():
    """Pig and chicken emit both columns; RAW is simply never scored, arriving
    as the VCF null '.'. So the expected-column contract is unchanged and the
    RAW display row drops itself — no per-species parse or display variant is
    needed."""
    spec = resolve_merged_spec("Sscrofa11.1")
    assert {"CADD_PHRED", "CADD_RAW"} <= spec.expected_csq_columns({"cadd": True})

    # '.' is not one of the parser's nullish literals ('', 'NA'); it reads as
    # null only because a float coercion of it fails. Pinned because that is
    # incidental, and a stray '.' reaching the panel would render as a score.
    index_map = get_prediction_index_map("Format: CADD_PHRED|CADD_RAW")
    parsed = apply_plugin_spec(
        ["12.34", "."], index_map, load_merged_spec("human_grch38").parsing.plugin("cadd")
    )
    assert parsed == {"phred": 12.34, "raw": None}
    raw_row = [
        row
        for option in spec.display.options if option.option_id == "cadd"
        for block in option.blocks
        for row in getattr(block, "rows", [])
        if row.source == "cadd.raw"
    ]
    assert raw_row and raw_row[0].placeholder is None  # absent -> dropped


# --- base config entries are composed, not copied ---------------------------


def test_a_genome_inherits_the_base_entries_without_restating_them():
    """The eight ubiquitous options used to be copied into every per-genome
    document. Each document now states only what is its own, and the loader
    layers base underneath."""
    base_ids = {e.id for e in load_merged_spec("base").config.entries}
    assert base_ids

    # `protein` is the one base entry a genome document restates, and it does so
    # to say something it can only say there: human 37/38 file the control under
    # a "Protein" category, every other genome leaves it uncategorised. That is
    # the override the next test describes, used for its intended purpose — see
    # docs/form-panels-to-json.md.
    overridden = {"protein"}

    for genome in ("human_grch37", "human_grch38"):
        # the assembled spec still offers all of them...
        assembled = {e.id for e in load_merged_spec(genome).config.entries}
        assert base_ids <= assembled, genome
        # ...and the document on disk names none of them but the override
        from app.vep.utils.spec_loader import SPEC_DIR
        document = json.loads((SPEC_DIR / f"{genome}.json").read_text())
        restated = base_ids & {e["id"] for e in document["config"]["entries"]}
        assert restated == overridden, f"{genome} restates base entries: {restated}"

        # An override earns its place by differing. A restated entry identical
        # to the base one is a copy that will drift, which is what this test was
        # written to stop.
        for entry_id in restated:
            base_entry = next(
                e for e in load_merged_spec("base").config.entries if e.id == entry_id
            )
            genome_entry = next(
                e for e in load_merged_spec(genome).config.entries if e.id == entry_id
            )
            assert genome_entry != base_entry, f"{genome} restates {entry_id} unchanged"


def test_a_genome_can_override_a_base_entry():
    """Inheritance is layering, not merging: a genome declaring the same id wins,
    so a base option needing a different file path somewhere can say so where the
    difference lives rather than leaving the base tier for everyone."""
    from app.vep.utils.spec_loader import _with_base_entries

    own = [{"id": "hgvs", "order": 10, "parsed_as": [],
            "config": {"emit": "flag", "keyword": "hgvs_custom"}}]
    merged = _with_base_entries("human_grch38", own)
    hgvs = [e for e in merged if e["id"] == "hgvs"]
    assert len(hgvs) == 1, "the base entry should be replaced, not duplicated"
    assert hgvs[0]["config"]["keyword"] == "hgvs_custom"


def test_the_base_spec_does_not_inherit_from_itself():
    base = load_merged_spec("base").config.entries
    assert len({e.id for e in base}) == len(base)


def test_composed_entries_are_ordered_for_emission():
    """`order` is one numbering space across both tiers, so an inherited entry
    lands in the right place in the config.ini rather than at either end."""
    entries = load_merged_spec("human_grch38").config.entries
    assert [e.order for e in entries] == sorted(e.order for e in entries)
