"""Tests for safe upload filenames and command arguments."""

import subprocess

import pytest

from app.vep.models.upload_vcf_files import (
    UnsafeFileNameException,
    sanitize_filename,
)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("sample[1].vcf", "sample_1_.vcf"),
        ("a$(id).vcf", "a_id_.vcf"),
        ("a`id`.vcf", "a_id_.vcf"),
        ("benign; rm -rf x.vcf", "benign_rm_-rf_x.vcf"),
        ("a|b.vcf", "a_b.vcf"),
        ("a&b.vcf", "a_b.vcf"),
        ("a\nb.vcf", "a_b.vcf"),
        ("../../etc/passwd", "passwd"),
        (r"..\..\windows\input.vcf", "input.vcf"),
        ("-flag-lookalike.vcf", "flag-lookalike.vcf"),
        ("résumé.vcf", "resume.vcf"),
    ],
)
def test_file_names_are_sanitized(name, expected):
    assert sanitize_filename(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "sample.vcf",
        "sample_1.vcf.gz",
        "NA12878.chr1-22.vcf",
        "temp_name",
    ],
)
def test_a_real_vcf_name_is_accepted(name):
    assert sanitize_filename(name) == name


def test_the_substitution_payload_survives_basename():
    """basename alone does not remove unsafe characters."""
    import os

    name = "a$(id).vcf"
    assert os.path.basename(name) == name
    assert sanitize_filename(name) == "a_id_.vcf"

    with_slash = "a$(touch /tmp/pwned).vcf"
    assert os.path.basename(with_slash) != with_slash


@pytest.mark.parametrize("name", [None, "", "...", "[]"])
def test_names_without_any_usable_characters_are_rejected(name):
    with pytest.raises(UnsafeFileNameException):
        sanitize_filename(name)


def test_sanitized_names_are_limited_to_a_portable_length():
    sanitized = sanitize_filename("a" * 300 + ".vcf.gz")
    assert sanitized == "a" * 248 + ".vcf.gz"
    assert len(sanitized) == 255


def test_bcftools_calls_pass_argument_lists_not_shell_strings():
    from app.vep.utils import vcf_meta, vcf_results

    for module in (vcf_meta, vcf_results):
        source = open(module.__file__).read()
        assert "shell=True" not in source, f"{module.__name__} still uses shell=True"


def test_a_metacharacter_path_is_passed_through_untouched(tmp_path):
    weird = tmp_path / "a$(touch pwned).vcf"
    output = subprocess.check_output(["echo", str(weird)], text=True)
    assert "$(touch pwned)" in output
    assert not (tmp_path / "pwned").exists()
