from urllib import response
from fastapi import FastAPI, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Extra
from aiohttp import ClientSession
from enum import Enum
import asyncio
import secrets
import json
import re

app = FastAPI()

# Setup persistent session for making http requests
@app.on_event('startup')
async def startup_event():
  app.client_session = ClientSession()

@app.on_event('shutdown')
async def shutdown_event():
  await app.client_session.close()

# Override response for input payload validation error
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exception):
  return JSONResponse(content={'error': str(exception)}, status_code=422)

# Override 404 response
@app.exception_handler(404)
async def invalid_path_handler(request, exception):
  return JSONResponse(content={'error': 'Invalid endpoint'}, status_code=404)

# Endpoint for serving the BLAST config
@app.get('/blast/config')
async def serve_config() -> dict:
  with open('data/blast_config.json') as f:
   config = json.load(f)
  return config


# Validate job submission payload
class Program(str, Enum):
  blastp = 'blastp'
  blastn = 'blastn'
  blastx = 'blastx'
  tblastn = 'tblastn'
  tblastx = 'tblastx'

class DbType(str, Enum):
  cdna = 'cdna'
  dna = 'dna'
  protein = 'pep'

class BlastParams(BaseModel, extra=Extra.allow):
  email: str | None = 'blast2020@ebi.ac.uk'
  title: str | None = ''
  program: Program
  database: DbType

class GenomeId(str, Enum):
  celegans = 'caenorhabditis_elegans_GCA_000002985_3'
  plasmodium = 'plasmodium_falciparum_GCA_000002765_2'
  ecoli = 'escherichia_coli_str_k_12_substr_mg1655_gca_000005845_GCA_000005845_2'
  yeast = 'saccharomyces_cerevisiae_GCA_000146045_2'
  human37 = 'homo_sapiens_GCA_000001405_14'
  wheat = 'triticum_aestivum_GCA_900519105_1'
  human38 = 'homo_sapiens_GCA_000001405_28'

class QuerySequence(BaseModel):
  id: int
  value: str

class BlastJob(BaseModel):
  genomeIds: list[GenomeId]
  querySequences: list[QuerySequence]
  parameters: BlastParams

# Infer the target species index file for BLAST payload
def get_blast_filename(genome_id: str, db_type: str) -> str:
  suffix = f'{db_type}.toplevel' if db_type == 'dna' else f'{db_type}.all'
  return f'ensembl/{genome_id}/{db_type}/{genome_id}.{suffix}'

# Submit a BLAST job to JD. Returns a resolvable for fetching the response.
async def run_blast(query: dict, blast_payload: dict, genome_id: str, db_type: str) -> dict:
  blast_payload['sequence'] = query['value']
  blast_payload['database'] = get_blast_filename(genome_id, db_type)
  url = 'http://wwwdev.ebi.ac.uk/Tools/services/rest/ncbiblast/run'
  async with app.client_session.post(url, data = blast_payload) as resp:
    response = await resp.text()
    if resp.status == 200:
      return {'sequence_id': query['id'], 'genome_id': genome_id, 'job_id': response}
    else:
      # Strip xhtml tags from the response message
      response = re.sub('<.*?>|\n+', '', response)
      return {'sequence_id': query['id'], 'genome_id': genome_id, 'error': response}

# Endpoint for submitting BLAST jobs to jDispatcher
@app.post('/blast/job')
async def submit_blast(payload: BlastJob) -> dict:
  payload = jsonable_encoder(payload)
  db_type = payload['parameters']['database']
  blast_jobs = []
  # Submit multiple concurrent BLAST jobs (one for each query seq. / target species combination)
  for query in payload['querySequences']:
    for genome_id in payload['genomeIds']:
      blast_jobs.append(run_blast(query, payload['parameters'], genome_id, db_type))
  job_results = await asyncio.gather(*blast_jobs)
  return {'submissionId': secrets.token_urlsafe(16), 'jobs': job_results}
  

# Proxy for JD BLAST REST API endpoints (/status/:id, /result/:id/:type)
@app.get("/blast/jobs/{action}/{params:path}")
async def blast_proxy(action: str, params: str, response: Response) -> dict:
  url = f"http://wwwdev.ebi.ac.uk/Tools/services/rest/ncbiblast/{action}/{params}"
  async with app.client_session.get(url) as resp:
    response.status_code = resp.status
    if params.endswith('json'):
      content = await resp.json()
    else:
      content = await resp.text()
    if resp.status == 200:
      return {action: content}
    else:
      if content:
        content = re.sub('<.*?>|\n+', '', content)
      else:
        content = f"Invalid JD endpoint: /{action}/{params}"
      return {'error': content}
