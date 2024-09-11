from contextlib import asynccontextmanager
from urllib import response
from fastapi import FastAPI, Response, APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from aiohttp import ClientSession, client_exceptions
from enum import Enum
from uuid import UUID
import asyncio
import secrets
import json
import re
import os

from core.config import BLAST_CONFIG, TRUST_ENV


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # Startup: setup data cache and requests session
#     app.client_session = ClientSession()
#     with open("/data/blast_config.json") as f:
#         app.blast_config = json.load(f)
#     yield
#     # Shutdown: close requests session
#     await app.client_session.close()


app = FastAPI()



# Override response for input payload validation error
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        content={
            "error": ";".join(f"{err['loc']}:{err['msg']}" for err in exc.errors())
        },
        status_code=422,
    )


# Override 404 response
@app.exception_handler(404)
async def invalid_path_handler(request, exception):
    return JSONResponse(content={"error": "Invalid endpoint"}, status_code=404)


# Handle connection errors to jDispatcher
@app.exception_handler(client_exceptions.ClientConnectorError)
async def upstream_connection_handler(request, exception):
    return JSONResponse(
        content={"error": "Cannot connect to jDispatcher"}, status_code=500
    )


# Endpoint for serving the BLAST config
@app.get("/config")
async def serve_config() -> dict:
    return BLAST_CONFIG


# Validate job submission payload
class Program(str, Enum):
    blastp = "blastp"
    blastn = "blastn"
    blastx = "blastx"
    tblastn = "tblastn"
    tblastx = "tblastx"


class DbType(str, Enum):
    cdna = "cdna"
    dna = "dna"
    dna_sm = "dna_sm"
    protein = "pep"


class BlastParams(BaseModel, extra="allow"):
    email: str = "blast2020@ebi.ac.uk"
    title: str = ""
    program: Program
    database: DbType


class QuerySequence(BaseModel):
    id: int
    value: str


class BlastJob(BaseModel):
    genome_ids: list[UUID]
    query_sequences: list[QuerySequence]
    parameters: BlastParams


class JobIDs(BaseModel):
    job_ids: list[str]


# Infer the target db path for BLAST job
suffix_map = {"dna": "unmasked", "dna_sm": "softmasked"}  # dna/dna_sm/cdna/pep


def get_db_path(genome_id: str, db_type: str) -> str:
    return f"ensembl/{genome_id}/{suffix_map.get(db_type, db_type)}"


# Submit a BLAST job to JD. Returns a resolvable for fetching the response.
blast_url = os.environ.get(
    "BLAST_URL", "http://wwwdev.ebi.ac.uk/Tools/services/rest/ncbiblast_ensembl"
)



async def run_blast(
    query: dict, blast_payload: dict, genome_id: str, db_type: str
) -> dict:
    blast_payload["sequence"] = query["value"]
    blast_payload["database"] = get_db_path(genome_id, db_type)
    url = f"{blast_url}/run"
    app.client_session = ClientSession(trust_env=TRUST_ENV)
    async with app.client_session.post(url, data=blast_payload) as resp:
        response = await resp.text()
        if resp.status == 200:
            return {
                "sequence_id": query["id"],
                "genome_id": genome_id,
                "job_id": response,
            }
        else:
            # Strip xhtml tags from the response message
            response = re.sub("<.*?>|\n+", "", response)
            return {
                "sequence_id": query["id"],
                "genome_id": genome_id,
                "error": response,
                "status": resp.status,
            }


# Endpoint for submitting BLAST jobs to jDispatcher
@app.post("/job")
async def submit_blast(payload: BlastJob) -> dict:
    payload = jsonable_encoder(payload)
    db_type = payload["parameters"]["database"]
    blast_jobs = []
    # Submit multiple concurrent BLAST jobs (one for each query seq. / target species combination)
    for query in payload["query_sequences"]:
        for genome_id in payload["genome_ids"]:
            blast_jobs.append(
                run_blast(query, payload["parameters"], genome_id, db_type)
            )
    job_results = await asyncio.gather(*blast_jobs)
    return {"submission_id": secrets.token_urlsafe(16), "jobs": job_results}


# Endpoint for querying a job status
@app.get("/jobs/status/{job_id}")
async def blast_job_status(job_id: str) -> dict:
    resp = await blast_proxy("status", job_id)
    if resp["status"] == "NOT_FOUND":
        response.status_code = 404
    resp["job_id"] = job_id
    return resp


# Endpoint for querying multiple job statuses
@app.post("/jobs/status")
async def blast_job_statuses(payload: JobIDs) -> dict:
    payload = jsonable_encoder(payload)
    status_requests = [blast_job_status(job_id) for job_id in payload["job_ids"]]
    statuses = await asyncio.gather(*status_requests)
    return {"statuses": statuses}


# Proxy for JD BLAST REST API endpoints (/status/:id, /result/:id/:type)
@app.get("/jobs/{action}/{params:path}")
async def blast_proxy(action: str, params: str, response: Response = None) -> dict:
    url = f"{blast_url}/{action}/{params}"
    app.client_session = ClientSession(trust_env=TRUST_ENV)
    async with app.client_session.get(url) as resp:
        if response:
            response.status_code = resp.status  # forward the status code from JD
        content = await resp.text()
        if params.endswith("json"):
            try:
                content = json.loads(content)
            except ValueError:
                pass
        if resp.status == 200:
            return {action: content}
        else:
            if content:
                # Clean JD error message for JSON
                content = re.sub("<.*?>", "", content)
                content = content.strip()
                content = re.sub("\n+", ". ", content)
                # Fix JD response status code (400->404)
                if "not found" in content:
                    response.status_code = 404
            else:
                content = f"Invalid JD endpoint: /{action}/{params}"
            return {"error": content}
