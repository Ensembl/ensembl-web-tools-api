"""
See the NOTICE file distributed with this work for additional information
regarding copyright ownership.


Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
import logging
import tempfile 
import os, json
  
from typing import Annotated
from core.config import VEP_CONFIG_INI_PATH
from fastapi import APIRouter, responses, UploadFile, Form

# from core.logging import InterceptHandler
from models.pipeline_model import ConfigIniParams
# logging.getLogger().handlers = [InterceptHandler()]

router = APIRouter()

@router.post("/submissions", name="submit_vep")
def submit_vep(genome_id:Annotated[str, Form()], input_file: UploadFile):
    try:
        return {"genome_id":genome_id,"filename": input_file.filename}
    except Exception as e:
        logging.info(e)

# Creates config ini file
def create_config_ini_file(symbol: bool = "true", biotype: bool = "true"):
    symbol = 1 if (symbol) else 0
    biotype = 1 if (biotype) else 0

    config_ini_params = ConfigIniParams(
        symbol = symbol,
        biotype = biotype
    )
    config_dump = config_ini_params.model_dump()

    print (config_dump['cache_version'])
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

create_config_ini_file()