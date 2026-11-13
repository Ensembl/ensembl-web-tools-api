"""A results VCF can hold bytes that are not UTF-8, because VEP copies them
through unchanged. Here "à" is the Latin-1 byte 0xE0."""

import gzip
import shutil

import pytest
from pydantic import FilePath

from app.tests.test_page_index import CSQ_DESC, write_indexed_vcf
from app.vep.utils import results_filters as rf
from app.vep.utils.tsv_export import gzip_text_stream, stream_vep_tsv
from app.vep.utils.vcf_results import get_results_from_path, stream_filtered_vcf_text

HEADER_LINE = '##FILTER=<ID=LowQual,Description="Qualità bassa">\n'
MISSENSE = "T|missense_variant|MODERATE|GENE1|ENSG1|Transcript|ENST1|protein_coding"
INTRON = "T|intron_variant|MODIFIER|GENE2|ENSG2|Transcript|ENST2|protein_coding"
VCF = (
    "##fileformat=VCFv4.2\n"
    + HEADER_LINE
    + f'##INFO=<ID=CSQ,Number=.,Type=String,Description="{CSQ_DESC}">\n'
    + "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    + f"chr1\t101\tvarià\tC\tT\t.\t.\tCSQ={MISSENSE}\n"
    + f"chr1\t102\tid_02\tC\tT\t.\t.\tCSQ={INTRON}\n"
)
MISSENSE_ONLY = [
    rf.ResultsFilter(field="consequence", operator="in", values=["missense_variant"])
]


@pytest.fixture
def latin1_vcf(tmp_path):
    return write_indexed_vcf(tmp_path, VCF, stride=4, encoding="latin-1")


@pytest.fixture
def latin1_plain_gzip_vcf(latin1_vcf):
    latin1_vcf.write_bytes(gzip.compress(VCF.encode("latin-1")))
    return latin1_vcf


def _downloaded(text_stream) -> bytes:
    return gzip.decompress(b"".join(gzip_text_stream(text_stream)))


def test_results_page_drops_non_utf8_bytes(latin1_vcf):
    results = get_results_from_path(5, 1, FilePath(latin1_vcf))

    assert [variant.name for variant in results.variants] == ["vari", "id_02"]


@pytest.mark.parametrize("vcf", ["latin1_vcf", "latin1_plain_gzip_vcf"])
def test_filtered_results_page_drops_non_utf8_bytes(vcf, request):
    vcf_path = FilePath(request.getfixturevalue(vcf))

    results = get_results_from_path(5, 1, vcf_path, filters=MISSENSE_ONLY)

    assert [variant.name for variant in results.variants] == ["vari"]


def test_bcftools_fallback_drops_non_utf8_bytes(latin1_vcf):
    if shutil.which("bcftools") is None:
        pytest.skip("bcftools is not installed")
    latin1_vcf.with_name(latin1_vcf.name + ".pageidx.json").unlink()

    results = get_results_from_path(5, 1, FilePath(latin1_vcf))

    assert [variant.name for variant in results.variants] == ["vari", "id_02"]


def test_filtered_vcf_download_drops_non_utf8_bytes(latin1_vcf):
    downloaded = _downloaded(
        stream_filtered_vcf_text(FilePath(latin1_vcf), MISSENSE_ONLY)
    )

    assert (
        downloaded.decode().splitlines(keepends=True)
        == VCF.replace("à", "").splitlines(keepends=True)[:-1]
    )


def test_tsv_download_drops_non_utf8_bytes(latin1_vcf):
    downloaded = _downloaded(stream_vep_tsv(FilePath(latin1_vcf)))

    assert downloaded.decode().splitlines()[1].startswith("vari\t1:101\tC\t")
