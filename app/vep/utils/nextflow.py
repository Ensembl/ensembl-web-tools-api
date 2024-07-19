import requests, logging
from loguru import logger
from requests import HTTPError

from core.logging import InterceptHandler
from vep.models.pipeline_model import PipelineParams, PipelineStatus
from core.config import (
    NF_TOKEN,
    SEQERA_WORKFLOW_LAUNCH_URL,
    SEQERA_API,
)

logging.getLogger().handlers = [InterceptHandler()]


def launch_workflow(pipeline_params: PipelineParams):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {NF_TOKEN}",
    }
    payload = pipeline_params.model_dump()
    try:
        response = requests.post(
            SEQERA_WORKFLOW_LAUNCH_URL, headers=headers, json=payload
        )
        response.raise_for_status()
        response_json = response.json()
        return response_json["workflowId"]

    except Exception as e:
        logger.exception("VEP WORKFLOW SUBMISSION ERROR: ", e)
        raise Exception


async def get_workflow_status(job_id):
    try:
        _headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {NF_TOKEN}",
        }
        _seqera_workflow_status_url = f"{SEQERA_API}/workflow/{job_id}"
        response = requests.get(_seqera_workflow_status_url, headers=_headers)

        response.raise_for_status()
        pipeline_status = PipelineStatus(job_id=job_id, status=response.json())
        return pipeline_status
    except HTTPError as e:
        raise e
    except Exception as e:
        logger.exception("VEP connection error: ", e)
        raise Exception
