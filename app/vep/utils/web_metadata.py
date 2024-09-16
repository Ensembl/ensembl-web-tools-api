from loguru import logger
import requests
from requests import HTTPError
from typing import List
from core.config import WEB_METADATA_API, VEP_SUPPORT_PATH
from vep.models.client_model import GenomeAnnotationProvider
import logging
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

async def get_genome_metadata(genome_id: str) -> GenomeAnnotationProvider:
    try:
        response = requests.get(
            WEB_METADATA_API
            + "genome/"
            + genome_id
            + "/dataset/genebuild/attributes?"
            + "attribute_names=genebuild.provider_name&"
            + "attribute_names=genebuild.display_version&"
            + "attribute_names=genebuild.last_geneset_update"
        )
        response.raise_for_status()
        attributes = {}
        for attribute in response.json()['attributes']:
            name = attribute['name']
            value = attribute['value']
            attributes[name] = value
        return attributes
    except HTTPError as http_error:
        logging.error(http_error)
        raise HTTPError
    except Exception as e:
        logging.error(e)
