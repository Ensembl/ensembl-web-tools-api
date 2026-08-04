"""The VCF record reader that replaced vcfpy.

The results path reads very little of a VCF — CHROM/POS/ID/REF/ALT and four
INFO keys — so this covers that surface and, more importantly, the two places
where a general library's behaviour was subtly different from what we need:
the two forms of an ALT allele, and *when* percent-escapes are resolved.
"""

import pytest

from app.vep.utils.vcf_reader import (
    Allele,
    parse_info,
    parse_record,
    read_records,
    unescape,
)

HEADER = "##fileformat=VCFv4.2\n"
COLUMNS = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"


def line(chrom="1", pos="100", ident=".", ref="C", alt="T", info="CSQ=T|x"):
    return "\t".join([chrom, pos, ident, ref, alt, ".", "PASS", info]) + "\n"


# --- the two forms of an ALT allele ------------------------------------------
#
# Both are used and they differ: the allele column shows the bare form, while
# _structural_info classifies on the serialized one and tests `startswith("<")`.


@pytest.mark.parametrize(
    "text,value,serialized",
    [
        ("A", "A", "A"),                       # substitution: one and the same
        ("ACGT", "ACGT", "ACGT"),
        ("<DEL>", "DEL", "<DEL>"),             # symbolic: bare form is inside
        ("<DEL:ME:ALU>", "DEL:ME:ALU", "<DEL:ME:ALU>"),
        ("G]17:198982]", None, "G]17:198982]"),  # breakend: no bare form
        ("[13:123457[C", None, "[13:123457[C"),
    ],
)
def test_an_allele_keeps_both_forms(text, value, serialized):
    allele = Allele(text)
    assert allele.value == value
    assert allele.serialize() == serialized


# --- escapes are resolved after splitting, not before ------------------------


def test_only_the_escapes_vcf_reserves_are_resolved():
    """The enriched ClinVar VCF has encodings of its own (`%2B`, `%26`) which
    are separators for the parsing spec — resolving them here would split a
    value on a character that was deliberately hidden."""
    assert unescape("a%3Db") == "a=b"
    assert unescape("a%2Cb") == "a,b"
    assert unescape("a%3Bb%3Ac") == "a;b:c"
    assert unescape("a%2Bb%26c") == "a%2Bb%26c"


def test_an_escaped_percent_does_not_cascade():
    """The ordering trap in the sequential form: resolving `%25` -> `%` first
    turns `%253A` into `%3A` and then into a colon. One pass, one replacement."""
    assert unescape("%253A") == "%3A"
    assert unescape("100%25") == "100%"


def test_a_value_with_no_escape_is_returned_as_it_stands():
    plain = "ENST00000631376.1"
    assert unescape(plain) is plain


def test_csq_entries_split_before_they_are_unescaped():
    """An entry holding an encoded comma keeps it through the split and only
    then becomes a comma of its own — it must never be read as a separator."""
    info = parse_info("CSQ=A|Disorder%2C_mitochondrial,B|Other")
    assert info["CSQ"] == ["A|Disorder,_mitochondrial", "B|Other"]


# --- the INFO column ---------------------------------------------------------


def test_only_the_keys_the_results_path_reads_are_parsed():
    info = parse_info("AC=2;CSQ=A|x;SVTYPE=DEL;END=500;SVLEN=-100;AN=4;DP=17")
    assert set(info) == {"CSQ", "SVTYPE", "END", "SVLEN"}
    assert info["SVTYPE"] == "DEL"
    assert info["END"] == "500"


def test_a_key_without_a_value_is_a_flag():
    assert parse_info("SVTYPE=DEL;END") == {"SVTYPE": "DEL", "END": True}


def test_a_missing_key_is_simply_absent():
    """So `INFO.get(...)` answers None, which is what the callers rely on."""
    assert parse_info("AC=2").get("CSQ") is None


# --- whole records -----------------------------------------------------------


def test_a_record_carries_the_fields_the_results_path_reads():
    record = parse_record(line(chrom="chr19", pos="82664", ident="rs1", ref="C", alt="T"))
    assert record.CHROM == "chr19"
    assert record.POS == 82664
    assert record.ID == ["rs1"]
    assert record.REF == "C"
    assert [a.value for a in record.ALT] == ["T"]


def test_ids_are_a_list_and_a_missing_one_is_empty():
    assert parse_record(line(ident=".")).ID == []
    assert parse_record(line(ident="rs1;rs2")).ID == ["rs1", "rs2"]


def test_a_multi_allele_record_keeps_every_alt_in_order():
    record = parse_record(line(alt="T,A,<DEL>"))
    assert [a.serialize() for a in record.ALT] == ["T", "A", "<DEL>"]
    assert [a.value for a in record.ALT] == ["T", "A", "DEL"]


def test_trailing_sample_columns_are_ignored():
    """The results path reads no FORMAT, samples or genotypes, so a file that
    carries them must parse the same as one that does not."""
    bare = line()
    with_samples = bare.rstrip("\n") + "\tGT:DP\t0/1:30\t1/1:44\n"
    assert parse_record(with_samples).INFO == parse_record(bare).INFO
    assert parse_record(with_samples).POS == parse_record(bare).POS


def test_header_lines_and_blank_lines_are_skipped():
    stream = [HEADER, COLUMNS, line(pos="1"), "\n", line(pos="2")]
    assert [r.POS for r in read_records(stream)] == [1, 2]
