from typing import Optional, List, Literal
from pydantic import BaseModel, validator
from core.config import NF_COMPUTE_ENV_ID

class VEPConfigParams(BaseModel):
    vcf: str
    vep_config: str

class LaunchParams(BaseModel):
    computeEnvId: str = NF_COMPUTE_ENV_ID
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

class ConfigIniParams(BaseModel):
  cache: int = 1
  dir_cache: str = "/nfs/production/flicek/ensembl/variation/data/VEP/tabixconverted/"
  species: str = "homo_sapiens"
  assembly: str = 'GRCh38'
  cache_version: int = 110
  offline: int = 1
  force_overwrite: int = 1
  symbol: int = 1
  biotype: int = 1
  transcript_version: int = 1
  canonical: int = 1
