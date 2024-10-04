from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional, Union

from pydantic import BaseModel, Field

class PaginationMetadata(BaseModel):
    page: int
    per_page: int
    total: int

class PredictedIntergenicConsequence(BaseModel):
    feature_type: Optional[Any] = Field(
        default=None,
        description="The value of this field is always null. The presence of null in this field will serve as a marker that this is a consequence of an intergenic variant.",
    )
    consequences: List[str] = Field(
        ...,
        description="The only expected member of this array will be the string 'intergenic_variant'",
    )


class FeatureType(Enum):
    transcript = "transcript"


class Strand(Enum):
    forward = "forward"
    reverse = "reverse"


class PredictedTranscriptConsequence(BaseModel):
    feature_type: FeatureType
    stable_id: str = Field(..., description="transcript stable id, versioned")
    gene_stable_id: str = Field(..., description="gene stable id, versioned")
    gene_symbol: Optional[str] = None
    biotype: str
    is_canonical: bool
    consequences: List[str]
    strand: Strand


class ReferenceVariantAllele(BaseModel):
    allele_sequence: str


class Location(BaseModel):
    region_name: str
    start: int
    end: int

class Metadata(BaseModel):
    pagination: PaginationMetadata



class AlternativeVariantAllele(BaseModel):
    allele_sequence: str
    allele_type: str
    representative_population_allele_frequency: Optional[float] = None
    predicted_molecular_consequences: List[
        Union[PredictedTranscriptConsequence, PredictedIntergenicConsequence]
    ]


class Variant(BaseModel):
    name: Optional[str] = Field(
        default=None,
        description="User's name for the variant; optional"
    )
    allele_type: str
    location: Location
    reference_allele: ReferenceVariantAllele
    alternative_alleles: List[AlternativeVariantAllele]


class VepResultsResponse(BaseModel):
    metadata: Metadata
    variants: List[Variant]
