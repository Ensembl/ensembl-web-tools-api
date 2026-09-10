"""Tests for the BGZF page-index seek path (app/vep/utils/vcf_results.py).

When a `<vcf>.pageidx.json` sidecar is present, get_results_from_path seeks to
the page via packed BGZF virtual offsets instead of scanning with bcftools.

These tests build their own BGZF fixtures in pure Python (a tiny block-splitting
writer that also reports the ground-truth virtual offset of every line), so they
run with no external tools/deps and deliberately span BGZF block boundaries.
"""

import gzip
import json
import struct
import subprocess
import zlib

import pytest
from pydantic import FilePath

from app.vep.models.display_panels_model import to_display_panels
from app.vep.utils.bgzf import _BgzfReader
from app.vep.utils.spec_loader import (
    load_merged_spec,
    write_display_panels_sidecar,
    write_expected_columns_sidecar,
    write_spec_sidecar,
)
from app.vep.utils.vcf_results import (
    _load_page_index,
    _read_indexed_page,
    get_results_from_path,
)

# --- pure-Python BGZF writer (fixtures) --------------------------------------

# The standard 28-byte BGZF end-of-file marker (an empty block).
BGZF_EOF = bytes.fromhex(
    "1f8b08040000000000ff0600424302001b0003000000000000000000"
)


def _bgzf_block(payload: bytes) -> bytes:
    compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
    cdata = compressor.compress(payload) + compressor.flush()
    bsize = 12 + 6 + len(cdata) + 8 - 1  # total block size - 1
    header = (
        b"\x1f\x8b\x08\x04\x00\x00\x00\x00\x00\xff"
        + struct.pack("<H", 6)
        + b"BC"
        + struct.pack("<H", 2)
        + struct.pack("<H", bsize)
    )
    trailer = struct.pack("<I", zlib.crc32(payload) & 0xFFFFFFFF) + struct.pack(
        "<I", len(payload) & 0xFFFFFFFF
    )
    return header + cdata + trailer


def write_bgzf(path, text: str, block_bytes: int = 64) -> list[int]:
    """Write `text` as BGZF, splitting the *uncompressed* stream into blocks of
    `block_bytes` (small, so lines cross block boundaries). Returns the packed
    virtual offset of the start of each line (ground truth, computed from block
    layout — independent of the reader under test)."""
    data = text.encode()
    blocks = [data[i : i + block_bytes] for i in range(0, len(data), block_bytes)] or [b""]

    out = bytearray()
    block_coffsets = []
    for block in blocks:
        block_coffsets.append(len(out))
        out += _bgzf_block(block)
    out += BGZF_EOF
    path.write_bytes(bytes(out))

    def voffset(global_uncompressed_offset: int) -> int:
        block = global_uncompressed_offset // block_bytes
        within = global_uncompressed_offset % block_bytes
        return (block_coffsets[block] << 16) | within

    line_voffsets, cursor = [], 0
    for line in text.splitlines(keepends=True):
        line_voffsets.append(voffset(cursor))
        cursor += len(line.encode())
    return line_voffsets


def write_indexed_vcf(tmp_path, text: str, *, stride: int, block_bytes: int = 64):
    """Write text as BGZF + its `.pageidx.json` sidecar; return the vcf path."""
    vcf_path = tmp_path / "results.vcf.gz"
    line_voffsets = write_bgzf(vcf_path, text, block_bytes=block_bytes)

    lines = text.splitlines(keepends=True)
    data_voffsets = [
        vo for line, vo in zip(lines, line_voffsets) if not line.startswith("#")
    ]
    index = {
        "version": 1,
        "vcf": vcf_path.name,
        "total_records": len(data_voffsets),
        "header_end_voffset": data_voffsets[0] if data_voffsets else 0,
        "stride": stride,
        "checkpoints": [data_voffsets[k] for k in range(0, len(data_voffsets), stride)],
    }
    (tmp_path / "results.vcf.gz.pageidx.json").write_text(json.dumps(index))
    write_spec_sidecar(tmp_path, load_merged_spec("human_grch38"))
    write_expected_columns_sidecar(tmp_path, set())
    write_display_panels_sidecar(
        tmp_path,
        to_display_panels([{"id": "general", "label": "General", "options": []}]),
    )
    return vcf_path


# --- fixtures ----------------------------------------------------------------

