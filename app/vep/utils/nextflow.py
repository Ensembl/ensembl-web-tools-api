import requests, logging
from loguru import logger
from requests import HTTPError

from core.logging import InterceptHandler
from vep.models.pipeline_model import PipelineParams, PipelineStatus
from core.config import (
    NF_TOKEN,
    SEQERA_API,
    NF_WORKSPACE_ID
)

logging.getLogger().handlers = [InterceptHandler()]


def launch_workflow(pipeline_params: PipelineParams):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {NF_TOKEN}",
    }
    params= {
        "workspaceId": NF_WORKSPACE_ID
    }
    SEQERA_WORKFLOW_LAUNCH_URL = SEQERA_API + "/workflow/launch"
    payload = pipeline_params.model_dump()
    try:
        response = requests.post(
            SEQERA_WORKFLOW_LAUNCH_URL, params=params, headers=headers, json=payload
        )
        response.raise_for_status()
        response_json = response.json()
        return response_json["workflowId"]

    except Exception as e:
        logger.exception("VEP WORKFLOW SUBMISSION ERROR: ", e)
        raise Exception


async def get_workflow_status(submission_id):
    try:
        _headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {NF_TOKEN}",
        }
        _seqera_workflow_status_url = f"{SEQERA_API}/workflow/{submission_id}"
        params= {
            "workspaceId": NF_WORKSPACE_ID
            }
        response = requests.get(_seqera_workflow_status_url, params=params, headers=_headers)

        response.raise_for_status()
        response_json = response.json()
        pipeline_status = PipelineStatus(submission_id=submission_id, status=response_json, outfile=response_json)
        return pipeline_status
    except HTTPError as e:
        raise e
    except Exception as e:
        logger.exception("VEP connection error: ", e)
        raise Exception
