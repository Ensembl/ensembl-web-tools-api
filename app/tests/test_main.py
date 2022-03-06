from fastapi.testclient import TestClient
import json
import pytest
from ..main import app
from ..main import process_job_payload

# Test config endpoint
def test_read_config():
	client = TestClient(app)
	with open('data/blast_config.json') as f:
		config = json.load(f)
	response = client.get('/blast/config')
	assert response.status_code == 200
	assert response.json() == config

# Load example job payload
@pytest.fixture
def job_payload():
	with open('app/tests/job_payload.json') as f:
		return json.load(f)


# Test job payload processing
def test_process_job_payload(job_payload):
	job = process_job_payload(job_payload)
	assert job['sequence'] == job_payload['querySequences'][0]

# Test job submission with correct payload
def test_blast_job(job_payload):
	with TestClient(app) as client: #include @startup hook
		response = client.post('/blast/job', json=job_payload)
		assert response.status_code == 200
		resp_json = response.json()
		assert 'jobIds' in resp_json
		assert resp_json['jobIds'][0].startswith('ncbiblast-')

# Test job submission with payload validation error
def test_blast_job_data_error(job_payload):
	with TestClient(app) as client:
		del job_payload['querySequences']
		response = client.post('/blast/job', json=job_payload)
		assert response.status_code == 422
		assert 'detail' in response.json()

# Test job submission with jDispatcher error
def test_blast_job_jd_error(job_payload):
	with TestClient(app) as client:
		#'stype'='dna' is incompatible with 'program'='blastp'
		job_payload['parameters']['stype'] = 'dna'
		response = client.post('/blast/job', json=job_payload)
		assert response.status_code == 400
		assert 'message' in response.json()

# Test jDispatcher proxy endpoint
def test_blast_proxy():
	with TestClient(app) as client:
		response = client.get('/blast/parameters')
		assert response.status_code == 200
		assert 'parameters' in response.json()