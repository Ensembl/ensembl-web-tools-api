import logging, os
from typing import Callable

from pydantic import (
    BaseModel,
    ConfigDict,
    DirectoryPath,
    FilePath,
    model_serializer,
    Field,
    AliasPath,
    field_serializer,
    model_validator,
)
from requests import HTTPError

from core.config import (
    DUMP_INI,
    NF_COMPUTE_ENV_ID,
    NF_PIPELINE_URL,
)
from core.logging import InterceptHandler

from vep.models.config_spec_model import ConfigSpec
from vep.utils.config_interpreter import emit_config_lines
from vep.utils.web_metadata import get_vep_support_location

logging.getLogger().handlers = [InterceptHandler()]


class VEPConfigParams(BaseModel):
    vcf: FilePath
    vep_config: FilePath
    outdir: DirectoryPath
    bin_size: int = 3000
    sort: bool = True
    vep_version: str = "115.2"

    @model_serializer
    def vep_config_serialiser(self):
        vcf_str = f'"input": "{self.vcf.as_posix()}"'
        config_str = f'"vep_config": "{self.vep_config.as_posix()}"'
        outdir_str = f'"outdir": "{self.outdir.as_posix()}"'
        bin_str = f'"bin_size": {self.bin_size}'
        sort_str = f'"sort": {"true" if self.sort else "false"}'
        vep_version_str = f'"vep_version": "{self.vep_version}"'
        json_str = (
            "{" + ", ".join([vcf_str, config_str, outdir_str, bin_str, sort_str, vep_version_str]) + "}"
        )
        return json_str


class LaunchParams(BaseModel):
    computeEnvId: str = NF_COMPUTE_ENV_ID
    pipeline: str = NF_PIPELINE_URL
    workDir: DirectoryPath
    revision: str = "release/115"
    pullLatest: bool = True
    configProfiles: list[str] = ["ensembl"]
    paramsText: VEPConfigParams

    @field_serializer("workDir")
    def serialize_workdir(self, workdir: DirectoryPath):
        return workdir.as_posix()


class PipelineParams(BaseModel):
    launch: LaunchParams


# Placeholder root for plugin data files. These paths are not yet resolved
# per-genome; they will be substituted for real locations later.
# TODO (pre-production, required): replace this placeholder with real per-genome
# plugin-data resolution. Every `plugin ...` line below interpolates it, so no
# plugin can run against real data until this is wired up.
PLUGIN_PATH = "/[placeholder_path]"


# --- DEV ONLY: real (beta) plugin-data locations ---------------------------
# So a DUMP_INI dev job's config.ini points at the real data on nfs (the manual
# HPC run reads it directly) instead of the PLUGIN_PATH placeholder. Wired only
# under DUMP_INI (see create_config_ini_file). REMOVE this whole block — and the
# DUMP_INI branch below — once production per-genome plugin-data resolution
# lands. Not the final production paths; the beta layout used for dev today.
_DEV_PLUGIN_ROOT = {
    "GRCh38": "/nfs/production/flicek/ensembl/variation/enseweb-data_tools/beta_plugins/grch38",
    "GRCh37": "/nfs/production/flicek/ensembl/variation/enseweb-data_tools/beta_plugins/grch37",
}
# Most datasets sit directly in the assembly's base dir; these few live in a
# named subdir under it (keyed by config-entry id). GRCh37 simply has no entry
# for the GRCh38-only datasets (AllOfUs / gnomAD CNV), so one map serves both.
_DEV_PLUGIN_SUBDIRS = {
    "allofus": "AllOfUs",
    "go": "GO_data_files",
    "phenotypes": "Phenotypes_data_files",
    "gnomad_cnv": "gnomAD_CNV",
    "gnomad_sv": "gnomAD_SV",
    "gnomad_exomes": "gnomAD_exomes",
    "gnomad_genomes": "gnomAD_genomes",
}


# Everything that is not one of the human assemblies: the GO / Phenotypes files
# for the other species share one tree, under the same per-dataset subdirs.
_DEV_OTHER_SPECIES_ROOT = (
    "/nfs/production/flicek/ensembl/variation/enseweb-data_tools/beta_plugins/other_species"
)


