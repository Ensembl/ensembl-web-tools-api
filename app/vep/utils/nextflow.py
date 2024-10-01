import requests
import logging

from vep.models.pipeline_model import PipelineParams
from core.config import NF_TOKEN, SEQERA_API, NF_WORKSPACE_ID


def launch_workflow(pipeline_params: PipelineParams):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {NF_TOKEN}",
    }
    params = {"workspaceId": NF_WORKSPACE_ID}
    SEQERA_WORKFLOW_LAUNCH_URL = SEQERA_API + "/workflow/launch"
    payload = pipeline_params.model_dump()
    response = requests.post(
        SEQERA_WORKFLOW_LAUNCH_URL, params=params, headers=headers, json=payload
    )
    response.raise_for_status()
    response_json = response.json()
    return response_json["workflowId"]


async def get_workflow_status(submission_id):
    _headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {NF_TOKEN}",
    }
    _seqera_workflow_status_url = f"{SEQERA_API}/workflow/{submission_id}"
    params = {"workspaceId": NF_WORKSPACE_ID}
    response = requests.get(
        _seqera_workflow_status_url, params=params, headers=_headers
    )

    response.raise_for_status()
    response_json = response.json()
    return response_json
