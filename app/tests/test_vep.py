import json
from io import StringIO

import pytest

from ..main import app, get_db_path

from ..vep.vcf_results import get_results_from_path, get_results_from_stream, _get_prediction_index_map, TARGET_COLUMNS

CSQ_DESCRIPTION = "Consequence annotations from Ensembl VEP. Format: Allele|Consequence|IMPACT|SYMBOL|Gene|Feature_type|Feature|BIOTYPE|EXON|INTRON|HGVSc|HGVSp|cDNA_position|CDS_position|Protein_position|Amino_acids|Codons|Existing_variation|REF_ALLELE|UPLOADED_ALLELE|DISTANCE|STRAND|FLAGS|SYMBOL_SOURCE|HGNC_ID|CANONICAL|SIFT|PolyPhen|AF|CLIN_SIG|SOMATIC|PHENO|MOTIF_NAME|MOTIF_POS|HIGH_INF_POS|MOTIF_SCORE_CHANGE|TRANSCRIPTION_FACTORS"

TEST_VCF = f"""##fileformat=VCFv4.2
##fileDate=20160824
##INFO=<ID=CSQ,Number=.,Type=String,Description="{CSQ_DESCRIPTION}">
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO
chr19	82664	.	C	T	50	PASS	CSQ=T|upstream_gene_variant|MODIFIER|FAM138F|ENSG00000282591|Transcript|ENST00000631376.1|lncRNA||||||||||rs868831437|C|C/T|4978|-1||HGNC|HGNC:33581|YES|||0.4860||||||||
chr19	82829	my_var	T	A	50	PASS	CSQ=A|intergenic_variant|MODIFIER|||||||||||||||rs1555675005|T|T/A|||||||||||||||||

"""


def test_load_csq_description_happy():
    
    expected_index = {TARGET_COLUMNS[x]:x for x in range(0,len(TARGET_COLUMNS))}
    
    csq_header = f"""Consequence annotations from Ensembl VEP. Format: {'|'.join(TARGET_COLUMNS)}"""
    
    prediction_index_map = _get_prediction_index_map(csq_header)
    assert  prediction_index_map == expected_index
    
def test_get_results_from_stream(): 
    
    results = get_results_from_stream(100,0,StringIO(TEST_VCF))
    
    expected_index = {TARGET_COLUMNS[x]:x for x in range(0,len(TARGET_COLUMNS))}
    
    assert len(results.variants) == 2
    
    assert results.metadata.pagination.page == 0
    assert results.metadata.pagination.per_page == 100
    assert results.metadata.pagination.total == 2
    
    assert results.variants[0].name == "."
    assert results.variants[1].name == "my_var"
    
    assert results.variants[0].reference_allele.allele_sequence == "C"
    assert results.variants[1].reference_allele.allele_sequence == "T"
    
    assert results.variants[0].alternative_alleles[0].allele_sequence == "T"
    assert results.variants[0].alternative_alleles[0].allele_type == "SNV"
    
    
    assert results.variants[0].alternative_alleles[0].representative_population_allele_frequency == 0.4860
    assert results.variants[1].alternative_alleles[0].representative_population_allele_frequency == None
    


@pytest.mark.skip(reason="Used to test against a real VCF file")
def test_get_results_with_file_and_dump(): 

    vcf_path = "/Users/jon/Programming/vep-vcf-results/vep-output-phase1-options-plus-con.vcf"
    results = get_results_from_path(100,2,vcf_path)
    
    expected_index = {TARGET_COLUMNS[x]:x for x in range(0,len(TARGET_COLUMNS))}
    
    with open("dump.json","w") as test_dump:
        test_dump.write(results.json())

    assert len(results.variants) == 100