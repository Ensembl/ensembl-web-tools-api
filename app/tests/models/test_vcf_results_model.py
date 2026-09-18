import json
import unittest
from pydantic import ValidationError

from vep.models.vcf_results_model import (
    Annotation,
    PaginationMetadata,
    PredictedIntergenicConsequence,
    PredictedRegulatoryConsequence,
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
from vep.models.display_panels_model import DisplayPanel
from vep.models.display_spec_model import DisplayPayload

DISPLAY_PANELS = [DisplayPanel(id="general", label="General")]
DISPLAY = DisplayPayload(options=[], plugin_scopes={})


class TestVCFResultModel(unittest.TestCase):

    def test_predicted_intergenic_consequence(self):
        consequence = PredictedIntergenicConsequence()
        self.assertIsNone(consequence.feature_type)
        self.assertEqual(consequence.consequences, ["intergenic_variant"])

    def test_predicted_regulatory_consequence(self):
        consequence = PredictedRegulatoryConsequence(
            stable_id="ENSM00000018397",
            consequences=["TF_binding_site_variant"],
        )
        self.assertIsNone(consequence.biotype)
        self.assertEqual(
            json.loads(consequence.model_dump_json()),
            {
                "feature_type": "regulatory",
                "stable_id": "ENSM00000018397",
                "biotype": None,
                "consequences": ["TF_binding_site_variant"],
                "annotation_refs": [],
            },
        )

    def test_a_regulatory_consequence_is_not_read_back_as_intergenic(self):
        # The intergenic model accepts any feature_type.
        allele = AlternativeVariantAllele.model_validate(
            {
                "allele_sequence": "T",
                "allele_type": "SNV",
                "predicted_molecular_consequences": [
                    {
                        "feature_type": "regulatory",
                        "stable_id": "ENSR1_D37Q",
                        "biotype": "enhancer",
                        "consequences": ["regulatory_region_variant"],
                    }
                ],
            }
        )
        [consequence] = allele.predicted_molecular_consequences
        self.assertIsInstance(consequence, PredictedRegulatoryConsequence)
        self.assertEqual(consequence.stable_id, "ENSR1_D37Q")

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

        # `gene_symbol` is optional.
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
            colocated_variants=["rs123"],
            annotations=[
                Annotation(plugin="spdi", scope="allele", data={"spdi": "1:1:A:T"})
            ],
            predicted_molecular_consequences=[
                PredictedIntergenicConsequence()
            ],
        )
        self.assertEqual(alternative_allele.colocated_variants, ["rs123"])
        self.assertEqual(alternative_allele.annotations[0].plugin, "spdi")

        # Optional annotation lists default to empty.
        alternative_allele_bare = AlternativeVariantAllele(
            allele_sequence="A",
            allele_type="insertion",
            predicted_molecular_consequences=[
                PredictedIntergenicConsequence()
            ],
        )
        self.assertEqual(alternative_allele_bare.colocated_variants, [])
        self.assertEqual(alternative_allele_bare.annotations, [])

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
                        PredictedIntergenicConsequence()
                    ]
                )
            ]
        )
        self.assertIsNone(variant.name)

        # `name` is optional.
        variant_no_name = Variant(
            allele_type="SNP",
            location=Location(region_name="1", start=10000, end=10001),
            reference_allele=ReferenceVariantAllele(allele_sequence="C"),
            alternative_alleles=[
                AlternativeVariantAllele(
                    allele_sequence="T",
                    allele_type="SNP",
                    predicted_molecular_consequences=[
                        PredictedIntergenicConsequence()
                    ]
                )
            ]
        )
        self.assertIsNone(variant_no_name.name)

    def test_metadata_required(self):
        metadata = Metadata(
            pagination=PaginationMetadata(page=1, per_page=10, total=100),
            display_panels=DISPLAY_PANELS,
            display=DISPLAY,
        )
        self.assertEqual(metadata.pagination.page, 1)

        # Results metadata requires pagination and display metadata.
        with self.assertRaises(ValidationError):
            Metadata()
        with self.assertRaises(ValidationError):
            Metadata(
                pagination=PaginationMetadata(page=1, per_page=10, total=100),
                display=DISPLAY,
            )
        with self.assertRaises(ValidationError):
            Metadata(
                pagination=PaginationMetadata(page=1, per_page=10, total=100),
                display_panels=DISPLAY_PANELS,
            )

    def test_vep_results_response(self):
        metadata = Metadata(
            pagination=PaginationMetadata(page=1, per_page=10, total=100),
            display_panels=DISPLAY_PANELS,
            display=DISPLAY,
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
                        PredictedIntergenicConsequence()
                    ]
                )
            ],
        )
        response = VepResultsResponse(metadata=metadata, variants=[variant])
        self.assertEqual(response.metadata.pagination.page, 1)
        self.assertEqual(len(response.variants), 1)

        # A response requires metadata.
        with self.assertRaises(ValidationError):
            VepResultsResponse(variants=[variant])
