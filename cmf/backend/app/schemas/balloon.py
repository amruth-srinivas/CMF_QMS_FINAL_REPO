"""
Pydantic schemas for Balloon model.
"""
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional


class BalloonBase(BaseModel):
    """Base schema for Balloon."""
    part_id: int  # Required - primary association
    document_id: Optional[int] = None  # Optional - for reference
    balloon_id: str
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    page: Optional[int] = 1
    nominal: Optional[float] = None
    utol: Optional[str] = None
    ltol: Optional[str] = None
    type: Optional[str] = None
    zone: Optional[str] = None
    measuring_instrument: Optional[str] = None
    op_no: Optional[str] = None
    sampling: Optional[int] = 3


class BalloonCreate(BalloonBase):
    """Schema for creating a new balloon."""
    pass


class BalloonUpdate(BaseModel):
    """Schema for updating a balloon."""
    part_id: Optional[int] = None
    document_id: Optional[int] = None
    balloon_id: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    page: Optional[int] = None
    nominal: Optional[float] = None
    utol: Optional[str] = None
    ltol: Optional[str] = None
    type: Optional[str] = None
    zone: Optional[str] = None
    measuring_instrument: Optional[str] = None
    op_no: Optional[str] = None
    sampling: Optional[int] = None


class BalloonResponse(BalloonBase):
    """Schema for balloon response."""
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

