import requests, logging
import json
from loguru import logger
from core.logging import InterceptHandler
from models.pipeline_model import PipelineParams
from core.config import NF_TOKEN, NF_PIPELINE_URL, NF_WORK_DIR, SEQERA_WORKFLOW_LAUNCH_URL

logging.getLogger().handlers = [InterceptHandler()]

def launch_workflow(pipeline_params: PipelineParams):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {NF_TOKEN}"
    }

    try:
        response = requests.post(SEQERA_WORKFLOW_LAUNCH_URL, headers=headers, json=pipeline_params)
        response.raise_for_status()
        responseJson = response.json()
        return responseJson['workflowId']

    except Exception as e:
        logger.exception("VEP WORKFLOW SUBMISSION ERROR: ", e)
        return None
