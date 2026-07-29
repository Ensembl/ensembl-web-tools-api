"""Regenerate the ontology id -> term-name table from the EFO release.

OpenTargets reports a GWAS association's trait as a bare accession —
`EFO_0006336`, `OBA_2050068`, `GO_0036273` — with no label, so showing anything
readable needs the id -> name mapping from somewhere.

That somewhere is this script, run occasionally, rather than a runtime
dependency or a per-variant API call: the OLS lookup service would answer the
same question, but a results page can carry hundreds of accessions and we would
be asking it the same handful of questions repeatedly, on the request path.
Deriving the table once and committing it costs disk and nothing at runtime.

**One file covers every prefix we see.** EFO is a merged ontology: its release
imports OBA, GO, MONDO, HP and Orphanet terms wholesale, so a single download
resolves all of them. There is no need for a table per ontology.

The OBO is streamed and parsed line-by-line — it is never written to disk.

    PYTHONPATH=app .venv/bin/python app/vep/scripts/generate_efo_terms.py

Behind a proxy that rejects urllib (some return 403 on its default user-agent),
pipe it in instead — the parse is the same either way:

    curl -sL https://www.ebi.ac.uk/efo/efo.obo \\
      | PYTHONPATH=app .venv/bin/python app/vep/scripts/generate_efo_terms.py -

Re-run it when EFO publishes a release whose terms you want to pick up. An
accession the table has never heard of is not an error — it simply shows as
itself.
"""

import json
import sys
import urllib.request
from pathlib import Path

OBO_URL = "https://www.ebi.ac.uk/efo/efo.obo"
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "efo_terms.json"

# Which ontologies to keep out of the ~88k terms the release carries. EFO, OBA
# and GO are what dev data uses today; MONDO (disease), HP (phenotype) and
# Orphanet (rare disease) are what OpenTargets draws on besides, so they are
# included rather than waiting to be missed in production. The rest — PR
# (protein), CHEBI (chemical), NCBITaxon, UBERON and friends — describe things a
# GWAS trait is not, and account for a third of the file.
KEEP_PREFIXES = ("EFO", "OBA", "GO", "MONDO", "HP", "Orphanet")

# EFO writes a retired term's name as "obsolete_thyroid disease" (or, for 752 of
# them, "obsolete thyroid disease"). That is curation bookkeeping rather than
# part of the name, so it is stripped and the fact recorded separately.
_OBSOLETE_PREFIXES = ("obsolete_", "obsolete ")


def accession(raw_id: str) -> str | None:
    """`efo:EFO_0001645` -> `EFO_0001645`, `GO:0036273` -> `GO_0036273`.

    Ids in this release are CURIEs, and in two shapes: EFO's own carry the
    accession in the local part (`efo:EFO_0001645`), while imported terms use
    the ordinary `PREFIX:number` form. A handful are bare URLs with no
    accession to recover, and are skipped.
    """
    if raw_id.startswith("http"):
        return None
    if ":" not in raw_id:
        return raw_id
    prefix, local = raw_id.split(":", 1)
    return local if "_" in local else f"{prefix}_{local}"


def clean_name(name: str) -> str:
    """The term name without EFO's obsolete bookkeeping prefix."""
    lowered = name.lower()
    for marker in _OBSOLETE_PREFIXES:
        if lowered.startswith(marker):
            return name[len(marker) :]
    return name


def release_version(data_version: str) -> str:
    """`http://www.ebi.ac.uk/efo/releases/v3.92.0/efo.owl` -> `3.92.0`.

    Anything that is not that shape is recorded verbatim rather than guessed at
    — a wrong version is worse than an unfamiliar one.
    """
    for part in data_version.split("/"):
        if part.startswith("v") and part[1:2].isdigit():
            return part[1:]
    return data_version


def parse_obo(lines) -> dict:
    """`{"version": str, "terms": {accession: name}, "retired": [accession]}`.

    The version comes from the OBO's own `data-version` header. `OBO_URL` serves
    whatever is current and is not itself versioned, so without recording this
    there is no way to tell which release a committed table came from, and a
    regeneration months later silently mixes two. To reproduce a specific one:

        curl -sL https://github.com/EBISPOT/efo/releases/download/v3.92.0/efo.obo

    **Obsolete terms are kept.** Skipping them looks tidier and is wrong for the
    same reason as the GO table: annotation sources lag ontology releases, so
    retired accessions are exactly the ones still turning up in real output —
    two of the eleven in dev data today (EFO_0001645 coronary artery disease,
    EFO_1000627 thyroid disease) are retired upstream. Dropping them would show
    a bare accession for the terms most likely to need a label.

    `retired` comes from `is_obsolete`, never from the name: EFO_0002302 is
    named `obsolete_H720` while not being flagged obsolete, so trusting the name
    would retire a live term. The prefix is stripped either way — it is a
    labelling artefact, not a claim this table should make.
    """
    terms: dict[str, str] = {}
    retired: list[str] = []
    version = ""
    term_id: str | None = None
    name: str | None = None
    obsolete = False
    in_term = False

    def flush() -> None:
        if not (in_term and term_id and name):
            return
        key = accession(term_id)
        if key is None or key.split("_")[0] not in KEEP_PREFIXES:
            return
        terms[key] = clean_name(name)
        if obsolete:
            retired.append(key)

    for line in lines:
        line = line.rstrip("\n")
        if not in_term and line.startswith("data-version: "):
            version = release_version(line[len("data-version: ") :].strip())
            continue
        if line.startswith("["):
            flush()
            in_term = line == "[Term]"
            term_id = name = None
            obsolete = False
            continue
        if not in_term:
            continue
        if line.startswith("id: "):
            term_id = line[4:].strip()
        elif line.startswith("name: "):
            name = line[6:].strip()
        elif line.startswith("is_obsolete: true"):
            obsolete = True
    flush()

    # Sorted so a regeneration that changes nothing produces no diff.
    return {
        "version": version,
        "terms": dict(sorted(terms.items())),
        "retired": sorted(retired),
    }


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "-":
        table = parse_obo(sys.stdin)
    else:
        with urllib.request.urlopen(OBO_URL) as response:
            table = parse_obo(
                line.decode("utf-8", "replace") for line in response
            )

    OUT_PATH.write_text(
        json.dumps(table, separators=(",", ":"), ensure_ascii=False) + "\n"
    )
    print(
        f"wrote {OUT_PATH} — EFO {table['version'] or 'version unknown'}, "
        f"{len(table['terms'])} terms, {len(table['retired'])} retired"
    )


if __name__ == "__main__":
    main()
