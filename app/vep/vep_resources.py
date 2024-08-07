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

from requests import HTTPError
from starlette.responses import JSONResponse, PlainTextResponse
from fastapi import Request, status, APIRouter

from core.error_response import response_error_handler
from core.logging import InterceptHandler
from vep.models.pipeline_model import (
    ConfigIniParams,
    VEPConfigParams,
    LaunchParams,
    PipelineParams,
)
from vep.models.upload_vcf_files import Streamer, MaxBodySizeException
from vep.utils.nextflow import launch_workflow, get_workflow_status
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
        ini_file = ini_parameters.create_config_ini_file(request_streamer.temp_dir)
        vep_job_config_parameters = VEPConfigParams(
            vcf=request_streamer.filepath, vep_config=ini_file.name
        )
        launch_params = LaunchParams(paramsText=vep_job_config_parameters, labelIds=[])
        pipeline_params = PipelineParams(launch=launch_params)
        if stream_result:
            workflow_id = launch_workflow(pipeline_params)
            return {"submission_id": workflow_id}
        else:
            raise Exception
    except MaxBodySizeException:
        return response_error_handler(result={"status": 413})
    except Exception as e:
        return response_error_handler(result={"status": 500})


@router.get("/submissions/{submission_id}/status", name="submission_status")
async def vep_status(request: Request, submission_id: str):
    try:
        workflow_status = await get_workflow_status(submission_id)
        return JSONResponse(content=workflow_status.dict())

    except HTTPError as http_error:
        if http_error.response.status_code in [403,400]:
            response_msg = json.dumps(
                {
                    "status_code": status.HTTP_404_NOT_FOUND,
                    "details": f"A submission with id {submission_id} was not found",
                }
            )
            return PlainTextResponse(
                response_msg, status_code=status.HTTP_404_NOT_FOUND
            )

        return response_error_handler(result={"status": http_error.response.status_code})
    except Exception as e:
        logging.debug(e)
        return response_error_handler(result={"status": 500})
