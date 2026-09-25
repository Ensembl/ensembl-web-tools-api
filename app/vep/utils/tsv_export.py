"""Flattened "expanded columnar" export (human-readable / spreadsheet-friendly).

Extracted from vcf_results. One tab-separated row per CSQ entry — every allele x
feature, transcript AND intergenic, i.e. fully expanded — with a column for the
variant location plus every CSQ field (all VEP + plugin annotations). Streamed
line by line so the whole file needn't be held in memory. Reads the VCF directly
(bgzip is gzip-readable), so it needs neither vcfpy nor bcftools.
"""

import gzip
import zlib
from typing import Iterable, Iterator
from pydantic import FilePath


def _parse_csq_format(info_line: str) -> list[str]:
    """Pull the pipe-delimited CSQ field names out of the ##INFO CSQ header."""
    fmt = info_line.split("Format:", 1)[1].split('">')[0].strip()
    return fmt.split("|")


def _vcf_alts_by_csq_allele(ref: str, alts: list[str]) -> dict[str, str]:
    """Map each CSQ Allele value back to the VCF ALT it came from.

    VEP strips the first base from an indel's alleles when REF and every ALT
    share it, and writes an empty allele as "-". "*" alleles take no part.
    """
    if all(len(alt) == len(ref) for alt in alts):
        return {alt: alt for alt in alts}
    first_bases = {allele[0] for allele in [ref, *alts] if allele and "*" not in allele}
    if len(first_bases) != 1:
        return {alt: alt for alt in alts}
    return {
        alt if "*" in alt else (alt[1:] or "-"): alt
        for alt in alts
    }


def gzip_text_stream(chunks: Iterator[str], level: int = 6) -> Iterator[bytes]:
    """Gzip-compress a stream of text chunks on the fly, yielding gzip-format
    bytes. Used to serve the flattened TSV download compressed (plain gzip, for
    broad compatibility) without buffering the whole table in memory."""
    # wbits 16 + MAX_WBITS => a standalone gzip container (header + trailer).
    compressor = zlib.compressobj(level, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    for chunk in chunks:
        compressed = compressor.compress(chunk.encode("utf-8"))
        if compressed:
            yield compressed
    tail = compressor.flush()
    if tail:
        yield tail


def flatten_vcf_lines(lines: Iterable[str]) -> Iterator[str]:
    """Yield VEP output VCF text lines flattened to tab-separated rows (with
    header). Works over any iterator of VCF lines — the raw file, or a filtered
    line stream — so the same flattener serves both the full and filtered TSV
    downloads. A line whose CSQ has already been narrowed (filtered) simply emits
    fewer rows; records with an empty CSQ emit none. Location, Ref and Allele
    follow the VCF record, so Allele holds the VCF ALT rather than VEP's
    trimmed allele."""
    csq_fields: list[str] | None = None
    allele_index: int | None = None
    header_emitted = False
    for line in lines:
        if line.startswith("##INFO=<ID=CSQ"):
            csq_fields = _parse_csq_format(line)
            allele_index = (
                csq_fields.index("Allele") if "Allele" in csq_fields else None
            )
            continue
        if line.startswith("#") or csq_fields is None:
            continue
        if not header_emitted:
            yield (
                "\t".join(["Uploaded_variation", "Location", "Ref"] + csq_fields)
                + "\n"
            )
            header_emitted = True
        columns = line.rstrip("\n").split("\t")
        if len(columns) < 8:
            continue
        chrom, pos, variant_id, ref, alt = columns[:5]
        if chrom.startswith("chr"):
            chrom = chrom[3:]
        location = f"{chrom}:{pos}"
        csq = next(
            (c[4:] for c in columns[7].split(";") if c.startswith("CSQ=")),
            None,
        )
        if not csq:
            continue
        vcf_alts = _vcf_alts_by_csq_allele(ref, alt.split(","))
        for entry in csq.split(","):
            values = entry.split("|")
            if len(values) < len(csq_fields):
                values += [""] * (len(csq_fields) - len(values))
            if allele_index is not None:
                values[allele_index] = vcf_alts.get(
                    values[allele_index], values[allele_index]
                )
            row = [variant_id, location, ref] + values[: len(csq_fields)]
            yield "\t".join(row) + "\n"


def stream_vep_tsv(vcf_path: FilePath) -> Iterator[str]:
    """Yield the whole VEP output VCF flattened to tab-separated rows (with
    header). Reads the file directly (bgzip is gzip-readable)."""
    with gzip.open(vcf_path, "rt") as vcf:
        yield from flatten_vcf_lines(vcf)
