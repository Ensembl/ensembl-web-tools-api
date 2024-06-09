from typing import Dict

import vcfpy

from ..vep.model import *

TARGET_COLUMNS = [
                    "Allele", "AF", "Consequence", "Feature", "Feature_type",
                    "BIOTYPE", "CANONICAL", "SYMBOL","Gene", "STRAND",
                    "IMPACT"
                ]

def get_prediction_index_map(csq_header:str, target_columns=TARGET_COLUMNS) -> dict: 
    
    csq_header = csq_header.split(":")[-1].strip()
    csq_headers = csq_header.split("|")
           
    map = {
        csq_headers[index]:index for index in range(len(csq_headers)) if csq_headers[index] in target_columns
    }
    
    ##TODO add exception if len(map) != len(TARGET_COLUMNS)
    
    return map

def get_alt_allele_details(alt:vcfpy.AltRecord,rec:vcfpy.Record,index_map:Dict) -> AlternativeVariantAllele:
    
    frequency = None
    consequences = []
    
    for str_csq in rec.INFO["CSQ"]:
            csq_values = str_csq.split("|")
            
            if csq_values[index_map["Allele"]] != alt.value: 
                continue
                
            if "AF" in index_map and csq_values[index_map["AF"]]:
                frequency = csq_values[index_map["AF"]]
                
            if csq_values[index_map["Feature_type"]] == "Transcript": 
                
                is_cononical = True if "CANONICAL" in index_map and csq_values[index_map["CANONICAL"]] == "YES" else False
                
                cons = []
                if "Consequence" in index_map and csq_values[index_map["Consequence"]]: 
                    cons = csq_values[index_map["Consequence"]].split("&")
                 
                #Do we all ways have a strand? check!   
                strand = Strand.reverse if "STRAND" in index_map and csq_values[index_map["STRAND"]] == "-1" else Strand.forward
                
                biotype = csq_values[index_map["BIOTYPE"]] if "BIOTYPE" in index_map and csq_values[index_map["BIOTYPE"]] else ""
                
                consequences.append(
                    PredictedTranscriptConsequence(
                    feature_type= FeatureType.transcript,
                    stable_id = "",
                    gene_stable_id = "",
                    biotype = biotype,
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
    prediction_index_map = get_prediction_index_map(csq_details)
    
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
            get_alt_allele_details(alt,record, prediction_index_map) for alt in record.ALT
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
    
    
    
    