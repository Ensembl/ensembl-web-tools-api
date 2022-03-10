from fastapi.testclient import TestClient
import json
import pytest
from ..main import app
from ..main import process_blast_payload

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


# Test job payload processing
def test_process_blast_payload(blast_payload):
	params, sequences = process_blast_payload(blast_payload)
	assert len(params['database']) == len(blast_payload['genomeIds'])
	assert blast_payload['genomeIds'][0] in params['database'][0]
	assert sequences == blast_payload['querySequences']

# Test job submission with correct payload
def test_blast_job(blast_payload):
	with TestClient(app) as client: #include @startup hook
		# Add data for multi-job submission
		blast_payload['genomeIds'].append('plasmodium_falciparum_GCA_000002765_2')
		blast_payload['querySequences'].append('MPIGSKERPTFKTRCNKADLGPI')
		response = client.post('/blast/job', json=blast_payload)
		assert response.status_code == 200
		resp = response.json()
		assert 'submissionId' in resp
		assert 'jobs' in resp
		assert len(resp['jobs']) == len(blast_payload['querySequences'])
		assert 'jobId' in resp['jobs'][0]
		assert resp['jobs'][0]['jobId'].startswith('ncbiblast-')

# Test job submission with payload validation error
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
		assert 'error' in response.json()['jobs'][0]

# Test jDispatcher BLAST proxy endpoint
def test_blast_proxy_success():
	with TestClient(app) as client:
		response = client.get('/blast/jobs/parameters')
		assert response.status_code == 200
		assert 'parameters' in response.json()

# Test JD proxy error response
def test_blast_proxy_error():
	with TestClient(app) as client:
		response = client.get('/blast/jobs/status/invalid-id')
		assert response.status_code == 406
		assert 'error' in response.json()

# Test invalid endpoint error response
def test_404_error():
	with TestClient(app) as client:
		response = client.get('/blast/invalid_path')
		assert response.status_code == 404
		assert response.json() == {'error': 'Invalid endpoint'}