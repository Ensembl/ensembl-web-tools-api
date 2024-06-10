import json

import pytest

from ..main import app, get_db_path

from ..vep.vcf_results import get_results, _get_prediction_index_map, TARGET_COLUMNS


def test_load_csq_description_happy():
    
    expected_index = {TARGET_COLUMNS[x]:x for x in range(0,len(TARGET_COLUMNS))}
    
    csq_header = f"""Consequence annotations from Ensembl VEP. Format: {'|'.join(TARGET_COLUMNS)}"""
    
    prediction_index_map = _get_prediction_index_map(csq_header)
    assert  prediction_index_map == expected_index

@pytest.mark.skip(reason="Used to test against a real VCF file")
def test_get_results_with_file(): 

    vcf_path = "/Users/jon/Programming/vep-vcf-results/vep-output-phase1-options-plus-con.vcf"
    results = get_results(100,2,vcf_path)
    
    expected_index = {TARGET_COLUMNS[x]:x for x in range(0,len(TARGET_COLUMNS))}
    
    with open("dump.json","w") as test_dump:
        test_dump.write(results.json())

    assert len(results.variants) == 100