""" Module for loading a VCF and parsing it into a VepResultsResponse
object as defined in APISpecification"""

from io import StringIO
import subprocess
from pydantic import FilePath
import vcfpy
from vep.models import vcf_results_model as model

TARGET_COLUMNS = [
    "Allele",
    "AF",
    "Consequence",
    "Feature",
    "Feature_type",
    "BIOTYPE",
    "CANONICAL",
    "SYMBOL",
    "Gene",
    "STRAND",
    "IMPACT",
]

META_FILE = "results_meta.json"

# Taken from https://github.com/Ensembl/ensembl-hypsipyle
# main/common/file_model/variant.py#L142
# Needs to be moved into a shared module
def _set_allele_type(alt_one_bp: bool, ref_one_bp: bool, ref_alt_equal_bp: bool):
    """Create a allele type for a variant based on Variation
    teams logic using ref and largest alt allele sizes"""
    match [alt_one_bp, ref_one_bp, ref_alt_equal_bp]:
        case [True, True, True]:
            allele_type = "SNV"
            so_term = "SO:0001483"

        case [True, False, False]:
            allele_type = "deletion"
            so_term = "SO:0000159"

        case [False, True, False]:
            allele_type = "insertion"
            so_term = "SO:0000667"

        case [False, False, False]:
            allele_type = "indel"
            so_term = "SO:1000032"

        case [False, False, True]:
            allele_type = "substitution"
            so_term = "SO:1000002"
    return allele_type, so_term


def _get_prediction_index_map(
    csq_header: str, target_columns: list[str] = TARGET_COLUMNS
) -> dict[str, int]:
    """Creates a dictionary of column indexes based
    on the CSQ info description"""
    csq_header = csq_header.split(":")[-1].strip()
    csq_headers = csq_header.split("|")

    map_index = {
        csq_headers[index]: index
        for index in range(len(csq_headers))
        if csq_headers[index] in target_columns
    }

    #if len(map_index) != len(target_columns): #CANONICAL is often missing
    #    raise Exception(f"Required columns missing from CSQ header: {map_index.keys()}")

    return map_index


def _get_csq_value(
    csq_values: list[str], csq_key: str, default_value: str | None, index_map: dict[str, int]
):
    """Helper method to return CSQ values or a default value
    if either the key or the value is missing"""
    if csq_key in index_map and csq_values[index_map[csq_key]]:
        return csq_values[index_map[csq_key]]
    return default_value


def _get_alt_allele_details(
    alt: str, ref: str, csqs: list[str], index_map: dict[str, int]
) -> model.AlternativeVariantAllele:
    """Creates  AlternativeVariantAllele based on
    target alt allele and CSQ entires"""
    frequency = None
    consequences = []
    allele_type = _set_allele_type(
        len(alt) < 2, len(ref) < 2, len(alt) == len(ref)
    )[0]

    for str_csq in csqs:
        csq_values = str_csq.split("|")

        if csq_values[index_map["Allele"]] != alt:
            continue

        frequency = _get_csq_value(csq_values, "AF", frequency, index_map)

        cons = _get_csq_value(csq_values, "Consequence", "", index_map)
        if len(cons) == 0:
            cons = []
        else:
            cons = cons.split("&")
        if csq_values[index_map["Feature_type"]] == "Transcript":
            is_cononical = (
                _get_csq_value(csq_values, "CANONICAL", "NO", index_map) == "YES"
            )

            # It looks like for Feature_type = Transcript that we always have a STRAND value
            strand = (
                model.Strand.reverse
                if _get_csq_value(csq_values, "STRAND", "1", index_map) == "-1"
                else model.Strand.forward
            )

            consequences.append(
                model.PredictedTranscriptConsequence(
                    feature_type=model.FeatureType.transcript,
                    stable_id=_get_csq_value(csq_values, "Feature", "", index_map),
                    gene_stable_id=_get_csq_value(csq_values, "Gene", "", index_map),
                    biotype=_get_csq_value(csq_values, "BIOTYPE", "", index_map),
                    is_canonical=is_cononical,
                    gene_symbol=_get_csq_value(csq_values, "SYMBOL", None, index_map),
                    consequences=cons,
                    strand=strand,
                )
            )
        elif "intergenic_variant" in cons:
            consequences.append(
                model.PredictedIntergenicConsequence(
                    feature_type=None,
                    consequences=["intergenic_variant"],
                )
            )

    return model.AlternativeVariantAllele(
        allele_sequence=alt,
        allele_type=allele_type,
        representative_population_allele_frequency=frequency,
        predicted_molecular_consequences=consequences,
    )


