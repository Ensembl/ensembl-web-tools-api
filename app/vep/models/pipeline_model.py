import logging, os
from pydantic import (
    BaseModel,
    DirectoryPath,
    FilePath,
    model_serializer,
    Field,
    AliasPath,
    field_serializer,
)
from requests import HTTPError

from core.config import (
    NF_COMPUTE_ENV_ID,
    NF_PIPELINE_URL,
)
from core.logging import InterceptHandler

from vep.utils.web_metadata import get_vep_support_location

logging.getLogger().handlers = [InterceptHandler()]


class VEPConfigParams(BaseModel):
    vcf: FilePath
    vep_config: FilePath
    outdir: DirectoryPath
    bin_size: int = 3000
    sort: bool = True

    @model_serializer
    def vep_config_serialiser(self):
        vcf_str = f'"input": "{self.vcf.as_posix()}"'
        config_str = f'"vep_config": "{self.vep_config.as_posix()}"'
        outdir_str = f'"outdir": "{self.outdir.as_posix()}"'
        bin_str = f'"bin_size": {self.bin_size}'
        sort_str = f'"sort": {"true" if self.sort else "false"}'
        json_str = (
            "{" + ", ".join([vcf_str, config_str, outdir_str, bin_str, sort_str]) + "}"
        )
        return json_str


class LaunchParams(BaseModel):
    computeEnvId: str = NF_COMPUTE_ENV_ID
    pipeline: str = NF_PIPELINE_URL
    workDir: DirectoryPath
    revision: str = "main"
    pullLatest: bool = True
    configProfiles: list[str] = ["ensembl"]
    paramsText: VEPConfigParams

    @field_serializer("workDir")
    def serialize_workdir(self, workdir: DirectoryPath):
        return workdir.as_posix()


class PipelineParams(BaseModel):
    launch: LaunchParams


class ConfigIniParams(BaseModel):
    genome_id: str
    force_overwrite: int = 1
    symbol: bool = False
    biotype: bool = False
    transcript_version: int = 1
    canonical: int = 1
    gff: str = ""
    fasta: str = ""

    def create_config_ini_file(self, directory):
        vep_support_location = get_vep_support_location(self.genome_id)
        self.gff = vep_support_location["gff_location"]
        self.fasta = vep_support_location["faa_location"]
        symbol = 1 if self.symbol else 0
        biotype = 1 if self.biotype else 0

        config_ini = f"""\
force_overwrite {self.force_overwrite}
symbol {symbol}
biotype {biotype}
transcript_version {self.transcript_version}
canonical {self.canonical}
gff {self.gff}
fasta {self.fasta}
"""
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
