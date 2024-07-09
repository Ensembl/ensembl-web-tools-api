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
from typing import Annotated
from fastapi import APIRouter, responses, UploadFile, Form

from core.logging import InterceptHandler
from models.pipeline_model import ConfigIniParams
logging.getLogger().handlers = [InterceptHandler()]

router = APIRouter()

@router.post("/submissions", name="submit_vep")
def submit_vep(genome_id:Annotated[str, Form()], input_file: UploadFile):
  try:
    return {"genome_id":genome_id,"filename": input_file.filename}
  except Exception as e:
    logging.info(e)
