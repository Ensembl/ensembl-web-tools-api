from typing import Optional, List, Literal
from pydantic import BaseModel, validator
from core.config import NF_COMPUTE_ENV_ID, VEP_CONFIG_INI_PATH

import tempfile 

class VEPConfigParams(BaseModel):
    vcf: str
    vep_config: str

class LaunchParams(BaseModel):
    computeEnvId: str = NF_COMPUTE_ENV_ID
    pipeline: str
    workDir: str
    revision: str = "main"
    pullLatest: bool = True
    configProfiles: List[str] = ["slurmnew"]
    paramsText: VEPConfigParams
    preRunScript: str = "module load nextflow"
    postRunScript: str = ""
    stubRun: bool = False
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

# Creates config ini file
def create_config_ini_file(symbol: bool = False, biotype: bool = False):
    symbol = 1 if (symbol) else 0
    biotype = 1 if (biotype) else 0

    config_ini_params = ConfigIniParams(
        symbol = symbol,
        biotype = biotype
    )
    config_dump = config_ini_params.model_dump()

    config_yaml = f'''cache {config_dump["cache"]}
dir_cache {config_dump["dir_cache"]}
species {config_dump["species"]}
assembly {config_dump["assembly"]}
cache_version {config_dump["cache_version"]}
offline {config_dump["offline"]}
force_overwrite {config_dump["force_overwrite"]}
symbol {symbol}
biotype {biotype}
transcript_version {config_dump["transcript_version"]}
canonical {config_dump["canonical"]}
'''
    ini_file = tempfile.NamedTemporaryFile(prefix="vep_", dir=VEP_CONFIG_INI_PATH, delete=False)
    try: 
        ini_file.write(config_yaml.encode())
    finally:
        ini_file.close()
    return ini_file