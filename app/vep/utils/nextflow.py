import requests
import json
from core.config import NF_TOKEN, NF_PIPELINE_URL, NF_COMPUTE_ENV_ID, NF_WORK_DIR, SEQERA_WORKFLOW_LAUNCH_URL
from models.pipeline_model import PipelineParams

def launch_workflow(pipeline_params: PipelineParams):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {NF_TOKEN}"
    }

    response = requests.post(SEQERA_WORKFLOW_LAUNCH_URL, headers=headers, json=pipeline_params)

    # Check if successful
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to launch workflow. Status code: {response.status_code}")
        return response.text


