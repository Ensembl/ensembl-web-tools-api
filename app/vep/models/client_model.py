from pydantic import BaseModel, Field
from typing import List, Optional

class FieldOptions:
    GENCODE_LABEL: str = "GENCODE"
    GENCODE_VALUE: str = "gencode_comprehensive"

class Options(BaseModel):
  label: str = FieldOptions.GENCODE_LABEL
  value: str = FieldOptions.GENCODE_VALUE

class TranscriptSet(BaseModel):
    label: str
    description: str = None
    type: str = "select"
    options: List[Options] = [Options()]
    default_value: str = FieldOptions.GENCODE_VALUE

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