def _dev_plugin_path(assembly: str) -> "Callable[[str], str]":
    """A per-entry `{path}` resolver for dev: the assembly's base dir, plus a
    named subdir for the datasets that live in one.

    An assembly with no root of its own is another species, not a broken
    lookup — it resolves under the shared other-species tree. Falling back to
    the GRCh38 root, as this once did, would have pointed a cattle job at human
    data files.
    """
    for prefix, root in _DEV_PLUGIN_ROOT.items():
        if (assembly or "").startswith(prefix):
            base = root
            break
    else:
        base = _DEV_OTHER_SPECIES_ROOT

    def resolve(entry_id: str) -> str:
        subdir = _DEV_PLUGIN_SUBDIRS.get(entry_id)
        return f"{base}/{subdir}" if subdir else base

    return resolve

# The option→config.ini translation — which `plugin …` / `custom …` line each
# selected option emits — now lives in the declarative config spec (the `config`
# section of specs/human_grch38.json), applied by vep.utils.config_interpreter.
# What used to be the hardcoded PLUGIN_CONFIG_LINES / PLUGIN_CONFIG_LINES_BY_ASSEMBLY
# maps and the gnomAD/AoU field builders is gone; create_config_ini_file is now a
# thin runtime over that spec plus the always-on base below.


def base_config_lines(
    *,
    assembly_name: str,
    gff: str,
    fasta: str,
    force_overwrite: int = 1,
    transcript_version: int = 1,
    canonical: int = 1,
) -> list[str]:
    """The always-on VEP config.ini lines — invocation invariants not exposed as
    options. Centralised here rather than scattered through the ini builder
    because, when the option-driven lines move to the declarative config spec,
    these stay in the backend: they are VEP invariants plus the two
    runtime-resolved paths (`gff`/`fasta`), which cannot be static spec data.
    See app/vep/docs/design/technical-notes.md (What the specs replaced).

    Assembly gating mirrors ConfigIniParams' own prefix checks:
      mane 1                 — human GRCh38 and the mouse reference (GRCm39) only
      assembly               — the human reference assemblies (GRCh38 / GRCh37)
      flag_gencode_primary 1 — human GRCh38 only
    """
    is_human_grch38 = assembly_name.startswith("GRCh38")
    is_human_grch37 = assembly_name.startswith("GRCh37")
    is_mouse_reference = assembly_name.startswith("GRCm39")

    lines = [
        f"force_overwrite {force_overwrite}",
        "numbers 1",
    ]
    # MANE annotations only exist for human GRCh38 and the mouse reference
    # (GRCm39); requesting `mane` for other species has no data.
    if is_human_grch38 or is_mouse_reference:
        lines.append("mane 1")
    # VEP assembly name, always on for the human reference assemblies.
    if is_human_grch38:
        lines.append("assembly GRCh38")
        # GENCODE primary annotation flag — human GRCh38 only.
        lines.append("flag_gencode_primary 1")
    elif is_human_grch37:
        lines.append("assembly GRCh37")
    lines += [
        "symbol 1",
        "biotype 1",
        "gene_version 1",
        f"transcript_version {transcript_version}",
        f"canonical {canonical}",
        # Disable VEP's database connection (cache/plugin-file mode only). A new
        # always-on invariant, not previously emitted anywhere. See design §4.5.
        "database 0",
        f"gff {gff}",
        f"fasta {fasta}",
    ]
    return lines


