from pydantic import BaseModel, Field
from typing import List, Optional

def default_options():
  return [
      Options(label="GENCODE", value="gencode_comprehensive"),
  ]

class Options(BaseModel):
  label: str = "GENCODE"
  value: str = "gencode_comprehensive"

class TranscriptSet(BaseModel):
    label: str
    description: str = None
    type: str = "select"
    options: List[Options] = Field(default_factory=default_options)
    default_value: str = "gencode_comprehensive"

class Symbol(BaseModel):
    label: str = "Gene symbol"
    description: str = None
    type: str = "boolean"
    default_value: bool = True

class Biotype(BaseModel):
    label: str = "Transcript biotype"
    description: str = None
    type: str = "boolean"
    default_value: bool = True

class FormConfig(BaseModel):
    transcript_set: TranscriptSet = TranscriptSet(label="")
    symbol: Symbol = Symbol()
    biotype: Biotype = Biotype()

class GenomeAnnotationProvider(BaseModel):
  annotation_provider_name: str
  annotation_version: str
