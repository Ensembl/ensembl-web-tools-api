"""Reading VCF records for the results path.

This replaces vcfpy, which was ~47% of a page request: 81ms of ~172ms, split
between a header parse that walked 282 `##` lines a character at a time and an
INFO unescape that made eight full-string passes over every value.

It is deliberately small, because the results path asks for very little. Per
record: CHROM, POS, ID, REF, ALT, and four INFO keys — CSQ, SVTYPE, SVLEN and
END. No samples, FORMAT, genotypes, FILTER, QUAL or tabix. A general VCF
library was being carried for a fraction of one.

Text in, records out. That is also what the rest of the results path already
does — filtering, the row slice, the page-index seek and the CSQ header all read
raw lines — so this removes a second representation rather than adding one.

★ The VCF's own percent-escapes are resolved here, but only *after* the INFO
fields and CSQ entries have been split — which is the ordering vcfpy got wrong.
It decoded first, turning `%2C` into a real comma 29,541 times over a 50-record
file before any splitting had run; nothing downstream happens to split on a
comma, so it never bit, but it is the wrong way round. Splitting on the raw text
means an encoded separator inside a value cannot be mistaken for a real one.

Only the eight escapes the VCF spec reserves are resolved. The enriched ClinVar
VCF's own encodings (`%2B`, `%26`) are left exactly as they are, for the parsing
spec to split on and `_decode_leaves` to resolve at the end — see
`clinvar-vcf-info-field-format`.
"""

import re
from typing import Iterable, Iterator


class Allele:
    """One ALT allele, in the two forms the results path needs.

    `value` is the bare form and `serialize()` the form as written in the file.
    They differ for the symbolic and breakend alleles, and both are used: the
    allele column shows the bare form, while `_structural_info` classifies on
    the serialized one. This mirrors vcfpy, whose `SymbolicAllele.value` is
    `DEL` against a `serialize()` of `<DEL>`, and whose `BreakEnd.value` is None.
    """

    __slots__ = ("value", "_text")

    def __init__(self, text: str):
        self._text = text
        if len(text) > 1 and text[0] == "<" and text[-1] == ">":
            self.value = text[1:-1]          # symbolic: <DEL> -> DEL
        elif "[" in text or "]" in text:
            self.value = None                # breakend: no bare form
        else:
            self.value = text                # a plain sequence is both

    def serialize(self) -> str:
        return self._text

    def __repr__(self) -> str:
        return f"Allele({self._text!r})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Allele) and self._text == other._text


class Record:
    """One VCF data line, carrying only the fields the results path reads.

    Field names match vcfpy's so the callers read the same either way.
    """

    __slots__ = ("CHROM", "POS", "ID", "REF", "ALT", "INFO")

    def __init__(self, CHROM, POS, ID, REF, ALT, INFO):
        self.CHROM = CHROM
        self.POS = POS
        self.ID = ID
        self.REF = REF
        self.ALT = ALT
        self.INFO = INFO

    def __repr__(self) -> str:
        return f"Record({self.CHROM}:{self.POS} {self.REF}->{self.ALT})"


# The escapes VCF reserves in INFO values (VCF 4.3 §1.2). Resolved in one pass,
# which is both cheaper than a replace per pair and free of the ordering trap
# that catches the sequential form: taking `%25` -> `%` first turns `%253A` into
# `%3A` and then into a colon. A single scan replaces each escape once.
_VCF_ESCAPES = {
    "%25": "%", "%3A": ":", "%3B": ";", "%3D": "=",
    "%2C": ",", "%0D": "\r", "%0A": "\n", "%09": "\t",
}
_ESCAPE_RE = re.compile("|".join(_VCF_ESCAPES))


def unescape(value: str) -> str:
    """Resolve the VCF's reserved percent-escapes in one pass.

    The `%` test is what makes this nearly free: most values carry no escape at
    all, and those skip the scan entirely.
    """
    if "%" not in value:
        return value
    return _ESCAPE_RE.sub(lambda m: _VCF_ESCAPES[m.group()], value)


# The INFO keys the results path reads. Everything else is skipped rather than
# parsed: a VEP output's INFO carries far more than this, and building objects
# for fields nobody asks for was a good part of what made the old reader slow.
_WANTED_INFO = frozenset({"CSQ", "SVTYPE", "SVLEN", "END"})

# CSQ holds one entry per consequence, comma-separated. The split happens on the
# raw text, before any decoding — an encoded comma inside an entry is still
# `%2C` here and so cannot be mistaken for a separator.
_MULTI_INFO = frozenset({"CSQ"})


def parse_info(info: str) -> dict:
    """The INFO column, restricted to the keys the results path reads.

    A key with no `=` is a flag and maps to True, as vcfpy had it. A missing
    key is simply absent, so `INFO.get(...)` answers None exactly as before.
    """
    parsed: dict = {}
    for field in info.split(";"):
        key, sep, value = field.partition("=")
        if key not in _WANTED_INFO:
            continue
        if not sep:
            parsed[key] = True
        elif key in _MULTI_INFO:
            # Split first, unescape second — an entry holding `%2C` keeps it
            # through the split and only then becomes a comma of its own.
            parsed[key] = [unescape(entry) for entry in value.split(",")]
        else:
            parsed[key] = unescape(value)
    return parsed


def parse_record(line: str) -> Record:
    """One data line as a Record. The caller must not pass a header line."""
    # maxsplit stops before FORMAT and the sample columns, which are never read.
    columns = line.rstrip("\n").split("\t", 8)
    chrom, pos, ident, ref, alt = columns[0], columns[1], columns[2], columns[3], columns[4]
    info = columns[7] if len(columns) > 7 else ""
    return Record(
        CHROM=chrom,
        # `.` means "no id"; several ids are semicolon-separated. vcfpy handed
        # back a list either way and the caller joins it.
        POS=int(pos),
        ID=[] if ident == "." else ident.split(";"),
        REF=ref,
        ALT=[Allele(a) for a in alt.split(",")] if alt != "." else [],
        INFO=parse_info(info),
    )


def read_records(lines: Iterable[str]) -> Iterator[Record]:
    """Every data line of `lines` as a Record, header lines skipped."""
    for line in lines:
        if line and line[0] != "#" and line.strip():
            yield parse_record(line)