class ConfigIniParams(BaseModel):
    """One submission: the job's own fields, and the options it selected.

    The options used to be 199 boolean/number/select fields declared here, one
    per control. None of them was ever read by attribute — they arrived as
    `ConfigIniParams(**payload)` and left as `.model_dump()` — so they were a
    third statement of what the config entries already say, after the form
    panels and the `fields=` clause, and the only one that could not tell one
    assembly's options from another's.

    They are now a map, validated against the spec for this submission's
    assembly (see `submission_options`). `extra="forbid"` so a caller still
    passing an option as a keyword fails loudly rather than having it dropped.
    """

    model_config = ConfigDict(extra="forbid")

    genome_id: str
    # VEP invariants, not options: always emitted, never chosen.
    force_overwrite: int = 1
    transcript_version: int = 1
    canonical: int = 1
    assembly_name: str = ""
    # Sent so the form's panels can be pinned to this job — the same predicate
    # /form_config uses. Without it every human-specific panel would be silently
    # dropped from the pin. It emits no config.ini line.
    species_taxonomy_id: str = ""
    gff: str = ""
    fasta: str = ""
    # {option id: value} for every option this genome offers, at the value the
    # client sent or the default the spec declares. Filled in below, so a caller
    # may pass only what it wants to change.
    options: dict[str, bool | int | str] = {}

    @model_validator(mode="after")
    def _resolve_options(self) -> "ConfigIniParams":
        """Complete the option map from the spec, and say so when the client
        sent something this genome has no option for.

        Dropped rather than rejected: a submission can be rerun for 28 days, so
        a replayed payload may still name an option that has since been retired,
        and failing that rerun would be worse than ignoring the option. Logging
        it is the part that was missing — pydantic's `extra` default discarded
        these without a word.
        """
        from vep.submission_options import option_values

        values, unknown = option_values(
            self.options,
            species_taxonomy_id=self.species_taxonomy_id,
            assembly_name=self.assembly_name,
        )
        if unknown:
            logging.warning(
                "submission for %s set options this genome does not offer, "
                "ignoring them: %s",
                self.assembly_name or "(no assembly)",
                ", ".join(unknown),
            )
        self.options = values
        return self

    def create_config_ini_file(self, directory, config_spec: ConfigSpec):
        """Write the VEP config.ini for this submission: the always-on base
        (`base_config_lines`) plus the option-driven `plugin …` / `custom …` /
        flag lines the config interpreter emits from `config_spec` — the
        `.config` half of the job's pinned merged spec. A thin runtime over the
        declarative spec; the option→line rules are data, not code here. See
        app/vep/docs/design/spec-and-extension-guide.md."""
        vep_support_location = get_vep_support_location(self.genome_id)
        self.gff = vep_support_location["gff_location"]
        self.fasta = vep_support_location["faa_location"]

        # Assembly of the selected species (e.g. "GRCh38.p14", "GRCh37.p13"),
        # resolved to the value the spec's `by_assembly` params key on (default
        # GRCh38) — the same notion of "which genome" the base config uses.
        assembly_name = self.assembly_name or ""
        assembly = "GRCh37" if assembly_name.startswith("GRCh37") else "GRCh38"

        lines = base_config_lines(
            assembly_name=assembly_name,
            gff=self.gff,
            fasta=self.fasta,
            force_overwrite=self.force_overwrite,
            transcript_version=self.transcript_version,
            canonical=self.canonical,
        )
        # Dev jobs (DUMP_INI) resolve `{path}` to the real beta data layout so
        # the dumped ini runs directly on the HPC; production still emits the
        # placeholder until real per-genome resolution lands (see PLUGIN_PATH).
        # The real assembly name, not the GRCh37/38 bucket above: that bucket
        # calls every other species GRCh38, which would point a cattle job at
        # human plugin data.
        plugin_path = _dev_plugin_path(assembly_name) if DUMP_INI else PLUGIN_PATH
        lines += emit_config_lines(
            config_spec,
            self.options,
            assembly=assembly,
            plugin_path=plugin_path,
            gff=self.gff,
        )

        config_ini = "\n".join(lines) + "\n"
        try:
            with open(os.path.join(directory, "config.ini"), "w") as ini_file:
                ini_file.write(config_ini)
            return ini_file
        except Exception as e:
            raise RuntimeError(f"Could not create VEP config ini file: {e}")


class PipelineStatus(BaseModel):
    submission_id: str
    status: str = Field(
        validation_alias=AliasPath("status", "workflow", "status"), default="FAILED"
    )

    @field_serializer("status")
    def serialize_status(self, status: str):
        if status == "UNKNOWN":
            status = "FAILED"
            logging.info(
                f"Unknown status was returned for submission {self.submission_id}"
            )
        return status
