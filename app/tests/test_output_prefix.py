from datetime import datetime
import json

from app.vep.models.pipeline_model import VEPConfigParams, output_prefix_for
from app.vep.vep_resources import get_vep_results_file_path


def test_textbox_input_uses_only_the_timestamp():
    assert output_prefix_for("input.txt", datetime(2026, 8, 26, 9, 5)) == (
        "2026-08-26-09-05"
    )


def test_uploaded_file_appends_its_filename_to_the_timestamp():
    assert output_prefix_for("patient.vcf.gz", datetime(2026, 8, 26, 14, 30)) == (
        "patient_2026-08-26-14-30"
    )


def test_output_prefix_is_in_the_nextflow_parameter_payload(tmp_path):
    input_vcf = tmp_path / "input.txt"
    input_vcf.write_text("chr1\t1\t.\tA\tT\n")
    config_ini = tmp_path / "config.ini"
    config_ini.write_text("symbol 1\n")

    params = VEPConfigParams(
        vcf=input_vcf,
        vep_config=config_ini,
        outdir=tmp_path,
        output_prefix="2026-08-26-09-05",
    )

    assert json.loads(params.model_dump())["output_prefix"] == "2026-08-26-09-05"


def test_results_file_uses_the_workflow_output_prefix(tmp_path):
    input_vcf = tmp_path / "patient.vcf.gz"
    input_vcf.write_bytes(b"")

    assert get_vep_results_file_path(
        str(input_vcf), "patient_2026-08-26-14-30"
    ) == tmp_path / "patient_2026-08-26-14-30_VEP.vcf.gz"