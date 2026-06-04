from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional


class ReportTemplateBase(BaseModel):
    name: str
    description: Optional[str] = None
    header_html: Optional[str] = None
    footer_html: Optional[str] = None
    is_default: bool = False


class ReportTemplateCreate(ReportTemplateBase):
    pass


class ReportTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    header_html: Optional[str] = None
    footer_html: Optional[str] = None
    is_default: Optional[bool] = None


class ReportTemplateResponse(ReportTemplateBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReportTemplateListResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    header_html: Optional[str] = None
    footer_html: Optional[str] = None
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