def _get_meta(vcf_path: FilePath) -> model.VcfMetadata:
    """Helper method to manage metainfo for a VCF file"""

    meta_path = vcf_path.with_name(META_FILE)
    if not meta_path.exists():
        variant_count_str = subprocess.check_output(
            f"bcftools stats {vcf_path} | grep 'number of records:'",
            shell=True, text=True
        )
        header_count_str = subprocess.check_output(
            f"bcftools view -h {vcf_path} | wc -l",
            shell=True, text=True
        )
        vcf_info = model.VcfMetadata(
            variant_count=int(variant_count_str.split(":")[-1]),
            header_count=int(header_count_str)
        )
        with open(meta_path, "w") as meta_file:
            meta_file.write(vcf_info.model_dump_json())
    else:
        with open(meta_path, "r") as meta_file:
            vcf_info = model.VcfMetadata.model_validate_json(meta_file.read())
    return vcf_info


def get_results_from_path(
    page_size: int, page: int, vcf_path: FilePath
) -> model.VepResultsResponse:
    """Returns a page of VCF data from the given filepath.
    Slices the input VCF file to a smaller one
    and converts it to stream for get_results_from_stream"""
    if not vcf_path.exists():
        raise Exception(f"VEP results file not found at {vcf_path}")

    # Fetch a pageful of variant records with headers
    vcf_info = _get_meta(vcf_path)
    total = vcf_info.variant_count
    page = max(page, 1) # normalize values
    page_size = min(max(page_size, 0), total)
    row_offset = min(page * page_size, total) + vcf_info.header_count
    vcf_headers = subprocess.check_output( # fetch all header rows
        f"bcftools view -h {vcf_path}", shell=True, text=True
    )
    vcf_slice = subprocess.check_output( # fetch subset of variant rows
        f"bcftools view {vcf_path} | head -n{row_offset} | tail -n{page_size}",
        shell=True, text=True
    )
    vcf_stream = StringIO(vcf_headers + vcf_slice)

    return get_results_from_stream(page_size, page, total, vcf_stream)


def get_results_from_stream(
    page_size: int, page: int, total: int, vcf_stream: StringIO
) -> model.VepResultsResponse:
    """Helper method to convert a filestream to VCF records for _get_results_from_vcfpy"""

    # Load vcf
    vcf_records = vcfpy.Reader.from_stream(vcf_stream)
    return _get_results_from_vcfpy(page_size, page, total, vcf_records)


def _get_results_from_vcfpy(
    page_size: int, page: int, total: int, vcf_records: vcfpy.Reader
) -> model.VepResultsResponse:
    """Generates a page of VCF data in the format described in
    APISpecification.yaml for a given VCFPY reader"""

    # Parse csq header
    prediction_index_map = _get_prediction_index_map(
        vcf_records.header.get_info_field_info("CSQ").description
    )

    variants = []
    # populate variants page
    if page*page_size <= total:
        for record in vcf_records:
            if record is None:
                break
            if record.CHROM.startswith("chr"):
                record.CHROM = record.CHROM[3:]

            ref_len = len(record.REF)

            # https://github.com/bihealth/vcfpy/blob/697768d032b6b476766fb4c524c91c8d24559330/vcfpy/record.py#L63
            # end does not look like it is implemented.
            # https://github.com/Penghui-Wang/PyVCF/blob/master/vcf/model.py#L190
            # from competing vcf module
            location = model.Location(
                region_name=record.CHROM,
                start=record.POS,
                end=record.POS + ref_len,
            )
            longest_alt = len(max((a.value for a in record.ALT), key=len))

            alt_allele_strings = list(set([
                csq_string.split("|")[prediction_index_map["Allele"]]
                for csq_string in record.INFO["CSQ"]
            ]))

            alt_alleles = [
                _get_alt_allele_details(alt, record.REF, record.INFO["CSQ"], prediction_index_map)
                for alt in alt_allele_strings
            ]

            variants.append(
                model.Variant(
                    name=";".join(record.ID) if len(record.ID) > 0 else ".",
                    location=location,
                    reference_allele=model.ReferenceVariantAllele(
                        allele_sequence=record.REF
                    ),
                    alternative_alleles=alt_alleles,
                    allele_type=_set_allele_type(
                        longest_alt < 2, ref_len < 2, longest_alt == ref_len
                    )[0],
                )
            )

    return model.VepResultsResponse(
        metadata=model.Metadata(
            pagination=model.PaginationMetadata(
                page=page, per_page=page_size, total=total
            )
        ),
        variants=variants,
    )
