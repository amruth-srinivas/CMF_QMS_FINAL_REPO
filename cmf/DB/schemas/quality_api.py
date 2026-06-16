"""Pydantic schemas for quality / Master BOC HTTP API."""
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from datetime import datetime


class MasterBocCreate(BaseModel):
    part_id: str = Field(..., description="Part number (oms.parts.part_number)")
    sales_order_id: int
    nominal: str
    uppertol: float
    lowertol: float
    zone: str
    dimension_type: str
    measured_instrument: str = Field(default="default", description="Default measurement instrument")
    op_no: int
    bbox: str = Field(..., description="JSON string of bbox / metadata")
    ipid: str


class MasterBocBulkCreate(BaseModel):
    items: List[MasterBocCreate]
    user_id: Optional[int] = None


class MasterBocUpdate(BaseModel):
    zone: Optional[str] = None
    measured_instrument: Optional[str] = None


class MasterBocResponse(BaseModel):
    id: int
    part_id: str
    sales_order_id: int
    nominal: str
    uppertol: float
    lowertol: float
    zone: str
    dimension_type: str
    measured_instrument: str
    op_no: int
    bbox: str
    ipid: str
    user_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class StageInspectionResponse(BaseModel):
    id: int
    part_id: int
    sale_order_id: int
    nominal_value: str
    uppertol: float
    lowertol: float
    zone: str
    dimension_type: str
    measurements: List[str] = []
    measured_mean: Optional[str] = None
    measured_instrument: str
    used_inst: str
    op_no: int
    quantity_no: Optional[int] = None
    bbox: Optional[str] = None
    is_done: bool = False

    model_config = ConfigDict(from_attributes=True)


class StageInspectionUpdate(BaseModel):
    measurements: Optional[List[str]] = None
    measured_mean: Optional[str] = None
    measured_instrument: Optional[str] = None
    used_inst: Optional[str] = None
    is_done: Optional[bool] = None


class StageInspectionMeasurementSummary(BaseModel):
    """True if any stage row for this part/order/op has a non-empty measurement field."""

    any_recorded: bool
    qty1_complete: bool = False
    qty_max: int = 1


class FTPStatusUpsert(BaseModel):
    order_id: int
    ipid: str = Field(..., description="FTP key for part/order/op scope")
    status: str = Field(default="pending", description="pending | approved | rejected")
    is_completed: Optional[bool] = None
    # For notification creation
    part_number: Optional[str] = None
    op_no: Optional[int] = None
    operation_id: Optional[int] = None
    requested_by_username: Optional[str] = None
    approved_by_username: Optional[str] = None
    approved_at: Optional[datetime] = None


class FTPStatusResponse(BaseModel):
    id: int
    order_id: int
    ipid: str
    is_completed: bool
    status: str
    approved_by_username: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class InspectionPlanStatusUpsert(BaseModel):
    part_number: str = Field(..., description="oms.parts.part_number")
    sales_order_id: int
    op_no: int
    status: str = Field(default="draft", description="draft | confirmed")
    confirmed_by_username: Optional[str] = Field(
        default=None,
        description="Login name of user who confirmed the plan (set when status becomes confirmed)",
    )


class InspectionPlanStatusResponse(BaseModel):
    id: int
    part_number: str
    sales_order_id: int
    op_no: int
    status: str
    confirmed_by_username: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OperationProductionSummaryItem(BaseModel):
    operation_id: int
    op_no: int
    required_quantity: int
    completed_quantity: int
    accepted_quantity: int
    rejected_quantity: int
    yield_percentage: float


class NoteBase(BaseModel):
    part_id: int
    document_id: Optional[int] = None
    op_no: int = 0
    is_operation_document: bool = False
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    page: Optional[int] = 1
    note_text: Optional[str] = None


class NoteCreate(NoteBase):
    pass


class NoteUpdate(BaseModel):
    part_id: Optional[int] = None
    document_id: Optional[int] = None
    op_no: Optional[int] = None
    is_operation_document: Optional[bool] = None
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    page: Optional[int] = None
    note_text: Optional[str] = None


class NoteResponse(NoteBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
