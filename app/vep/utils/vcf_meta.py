"""VCF metadata (variant / header counts) with a local file cache.

Extracted from vcf_results. Used by the bcftools fallback path in
get_results_from_path when no page-index sidecar is present.
"""

import subprocess
from pydantic import FilePath
from vep.models import vcf_results_model as model

META_FILE = "results_meta.json"


def _is_meta_cache_stale(meta_path: FilePath, vcf_path: FilePath) -> bool:
    """True if the metadata cache exists but predates its VCF."""
    return (
        meta_path.exists()
        and meta_path.stat().st_mtime < vcf_path.stat().st_mtime
    )


def _get_vcf_meta(vcf_path: FilePath) -> model.VcfMetadata:
    """Helper method to manage metainfo for a VCF file"""

    meta_path = vcf_path.with_name(META_FILE)
    if not meta_path.exists() or _is_meta_cache_stale(meta_path, vcf_path):
        # Argument lists, not a shell string: the path derives from the
        # uploaded file's name, so interpolating it into a shell command let a
        # filename like `a$(...).vcf` run whatever it liked. The `grep` and
        # `wc -l` the pipeline used are done here instead.
        stats_output = subprocess.check_output(
            ["bcftools", "stats", str(vcf_path)], text=True
        )
        variant_count_str = next(
            (line for line in stats_output.splitlines() if "number of records:" in line),
            "",
        )
        header_output = subprocess.check_output(
            ["bcftools", "view", "-h", str(vcf_path)], text=True
        )
        header_count_str = str(len(header_output.splitlines()))
        try:
            vcf_info = model.VcfMetadata(
                variant_count=int(variant_count_str.split(":")[-1]),
                header_count=int(header_count_str)
            )
        except ValueError as e:
            e.args = (
                f"_get_vcf_meta: unexpected bcftools output: variant_count: {variant_count_str} | header_count: {header_count_str}",
                *e.args,
            )
            raise

        with open(meta_path, "w") as meta_file:
            meta_file.write(vcf_info.model_dump_json())
    else:
        with open(meta_path, "r") as meta_file:
            vcf_info = model.VcfMetadata.model_validate_json(meta_file.read())
    return vcf_info