CSQ_DESC = (
    "Consequence annotations from Ensembl VEP. Format: "
    "Allele|Consequence|IMPACT|SYMBOL|Gene|Feature_type|Feature|BIOTYPE"
)


def make_vcf(n_records: int) -> str:
    header = (
        "##fileformat=VCFv4.2\n"
        f'##INFO=<ID=CSQ,Number=.,Type=String,Description="{CSQ_DESC}">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    )
    rows = []
    for i in range(1, n_records + 1):
        csq = f"T|missense_variant|MODERATE|GENE{i}|ENSG{i}|Transcript|ENST{i}|protein_coding"
        rows.append(f"chr1\t{100 + i}\tid_{i:02d}\tC\tT\t.\t.\tCSQ={csq}\n")
    return header + "".join(rows)


@pytest.fixture
def indexed_vcf(tmp_path):
    # 12 records, checkpoints every 4 records, tiny blocks -> multi-block file.
    return write_indexed_vcf(tmp_path, make_vcf(12), stride=4, block_bytes=64)


# --- _read_indexed_page ------------------------------------------------------


def test_read_indexed_page_matches_sequential(tmp_path):
    text = make_vcf(12)
    vcf_path = write_indexed_vcf(tmp_path, text, stride=4)
    index = _load_page_index(FilePath(vcf_path))

    header_seq, records_seq = [], []
    with gzip.open(vcf_path, "rt") as handle:
        for line in handle:
            (header_seq if line.startswith("#") else records_seq).append(line)

    for page, page_size in [(1, 5), (2, 5), (3, 5), (4, 5), (1, 1), (12, 1), (2, 4)]:
        header, rows = _read_indexed_page(FilePath(vcf_path), index, page, page_size)
        start = (page - 1) * page_size
        assert header.splitlines(keepends=True) == header_seq
        assert rows.splitlines(keepends=True) == records_seq[start : start + page_size]


def test_reader_seeks_across_block_boundaries(tmp_path):
    text = make_vcf(12)
    vcf_path = write_indexed_vcf(tmp_path, text, stride=4, block_bytes=48)
    index = _load_page_index(FilePath(vcf_path))
    # tiny blocks -> the file really is multi-block (more than one checkpoint slot)
    assert len(index["checkpoints"]) == 3

    records_seq = [
        line for line in gzip.open(vcf_path, "rt") if not line.startswith("#")
    ]
    with _BgzfReader(str(vcf_path)) as reader:
        # seek straight to checkpoint 2 (record index 8) and read it back
        reader.seek(index["checkpoints"][2])
        assert reader.readline().decode() == records_seq[8]


# --- get_results_from_path (end to end, via the index) -----------------------


def test_get_results_page_via_index(indexed_vcf):
    result = get_results_from_path(5, 2, FilePath(indexed_vcf))
    assert [v.name for v in result.variants] == [f"id_{i:02d}" for i in range(6, 11)]
    assert result.metadata.pagination.page == 2
    assert result.metadata.pagination.per_page == 5
    assert result.metadata.pagination.total == 12
    # "chr" prefix stripped, location parsed
    assert result.variants[0].location.region_name == "1"


def test_get_results_last_partial_page_via_index(indexed_vcf):
    result = get_results_from_path(5, 3, FilePath(indexed_vcf))
    assert [v.name for v in result.variants] == ["id_11", "id_12"]
    assert result.metadata.pagination.total == 12


def test_get_results_beyond_end_is_empty(indexed_vcf):
    result = get_results_from_path(5, 10, FilePath(indexed_vcf))
    assert result.variants == []
    assert result.metadata.pagination.total == 12


def test_index_path_does_not_shell_out(monkeypatch, indexed_vcf):
    # with a sidecar present, no bcftools subprocess should be invoked
    def boom(*args, **kwargs):
        raise AssertionError("subprocess called despite page index present")

    monkeypatch.setattr(subprocess, "check_output", boom)
    result = get_results_from_path(5, 1, FilePath(indexed_vcf))
    assert [v.name for v in result.variants] == [f"id_{i:02d}" for i in range(1, 6)]


def test_no_sidecar_returns_none(tmp_path):
    plain = tmp_path / "plain.vcf.gz"
    write_bgzf(plain, make_vcf(3))
    assert _load_page_index(FilePath(plain)) is None


# --- seeking to a filtered page ----------------------------------------------
#
# A filtered request scans the whole file once to find every match, then caches
# the ordinals of the matching records. Later pages of that same filter set use
# the checkpoints to start reading beside the records they need instead of at
# record 0.


def make_mixed_vcf(n_records: int) -> str:
    """`n_records` records where every even one is missense and the rest are
    synonymous, so a missense filter keeps exactly half."""
    header = (
        "##fileformat=VCFv4.2\n"
        f'##INFO=<ID=CSQ,Number=.,Type=String,Description="{CSQ_DESC}">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    )
    rows = []
    for i in range(n_records):
        cons = "missense_variant" if i % 2 == 0 else "synonymous_variant"
        csq = f"T|{cons}|MODERATE|GENE{i}|ENSG{i}|Transcript|ENST{i}|protein_coding"
        rows.append(f"chr1\t{100 + i}\tid_{i:03d}\tC\tT\t.\t.\tCSQ={csq}\n")
    return header + "".join(rows)


def _missense_filter():
    from app.vep.utils import results_filters as rf

    return rf.ResultsFilter(field="consequence", operator="in", values=["missense_variant"])


def _filtered_page(vcf_path, page, page_size):
    return get_results_from_path(
        page_size, page, FilePath(vcf_path), [_missense_filter()]
    )


def test_a_seeked_page_shows_the_same_variants_as_an_unseeked_one(tmp_path):
    """The checkpoints change where reading starts, never what the page holds.
    If this fails, a deep filtered page shows the wrong variants."""
    from app.vep.utils import vcf_results

    text = make_mixed_vcf(200)
    vcf_path = write_indexed_vcf(tmp_path, text, stride=10, block_bytes=256)
    sidecar = tmp_path / "results.vcf.gz.pageidx.json"
    kept_sidecar = sidecar.read_text()

    def names(page):
        return [v.name for v in _filtered_page(vcf_path, page, 5).variants]

    for page in (1, 2, 9, 20):
        vcf_results.clear_scan_cache()
        sidecar.unlink()  # no index -> read from the top
        _filtered_page(vcf_path, 1, 5)  # warm the match set
        without_seek = names(page)

        vcf_results.clear_scan_cache()
        sidecar.write_text(kept_sidecar)  # index present -> seek
        _filtered_page(vcf_path, 1, 5)
        with_seek = names(page)

        assert with_seek == without_seek, f"page {page} differs when seeked"
        assert with_seek, f"page {page} came back empty"


def test_a_deep_page_stops_reading_most_of_the_file(tmp_path):
    """The point of the seek. Page 18 of a 200-record file wants records
    170-178; with a checkpoint every 10 records the reader should start at
    record 170 and read a few dozen lines, not 179.

    Counts lines actually read, because a test that only compared output would
    pass just as well if the seek never happened."""
    from app.vep.utils import vcf_results

    vcf_path = write_indexed_vcf(tmp_path, make_mixed_vcf(200), stride=10, block_bytes=256)
    vcf_results.clear_scan_cache()
    _filtered_page(vcf_path, 1, 5)  # cold scan populates the match ordinals

    reads = {"n": 0}
    # Patch the class vcf_results actually holds. The test suite imports this
    # module as `app.vep.utils.bgzf` while the app imports it as
    # `vep.utils.bgzf`; those are two module objects with two separate
    # _BgzfReader classes, so patching the wrong one silently counts nothing.
    reader_class = vcf_results._BgzfReader
    original = reader_class.readline

    def counting_readline(self):
        reads["n"] += 1
        return original(self)

    reader_class.readline = counting_readline
    try:
        page = _filtered_page(vcf_path, 18, 5)
    finally:
        reader_class.readline = original

    assert [v.name for v in page.variants] == [
        f"id_{i:03d}" for i in (170, 172, 174, 176, 178)
    ]
    assert reads["n"] > 0, "counted nothing; the patch missed the reader in use"
    # 3 header lines + at most one checkpoint stride of records + the page.
    # Reading from the top would be 179 records instead.
    assert reads["n"] < 40, f"read {reads['n']} lines; the seek did not happen"


def test_a_stale_page_index_is_not_used_to_seek(tmp_path):
    """A sidecar built from a different version of the VCF points at offsets
    that mean nothing in this one, so seeking on it would serve whatever
    happens to sit there. The scan counted the records itself, so a sidecar
    whose total disagrees is refused and the page is read from the top.

    The stale sidecar here is a real one, generated from a 90-record file
    written with a different BGZF block size, so its virtual offsets point into
    the wrong blocks of the file it is placed beside. Note that a shorter file
    of the *same* block size would not do: its records are a byte-for-byte
    prefix, so its checkpoints would happen to be right."""
    from app.vep.utils import vcf_results

    vcf_path = write_indexed_vcf(tmp_path, make_mixed_vcf(200), stride=10, block_bytes=256)
    sidecar = tmp_path / "results.vcf.gz.pageidx.json"

    vcf_results.clear_scan_cache()
    _filtered_page(vcf_path, 1, 5)
    truthful = [v.name for v in _filtered_page(vcf_path, 15, 5).variants]
    assert truthful == [f"id_{i:03d}" for i in (140, 142, 144, 146, 148)]

    other = tmp_path / "other"
    other.mkdir()
    write_indexed_vcf(other, make_mixed_vcf(90), stride=10, block_bytes=64)
    stale = json.loads((other / "results.vcf.gz.pageidx.json").read_text())
    good = json.loads(sidecar.read_text())
    assert stale["checkpoints"][:9] != good["checkpoints"][:9], "sidecar is not stale"
    sidecar.write_text(json.dumps(stale))

    vcf_results.clear_scan_cache()
    _filtered_page(vcf_path, 1, 5)
    assert [v.name for v in _filtered_page(vcf_path, 15, 5).variants] == truthful


def test_filtering_still_works_without_a_page_index(tmp_path):
    """A VCF written with plain gzip has no BGZF block sizes and no sidecar.
    It cannot seek, but it must still filter and paginate correctly."""
    from app.vep.utils import vcf_results
    from app.vep.utils.bgzf import is_bgzf

    vcf_path = tmp_path / "results.vcf.gz"
    with gzip.open(vcf_path, "wt") as handle:
        handle.write(make_mixed_vcf(60))
    write_spec_sidecar(tmp_path, load_merged_spec("human_grch38"))
    write_expected_columns_sidecar(tmp_path, set())
    write_display_panels_sidecar(
        tmp_path,
        to_display_panels([{"id": "general", "label": "General", "options": []}]),
    )
    assert not is_bgzf(str(vcf_path))

    vcf_results.clear_scan_cache()
    first = _filtered_page(vcf_path, 1, 5)
    assert first.metadata.filters.filtered_total == 30
    assert [v.name for v in _filtered_page(vcf_path, 4, 5).variants] == [
        f"id_{i:03d}" for i in (30, 32, 34, 36, 38)
    ]


# --- is_bgzf and checkpoint lookup -------------------------------------------


def test_is_bgzf_tells_the_two_gzip_flavours_apart(tmp_path):
    """_BgzfReader raises on a plain gzip file, so the reader is chosen on this.
    Getting it wrong turns a working request into a 500."""
    from app.vep.utils.bgzf import is_bgzf

    plain = tmp_path / "plain.vcf.gz"
    with gzip.open(plain, "wt") as handle:
        handle.write("##fileformat=VCFv4.2\n")
    blocked = tmp_path / "blocked.vcf.gz"
    write_bgzf(blocked, "##fileformat=VCFv4.2\n")

    assert is_bgzf(str(blocked))
    assert not is_bgzf(str(plain))
    assert not is_bgzf(str(tmp_path / "missing.vcf.gz"))


def test_checkpoint_covering_never_overshoots():
    """The checkpoint returned must sit at or before the record asked for;
    overshooting would skip the record and drop it from the page."""
    from app.vep.utils.vcf_results import _checkpoint_covering

    index = {"stride": 10, "checkpoints": [1000, 2000, 3000, 4000]}
    assert _checkpoint_covering(index, 0) == (1000, 0)
    assert _checkpoint_covering(index, 9) == (1000, 0)
    assert _checkpoint_covering(index, 10) == (2000, 10)
    assert _checkpoint_covering(index, 35) == (4000, 30)
    # Past the last checkpoint: fall back to it and read forward.
    assert _checkpoint_covering(index, 999) == (4000, 30)


def test_checkpoint_covering_gives_up_on_an_unusable_index():
    """An index with no checkpoints, or a nonsense stride, means read from the
    top rather than divide by zero."""
    from app.vep.utils.vcf_results import _checkpoint_covering

    assert _checkpoint_covering({"stride": 10, "checkpoints": []}, 5) is None
    assert _checkpoint_covering({"stride": 0, "checkpoints": [1]}, 5) is None
    assert _checkpoint_covering({}, 5) is None
