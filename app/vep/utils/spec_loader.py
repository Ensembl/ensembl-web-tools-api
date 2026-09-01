"""Where the merged annotation spec comes from, how it is pinned to a job, and
which one applies to a given submission.

This is the seam that keeps "local JSON file" vs "annotation API" from being a
decision we have to make yet. Today `load_merged_spec` reads a JSON document
shipped in `vep/specs/`; when the API exists, only its body changes — an HTTP GET
plus a cache keyed on the spec's content digest. Everything downstream takes a
validated `MergedSpec` either way (its `.config` half drives config.ini
generation at submission, its `.parsing` half parses the results).

The file is not a mock of the API: it is the same document the API will serve,
and the same one pinned alongside a job at submission time.
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from pydantic import FilePath

from vep.models.display_panels_model import (
    DisplayPanel,
    dump_display_panels,
    to_display_panels,
)
from vep.models.display_spec_model import DisplayOptionSpec
from vep.models.merged_spec_model import MergedSpec

SPEC_DIR = Path(__file__).resolve().parent.parent / "specs"

# Written alongside a job's config at submission time, so the spec used to
# generate its options is the one used to parse its results, even if the
# bundled spec changes in between (see resolve_merged_spec / write_spec_sidecar).
# The name is retained (results-meta / page-index sidecars sit beside it); its
# content is now the whole merged document, not just the parsing half.
SPEC_SIDECAR_FILE = "parsing_spec.json"

# The per-job CSQ columns the submitted options require, pinned beside the spec
# at submission and checked against the pipeline output header at results time
# (the runtime missing-expected-field check). Job-specific, so kept separate from
# the (assembly-generic) merged spec document.
EXPECTED_COLUMNS_SIDECAR_FILE = "expected_columns.json"

# The option panels this job was submitted against, pinned beside the spec at
# submission and handed back on the results response so the results view lays
# itself out from the submitted options rather than the live form config (which
# may have gained or lost panels since). Computed per job (it depends on the
# submission's species/assembly), so a sidecar rather than part of the
# content-digested spec document.
DISPLAY_PANELS_SIDECAR_FILE = "display_panels.json"


def _content_digest(payload: dict) -> str:
    """A stable digest of a spec's meaning, ignoring its own `spec_version`.

    Independent of key order and of whitespace. `payload` must be a *validated
    model's* dump (see load_merged_spec_file), not raw user-authored JSON:
    hand-written specs use aliases (`from`, `as`) and omit fields at their
    default, while a round-tripped `model_dump()` uses field names and fills in
    every default. Hashing the raw file directly would make the digest depend on
    which of those wrote it — exactly the instability version pinning exists to
    avoid.
    """
    content = {key: value for key, value in payload.items() if key != "spec_version"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_merged_spec_file(path: Path) -> MergedSpec:
    """Parse and validate a *self-contained* merged spec document — a pinned job
    sidecar, or a fully-authored spec — raising if it does not conform (including
    the config↔parsing consistency check in MergedSpec). A bundled genome spec is
    assembled from its library first; see `load_merged_spec` / `_assemble_payload`.
    The content digest is computed at load, not read from the file (see
    `_finalize`).
    """
    return _finalize(json.loads(path.read_text()))


def _finalize(payload: dict) -> MergedSpec:
    """Validate a full merged-spec payload and stamp its computed content digest
    onto both spec_version fields.

    The version is a property of the content (see load_merged_spec_file): the
    digest is taken from the validated model's canonical dump with the nested
    `parsing.spec_version` excluded (the top-level one is stripped by
    `_content_digest`), so a round-trip through the sidecar hashes to the same
    value, and the computed digest is mirrored onto the parsing view.
    """
    payload.setdefault("spec_version", "")  # satisfy the field before it's computed
    spec = MergedSpec.model_validate(payload)
    canonical_dump = spec.model_dump(
        mode="json", by_alias=True, exclude={"parsing": {"spec_version": True}}
    )
    digest = _content_digest(canonical_dump)
    spec.spec_version = digest
    spec.parsing.spec_version = digest
    return spec


def _select_library(library: dict, config_entries: list[dict]) -> dict:
    """The subset of the shared library a genome offers, chosen from its config.

    A genome's `config` entries name the parse plugins they emit columns for (via
    `parsed_as`); those are the plugins it runs. A display option belongs only
    when *every* plugin it reads is among them — so an assembled spec never
    advertises an option the genome has no data for, and the display↔parsing
    consistency check still resolves (no dangling plugin ref). GRCh38 enables all
    of them, so it selects the whole library unchanged (the Phase 0 baseline
    holds); a genome with fewer entries gets a smaller spec.
    """
    enabled_plugins = {
        plugin
        for entry in config_entries
        for plugin in entry.get("parsed_as", [])
    }
    plugins = [
        plugin
        for plugin in library["parsing"]["plugins"]
        if plugin["plugin"] in enabled_plugins
    ]
    options = [
        option
        for option in library["display"]["options"]
        if DisplayOptionSpec.model_validate(option).plugin_refs() <= enabled_plugins
    ]
    selected = {
        "parsing": {**library["parsing"], "plugins": plugins},
        "display": {**library["display"], "options": options},
    }
    # Help is carried whole. It is an inert lookup keyed by option id, read only
    # when an option is already being shown, so an unused entry costs nothing;
    # filtering it would need a third rule, since help is keyed across both id
    # spaces (a form option, a display option, or — as with ClinVar — one and
    # not the other).
    if "help" in library:
        selected["help"] = library["help"]
    return selected


BASE_ENTRY_SPEC = "base"


def _with_base_entries(name: str, entries: list[dict]) -> list[dict]:
    """`entries` layered on the ubiquitous ones every genome gets.

    The options in `base.json` need no data file beyond the genome itself, so
    every genome offers them. They used to be copied into each per-genome
    document — all eight byte-identical in both human specs — which meant a
    change to any of them had to land in three files or the genomes silently
    disagreed. Now each document states only what is *its own*.

    A genome may still override one by declaring an entry with the same id: its
    version wins. Nothing does today, but a genome needing a different file path
    or parameter for a base option should be able to say so where the difference
    lives, rather than forcing the option out of the base tier for everyone.
    """
    if name == BASE_ENTRY_SPEC:
        return entries
    own = {entry["id"] for entry in entries}
    base = json.loads((SPEC_DIR / f"{BASE_ENTRY_SPEC}.json").read_text())
    inherited = [e for e in base["config"]["entries"] if e["id"] not in own]
    # `order` is a single numbering space across both tiers, so the merged list
    # sorts into the sequence the config.ini expects regardless of which
    # document an entry came from.
    return sorted(inherited + entries, key=lambda entry: entry["order"])


def _assemble_payload(name: str, extra_entries: list[dict] | None = None) -> dict:
    """The full merged-spec payload for a bundled genome, assembled from the
    shared library it references.

    A genome document is thin: its own identity + `config` (availability and file
    paths), plus a `library` naming the shared `parsing` / `display` document
    that holds the ~species-agnostic plugin and option definitions. The genome's
    config selects which of them it offers (see `_select_library`); assembling
    here — rather than authoring one monolith per genome — keeps the shared half
    in one place, while everything downstream still receives the same
    self-contained MergedSpec (the config↔parsing↔display consistency check, the
    content digest, the job pin and results parsing all run on the assembled
    document). A document with no `library` (a fully-authored spec, or a pinned
    sidecar loaded via `load_merged_spec_file`) is returned unchanged.
    """
    doc = json.loads((SPEC_DIR / f"{name}.json").read_text())
    doc["config"]["entries"] = _with_base_entries(name, doc["config"]["entries"])
    if extra_entries:
        # Added before the library is selected: the selection is driven by the
        # config entries, so an entry appended afterwards would name a plugin
        # that had already been filtered out.
        doc["config"]["entries"] = sorted(
            doc["config"]["entries"] + extra_entries, key=lambda e: e["order"]
        )
    library_name = doc.pop("library", None)
    if library_name is None:
        return doc
    library = json.loads((SPEC_DIR / f"{library_name}.json").read_text())
    return {**doc, **_select_library(library, doc["config"]["entries"])}


def load_merged_spec(name: str) -> MergedSpec:
    """The named merged spec from the bundled spec directory, e.g. "human_grch38"
    — assembled from the shared library it references (see _assemble_payload),
    then validated and digested like any full document."""
    return _finalize(_assemble_payload(name))


# Assembly-name prefixes, mirroring ConfigIniParams' own is_human_grch38 /
# is_human_grch37 / is_mouse_reference checks (pipeline_model.py) so a spec is
# picked using the same notion of "which genome is this" as the ini builder.
# Human GRCh38 and GRCh37 have specs; a submission for any other assembly fails
# loudly here rather than being silently parsed with the wrong one.
# Assemblies that offer MORE than the base. Not a gate: an assembly absent from
# here still runs, on `BASE_SPEC`. VEP works on any genome with a GFF and a
# FASTA, so a spec decides which extra options a species is offered — never
# whether it can be submitted.
_ASSEMBLY_SPECS = {
    "GRCh38": "human_grch38",
    "GRCh37": "human_grch37",
}

# The options every genome gets: VEP mechanics read off the genome's own
# gene set, with no species data files behind them.
BASE_SPEC = "base"


# Species that carry GO / Phenotypes data files of their own. Keyed by assembly
# so the submit path can use the assembly resolved from the genome UUID.
# Deliberately a table, not one document per species: the file names follow
# entirely from the production name, so the rule is stated once in the document's
# `templates` and the table only says which species have which data. The form
# reads the same table, so the options offered and the spec used cannot drift.
SPECIES_ANNOTATIONS_FILE = "species_annotations"


@lru_cache(maxsize=1)
def _species_annotations() -> dict:
    return json.loads((SPEC_DIR / f"{SPECIES_ANNOTATIONS_FILE}.json").read_text())


# Characters that may follow a table assembly name and still be the same
# assembly — a patch or sub-version suffix, e.g. GRCm39 matching "GRCm39.p1".
_ASSEMBLY_SUFFIX_BOUNDARIES = (".", "_", "-")


def _is_same_assembly(assembly_name: str, table_name: str) -> bool:
    """Whether a submitted assembly name is the table's `table_name`.

    A plain `startswith` was fine when every name was long and distinctive, but
    the table now holds short ones — Ciona's assembly is literally `KH` — and a
    bare prefix test would hand an unrelated `KH…` genome Ciona's GO file.
    Requiring a separator keeps the patch-suffix tolerance without that.
    """
    if assembly_name == table_name:
        return True
    if not assembly_name.startswith(table_name):
        return False
    return assembly_name[len(table_name)] in _ASSEMBLY_SUFFIX_BOUNDARIES


def species_annotation_entry(assembly_name: str) -> dict | None:
    """The extras table's row for an assembly, or None."""
    for row in _species_annotations()["species"]:
        if _is_same_assembly(assembly_name or "", row["assembly"]):
            return row
    return None


