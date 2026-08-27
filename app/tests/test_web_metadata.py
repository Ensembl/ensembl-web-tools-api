import asyncio
import threading

from vep.utils import web_metadata


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_get_vep_support_location_uses_metadata_base(monkeypatch):
    requested_urls = []
    monkeypatch.setattr(web_metadata, "WEB_METADATA_API", "https://ensembl.org/api/metadata/")
    monkeypatch.setattr(web_metadata, "VEP_SUPPORT_PATH", "/support")
    monkeypatch.setattr(
        web_metadata.requests,
        "get",
        lambda url, **kwargs: requested_urls.append(url)
        or _FakeResponse({"faa_location": "GCA_000001405.29/genome.fa", "gff_location": "GCA_000001405.29/genome.gff"}),
    )

    assert web_metadata.get_vep_support_location("genome-id") == {
        "faa_location": "/support/GCA_000001405.29/genome.fa",
        "gff_location": "/support/GCA_000001405.29/genome.gff",
    }
    assert requested_urls == [
        "https://ensembl.org/api/metadata/genome/genome-id/vep/file_paths"
    ]


def test_get_genome_genebuild_uses_metadata_base(monkeypatch):
    requested_urls = []
    monkeypatch.setattr(web_metadata, "WEB_METADATA_API", "https://ensembl.org/api/metadata/")
    monkeypatch.setattr(
        web_metadata.requests,
        "get",
        lambda url, **kwargs: requested_urls.append(url)
        or _FakeResponse(
            {
                "attributes": [
                    {"name": "genebuild.provider_name", "value": "GENCODE"},
                    {"name": "genebuild.provider_version", "value": "50"},
                ]
            }
        ),
    )

    assert asyncio.run(web_metadata.get_genome_genebuild("genome-id")) == {
        "genebuild.provider_name": "GENCODE",
        "genebuild.provider_version": "50",
    }
    assert requested_urls == [
        "https://ensembl.org/api/metadata/genome/genome-id/dataset/genebuild/attributes?"
        "attribute_names=genebuild.provider_name&"
        "attribute_names=genebuild.provider_version&"
        "attribute_names=genebuild.last_geneset_update"
    ]


def test_get_genome_explain_uses_metadata_base_timeout_and_threadpool(monkeypatch):
    requested_calls = []
    loop_thread = {}
    payload = {
        "species_taxonomy_id": "9606",
        "assembly": {"name": "GRCh38.p14"},
    }

    monkeypatch.setattr(web_metadata, "WEB_METADATA_API", "https://ensembl.org/api/metadata/")
    monkeypatch.setattr(
        web_metadata.requests,
        "get",
        lambda url, **kwargs: requested_calls.append(
            {"url": url, "kwargs": kwargs, "thread_id": threading.get_ident()}
        ) or _FakeResponse(payload),
    )

    async def run():
        loop_thread["id"] = threading.get_ident()
        return await web_metadata.get_genome_explain("genome-id")

    assert asyncio.run(run()) == payload
    assert len(requested_calls) == 1
    call = requested_calls[0]
    assert call["url"] == "https://ensembl.org/api/metadata/genome/genome-id/explain"
    assert call["kwargs"] == {"timeout": web_metadata.METADATA_TIMEOUT}
    assert call["thread_id"] != loop_thread["id"]
