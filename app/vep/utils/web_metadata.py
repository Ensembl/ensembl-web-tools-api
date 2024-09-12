import requests

import logging
from requests import HTTPError

from core.config import WEB_METADATA_API, VEP_SUPPORT_PATH
from core.logging import InterceptHandler

logging.getLogger().handlers = [InterceptHandler()]


def get_vep_support_location(genome_id):
    try:
        response = requests.get(
            WEB_METADATA_API
            + "genome/"
            + genome_id
            + "/dataset/genebuild/attributes?attribute_names=vep.bgz_location"
        )
        response.raise_for_status()
        return VEP_SUPPORT_PATH + response.json()["attributes"].pop()["value"]
    except HTTPError as http_error:
        logging.error(http_error)
        raise HTTPError
    except Exception as e:
        logging.error(e)
