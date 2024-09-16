"""
See the NOTICE file distributed with this work for additional information
regarding copyright ownership.


Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import logging
import sys

from loguru import logger
from starlette.config import Config
from starlette.datastructures import CommaSeparatedStrings

from .logging import InterceptHandler
import json

VERSION = "0.0.0"
API_PREFIX = "/api/tools"

config = Config(".env")
DEBUG: bool = config("DEBUG", cast=bool, default=False)
PROJECT_NAME: str = config("PROJECT_NAME", default="Ensembl Web Tools API")
ALLOWED_HOSTS: list[str] = config(
    "ALLOWED_HOSTS",
    cast=CommaSeparatedStrings,
    default="*",
)
with open("/data/blast_config.json") as f:
    BLAST_CONFIG = json.load(f)

# logging configuration
LOGGING_LEVEL = logging.DEBUG if DEBUG else logging.INFO
LOGGERS = ("uvicorn.asgi", "uvicorn.access")

log = logging.getLogger("gunicorn.access")

logging.getLogger().handlers = [InterceptHandler()]
for logger_name in LOGGERS:
    logging_logger = logging.getLogger(logger_name)
    logging_logger.handlers = [InterceptHandler(level=LOGGING_LEVEL)]

logger.configure(handlers=[{"sink": sys.stderr, "level": LOGGING_LEVEL}])

logging.info(BLAST_CONFIG)

# Nextflow Configurations
NF_TOKEN = config("NF_TOKEN")
NF_COMPUTE_ENV_ID = config("NF_COMPUTE_ENV_ID")
NF_PIPELINE_URL = config("NF_PIPELINE_URL")
NF_WORK_DIR = config("NF_WORK_DIR")
SEQERA_API = config("SEQERA_API")
NF_WORKSPACE_ID = config("NF_WORKSPACE_ID")

UPLOAD_DIRECTORY = config("UPLOAD_DIRECTORY", default="/tmpdir")
WEB_METADATA_API = config(
    "WEB_METADATA_API", default="https://beta.ensembl.org/api/metadata/"
)
VEP_SUPPORT_PATH = config("VEP_SUPPORT_PATH", default="/tmpdir")