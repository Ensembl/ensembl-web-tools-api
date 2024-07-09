from typing import Optional, List, Literal
from pydantic import BaseModel, validator
from core.config import NF_COMPUTE_ENV_ID, VEP_CONFIG_INI_PATH
from core.logging import InterceptHandler
from models.pipeline_model import ConfigIniParams

logging.getLogger().handlers = [InterceptHandler()]

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
  symbol: bool = False
  biotype: bool = False
  transcript_version: int = 1
  canonical: int = 1
  ini_file: str = None

  # Creates config ini file
  def create_config_ini_file(self):

    symbol = 1 if self.symbol else 0
    biotype = 1 if self.biotype else 0

    config_yaml = f'''cache {self.cache}
dir_cache {self.dir_cache}
species {self.species}
assembly {self.assembly}
cache_version {self.cache_version}
offline {self.offline}
force_overwrite {self.force_overwrite}
symbol {symbol}
biotype {biotype}
transcript_version {self.transcript_version}
canonical {self.canonical}
'''
    try:
      with tempfile.NamedTemporaryFile(prefix="vep_", suffix=".ini", dir=VEP_CONFIG_INI_PATH, delete=False) as ini_file:
        ini_file.write(config_yaml.encode())
      return ini_file
    except Exception as e:
      logging.info(e)
      raise RuntimeError("Could not create vep config ini file") from e
