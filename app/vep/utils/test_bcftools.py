#!python
from cyvcf2 import VCF
import pysam.bcftools
import time
import subprocess

in_path = "/Users/andres/Desktop/vep_data"
in_vcf = f"{in_path}/vep-output-example-without-phase1-options.bcf"
offset = 100
page_size = 5
filter_k = "Biotype"
filter_v = "protein_coding"
ts = round(time.time(), 3)

def timer(msg='timer'):
  ts2 = round(time.time(), 3)
  print(f"{msg}: {round(ts2-ts, 3)}s")
  reset(ts2)

def reset(t=None):
  global ts
  if t:
    ts = t
  else:
    ts = round(time.time(), 3)

def test_cyvcf(infile, filter_str=''):
  reset()
  line = 0
  out = []
  for variant in VCF(infile):
    if (filter_str and filter_str not in variant.INFO.get('CSQ')):
      continue
    line += 1
    if line<offset:
      continue
    print(variant.CHROM, variant.POS)
    out.append(variant)
    if line == offset+page_size:
      break
  timer('cyVCF')
  return out

def test_pysam():
  reset()
  pysam.bcftools.view("-f '%CHROM %POS'", "-i \"CSQ~'protein_coding'\"", "-o", f"{in_path}/filtered.bcf", in_vcf, catch_stdout=False)
  test_cyvcf(f"{in_path}/filtered.bcf")
  timer('pySAM')


def test_subprocess():
  reset()
  ret = subprocess.run(f"bcftools +split-vep {in_vcf} -f '%CHROM %POS %CSQ\n' -i '{filter_k}=\"{filter_v}\" && key<value' -o 'filetered.bcf' | head +{offset+page_size} | tail -{page_size}", shell=True, capture_output=True)
  print(ret)
  timer('CLI')
  #test_cyvcf(f"{in_path}/filtered2.bcf")

def main():
  #test_cyvcf(in_vcf, filter_str=filter_v)
  #test_pysam()
  test_subprocess()

if __name__ == "__main__":
  main()
