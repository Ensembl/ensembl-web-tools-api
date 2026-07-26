"""Resolve the form's quick-select species presets against the metadata API.

The frontend used to ship these as hardcoded genome UUIDs. Those are release
-scoped: the same assembly gets a new UUID each integrated release, so a
committed list silently rots — and a retired UUID makes the metadata lookup
return 500, which the form surfaces as a blank options section.

Only the assembly accessions are fixed here. Everything else — UUID, names,
release — comes from the metadata API at request time.

Resolution rule, agreed with the metadata team: the preset is the genome for
that accession in the release where `is_current` is true *and* the type is
`integrated`. Both halves matter:

  * `integrated` alone is not enough — several releases can be current at once
    (there is normally a newer `partial` alongside the integrated one), and a
    preset must never silently point a job at a partial release.
  * `is_current` alone is not enough, for the same reason.

Nothing keys off the `archive` type: it is still being rolled out, so the rule
is written positively and ignores it entirely.

`/genome/{accession}/explain` is what does the work — it takes an accession
directly and returns the integrated genome. Note that `/genomeid`, which looks
like the obvious choice, picks by highest release_version and so returns the
*partial* genome; it is deliberately not used here.
"""

import logging

import requests
from starlette.concurrency import run_in_threadpool

from core.config import GENOME_METADATA_API

# (connect, read). Local rather than from core.config so this does not collide
# with the parked timeouts branch (#60), which introduces a shared constant for
# every outbound call; fold this into it when that lands.
METADATA_TIMEOUT = (5.0, 15.0)

# Assembly accessions only. Everything else is resolved; see the module
# docstring for why nothing genome-specific is committed here.
PRESET_ACCESSIONS: list[str] = [
    "GCA_000001405.29",  # Human   GRCh38.p14
    "GCA_000001405.14",  # Human   GRCh37.p13
    "GCA_009914755.4",   # Human   T2T-CHM13v2.0
    "GCA_000001635.9",   # Mouse   GRCm39
]

INTEGRATED = "integrated"


def _get(path: str):
    response = requests.get(
        f"{GENOME_METADATA_API}{path}", timeout=METADATA_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def _current_integrated_release_name(releases: list[dict]) -> str | None:
    """The one release that is both current and integrated.

    There is normally also a current `partial` release with a *later* name, so
    this cannot be "the newest current release".
    """
    for release in releases:
        if release.get("is_current") and release.get("type") == INTEGRATED:
            return release.get("name")
    return None


def _as_preset(genome: dict) -> dict:
    """Shape a genome record the way the form's species field expects."""
    assembly = genome.get("assembly") or {}
    return {
        "genome_id": genome.get("genome_id"),
        "genome_tag": genome.get("genome_tag"),
        "common_name": genome.get("common_name"),
        "scientific_name": genome.get("scientific_name"),
        "species_taxonomy_id": genome.get("species_taxonomy_id"),
        "type": genome.get("type"),
        "is_reference": genome.get("is_reference", False),
        "assembly": {
            "accession_id": assembly.get("accession_id"),
            "name": assembly.get("name"),
        },
        "release": genome.get("release") or {},
    }


def _resolve_one(accession: str, release_name: str) -> dict | None:
    """The genome for `accession` in the current integrated release, or None.

    Returning None drops the preset from the list. A missing button is a much
    better outcome than one that runs jobs against the wrong release, and for
    these four assemblies it should not happen at all.
    """
    genome = _get(f"genome/{accession}/explain")
    release = genome.get("release") or {}
    if release.get("type") != INTEGRATED or release.get("name") != release_name:
        logging.warning(
            "species preset %s resolved to release %s/%s, not the current "
            "integrated release %s — dropping it",
            accession,
            release.get("name"),
            release.get("type"),
            release_name,
        )
        return None
    return _as_preset(genome)


def _resolve_presets() -> list[dict]:
    """Blocking. Call through `get_species_presets`."""
    release_name = _current_integrated_release_name(_get("releases"))
    if release_name is None:
        logging.error(
            "no current integrated release from the metadata API; "
            "serving no species presets"
        )
        return []

    presets = []
    for accession in PRESET_ACCESSIONS:
        try:
            preset = _resolve_one(accession, release_name)
        except Exception:
            # One unresolvable accession must not cost the user the others.
            logging.exception("could not resolve species preset %s", accession)
            continue
        if preset is not None:
            presets.append(preset)
    return presets


async def get_species_presets() -> list[dict]:
    """Presets for the form's quick-select buttons, resolved to the current
    integrated release. `requests` is synchronous, so this runs off the event
    loop rather than stalling every other in-flight request."""
    return await run_in_threadpool(_resolve_presets)