def species_extra_config_entries(assembly_name: str) -> list[dict]:
    """The GO / Phenotypes config entries for a species, built from the shared
    templates with its own production name. Empty for a species with no data."""
    row = species_annotation_entry(assembly_name)
    if row is None:
        return []
    templates = _species_annotations()["templates"]
    entries = []
    for dataset in row["datasets"]:
        entry = json.loads(json.dumps(templates[dataset]))
        # `{production_name}` where the name follows from the species (GO,
        # Phenotypes); `{file}` where it does not and the row names it (CADD's
        # files are named per-project, not per-species). `{path}` is left alone —
        # the config interpreter resolves it per entry, later.
        substitutions = {
            "{production_name}": row["production_name"],
            "{file}": (row.get("files") or {}).get(dataset, ""),
        }
        for key, value in entry["config"]["params"].items():
            if isinstance(value, str):
                for token, replacement in substitutions.items():
                    value = value.replace(token, replacement)
                entry["config"]["params"][key] = value
        entries.append(entry)
    return entries


def resolve_merged_spec(assembly_name: str) -> MergedSpec:
    """The merged spec for a submission's assembly.

    An assembly with no spec of its own falls back to the base spec rather than
    failing: the pipeline needs only a GFF and a FASTA, both of which the
    metadata API serves for every genome it knows, so there is nothing about an
    unlisted species that stops a job running — it is simply offered fewer
    options.

    The submissions endpoint resolves `assembly_name` from the genome UUID
    before constructing ConfigIniParams. Real per-species branching (as
    opposed to per-assembly) would need an explicit metadata field.
    """
    for prefix, spec_name in _ASSEMBLY_SPECS.items():
        if (assembly_name or "").startswith(prefix):
            return load_merged_spec(spec_name)
    extras = species_extra_config_entries(assembly_name)
    if not extras:
        return load_merged_spec(BASE_SPEC)
    payload = _assemble_payload(BASE_SPEC, extra_entries=extras)
    row = species_annotation_entry(assembly_name)
    payload["genome"] = {
        "species_taxonomy_id": row["species_taxonomy_id"],
        "assembly": row["assembly"],
    }
    return _finalize(payload)


