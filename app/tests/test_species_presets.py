"""Tests for resolving the form's quick-select species presets.

The rule under test is narrow but load-bearing: a preset is the genome for its
accession in the release that is BOTH `is_current` and `integrated`. The live
API really does return a current `partial` release alongside the integrated
one, with a *later* name, so "newest current release" and "the integrated one"
are different answers — and picking the partial would quietly run jobs against
the wrong annotation.
"""

import asyncio
import threading

import pytest

from vep.utils import species_presets


# Shaped like the live /releases payload: two entries are current, and the
# partial one has the later name.
RELEASES = [
    {"name": "2024-11", "type": "archive", "is_current": False},
    {"name": "2025-02", "type": "integrated", "is_current": True},
    {"name": "2026-07-13", "type": "partial", "is_current": True},
]

INTEGRATED_GENOME = {
    "genome_id": "a7335667-93e7-11ec-a39d-005056b38ce3",
    "genome_tag": "GCA_000001405.29",
    "common_name": "Human",
    "scientific_name": "Homo sapiens",
    "species_taxonomy_id": "9606",
    "type": None,
    "is_reference": True,
    "assembly": {"accession_id": "GCA_000001405.29", "name": "GRCh38.p14"},
    "release": {"name": "2025-02", "type": "integrated"},
}

PARTIAL_GENOME = {
    **INTEGRATED_GENOME,
    "genome_id": "59871324-7803-4234-856e-2a2bd96d7b3c",
    "release": {"name": "2026-07-13", "type": "partial"},
}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_api(explain_payloads, releases=RELEASES, record=None):
    """Stand in for requests.get against the metadata API."""

    def _get(url, **kwargs):
        if record is not None:
            record.append({"url": url, "kwargs": kwargs,
                           "thread_id": threading.get_ident()})
        if url.endswith("releases"):
            return _FakeResponse(releases)
        accession = url.split("/genome/")[1].split("/explain")[0]
        if accession not in explain_payloads:
            raise AssertionError(f"unexpected accession requested: {accession}")
        payload = explain_payloads[accession]
        if isinstance(payload, Exception):
            raise payload
        return _FakeResponse(payload)

    return _get


def _resolve(monkeypatch, explain_payloads, releases=RELEASES, accessions=None,
             record=None):
    monkeypatch.setattr(species_presets.requests, "get",
                        _fake_api(explain_payloads, releases, record))
    if accessions is not None:
        monkeypatch.setattr(species_presets, "PRESET_ACCESSIONS", accessions)
    return asyncio.run(species_presets.get_species_presets())


# --- the resolution rule ----------------------------------------------------


def test_resolves_to_the_current_integrated_release(monkeypatch):
    presets = _resolve(
        monkeypatch,
        {"GCA_000001405.29": INTEGRATED_GENOME},
        accessions=["GCA_000001405.29"],
    )

    assert len(presets) == 1
    assert presets[0]["genome_id"] == INTEGRATED_GENOME["genome_id"]
    assert presets[0]["release"] == {"name": "2025-02", "type": "integrated"}


def test_a_partial_release_genome_is_dropped(monkeypatch):
    """The trap: the partial release is also `is_current`, and its name sorts
    later. Taking it would run jobs against the wrong annotation."""
    presets = _resolve(
        monkeypatch,
        {"GCA_000001405.29": PARTIAL_GENOME},
        accessions=["GCA_000001405.29"],
    )

    assert presets == []


def test_integrated_but_not_the_current_release_is_dropped(monkeypatch):
    """`integrated` alone is not sufficient: an older integrated release is
    still integrated."""
    stale = {**INTEGRATED_GENOME, "release": {"name": "2024-11", "type": "integrated"}}
    presets = _resolve(
        monkeypatch, {"GCA_000001405.29": stale}, accessions=["GCA_000001405.29"]
    )

    assert presets == []


def test_no_current_integrated_release_yields_no_presets(monkeypatch):
    releases = [{"name": "2026-07-13", "type": "partial", "is_current": True}]
    presets = _resolve(
        monkeypatch,
        {"GCA_000001405.29": INTEGRATED_GENOME},
        releases=releases,
        accessions=["GCA_000001405.29"],
    )

    assert presets == []


