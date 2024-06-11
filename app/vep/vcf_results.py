from typing import Dict, Any

import vcfpy

from ..vep.model import *

TARGET_COLUMNS = [
                    "Allele", "AF", "Consequence", "Feature", "Feature_type",
                    "BIOTYPE", "CANONICAL", "SYMBOL","Gene", "STRAND",
                    "IMPACT"
                ]
                
#Taken from https://github.com/Ensembl/ensembl-hypsipyle/blob/main/common/file_model/variant.py#L142
#Needs to be moved into a shared module
def _set_allele_type(alt_one_bp: bool, ref_one_bp: bool, ref_alt_equal_bp: bool):         
        match [alt_one_bp, ref_one_bp, ref_alt_equal_bp]:
            case [True, True, True]: 
                allele_type = "SNV" 
                SO_term = "SO:0001483"

            case [True, False, False]: 
                allele_type = "deletion" 
                SO_term = "SO:0000159"

            case [False, True, False]: 
                allele_type = "insertion"
                SO_term = "SO:0000667"

            case [False, False, False]: 
                allele_type = "indel"
                SO_term = "SO:1000032"

            case [False, False, True]: 
                allele_type = "substitution"
                SO_term = "SO:1000002"   
        return allele_type, SO_term
        
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
            
            cons = _get_csq_value(csq_values, "Consequence", "", index_map).split("&") 
            if csq_values[index_map["Feature_type"]] == "Transcript": 
                
                is_cononical = _get_csq_value(csq_values, "CANONICAL", "NO", index_map) == "YES" 

                #It looks like for Feature_type = Transcript that we always have a STRAND value  
                strand = Strand.reverse if _get_csq_value(csq_values, "STRAND", "1", index_map) == "-1" else Strand.forward

                consequences.append(
                    PredictedTranscriptConsequence(
                    feature_type= FeatureType.transcript,
                    stable_id = _get_csq_value(csq_values, "Feature", "", index_map),
                    gene_stable_id = _get_csq_value(csq_values, "Gene", "", index_map),
                    biotype = _get_csq_value(csq_values, "BIOTYPE", "", index_map),
                    is_canonical = is_cononical,
                    gene_symbol = _get_csq_value(csq_values, "SYMBOL", "", index_map),
                    consequences= cons,
                    strand= strand,
                    )
                )
            elif "intergenic_variant" in cons:
                consequences.append(
                    PredictedIntergenicConsequence(
                        feature_type="",
                        consequences = ['intergenic_variant'],
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
    count = 0
    offset = page_size * page
    
    #This is very slow. We need to find a better way of handling this. vcfpy __next__ might be the key as it reads lines
    for r in vcf_records:
        count += 1
        if count >= offset:
            break
        
    #build page
    variants = []
    count = 0
    
    #populate page
    for record in vcf_records: 
        chrom = record.CHROM
        if chrom.startswith("chr"):
            chrom = chrom[3:]
            
        ref_len = len(record.REF)

        #https://github.com/bihealth/vcfpy/blob/697768d032b6b476766fb4c524c91c8d24559330/vcfpy/record.py#L63
        #end does not look like it is implemented.
        #Using https://github.com/Penghui-Wang/PyVCF/blob/master/vcf/model.py#L190 from competting vcf module 
        l = Location(
            region_name = chrom,
            start = record.begin,
            end = record.end if record.end else record.begin + ref_len
        )
            
        rva = ReferenceVariantAllele(
            allele_sequence = record.REF
        )
        
        longest_alt = len(max([a.value for a in record.ALT], key=len))
        
        
        alt_alleles = [
            _get_alt_allele_details(alt,record, prediction_index_map) for alt in record.ALT
        ]
            
        v = Variant(
            name = ";".join(record.ID) if len(record.ID) > 0 else ".",
            location = l,
            reference_allele = rva,
            alternative_alleles= alt_alleles,
            allele_type = _set_allele_type(longest_alt <2, ref_len < 2, longest_alt == ref_len)[0],
        )
        variants.append(v)
        
        count+= 1   
        if count >= page_size: 
            break
            
    #Also very slow. We could compute this and add it to the VCF header
    total = offset + count
    for r in vcf_records:
        total += 1
    
    meta = Metadata(
        pagination = PaginationMetadata(
            page=page,
            per_page=page_size,
            total= total
        )
    )
       
         
    return VepResultsResponse(
        metadata= meta,
        variants= variants
    )
    
    
    
    