from fastapi.testclient import TestClient
import json
import pytest
from ..main import app
from ..main import get_blast_filename

# Test config endpoint
def test_read_config():
	client = TestClient(app)
	with open('data/blast_config.json') as f:
		config = json.load(f)
	response = client.get('/blast/config')
	assert response.status_code == 200
	assert response.json() == config

# Load example BLAST job payload
@pytest.fixture
def blast_payload():
	with open('app/tests/blast_payload.json') as f:
		return json.load(f)

# Test BLAST index filename inference
def test_get_blast_filename(blast_payload):
	genome_id = blast_payload['genomeIds'][0]
	db_type = 'pep'
	filename = get_blast_filename(genome_id, db_type)
	assert filename == f'ensembl/{genome_id}/{db_type}/{genome_id}.{db_type}.all'
	db_type = 'dna'
	filename = get_blast_filename(genome_id, db_type)
	assert filename.endswith(f'{db_type}.toplevel') 

# Test single BLAST job submission with a valid payload
def test_blast_job(blast_payload):
	with TestClient(app) as client: #include @startup hook
		response = client.post('/blast/job', json=blast_payload)
		assert response.status_code == 200
		resp = response.json()
		assert 'submissionId' in resp
		assert 'jobs' in resp
		assert len(resp['jobs']) == 1
		job = resp['jobs'][0]
		assert 'sequence_id' in job
		assert 'genome_id' in job
		assert 'job_id' in job
		assert job['job_id'].startswith('ncbiblast-')
		assert 'sequence_id' in job and job['sequence_id'] == 1

# Test multiple BLAST job submission with a valid payload
def test_blast_job(blast_payload):
	with TestClient(app) as client:
		blast_payload['genomeIds'].append('plasmodium_falciparum_GCA_000002765_2')
		blast_payload['querySequences'].append({'id': 2, 'value': 'MPIGSKERPTFKTRCNKADLGPI'})
		response = client.post('/blast/job', json=blast_payload)
		assert response.status_code == 200
		resp = response.json()
		assert 'submissionId' in resp
		assert 'jobs' in resp
		assert len(resp['jobs']) == 4
		job = resp['jobs'][3]
		assert 'sequence_id' in job
		assert 'genome_id' in job
		assert 'job_id' in job
		assert job['job_id'].startswith('ncbiblast-')
		assert 'sequence_id' in job and job['sequence_id'] == 2

# Test incoming payload validation for BLAST job submission
def test_blast_job_data_error(blast_payload):
	with TestClient(app) as client:
		del blast_payload['querySequences']
		response = client.post('/blast/job', json=blast_payload)
		assert response.status_code == 422
		resp = response.json()
		assert 'error' in resp
		assert 'validation error' in resp['error']

# Test job submission with jDispatcher error
def test_blast_job_jd_error(blast_payload):
	with TestClient(app) as client:
		# 'stype'='dna' is incompatible with 'program'='blastp'
		blast_payload['parameters']['stype'] = 'dna'
		response = client.post('/blast/job', json=blast_payload)
		assert response.status_code == 200
		resp = response.json()
		assert 'jobs' in resp
		assert len(resp['jobs']) == 1
		job = resp['jobs'][0]
		assert 'sequence_id' in job
		assert 'genome_id' in job
		assert 'error' in job

# Test jDispatcher BLAST proxy endpoint
def test_blast_proxy_success():
	with TestClient(app) as client:
		response = client.get('/blast/jobs/status/ncbiblast-12345')
		assert response.status_code == 200
		assert response.json() == {'status': 'NOT_FOUND'}

# Test JD proxy error response
def test_blast_proxy_error():
	with TestClient(app) as client:
		response = client.get('/blast/jobs/na/na')
		assert response.status_code == 404
		assert 'error' in response.json()

# Test invalid endpoint error response
def test_404_error():
	with TestClient(app) as client:
		response = client.get('/blast/invalid_path')
		assert response.status_code == 404
		assert response.json() == {'error': 'Invalid endpoint'}