# --- resilience -------------------------------------------------------------


def test_one_bad_accession_does_not_lose_the_others(monkeypatch):
    """A missing button is acceptable; losing the whole row is not."""
    other = {
        **INTEGRATED_GENOME,
        "genome_id": "3704ceb1-948d-11ec-a39d-005056b38ce3",
        "assembly": {"accession_id": "GCA_000001405.14", "name": "GRCh37.p13"},
    }
    presets = _resolve(
        monkeypatch,
        {
            "GCA_000001405.29": RuntimeError("metadata API is having a bad day"),
            "GCA_000001405.14": other,
        },
        accessions=["GCA_000001405.29", "GCA_000001405.14"],
    )

    assert [p["assembly"]["accession_id"] for p in presets] == ["GCA_000001405.14"]


def test_preset_order_follows_the_configured_accessions(monkeypatch):
    second = {
        **INTEGRATED_GENOME,
        "genome_id": "3704ceb1-948d-11ec-a39d-005056b38ce3",
        "assembly": {"accession_id": "GCA_000001405.14", "name": "GRCh37.p13"},
    }
    presets = _resolve(
        monkeypatch,
        {"GCA_000001405.29": INTEGRATED_GENOME, "GCA_000001405.14": second},
        accessions=["GCA_000001405.14", "GCA_000001405.29"],
    )

    assert [p["assembly"]["name"] for p in presets] == ["GRCh37.p13", "GRCh38.p14"]


# --- shape and mechanics ----------------------------------------------------


def test_preset_carries_every_field_the_species_field_needs(monkeypatch):
    presets = _resolve(
        monkeypatch,
        {"GCA_000001405.29": INTEGRATED_GENOME},
        accessions=["GCA_000001405.29"],
    )

    assert set(presets[0]) == {
        "genome_id", "genome_tag", "common_name", "scientific_name",
        "species_taxonomy_id", "type", "is_reference", "assembly", "release",
    }
    assert set(presets[0]["assembly"]) == {"accession_id", "name"}


def test_every_metadata_call_sets_a_timeout_and_runs_off_the_event_loop(monkeypatch):
    record = []
    loop_thread = {}

    monkeypatch.setattr(species_presets.requests, "get",
                        _fake_api({"GCA_000001405.29": INTEGRATED_GENOME},
                                  record=record))
    monkeypatch.setattr(species_presets, "PRESET_ACCESSIONS", ["GCA_000001405.29"])

    async def run():
        loop_thread["id"] = threading.get_ident()
        return await species_presets.get_species_presets()

    asyncio.run(run())

    assert record, "no metadata calls were made"
    for call in record:
        assert call["kwargs"].get("timeout") is not None, f"no timeout: {call['url']}"
        assert call["thread_id"] != loop_thread["id"], (
            "metadata request ran on the event-loop thread"
        )


def test_accession_is_looked_up_directly_not_by_keyword_search(monkeypatch):
    """/genomeid resolves an accession by highest release_version, which returns
    the partial genome. The explain endpoint is the one that must be used."""
    record = []
    _resolve(
        monkeypatch,
        {"GCA_000001405.29": INTEGRATED_GENOME},
        accessions=["GCA_000001405.29"],
        record=record,
    )

    urls = [c["url"] for c in record]
    assert any(u.endswith("genome/GCA_000001405.29/explain") for u in urls)
    assert not any("genomeid" in u for u in urls)


def test_requests_use_the_configured_metadata_base(monkeypatch):
    record = []
    monkeypatch.setattr(species_presets, "WEB_METADATA_API", "https://ensembl.org/api/metadata/")
    _resolve(
        monkeypatch,
        {"GCA_000001405.29": INTEGRATED_GENOME},
        accessions=["GCA_000001405.29"],
        record=record,
    )

    assert all(call["url"].startswith("https://ensembl.org/api/metadata/") for call in record)
