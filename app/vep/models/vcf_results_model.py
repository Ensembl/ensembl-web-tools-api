from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

class VcfMetadata(BaseModel):
    variant_count: int = Field(
        description="Total number of variant records in the VCF file"
    )
    header_count: int = Field(
        description="Number of header rows in the VCF file"
    )

class PaginationMetadata(BaseModel):
    page: int
    per_page: int
    total: int


class PredictedIntergenicConsequence(BaseModel):
    feature_type: Any | None = Field(
        default=None,
        description="The value of this field is always null. The presence of null in this field will serve as a marker that this is a consequence of an intergenic variant.",
    )
    consequences: list[str] = Field(
        default=['intergenic_variant'],
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
    gene_symbol: str | None = None
    biotype: str
    is_canonical: bool
    consequences: list[str]
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
    representative_population_allele_frequency: float | None = None
    predicted_molecular_consequences: list[
        PredictedTranscriptConsequence | PredictedIntergenicConsequence
    ]


class Variant(BaseModel):
    name: str | None = Field(
        default=None,
        description="User's name for the variant; optional"
    )
    allele_type: str
    location: Location
    reference_allele: ReferenceVariantAllele
    alternative_alleles: list[AlternativeVariantAllele]


class VepResultsResponse(BaseModel):
    metadata: Metadata
    variants: list[Variant]
