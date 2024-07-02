from typing import Optional, List, Literal
from pydantic import BaseModel, validator
class VEPConfigParams(BaseModel):
    vcf: str
    vep_config: str
class LaunchParams(BaseModel):
    computeEnvId: str = "17wuWKrWOZW5JrLoGGwPdD"
    pipeline: str
    workDir: str
    revision: str = "main"
    pullLatest: bool = "true"
    configProfiles: List[str] = ["slurmnew"]
    paramsText: VEPConfigParams
    preRunScript: str = "module load nextflow"
    postRunScript: str = ""
    stubRun: bool = "false"
    labelIds: List[str]
    headJobCpus: int = 1
    headJobMemoryMb: int = 4
class PipelineParams(BaseModel):
    launch: LaunchParams
