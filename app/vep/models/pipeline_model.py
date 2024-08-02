from typing import List
from pydantic import (
    BaseModel,
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
import logging, os

logging.getLogger().handlers = [InterceptHandler()]


class VEPConfigParams(BaseModel):
    vcf: str
    vep_config: str

    @model_serializer
    def vep_config_serialiser(self):
        vcf_str = '"vcf":"' + self.vcf + '"'
        config_str = '"vep_config":"' + self.vep_config + '"'
        stringified_encoded_json = "{" + vcf_str + "," + config_str + "}"
        return stringified_encoded_json


class LaunchParams(BaseModel):
    computeEnvId: str = NF_COMPUTE_ENV_ID
    pipeline: str = NF_PIPELINE_URL
    workDir: str = NF_WORK_DIR
    revision: str = "main"
    pullLatest: bool = True
    configProfiles: List[str] = ["slurmnew"]
    paramsText: VEPConfigParams
    preRunScript: str = ""
    postRunScript: str = ""
    stubRun: bool = False
    labelIds: List[str]
    headJobCpus: int = 1
    headJobMemoryMb: int = 4


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
    status: str = Field(alias=AliasPath("workflow", "status"), default="FAILED")

    @field_serializer("status")
    def serialize_status(self, status: str):
        if status == "UNKNOWN":
            status = "FAILED"
            logging.info("UNKNOWN STATUS WAS RETURNED HERE")
        return status
