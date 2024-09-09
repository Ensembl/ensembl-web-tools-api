from loguru import logger
import requests
from typing import List
from core.config import ENSEMBL_WEB_METADATA_API
from vep.models.client_model import GenomeAnnotationProvider

async def get_genome_metadata(genome_id: str) -> GenomeAnnotationProvider:

    try:
      session = requests.Session()
      with session.get(
          url=f"{ENSEMBL_WEB_METADATA_API}/genome/{genome_id}/details"
      ) as response:
          response.raise_for_status()
          metadata = response.json()
    except requests.exceptions.HTTPError as HTTPError:
      logger.error(f"HTTPError: {HTTPError}")
      return None
    except Exception as e:
      logger.exception(e)
      return None

    provider = metadata["annotation_provider"]
    version = metadata["annotation_version"]
    return GenomeAnnotationProvider(annotation_provider_name = provider["name"], annotation_version = version)

