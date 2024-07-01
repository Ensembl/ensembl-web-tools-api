from io import StringIO

import pytest
import vcfpy

from app.vep.models import vcf_results_model as model
from app.vep.utils.vcf_results import get_results_from_path, get_results_from_stream, _get_prediction_index_map, TARGET_COLUMNS
from app.vep.utils.vcf_results import _set_allele_type, _get_alt_allele_details, _get_csq_value

CSQ_DESCRIPTION = "Consequence annotations from Ensembl VEP. Format: Allele|Consequence|IMPACT|SYMBOL|Gene|Feature_type|Feature|BIOTYPE|EXON|INTRON|HGVSc|HGVSp|cDNA_position|CDS_position|Protein_position|Amino_acids|Codons|Existing_variation|REF_ALLELE|UPLOADED_ALLELE|DISTANCE|STRAND|FLAGS|SYMBOL_SOURCE|HGNC_ID|CANONICAL|SIFT|PolyPhen|AF|CLIN_SIG|SOMATIC|PHENO|MOTIF_NAME|MOTIF_POS|HIGH_INF_POS|MOTIF_SCORE_CHANGE|TRANSCRIPTION_FACTORS"

CSQ_1 = "T|upstream_gene_variant|MODIFIER|FAM138F|ENSG00000282591|Transcript|ENST00000631376.1|lncRNA||||||||||rs868831437|C|C/T|4978|-1||HGNC|HGNC:33581|YES|||0.4860||||||||"

CSQ_2 = "A|intergenic_variant|MODIFIER|||||||||||||||rs1555675005|T|T/A|||||||||||||||||"

CSQ_NO_FREQ = "T|upstream_gene_variant|MODIFIER|FAM138F|ENSG00000282591|Transcript|ENST00000631376.1|lncRNA||||||||||rs868831437|C|C/T|4978|-1||HGNC|HGNC:33581|YES|||||||||||"

CSQ_NO_CON = "T||MODIFIER|FAM138F|ENSG00000282591|Transcript|ENST00000631376.1|lncRNA||||||||||rs868831437|C|C/T|4978|-1||HGNC|HGNC:33581|YES|||||||||||"

TEST_VCF = f"""##fileformat=VCFv4.2
##fileDate=20160824
##INFO=<ID=CSQ,Number=.,Type=String,Description="{CSQ_DESCRIPTION}">
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO
chr19	82664	.	C	T	50	PASS	CSQ={CSQ_1}
chr19	82829	my_var	T	A	50	PASS	CSQ={CSQ_2}

"""


def test_get_prediction_index_map():
    
    expected_index = {TARGET_COLUMNS[x]:x for x in range(0,len(TARGET_COLUMNS))}
    
    csq_header = f"""Consequence annotations from Ensembl VEP. Format: {'|'.join(TARGET_COLUMNS)}"""
    
    prediction_index_map = _get_prediction_index_map(csq_header)
    assert  prediction_index_map == expected_index
 
def test_set_allele_type(): 
   
    outcomes = {
        "SNV":(True,True,True),
        "deletion":(True,False,False),
        "insertion":(False,True,False),
        "indel":(False,False,False),
        "substitution":(False,False,True),
    }
   
    for expected, args in outcomes.items():
        assert _set_allele_type(*args)[0] == expected
   
def test_get_csq_value(): 
    index_map = {
        "TEST_STR":0,
        "TEST_NUM":1,
        "TEST_BOOL":2,
        "TEST_EMPTY":3,
    }
    csq_values = ["foo",2,True,""]
    
    assert _get_csq_value(csq_values,"TEST_STR","ERROR",index_map) == "foo"
    assert _get_csq_value(csq_values,"TEST_NUM",-1,index_map) == 2
    assert _get_csq_value(csq_values,"TEST_BOOL",False,index_map)
    assert _get_csq_value(csq_values,"TEST_MISSING","ERROR",index_map) == "ERROR"
    assert _get_csq_value(csq_values,"TEST_EMPTY",None,index_map) == None
 
       
def test_get_alt_allele_details():
    #alt: vcfpy.AltRecord, csqs: List[str], index_map: Dict
    altRec = vcfpy.Substitution("SNV",value="T")
    
    index_map = _get_prediction_index_map(CSQ_DESCRIPTION)
    
    csq_list = [CSQ_1,CSQ_2,CSQ_NO_FREQ]
    
    # model.AlternativeVariantAllele
    results = _get_alt_allele_details(altRec, csq_list, index_map)
    
    assert type(results) == model.AlternativeVariantAllele 
    assert results.allele_sequence == "T"
    assert results.allele_type == "SNV"
    assert results.representative_population_allele_frequency == 0.4860
    assert len(results.predicted_molecular_consequences) == 2
    assert results.predicted_molecular_consequences[0].feature_type == model.FeatureType.transcript
    assert results.predicted_molecular_consequences[0].biotype == "lncRNA"
    assert results.predicted_molecular_consequences[0].gene_symbol == "FAM138F"
    
def test_get_alt_allele_no_consequence():
    #alt: vcfpy.AltRecord, csqs: List[str], index_map: Dict
    altRec = vcfpy.Substitution("SNV",value="T")
    
    index_map = _get_prediction_index_map(CSQ_DESCRIPTION)
    
    csq_list = [CSQ_NO_CON]
    
    # model.AlternativeVariantAllele
    results = _get_alt_allele_details(altRec, csq_list, index_map)
    
    assert type(results) == model.AlternativeVariantAllele 
    assert results.allele_sequence == "T"
    assert len(results.predicted_molecular_consequences) == 1 
    assert results.predicted_molecular_consequences[0].consequences == []
 
           
def test_get_alt_allele_details_intergenic():
    #alt: vcfpy.AltRecord, csqs: List[str], index_map: Dict
    altRec = vcfpy.Substitution("SNV",value="A")
    
    index_map = _get_prediction_index_map(CSQ_DESCRIPTION)
    
    csq_list = [CSQ_2]
    
    # model.AlternativeVariantAllele
    results = _get_alt_allele_details(altRec, csq_list, index_map)
    
    assert type(results) == model.AlternativeVariantAllele 
    assert results.allele_sequence == "A"
    assert results.allele_type == "SNV"
    assert len(results.predicted_molecular_consequences) == 1 
    assert results.predicted_molecular_consequences[0].feature_type == None
    assert len(results.predicted_molecular_consequences[0].consequences) == 1 
    assert results.predicted_molecular_consequences[0].consequences[0] == "intergenic_variant"

  
    
def test_get_results_from_stream(): 
    results = get_results_from_stream(100, 0, StringIO(TEST_VCF))
    
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
    
    with open("dump.json", "w") as test_dump:
        test_dump.write(results.json())

    assert len(results.variants) == 100

