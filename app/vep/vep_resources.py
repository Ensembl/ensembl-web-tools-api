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
from starlette.responses import JSONResponse, FileResponse
from fastapi import Request, status, APIRouter
from enum import Enum

from core.error_response import response_error_handler
from core.logging import InterceptHandler
from vep.models.pipeline_model import (
    ConfigIniParams,
    VEPConfigParams,
    LaunchParams,
    PipelineParams,
    PipelineStatus,
)
from vep.models.submission_form import Dropdown, FormConfig
from vep.models.upload_vcf_files import Streamer, MaxBodySizeException
from vep.utils.nextflow import launch_workflow, get_workflow_status
from vep.utils.vcf_results import get_results_from_path
from vep.utils.web_metadata import get_genome_metadata
import json
from pydantic import FilePath

logging.getLogger().handlers = [InterceptHandler()]

router = APIRouter()


class VepStatus(str, Enum):
    submitted = "SUBMITTED"
    running = "RUNNING"
    succeeded = "SUCCEEDED"
    failed = "FAILED"
    cancelled = "CANCELLED"


@router.post("/submissions", name="submit_vep")
async def submit_vep(request: Request):
    try:
        request_streamer = Streamer(request=request)
        stream_result = await request_streamer.stream()
        vep_job_parameters = request_streamer.parameters.value.decode()
        genome_id = request_streamer.genome_id.value.decode()
        vep_job_parameters_dict = json.loads(vep_job_parameters)
        ini_parameters = ConfigIniParams(**vep_job_parameters_dict, genome_id=genome_id)
        ini_file = ini_parameters.create_config_ini_file(request_streamer.temp_dir)
        vep_job_config_parameters = VEPConfigParams(
            vcf=request_streamer.filepath,
            vep_config=ini_file.name,
            outdir=request_streamer.temp_dir,
        )
        launch_params = LaunchParams(paramsText=vep_job_config_parameters)
        pipeline_params = PipelineParams(launch=launch_params)
        if stream_result:
            workflow_id = launch_workflow(pipeline_params)
            return {"submission_id": workflow_id}
        else:
            raise Exception
    except MaxBodySizeException:
        return response_error_handler(result={"status": 413})
    except Exception as e:
        logging.error(e)
        return response_error_handler(result={"status": 500})


@router.get("/submissions/{submission_id}/status", name="submission_status")
async def vep_status(request: Request, submission_id: str):
    try:
        workflow_status = await get_workflow_status(submission_id)
        submission_status = PipelineStatus(
            submission_id=submission_id, status=workflow_status
        )
        return JSONResponse(content=submission_status.dict())

    except HTTPError as http_error:
        logging.warning(http_error)
        if http_error.response.status_code in [403, 400]:
            response_msg = {
                "details": f"A submission with id {submission_id} was not found",
            }
            return JSONResponse(
                content=response_msg, status_code=status.HTTP_404_NOT_FOUND
            )

        return response_error_handler(
            result={"status": http_error.response.status_code}
        )
    except Exception as e:
        logging.error(e)
        return response_error_handler(result={"status": 500})


def get_vep_results_file_path(input_vcf_file):
    input_vcf_path = FilePath(input_vcf_file)
    vep_results_file = input_vcf_path.with_name(
        input_vcf_path.stem + "_VEP"
    ).with_suffix(".vcf.gz")
    return vep_results_file


