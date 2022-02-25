## Tools API endpoint.

A FastAPI app for providing the tools backend for Ensembl 2020 client.

### Quick Start

1. Build the container: `docker build -t tools-api .`
2. Launch the app: `docker run --name tools-api -p 80:8013 tools-api`
3. See the OpenAPI docs for usage: `http://localhost/docs`