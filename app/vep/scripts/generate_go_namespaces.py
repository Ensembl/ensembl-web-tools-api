"""Regenerate the GO id -> aspect table from the Gene Ontology's OBO release.

The GO plugin emits `GO:0000122:negative_regulation_of_...` — an id and a name,
with no aspect — so grouping terms by cellular component / molecular function /
biological process needs the id -> namespace mapping from somewhere.

That somewhere is this script, run occasionally, rather than a runtime
dependency. `goatools` would answer the same question, but it pulls numpy,
pandas, scipy, statsmodels, pydot and openpyxl to do it, and still needs the
same 32 MB OBO shipped alongside; we would use exactly one attribute of its DAG.
Deriving the table once and committing it costs a few hundred KB and nothing at
runtime.

The OBO is streamed and parsed line-by-line — it is never written to disk.

    PYTHONPATH=app .venv/bin/python app/vep/scripts/generate_go_namespaces.py

Behind a proxy that rejects urllib (some return 403 on its default user-agent),
pipe it in instead — the parse is the same either way:

    curl -sL https://purl.obolibrary.org/obo/go/go-basic.obo \\
      | PYTHONPATH=app .venv/bin/python app/vep/scripts/generate_go_namespaces.py -

Re-run it when GO publishes a release whose terms you want to pick up. A term
the table has never heard of is not an error — it simply groups as unknown.
"""

import json
import sys
import urllib.request
from pathlib import Path

OBO_URL = "https://purl.obolibrary.org/obo/go/go-basic.obo"
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "go_namespaces.json"

# Every GO term carries exactly one of these.
NAMESPACES = ("biological_process", "cellular_component", "molecular_function")


def parse_obo(lines) -> dict[str, list[int]]:
    """id -> namespace, as `{namespace: [numeric ids]}`.

    Ids are stored without the `GO:` prefix and as ints, which is what makes the
    table small: the prefix is on every one of ~40k entries and carries nothing.

    **Obsolete terms are kept.** Skipping them looks tidier and is wrong: the
    annotation files lag GO releases, so obsolete ids are exactly the ones still
    turning up in real output — GO:0005615 (extracellular space) is obsolete
    upstream and still annotates dev data today. GO keeps a `namespace` on them,
    so they group correctly; dropping them would strand real terms as unknown.
    """
    by_namespace: dict[str, list[int]] = {name: [] for name in NAMESPACES}
    term_id: int | None = None
    namespace: str | None = None
    in_term = False

    def flush() -> None:
        if in_term and term_id is not None and namespace:
            by_namespace[namespace].append(term_id)

    for raw in lines:
        line = raw.decode("utf-8", "replace").rstrip("\n") if isinstance(raw, bytes) else raw.rstrip("\n")
        if line.startswith("["):
            flush()
            in_term = line == "[Term]"
            term_id, namespace = None, None
        elif not in_term:
            continue
        elif line.startswith("id: GO:"):
            term_id = int(line[len("id: GO:"):])
        elif line.startswith("namespace: "):
            candidate = line[len("namespace: "):]
            namespace = candidate if candidate in by_namespace else None
    flush()

    for ids in by_namespace.values():
        ids.sort()
    return by_namespace


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "-":
        by_namespace = parse_obo(sys.stdin)
    else:
        # A bare urllib request is 403'd by some proxies, hence the user-agent.
        request = urllib.request.Request(OBO_URL, headers={"User-Agent": "ensembl-web-tools-api"})
        with urllib.request.urlopen(request, timeout=120) as response:
            by_namespace = parse_obo(response)

    total = sum(len(ids) for ids in by_namespace.values())
    if total < 10_000:
        # A truncated download would otherwise quietly ship a table that groups
        # most terms as unknown.
        print(f"refusing to write: only {total} terms parsed", file=sys.stderr)
        return 1

    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(by_namespace, separators=(",", ":")) + "\n")
    for name, ids in by_namespace.items():
        print(f"  {name:20s} {len(ids):6d}")
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size / 1024:.0f} KB, {total} terms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
