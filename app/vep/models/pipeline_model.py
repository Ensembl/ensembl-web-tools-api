from pydantic import (
    BaseModel,
    DirectoryPath,
    FilePath,
    model_serializer,
    Field,
    AliasPath,
    field_serializer,
)
from core.config import (
    NF_COMPUTE_ENV_ID,
    NF_PIPELINE_URL,
    NF_WORK_DIR,
)
from core.logging import InterceptHandler
import json, logging, os

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
            "{" + ", ".join(
                [vcf_str, config_str, outdir_str, bin_str, sort_str]
            ) + "}"
        )
        return json_str


class LaunchParams(BaseModel):
    computeEnvId: str = NF_COMPUTE_ENV_ID
    pipeline: str = NF_PIPELINE_URL
    workDir: str = NF_WORK_DIR
    revision: str = "main"
    pullLatest: bool = True
    configProfiles: list[str] = ["ensembl"]
    paramsText: VEPConfigParams


class PipelineParams(BaseModel):
    launch: LaunchParams


class ConfigIniParams(BaseModel):
    force_overwrite: int = 1
    symbol: bool = False
    biotype: bool = False
    transcript_version: int = 1
    canonical: int = 1
    gff: str = "/nfs/public/rw/enswbsites/dev/vep/test/genes.gff3.bgz"
    fasta: str = "/nfs/public/rw/enswbsites/dev/vep/test/unmasked.fa.bgz"

    def create_config_ini_file(self, dir):
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
            with open(os.path.join(dir, "config.ini"), "w") as ini_file:
                ini_file.write(config_ini)
            return ini_file
        except Exception as e:
            logging.info(e)
            raise RuntimeError("Could not create vep config ini file")


class PipelineStatus(BaseModel):
    submission_id: str
    status: str = Field(
        validation_alias=AliasPath("status", "workflow", "status"), default="FAILED"
    )

    @field_serializer("status")
    def serialize_status(self, status: str):
        if status == "UNKNOWN":
            status = "FAILED"
            logging.info("UNKNOWN STATUS WAS RETURNED HERE")
        return status
