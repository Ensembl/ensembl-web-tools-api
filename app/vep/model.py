# generated by datamodel-codegen:
#   filename:  APISpecification.yaml
#   timestamp: 2024-06-08T13:06:56+00:00

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class PaginationMetadata(BaseModel):
    page: float
    per_page: float
    total: float


class FeatureType(Enum):
    transcript = 'transcript'


class Strand(Enum):
    forward = 'forward'
    reverse = 'reverse'


class PredictedTranscriptConsequence(BaseModel):
    feature_type: FeatureType
    stable_id: str = Field(..., description='transcript stable id, versioned')
    gene_stable_id: str = Field(..., description='gene stable id, versioned')
    biotype: str
    is_canonical: bool
    consequences: List[str]
    strand: Strand


class ReferenceVariantAllele(BaseModel):
    allele_sequence: str


class Location(BaseModel):
    region_name: str
    start: float
    end: float


class Metadata(BaseModel):
    pagination: PaginationMetadata


class AlternativeVariantAllele(BaseModel):
    allele_sequence: str
    allele_type: str
    representative_population_allele_frequency: Optional[float] = None
    predicted_molecular_consequences: List[PredictedTranscriptConsequence]


class Variant(BaseModel):
    name: str = Field(..., description="User's name for the variant; optional")
    location: Optional[Location] = None
    reference_allele: ReferenceVariantAllele
    alternative_alleles: List[AlternativeVariantAllele]


class VepResultsResponse(BaseModel):
    metadata: Metadata
    variants: List[Variant]
