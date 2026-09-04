"""The upload file name is attacker-controlled, and it becomes a path.

A client sets it via the `Filename` request header (or the multipart part's own
filename). `os.path.basename` strips directories but leaves shell
metacharacters, and that path was interpolated into `bcftools …` shell strings
after a round trip through the pipeline — so `a$(touch /tmp/x).vcf` ran.

These pin both halves of the fix: the name is validated at the door, and the
commands no longer go through a shell at all.
"""

import subprocess

import pytest

from app.vep.models.upload_vcf_files import (
    SAFE_FILENAME,
    Streamer,
    UnsafeFileNameException,
)


# --- the name is checked at the door ---------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "a$(touch /tmp/pwned).vcf",  # command substitution: needs no '/' to survive basename
        "a`id`.vcf",
        "benign; rm -rf x.vcf",
        "a|b.vcf",
        "a&b.vcf",
        "a\nb.vcf",
        "../../etc/passwd",
        "-flag-lookalike.vcf",  # would be read as a bcftools option
        "",
    ],
)
def test_an_unsafe_file_name_is_rejected(name):
    with pytest.raises(Exception):
        Streamer.file_name_validator(name)


@pytest.mark.parametrize(
    "name",
    [
        "sample.vcf",
        "sample_1.vcf.gz",
        "NA12878.chr1-22.vcf",
        "temp_name",  # the default when no header is sent
    ],
)
def test_a_real_vcf_name_is_accepted(name):
    Streamer.file_name_validator(name)  # must not raise


def test_the_substitution_payload_survives_basename():
    """Why basename is not enough on its own.

    Note the payload carries no '/': one that does (`a$(touch /tmp/x).vcf`) is
    genuinely truncated by basename, which is what makes this look safe at a
    glance. Command substitution needs no slash, so nothing is stripped and the
    name arrives at the shell whole.
    """
    import os

    name = "a$(id).vcf"
    assert os.path.basename(name) == name  # untouched
    assert not SAFE_FILENAME.fullmatch(name)  # the validator is what stops it

    with_slash = "a$(touch /tmp/pwned).vcf"
    assert os.path.basename(with_slash) != with_slash  # basename does bite here


def test_unsafe_names_raise_the_specific_exception():
    """The route maps this to a 400; a bare Exception would become a 500 and
    read as a server bug."""
    with pytest.raises(UnsafeFileNameException):
        Streamer.file_name_validator("a$(id).vcf")


# --- and the commands no longer reach a shell -------------------------------


def test_bcftools_calls_pass_argument_lists_not_shell_strings():
    """Defence in depth: even if a name slipped past the validator, nothing in
    the results path hands it to a shell."""
    from app.vep.utils import vcf_meta, vcf_results

    for module in (vcf_meta, vcf_results):
        source = open(module.__file__).read()
        assert "shell=True" not in source, f"{module.__name__} still uses shell=True"


def test_a_metacharacter_path_is_passed_through_untouched(tmp_path, monkeypatch):
    """An argument list hands the path to the program verbatim: no word
    splitting, no substitution. Proven with `echo` rather than bcftools so the
    test needs no external tool."""
    weird = tmp_path / "a$(touch pwned).vcf"
    output = subprocess.check_output(["echo", str(weird)], text=True)
    assert "$(touch pwned)" in output
    assert not (tmp_path / "pwned").exists()
