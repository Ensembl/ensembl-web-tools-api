import asyncio

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
        lambda url: requested_urls.append(url)
        or _FakeResponse({"faa_location": "GCA_000001405.29/genome.fa", "gff_location": "GCA_000001405.29/genome.gff"}),
    )

    assert web_metadata.get_vep_support_location("genome-id") == {
        "faa_location": "/support/GCA_000001405.29/genome.fa",
        "gff_location": "/support/GCA_000001405.29/genome.gff",
    }
    assert requested_urls == [
        "https://ensembl.org/api/metadata/genome/genome-id/vep/file_paths"
    ]


def test_get_genome_metadata_uses_metadata_base(monkeypatch):
    requested_urls = []
    monkeypatch.setattr(web_metadata, "WEB_METADATA_API", "https://ensembl.org/api/metadata/")
    monkeypatch.setattr(
        web_metadata.requests,
        "get",
        lambda url: requested_urls.append(url)
        or _FakeResponse(
            {
                "attributes": [
                    {"name": "genebuild.provider_name", "value": "GENCODE"},
                    {"name": "genebuild.provider_version", "value": "50"},
                ]
            }
        ),
    )

    assert asyncio.run(web_metadata.get_genome_metadata("genome-id")) == {
        "genebuild.provider_name": "GENCODE",
        "genebuild.provider_version": "50",
    }
    assert requested_urls == [
        "https://ensembl.org/api/metadata/genome/genome-id/dataset/genebuild/attributes?"
        "attribute_names=genebuild.provider_name&"
        "attribute_names=genebuild.provider_version&"
        "attribute_names=genebuild.last_geneset_update"
    ]
