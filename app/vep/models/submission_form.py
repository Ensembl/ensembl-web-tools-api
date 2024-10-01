from pydantic import BaseModel


class DropdownOption(BaseModel):
    label: str
    value: str


class Dropdown(BaseModel):
    label: str
    description: str | None = None
    type: str = "select"
    options: list[DropdownOption]
    default_value: str


class Checkbox(BaseModel):
    label: str
    description: str | None = None
    type: str = "boolean"
    default_value: bool = True


class FormConfig(BaseModel):
    transcript_set: Dropdown
    symbol: Checkbox = Checkbox(label="Gene symbol")
    biotype: Checkbox = Checkbox(label="Transcript biotype")


class GenomeAnnotationProvider(BaseModel):
    annotation_provider_name: str
    annotation_version: str
    last_geneset_update: str