def write_spec_sidecar(directory: str | Path, spec: MergedSpec) -> Path:
    """Pin `spec` to a job by writing the whole merged document into the job's
    directory.

    In the real pipeline, `directory` is the job's own outdir, alongside its
    config.ini and (eventually) its output VCF, so `load_spec_sidecar` finds it
    from the results path with no other bookkeeping needed.

    The job directory is the pipeline outdir, alongside its `config.ini` and
    eventual output VCF, so results resolve this pin from the VCF's directory.
    """
    path = Path(directory) / SPEC_SIDECAR_FILE
    path.write_text(spec.model_dump_json())
    return path


def load_spec_sidecar(vcf_path: FilePath) -> MergedSpec | None:
    """The merged spec pinned alongside `vcf_path`'s directory, or None if there
    isn't one (e.g. output from before this existed). Keyed off the VCF path the
    same way results_meta.json and the page-index sidecar are, via `.with_name()`."""
    sidecar_path = vcf_path.with_name(SPEC_SIDECAR_FILE)
    if not sidecar_path.exists():
        return None
    return load_merged_spec_file(sidecar_path)


def write_expected_columns_sidecar(
    directory: str | Path, columns: set[str]
) -> Path:
    """Pin the CSQ columns this job's options require, beside its spec sidecar,
    for the results-time missing-expected-field check. Sorted for a stable file."""
    path = Path(directory) / EXPECTED_COLUMNS_SIDECAR_FILE
    path.write_text(json.dumps(sorted(columns)))
    return path


