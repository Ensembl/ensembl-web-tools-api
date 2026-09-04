import os
import requests
from starlette.concurrency import run_in_threadpool

from vep.models.submission_form import GenomeAnnotationProvider

from core.config import WEB_METADATA_API, VEP_SUPPORT_PATH

METADATA_TIMEOUT = (5.0, 15.0)


def get_vep_support_location(genome_id: str) -> dict:
    try:
        response = requests.get(
            WEB_METADATA_API
            + "genome/"
            + genome_id
            + "/vep/file_paths", timeout=METADATA_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        return {
            "faa_location": f"{VEP_SUPPORT_PATH}/{data['faa_location']}",
            "gff_location": f"{VEP_SUPPORT_PATH}/{data['gff_location']}"
        }
    except KeyError as e:
        e.args = (
            f"get_vep_support_location(): unexpected metadata API payload for {genome_id}:",
            *e.args,
        )
        raise
    except requests.HTTPError as e:
        e.args = (
            f"get_vep_support_location(): error response from metadata API for {genome_id}:",
            *e.args,
        )
        raise
    except Exception as e:
        e.args = (f"{type(e).__name__} in get_vep_support_location():", *e.args)
        raise


async def get_genome_genebuild(genome_id: str) -> GenomeAnnotationProvider:
    return await run_in_threadpool(_get_genome_genebuild, genome_id)


async def get_genome_assembly_name(genome_id: str) -> str:
    """Resolve a genome UUID to the canonical assembly name used by VEP."""
    return await run_in_threadpool(_get_genome_assembly_name, genome_id)


def _get_genome_assembly_name(genome_id: str) -> str:
    genome = _get_genome_explain(genome_id)
    assembly_name = (genome.get("assembly") or {}).get("name")
    if not isinstance(assembly_name, str) or not assembly_name:
        raise ValueError(
            "get_genome_assembly_name(): unexpected metadata API explain payload "
            f"for {genome_id}: missing assembly.name"
        )
    return assembly_name


def _get_genome_explain(genome_id: str) -> dict:
    try:
        response = requests.get(
            WEB_METADATA_API + "genome/" + genome_id + "/explain",
            timeout=METADATA_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as e:
        e.args = (
            f"get_genome_explain(): error response from metadata API for {genome_id}:",
            *e.args,
        )
        raise
    except Exception as e:
        e.args = (f"{type(e).__name__} in get_genome_explain():", *e.args)
        raise


def _get_genome_genebuild(genome_id: str) -> GenomeAnnotationProvider:
    try:
        response = requests.get(
            WEB_METADATA_API
            + "genome/"
            + genome_id
            + "/dataset/genebuild/attributes?"
            + "attribute_names=genebuild.provider_name&"
            + "attribute_names=genebuild.provider_version&"
            + "attribute_names=genebuild.last_geneset_update",
            timeout=METADATA_TIMEOUT,
        )
        response.raise_for_status()
        attributes = {}
        for attribute in response.json()["attributes"]:
            name = attribute["name"]
            value = attribute["value"]
            attributes[name] = value
        return attributes
    except KeyError as e:
        e.args = (
            f"get_genome_genebuild(): unexpected metadata API payload for {genome_id}:",
            *e.args,
        )
        raise
    except requests.HTTPError as e:
        e.args = (
            f"get_genome_genebuild(): error response from metadata API for {genome_id}:",
            *e.args,
        )
        raise
    except Exception as e:
        e.args = (f"{type(e).__name__} in get_genome_genebuild():", *e.args)
        raise
