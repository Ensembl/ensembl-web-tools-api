import unittest
from pydantic import ValidationError

from vep.models.vcf_results_model import (
    PaginationMetadata,
    PredictedIntergenicConsequence,
    PredictedTranscriptConsequence,
    FeatureType,
    Strand,
    ReferenceVariantAllele,
    Location,
    AlternativeVariantAllele,
    Variant,
    Metadata,
    VepResultsResponse,
)


class TestOptionalFields(unittest.TestCase):

    def test_predicted_intergenic_consequence(self):
        consequence = PredictedIntergenicConsequence(
            feature_type=None,
            consequences=["intergenic_variant"]
        )
        self.assertIsNone(consequence.feature_type)
        self.assertEqual(consequence.consequences, ["intergenic_variant"])

        # Missing consequences should raise a ValidationError
        with self.assertRaises(ValidationError):
            PredictedIntergenicConsequence(feature_type=None)

    def test_predicted_transcript_consequence(self):
        consequence = PredictedTranscriptConsequence(
            feature_type=FeatureType.transcript,
            stable_id="ENST00000367770.8",
            gene_stable_id="ENSG00000157764.13",
            gene_symbol=None,
            biotype="protein_coding",
            is_canonical=True,
            consequences=["missense_variant"],
            strand=Strand.forward,
        )
        self.assertIsNone(consequence.gene_symbol)

        # Valid instance without explicitly setting gene_symbol (default=None)
        consequence_no_symbol = PredictedTranscriptConsequence(
            feature_type=FeatureType.transcript,
            stable_id="ENST00000367770.8",
            gene_stable_id="ENSG00000157764.13",
            biotype="protein_coding",
            is_canonical=True,
            consequences=["missense_variant"],
            strand=Strand.forward,
        )
        self.assertIsNone(consequence_no_symbol.gene_symbol)

    def test_alternative_variant_allele(self):
        alternative_allele = AlternativeVariantAllele(
            allele_sequence="A",
            allele_type="insertion",
            representative_population_allele_frequency=None,
            predicted_molecular_consequences=[
                PredictedIntergenicConsequence(
                    feature_type=None,
                    consequences=["intergenic_variant"],
                )
            ],
        )
        self.assertIsNone(alternative_allele.representative_population_allele_frequency)

        # Valid instance without explicitly setting representative_population_allele_frequency (default=None)
        alternative_allele_no_freq = AlternativeVariantAllele(
            allele_sequence="A",
            allele_type="insertion",
            predicted_molecular_consequences=[
                PredictedIntergenicConsequence(
                    feature_type=None,
                    consequences=["intergenic_variant"],
                )
            ],
        )
        self.assertIsNone(alternative_allele_no_freq.representative_population_allele_frequency)

    def test_variant(self):
        variant = Variant(
            name=None,
            allele_type="SNP",
            location=Location(region_name="1", start=10000, end=10001),
            reference_allele=ReferenceVariantAllele(allele_sequence="C"),
            alternative_alleles=[
                AlternativeVariantAllele(
                    allele_sequence="T",
                    allele_type="SNP",
                    predicted_molecular_consequences=[
                        PredictedIntergenicConsequence(
                            feature_type=None,
                            consequences=["intergenic_variant"]
                        )
                    ]
                )
            ]
        )
        self.assertIsNone(variant.name)

        # Valid instance without explicitly setting name (default=None)
        variant_no_name = Variant(
            allele_type="SNP",
            location=Location(region_name="1", start=10000, end=10001),
            reference_allele=ReferenceVariantAllele(allele_sequence="C"),
            alternative_alleles=[
                AlternativeVariantAllele(
                    allele_sequence="T",
                    allele_type="SNP",
                    predicted_molecular_consequences=[
                        PredictedIntergenicConsequence(
                            feature_type=None,
                            consequences=["intergenic_variant"]
                        )
                    ]
                )
            ]
        )
        self.assertIsNone(variant_no_name.name)

    def test_metadata_required(self):
        metadata = Metadata(
            pagination=PaginationMetadata(page=1, per_page=10, total=100)
        )
        self.assertEqual(metadata.pagination.page, 1)

        # Invalid instance without pagination - should raise ValidationError
        with self.assertRaises(ValidationError):
            Metadata()

    def test_vep_results_response(self):
        metadata = Metadata(
            pagination=PaginationMetadata(page=1, per_page=10, total=100)
        )
        variant = Variant(
            name=None,
            allele_type="SNV",
            location=Location(region_name="1", start=10000, end=10001),
            reference_allele=ReferenceVariantAllele(allele_sequence="A"),
            alternative_alleles=[
                AlternativeVariantAllele(
                    allele_sequence="T",
                    allele_type="SNP",
                    predicted_molecular_consequences=[
                        PredictedIntergenicConsequence(
                            feature_type=None,
                            consequences=["intergenic_variant"],
                        )
                    ]
                )
            ],
        )
        response = VepResultsResponse(metadata=metadata, variants=[variant])
        self.assertEqual(response.metadata.pagination.page, 1)
        self.assertEqual(len(response.variants), 1)

        # Invalid instance without metadata - should raise ValidationError
        with self.assertRaises(ValidationError):
            VepResultsResponse(variants=[variant])