@router.get("/submissions/{submission_id}/download", name="download_results")
async def download_results(request: Request, submission_id: str):
    try:
        workflow_status = await get_workflow_status(submission_id)
        submission_status = PipelineStatus(
            submission_id=submission_id, status=workflow_status
        )
        if submission_status.status == VepStatus.succeeded:
            input_vcf_file = workflow_status["workflow"]["params"]["input"]
            results_file_path = get_vep_results_file_path(input_vcf_file)
            if results_file_path.exists():
                return FileResponse(
                    results_file_path,
                    media_type="application/gzip",
                    filename=results_file_path.name,
                )
            else:
                response_msg = {
                    "details": f"A submission with id {submission_id} succeeded but could not find output file",
                }
                return JSONResponse(
                    content=response_msg, status_code=status.HTTP_404_NOT_FOUND
                )
        else:
            response_msg = {
                "details": f"A submission with id {submission_id} is not yet finished",
            }
            return JSONResponse(
                content=response_msg, status_code=status.HTTP_404_NOT_FOUND
            )

    except HTTPError as http_error:
        logging.warning(http_error)
        if http_error.response.status_code in [403, 400]:
            response_msg = {
                "status_code": status.HTTP_404_NOT_FOUND,
                "details": f"A submission with id {submission_id} was not found",
            }
            return JSONResponse(
                content=response_msg, status_code=status.HTTP_404_NOT_FOUND
            )
        return response_error_handler(
            result={"status": http_error.response.status_code}
        )
    except Exception as e:
        logging.error(e)
        return response_error_handler(result={"status": 500})


@router.get("/submissions/{submission_id}/results", name="view_results")
async def fetch_results(request: Request, submission_id: str, page: int, per_page: int):
    try:
        workflow_status = await get_workflow_status(submission_id)
        submission_status = PipelineStatus(
            submission_id=submission_id, status=workflow_status
        )
        if submission_status.status == VepStatus.succeeded:
            input_vcf_file = workflow_status["workflow"]["params"]["input"]
            results_file_path = get_vep_results_file_path(input_vcf_file)
            if results_file_path.exists():
                return get_results_from_path(
                    vcf_path=results_file_path, page=page, page_size=per_page
                )
            else:
                response_msg = {
                    "details": f"A submission with id {submission_id} succeeded but could not find output file",
                }
                return JSONResponse(
                    content=response_msg, status_code=status.HTTP_404_NOT_FOUND
                )
        else:
            response_msg = {
                "details": f"A submission with id {submission_id} is not yet finished",
            }
            return JSONResponse(
                content=response_msg, status_code=status.HTTP_404_NOT_FOUND
            )

    except HTTPError as http_error:
        if http_error.response.status_code in [403, 400]:
            response_msg = json.dumps(
                {
                    "status_code": status.HTTP_404_NOT_FOUND,
                    "details": f"A submission with id {submission_id} was not found",
                }
            )
            return JSONResponse(
                content=response_msg, status_code=status.HTTP_404_NOT_FOUND
            )
        return response_error_handler(
            result={"status": http_error.response.status_code}
        )
    except Exception as e:
        logging.error(e)
        return response_error_handler(result={"status": 500})

@router.get("/form_config/{genome_id}", name="get_form_config")
async def get_form_config(request: Request, genome_id: str):
    try:
        attributes = await get_genome_metadata(genome_id)
        annotation_provider_name = attributes.get("genebuild.provider_name", "")
        annotation_version = attributes.get("genebuild.provider_version", "")
        last_updated_date = attributes.get("genebuild.last_geneset_update", "")

        if (annotation_version or last_updated_date):
            label = f"{annotation_provider_name} {annotation_version or last_updated_date}"
            value = f"{annotation_provider_name}_{annotation_version or last_updated_date}"
        else:
            label = f"{annotation_provider_name}"
            value = f"{annotation_provider_name}"

        options = [{
            "label": label,
            "value": value
        }]

        default_option = options[0]
        transcript_set = Dropdown(
            label="Transcript set",
            options=options,
            default_value= default_option["value"]
        )

        form_config = FormConfig(
            transcript_set = transcript_set
        )
        return { "parameters": form_config }

    except HTTPError as http_error:
        if http_error.response.status_code == 404:
            response_msg = json.dumps(
                {
                    "status_code": status.HTTP_404_NOT_FOUND,
                    "details": f"genome id {genome_id} not found",
                }
            )
            return JSONResponse(
                content=response_msg, status_code=status.HTTP_404_NOT_FOUND
            )
        return response_error_handler(
            result={"status": http_error.response.status_code}
        )
    except Exception as e:
        logging.error(e)
        return response_error_handler(result={"status": 500})