"""
Pydantic schemas for Report Config (template) API.
"""
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional, List


class ReportConfigFieldBase(BaseModel):
    section: str = Field(..., description="header or footer")
    field_label: str = Field(..., min_length=1, max_length=255)
    backend_key: str = Field(..., min_length=1, max_length=100)


class ReportConfigFieldCreate(ReportConfigFieldBase):
    pass


class ReportConfigFieldUpdate(BaseModel):
    section: Optional[str] = Field(None, description="header or footer")
    field_label: Optional[str] = Field(None, min_length=1, max_length=255)
    backend_key: Optional[str] = Field(None, min_length=1, max_length=100)


class ReportConfigFieldResponse(BaseModel):
    id: int
    report_id: int
    section: str
    field_label: str
    backend_key: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReportConfigBase(BaseModel):
    report_name: str = Field("Inspection Report", max_length=255)
    company_name: Optional[str] = Field(None, max_length=255)


class ReportConfigCreate(ReportConfigBase):
    pass


class ReportConfigUpdate(BaseModel):
    report_name: Optional[str] = Field(None, max_length=255)
    company_name: Optional[str] = Field(None, max_length=255)
    is_locked: Optional[bool] = None


class ReportConfigResponse(BaseModel):
    id: int
    report_name: str
    company_name: Optional[str]
    logo_path: Optional[str]
    is_locked: bool
    created_at: datetime
    updated_at: datetime
    fields: List[ReportConfigFieldResponse] = []

    model_config = ConfigDict(from_attributes=True)


class ReportConfigListResponse(BaseModel):
    id: int
    report_name: str
    company_name: Optional[str]
    logo_path: Optional[str]
    is_locked: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
