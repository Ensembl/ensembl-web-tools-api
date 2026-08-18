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
TRUST_ENV: bool = config("TRUST_ENV", cast=bool, default=True)
PROJECT_NAME: str = config("PROJECT_NAME", default="Ensembl Web Tools API")
ALLOWED_HOSTS: list[str] = config(
    "ALLOWED_HOSTS",
    cast=CommaSeparatedStrings,
    default="*",
)
# In the container the data dir is mounted at /data; for local dev fall back to
# the repo's own data/ directory so the app boots without that mount.
import os as _os

_blast_config_path = "/data/blast_config.json"
if not _os.path.exists(_blast_config_path):
    _blast_config_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "data", "blast_config.json"
    )
with open(_blast_config_path) as f:
    BLAST_CONFIG = json.load(f)


# logging configuration
logging.basicConfig(level=logging.DEBUG)
LOGGING_LEVEL = logging.DEBUG if DEBUG else logging.INFO
LOGGERS = ("uvicorn.asgi", "uvicorn.access")
logging.getLogger().handlers = [InterceptHandler()]
for logger_name in LOGGERS:
    logging_logger = logging.getLogger(logger_name)
    logging_logger.handlers = [InterceptHandler(level=LOGGING_LEVEL)]

logger.configure(handlers=[{"sink": sys.stderr, "level": LOGGING_LEVEL}])

# Nextflow configuration. Deployment supplies these values for the workflow
# service and its shared work directory.
NF_TOKEN = config("NF_TOKEN", default="")
NF_COMPUTE_ENV_ID = config("NF_COMPUTE_ENV_ID", default="")
NF_PIPELINE_URL = config("NF_PIPELINE_URL", default="")
NF_WORK_DIR = config("NF_WORK_DIR", default="")
SEQERA_API = config("SEQERA_API", default="")
NF_WORKSPACE_ID = config("NF_WORKSPACE_ID", default="")

WEB_METADATA_API = config(
    "WEB_METADATA_API", default="https://www.ensembl.org/api/metadata/"
)
VEP_SUPPORT_PATH = config("VEP_SUPPORT_PATH", default="/tmpdir")
VEP_PLUGIN_DATA_PATH = _os.path.join(VEP_SUPPORT_PATH, "vep-plugins-data")
