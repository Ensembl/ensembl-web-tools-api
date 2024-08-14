import vcfpy

path_to_file = '/Users/andrey/Downloads/vep-test/vep-output-example-without-phase1-options.vcf'

vcf_reader = vcfpy.Reader.from_path(path_to_file)

def get_consequence_info_index_map(reader: vcfpy.Reader):
    consequence_headers_description = vcf_reader.header.get_info_field_info("CSQ").description
    consequence_header_names = consequence_headers_description.split("Format: ")[1].split("|")
    index_map = {
        consequence_header_names[index]: index
        for index in range(len(consequence_header_names))
    }
    return index_map

def get_variant_name_from_record(record: vcfpy.Record):
    return record.ID or '.'

def get_region_name_from_record(record: vcfpy.Record):
    region_name = record.CHROM
    if region_name.startswith("chr"):
        region_name = region_name[3:]
    return region_name

def get_rerefence_allele_from_record(record: vcfpy.Record):
    return record.REF

def get_start_from_record(record: vcfpy.Record):
    return record.begin

def get_reference_allele_from_record(record: vcfpy.Record):
    return record.REF

def get_alternative_allele_from_record(record: vcfpy.Record):
    return record.REF

def get_consequences_from_record(record: vcfpy.Record):
    consequence_info = record.INFO["CSQ"] # That's going to be an array
    result = []

    for item in consequence_info:
        item = item.split('|')
        record = {
            "alternative_allele": item[consequence_info_index_map['Allele']],
            "consequences": item[consequence_info_index_map['Consequence']].split("&"),
            "reference_allele": item[consequence_info_index_map['REF_ALLELE']], # Could probably just do record.REF
            "feature_type": item[consequence_info_index_map['Feature_type']] or None,
            "feature_id": item[consequence_info_index_map['Feature']] or None,
            "biotype": item[consequence_info_index_map['BIOTYPE']] or None,
            "gene_id": item[consequence_info_index_map['Gene']] or None,
            "gene_symbol": item[consequence_info_index_map['SYMBOL']] or None,
        }
        result.append(record)
    return result


consequence_info_index_map = get_consequence_info_index_map(vcf_reader)


# TODO: add variant type (SNV, deletion, insertion, etc.)
# TODO: add variant end coordinate
# TODO: add transcript canonical info
def parse_vcf_data():
    count = 0

    for record in vcf_reader:
        parsed_record = {
            "variant_name": get_variant_name_from_record(record),
            "region_name": get_region_name_from_record(record),
            "start": get_start_from_record(record),
            "reference_allele": get_rerefence_allele_from_record(record),
            "consequences": get_consequences_from_record(record)
        }
        yield parsed_record
        count += 1


