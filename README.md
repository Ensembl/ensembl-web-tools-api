## Tools API

A FastAPI app providing the tools backend microservice for Ensembl 2020 client.

### Endpoints

- /api/tools/blast/config
- /api/tools/blast/job
- /api/tools/blast/<jd_endpoint>

### Setup

With Docker:
```
docker build -t tools-api .
docker run --name tools-api -p 80:8013 tools-api
```
Directly:
```
pip3 install --no-cache-dir -r requirements.txt
uvicorn app.main:app --proxy-headers --host 0.0.0.0 --port 80
```
### Usage

See the documentation for usage: `http://localhost/docs`

### Deployment

The service/ingress templates in `k8s` directory root are stored in `ensembl-k8s-manifests` repo and used for integration to Ensembl 2020 review apps CI/CD pipeline in `ensembl-client` repo. Rest of the configuration files (in `base` and `overlays` subdirs) are used to deploy updates in Tools API (see `.gitlab-ci.yml`).