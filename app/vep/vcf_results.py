from typing import Dict, Any

import vcfpy

from ..vep.model import *

TARGET_COLUMNS = [
                    "Allele", "AF", "Consequence", "Feature", "Feature_type",
                    "BIOTYPE", "CANONICAL", "SYMBOL","Gene", "STRAND",
                    "IMPACT"
                ]

def _get_prediction_index_map(csq_header:str, target_columns=TARGET_COLUMNS) -> dict: 
    
    csq_header = csq_header.split(":")[-1].strip()
    csq_headers = csq_header.split("|")
           
    map = {
        csq_headers[index]:index for index in range(len(csq_headers)) if csq_headers[index] in target_columns
    }
    
    ##TODO add exception if len(map) != len(TARGET_COLUMNS)
    
    return map

def _get_csq_value(csq_values:List, csq_key:str, default_value:Any, index_map:Dict) -> Any:
    if csq_key in index_map and csq_values[index_map[csq_key]]: 
        return csq_values[index_map[csq_key]]
    return default_value
    

def _get_alt_allele_details(alt:vcfpy.AltRecord,rec:vcfpy.Record,index_map:Dict) -> AlternativeVariantAllele:
    
    frequency = None
    consequences = []
    
    for str_csq in rec.INFO["CSQ"]:
            csq_values = str_csq.split("|")
            
            if csq_values[index_map["Allele"]] != alt.value: 
                continue
                
            frequency = _get_csq_value(csq_values, "AF", None, index_map)
                
            if csq_values[index_map["Feature_type"]] == "Transcript": 
                
                is_cononical = _get_csq_value(csq_values, "CANONICAL", "NO", index_map) == "YES" 
                cons = _get_csq_value(csq_values, "Consequence", "", index_map).split("&")
                 
                #It looks like for Feature_type = Transcript that we always have a STRAND value  
                strand = Strand.reverse if _get_csq_value(csq_values, "STRAND", "1", index_map) == "-1" else Strand.forward

                consequences.append(
                    PredictedTranscriptConsequence(
                    feature_type= FeatureType.transcript,
                    stable_id = _get_csq_value(csq_values, "Feature", "", index_map),
                    gene_stable_id = _get_csq_value(csq_values, "Gene", "", index_map),
                    biotype = _get_csq_value(csq_values, "BIOTYPE", "", index_map),
                    is_canonical = is_cononical,
                    consequences= cons,
                    strand= strand,
                    )
                )
                      
    return AlternativeVariantAllele(
        allele_sequence=alt.value,
        allele_type=alt.type,
        representative_population_allele_frequency=frequency,
        predicted_molecular_consequences= consequences
    )
            

def get_results(page_size:int,page:int,vcf_path:str) -> VepResultsResponse: 
    # Check file file exists 
    
    # Load vcf 
    vcf_records = vcfpy.Reader.from_path(vcf_path)
    
    # Parse csq header 
    csq_details = vcf_records.header.get_info_field_info("CSQ").description
    prediction_index_map = _get_prediction_index_map(csq_details)
    
    # handle offset 
    offset = page_size * page
    
    #build page
    variants = []
    count = 0
    
    #populate page
    for record in vcf_records: 
        chrom = record.CHROM
        if chrom.startswith("chr"):
            chrom = chrom[3:]
            
        
        l = Location(
            region_name = chrom,
            start = record.begin,
            end = record.end if record.end else record.begin
        )
            
        rva = ReferenceVariantAllele(
            allele_sequence = record.REF
        )
        
        alt_alleles = [
            _get_alt_allele_details(alt,record, prediction_index_map) for alt in record.ALT
        ]
            
        v = Variant(
            name = ";".join(record.ID) if len(record.ID) > 0 else ".",
            location = l,
            reference_allele = rva,
            alternative_alleles= alt_alleles
        )
        variants.append(v)
        
        count+= 1   
        if count >= page_size: 
            break
    
    meta = Metadata(
        pagination = PaginationMetadata(
            page=page,
            per_page=page_size,
            total= 10000
        )
    )
       
         
    return VepResultsResponse(
        metadata= meta,
        variants= variants
    )
    
    
    
    