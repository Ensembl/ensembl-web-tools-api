from fastapi import FastAPI, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Extra
from enum import Enum
import json
from aiohttp import ClientSession

app = FastAPI()

# Setup persistent session for making http requests
@app.on_event('startup')
async def startup_event():
  app.client_session = ClientSession()

@app.on_event('shutdown')
async def shutdown_event():
  await app.client_session.close()

# Endpoint for serving the BLAST config
@app.get('/blast/config')
async def serve_config():
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

# Endpoint for submitting a BLAST job to jDispatcher
@app.post('/blast/job')
async def run_blast(incoming: BlastJob, response: Response):
  payload = jsonable_encoder(incoming)
  # Infer target db filepath from prevalidated input
  genomeid = payload['genomeIds'][0]
  dbtype = payload['parameters']['database']
  suffix = f'{dbtype}.toplevel' if dbtype == 'dna' else f'{dbtype}.all'
  dbfile = f'ensembl/{genomeid}/{dbtype}/{genomeid}.{suffix}'
  payload['parameters']['database'] = dbfile
  payload['parameters']['sequence'] = payload['querySequences'][0]
  # Submit the job
  url = 'http://wwwdev.ebi.ac.uk/Tools/services/rest/ncbiblast/run'
  async with app.client_session.post(url, data = payload['parameters']) as resp:
    content = await resp.text()
    if resp.status == 200:
      return {'jobIds': [content]}
    else:
      response.status_code = resp.status
      return {'message': content}

# General proxy for jDispatcher Blast REST API endpoints
@app.get("/blast/{path:path}")
async def blast_proxy(path: str, response: Response):
  url = f"http://wwwdev.ebi.ac.uk/Tools/services/rest/ncbiblast/{path}"
  async with app.client_session.get(url) as resp:
    response.status_code = resp.status
    return await resp.text()

