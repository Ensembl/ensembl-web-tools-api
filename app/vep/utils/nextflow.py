import requests
import json
from core.config import NF_TOKEN, NF_PIPELINE_URL, NF_COMPUTE_ENV_ID, NF_WORK_DIR
from models.pipeline_model import PipelineParams

def launch_workflow(pipeline_params: PipelineParams):
    url = "https://api.cloud.seqera.io/workflow/launch" # ENV
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {NF_TOKEN}"
    }

    response = requests.post(url, headers=headers, json=pipeline_params)

    # Check if successful
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to launch workflow. Status code: {response.status_code}")
        return response.text


