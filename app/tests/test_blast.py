from fastapi.testclient import TestClient
import json
import pytest
from ..app.blast.blast import get_db_path
from ..app.main import app

# Test config endpoint
def test_read_config():
	with TestClient(app) as client: #include @startup hook
		with open('./data/blast_config.json') as f:
			config = json.load(f)
		response = client.get('/blast/config')
		assert response.status_code == 200
		assert response.json() == config

# Load example BLAST job payload
@pytest.fixture
def blast_payload():
	with open('tests/blast_payload.json') as f:
		return json.load(f)

# Test BLAST database path inference
def test_get_db_path(blast_payload):
	genome_id = blast_payload['genome_ids'][0]
	filename = get_db_path(genome_id, 'dna_sm')
	assert filename == f'ensembl/{genome_id}/softmasked'
	filename = get_db_path(genome_id, 'pep')
	assert filename.endswith('pep')

# Test single BLAST job submission with a valid payload
def test_blast_job(blast_payload):
	with TestClient(app) as client:
		response = client.post('/blast/job', json=blast_payload)
		assert response.status_code == 200
		resp = response.json()
		assert 'submission_id' in resp
		assert 'jobs' in resp
		assert len(resp['jobs']) == 1
		job = resp['jobs'][0]
		assert 'sequence_id' in job
		assert 'genome_id' in job
		assert 'job_id' in job
		assert job['job_id'].startswith('ncbiblast')
		assert 'sequence_id' in job and job['sequence_id'] == 1

# Test multiple BLAST job submission with a valid payload
def test_blast_jobs(blast_payload):
	with TestClient(app) as client:
		blast_payload['genome_ids'].append(blast_payload['genome_ids'][0])
		blast_payload['query_sequences'].append({'id': 2, 'value': 'MPIGSKERPTFKTRCNKADLGPI'})
		response = client.post('/blast/job', json=blast_payload)
		assert response.status_code == 200
		resp = response.json()
		assert 'submission_id' in resp
		assert 'jobs' in resp
		assert len(resp['jobs']) == 4
		job = resp['jobs'][3]
		assert 'genome_id' in job and job['genome_id'] == blast_payload['genome_ids'][0]
		assert 'job_id' in job and job['job_id'].startswith('ncbiblast')
		assert 'sequence_id' in job and job['sequence_id'] == 2

# Test incoming payload validation for BLAST job submission
def test_blast_job_data_error(blast_payload):
	with TestClient(app) as client:
		del blast_payload['query_sequences']
		response = client.post('/blast/job', json=blast_payload)
		assert response.status_code == 422
		resp = response.json()
		assert 'error' in resp
		assert 'Field required' in resp['error']

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

# Test BLAST job status endpoint
def test_blast_job_status():
	with TestClient(app) as client:
		response = client.get('/blast/jobs/status/ncbiblast_ensembl-12345')
		assert response.status_code == 200
		assert 'status' in response.json()

# Test multiple jobs status endpoint
# Example job id: ncbiblast_ensembl-R20220907-111749-0693-28451168-np2
def test_blast_job_statuses():
	with TestClient(app) as client:
		job_ids = {'job_ids': ['ncbiblast-1234', 'ncbiblast-5678']}
		response = client.post('/blast/jobs/status', json=job_ids)
		assert response.status_code == 200
		resp = response.json()
		assert 'statuses' in resp
		assert len(resp['statuses']) == 2
		assert 'job_id' in resp['statuses'][0]
		assert 'status' in resp['statuses'][0]

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
