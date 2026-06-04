"""
Pydantic schemas for Measurement model.
"""
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional
from app.models.measurement import GoNoGoStatus


class MeasurementBase(BaseModel):
    """Base schema for Measurement."""
    balloon_id: int
    part_id: Optional[int] = None
    quantity: Optional[int] = 1  # Quantity of parts measured
    m1: Optional[float] = None
    m2: Optional[float] = None
    m3: Optional[float] = None
    mean: Optional[float] = None
    go_or_no_go: Optional[GoNoGoStatus] = None
    measured_by: Optional[str] = None
    instrument_id: Optional[int] = None
    notes: Optional[str] = None


class MeasurementCreate(MeasurementBase):
    """Schema for creating a new measurement."""
    pass


class MeasurementUpdate(BaseModel):
    """Schema for updating a measurement."""
    balloon_id: Optional[int] = None
    part_id: Optional[int] = None
    quantity: Optional[int] = None
    m1: Optional[float] = None
    m2: Optional[float] = None
    m3: Optional[float] = None
    mean: Optional[float] = None
    go_or_no_go: Optional[GoNoGoStatus] = None
    measured_by: Optional[str] = None
    instrument_id: Optional[int] = None
    notes: Optional[str] = None


class MeasurementResponse(MeasurementBase):
    """Schema for measurement response."""
    id: int
    measured_at: datetime
    instrument_code: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