def load_expected_columns_sidecar(vcf_path: FilePath) -> set[str] | None:
    """The expected CSQ columns pinned alongside `vcf_path`, or None if there is
    no sidecar (output from before this existed). Keyed off the VCF path via
    `.with_name()`, like the spec and page-index sidecars."""
    sidecar_path = vcf_path.with_name(EXPECTED_COLUMNS_SIDECAR_FILE)
    if not sidecar_path.exists():
        return None
    return set(json.loads(sidecar_path.read_text()))


def write_display_panels_sidecar(
    directory: str | Path, panels: list[DisplayPanel]
) -> Path:
    """Pin the option panels this job was submitted against, beside its spec
    sidecar, so the results view can render the submitted layout rather than the
    current one. Same directory convention as the other sidecars."""
    path = Path(directory) / DISPLAY_PANELS_SIDECAR_FILE
    path.write_text(json.dumps(dump_display_panels(panels)))
    return path


def load_display_panels_sidecar(vcf_path: FilePath) -> list[DisplayPanel] | None:
    """The option panels pinned alongside `vcf_path`, or None if there is no
    sidecar (output from before this existed — such a job keeps rendering
    against the live form-config panels). Keyed off the VCF path via
    `.with_name()`, like the spec and expected-columns sidecars."""
    sidecar_path = vcf_path.with_name(DISPLAY_PANELS_SIDECAR_FILE)
    if not sidecar_path.exists():
        return None
    return to_display_panels(json.loads(sidecar_path.read_text()))
