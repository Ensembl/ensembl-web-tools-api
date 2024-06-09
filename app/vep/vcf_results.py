import vcfpy

from ..vep.model import Variant, Location, ReferenceVariantAllele, Metadata, PaginationMetadata, VepResultsResponse

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
            
        v = Variant(
            name = ";".join(record.ID) if len(record.ID) > 0 else ".",
            location = l,
            reference_allele = rva,
            alternative_alleles= []
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
    
    
    
    