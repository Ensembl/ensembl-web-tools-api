import requests
from starlette.concurrency import run_in_threadpool

from vep.models.pipeline_model import PipelineParams
from core.config import (
    NF_TOKEN,
    NF_COMPUTE_ENV_ID,
    NF_PIPELINE_URL,
    SEQERA_API,
    NF_WORKSPACE_ID,
)

SEQERA_TIMEOUT = (5.0, 30.0)


def launch_workflow(pipeline_params: PipelineParams):
    try:
        missing = [
            name for name, value in {
                "NF_TOKEN": NF_TOKEN,
                "NF_COMPUTE_ENV_ID": NF_COMPUTE_ENV_ID,
                "NF_PIPELINE_URL": NF_PIPELINE_URL,
                "SEQERA_API": SEQERA_API,
                "NF_WORKSPACE_ID": NF_WORKSPACE_ID,
            }.items() if not value
        ]
        if missing:
            raise RuntimeError(
                "VEP workflow configuration is incomplete: " + ", ".join(missing)
            )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {NF_TOKEN}",
        }
        params = {"workspaceId": NF_WORKSPACE_ID}
        SEQERA_WORKFLOW_LAUNCH_URL = SEQERA_API + "/workflow/launch"
        payload = pipeline_params.model_dump()
        response = requests.post(
            SEQERA_WORKFLOW_LAUNCH_URL, params=params, headers=headers, json=payload,
            timeout=SEQERA_TIMEOUT,
        )
        response.raise_for_status()
        response_json = response.json()
        return response_json["workflowId"]
    except KeyError as e:
        e.args = (
            f"launch_workflow(): unexpected payload from Seqera: f{response.text}",
            *e.args,
        )
        raise
    except requests.HTTPError as e:
        e.args = (
            "launch_workflow(): error response from Seqera:",
            *e.args,
        )
        raise
    except (requests.ConnectionError, requests.Timeout) as e:
        e.args = (
            "launch_workflow(): network error while connecting to Seqera:",
            *e.args,
        )
        raise
    except Exception as e:
        e.args = (f"{type(e).__name__} in launch_workflow():", *e.args)
        raise


async def get_workflow_status(submission_id):
    return await run_in_threadpool(_get_workflow_status, submission_id)


def _get_workflow_status(submission_id):
    try:
        _headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {NF_TOKEN}",
        }
        _seqera_workflow_status_url = f"{SEQERA_API}/workflow/{submission_id}"
        params = {"workspaceId": NF_WORKSPACE_ID}
        response = requests.get(
            _seqera_workflow_status_url, params=params, headers=_headers,
            timeout=SEQERA_TIMEOUT,
        )

        response.raise_for_status()
        response_json = response.json()
        return response_json
    except KeyError as e:
        e.args = (
            f"launch_workflow(): unexpected payload from Seqera: f{response.text}",
            *e.args,
        )
        raise
    except requests.HTTPError as e:
        e.args = (
            "launch_workflow(): error response from Seqera:",
            *e.args,
        )
        raise
    except (requests.ConnectionError, requests.Timeout) as e:
        e.args = (
            "launch_workflow(): network error while connecting to Seqera:",
            *e.args,
        )
        raise
    except Exception as e:
        e.args = (f"{type(e).__name__} in launch_workflow():", *e.args)
        raise
