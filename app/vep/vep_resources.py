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
from fastapi import Request, HTTPException, status, APIRouter

from core.logging import InterceptHandler
from vep.models.upload_vcf_files import Streamer, MaxBodySizeException
from vep.models.pipeline_model import *
from vep.utils.nextflow import launch_workflow
import json

logging.getLogger().handlers = [InterceptHandler()]

router = APIRouter()


@router.post("/submissions", name="submit_vep")
async def submit_vep(request: Request):
    try:
        request_streamer = Streamer(request=request)
        stream_result = await request_streamer.stream()
        vep_job_parameters = request_streamer.parameters.value.decode()
        genome_id = request_streamer.genome_id.value.decode()

        vep_job_parameters_dict = json.loads(vep_job_parameters)
        ini_parameters = ConfigIniParams(**vep_job_parameters_dict)
        inifile = ini_parameters.create_config_ini_file(request_streamer.temp_dir)
        vep_job_config_parameters = VEPConfigParams(
            vcf=request_streamer.filepath, vep_config=inifile.name
        )
        launch_params = LaunchParams(paramsText=vep_job_config_parameters, labelIds=[])
        pipeline_params = PipelineParams(launch=launch_params)
        if stream_result:
            workflow_id = launch_workflow(pipeline_params)
            return {"submission_id": workflow_id}
        else:
            raise Exception
    except MaxBodySizeException:
        return HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Maximum file size limit exceeded.",
        )
    except Exception as e:
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not submit VEP job/workflow.",
        )
