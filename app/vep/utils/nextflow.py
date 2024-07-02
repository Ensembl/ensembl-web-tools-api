import requests, logging
import json
from loguru import logger
from core.logging import InterceptHandler
from models.pipeline_model import PipelineParams
from app.error_response import response_error_handler
from core.config import NF_TOKEN, NF_PIPELINE_URL, NF_COMPUTE_ENV_ID, NF_WORK_DIR, SEQERA_WORKFLOW_LAUNCH_URL

logging.getLogger().handlers = [InterceptHandler()]

def launch_workflow(pipeline_params: PipelineParams):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {NF_TOKEN}"
    }

    try:
        response = requests.post(SEQERA_WORKFLOW_LAUNCH_URL, headers=headers, json=pipeline_params)
        response.raise_for_status()

    except requests.exceptions.HTTPError as HTTPError:
        return response_error_handler({"status": HTTPError.response.status_code})

    except Exception as e:
        logger.exception(e)
        return response_error_handler({"status": 500})

    # Check if successful
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to launch workflow. Status code: {response.status_code}")
        return response.text
