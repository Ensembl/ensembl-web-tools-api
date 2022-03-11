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

class GenomeId(str, Enum):
  celegans = 'caenorhabditis_elegans_GCA_000002985_3'
  plasmodium = 'plasmodium_falciparum_GCA_000002765_2'
  ecoli = 'escherichia_coli_str_k_12_substr_mg1655_gca_000005845_GCA_000005845_2'
  yeast = 'saccharomyces_cerevisiae_GCA_000146045_2'
  human37 = 'homo_sapiens_GCA_000001405_14'
  wheat = 'triticum_aestivum_GCA_900519105_1'
  human38 = 'homo_sapiens_GCA_000001405_28'

class BlastParams(BaseModel, extra=Extra.allow):
  email: str | None = 'blast2020@ebi.ac.uk'
  title: str | None = ''
  program: Program
  database: DbType

class BlastJob(BaseModel):
  genomeIds: list[GenomeId]
  querySequences: list[str]
  parameters: BlastParams

# Process BLAST job submission payload
def process_blast_payload(payload) -> tuple([dict, list]):
  # Input payload conforms to BlastJob datamodel
  dbtype = payload['parameters']['database']
  suffix = f'{dbtype}.toplevel' if dbtype == 'dna' else f'{dbtype}.all'
  dbfiles = []
  # Infer filepaths for target databases
  for genomeid in payload['genomeIds']:
    dbfiles.append(f'ensembl/{genomeid}/{dbtype}/{genomeid}.{suffix}')
  payload['parameters']['database'] = dbfiles
  return (payload['parameters'], payload['querySequences'])

async def run_blast(query_seq, params) -> dict:
  params['sequence'] = query_seq
  url = 'http://wwwdev.ebi.ac.uk/Tools/services/rest/ncbiblast/run'
  async with app.client_session.post(url, data = params) as resp:
    content = await resp.text()
    if resp.status == 200:
      return {'jobId': content}
    else:
      # Strip xhtml tags from the response message
      content = re.sub('<.*?>|\n+', '', content)
      return {'error': content}

# Endpoint for submitting a BLAST job to jDispatcher
@app.post('/blast/job')
async def submit_blast(payload: BlastJob) -> dict:
  params, sequences = process_blast_payload(jsonable_encoder(payload))
  # Submit concurrent BLAST jobs (one for each query sequence)
  blast_tasks = [run_blast(seq, params) for seq in sequences]
  jobs = await asyncio.gather(*blast_tasks)
  return {'submissionId': secrets.token_urlsafe(16), 'jobs': jobs}
  

# Proxy for JD BLAST REST API endpoints (/status/:id, /result/:id/:type)
@app.get("/blast/jobs/{action}/{params:path}")
async def blast_proxy(action: str, params: str, response: Response) -> dict:
  url = f"http://wwwdev.ebi.ac.uk/Tools/services/rest/ncbiblast/{action}/{params}"
  async with app.client_session.get(url) as resp:
    response.status_code = resp.status
    content = await resp.text()
    content = re.sub('<.*?>|\n+', '', content)
    if resp.status == 200:
      return {action: content}
    else:
      if not content:
        content = f"Invalid JD endpoint: /{action}/{params}"
      return {'error': content}
