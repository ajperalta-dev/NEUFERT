from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator,field_validator

class Strict(BaseModel):model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
class Dimension(Strict):
    label:str
    value:float
    value_max:float|None=None
    unit:str
    context:str
    status:Literal['verified','corrected','uncertain']='uncertain'
    ocr_raw:str
    verification_level:str|None=None
    verification_pass2:dict|None=None
    status_history:list[dict]=Field(default_factory=list)
    original_value:float|None=None
    @model_validator(mode='after')
    def ordered(self):
        if self.value_max is not None and self.value_max<self.value:raise ValueError('Reversed range')
        return self
class Ficha(Strict):
    id:str
    pdf_page:int=Field(ge=1,le=608)
    book_page:int|None
    chapter:str|None
    section:str|None
    title:str
    summary:str
    building_type:str
    spaces:list[str]
    uses:list[str]
    furniture_equipment:list[str]
    dimensions:list[Dimension]
    figure_refs:list[str]
    cross_refs:list[str]
    keywords:list[str]
    tags_architectural:list[str]
    confidence:float=Field(ge=0,le=1)
    @field_validator('tags_architectural')
    @classmethod
    def controlled_tags(cls,values):
        unknown=set(values)-set(TAGS)
        if unknown:raise ValueError(f'Unknown tags {sorted(unknown)}. Use only {TAGS}, or an empty list when none apply.')
        return values
class PageFichas(Strict):fichas:list[Ficha]
class Check(Strict):
    ficha_index:int=Field(ge=0)
    dimension_index:int=Field(ge=0)
    status:Literal['verified','corrected','uncertain']
    value:float|None=None
    value_max:float|None=None
    reason:str
class Checks(Strict):checks:list[Check]

TAGS=['accessibility','circulation','ergonomics','anthropometry','modularity','clearance','safety','adaptability','spatial_proportion','daylighting','ventilation']
