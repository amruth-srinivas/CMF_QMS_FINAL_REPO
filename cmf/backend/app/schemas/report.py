"""
Pydantic schemas for Report models.
"""
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List
from app.models.measurement import GoNoGoStatus
from app.models.document import DocumentType


class ProjectInfo(BaseModel):
    """Project information for report."""
    id: int
    project_number: str
    name: str
    reference_no: Optional[str] = None
    customer_details: Optional[str] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class AssemblyInfo(BaseModel):
    """Assembly information for report."""
    id: int
    name: str
    project_id: int
    parent_assembly_id: Optional[int] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class BOCInfo(BaseModel):
    """Bill of Components information."""
    project: Optional[ProjectInfo] = None
    assembly: Optional[AssemblyInfo] = None
    quantity: int  # Quantity from PartLocation
    
    model_config = ConfigDict(from_attributes=True)


class BalloonInfo(BaseModel):
    """Balloon information for report."""
    id: int
    balloon_id: str
    document_id: Optional[int] = None
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
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class MeasurementInfo(BaseModel):
    """Measurement information for report."""
    id: int
    balloon_id: int
    quantity: Optional[int] = 1
    m1: Optional[float] = None
    m2: Optional[float] = None
    m3: Optional[float] = None
    mean: Optional[float] = None
    go_or_no_go: Optional[GoNoGoStatus] = None
    measured_by: Optional[str] = None
    measured_at: datetime
    notes: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class BalloonWithMeasurements(BaseModel):
    """Balloon with its measurements."""
    balloon: BalloonInfo
    measurements: List[MeasurementInfo] = []


class DocumentVersionInfo(BaseModel):
    """Document version information."""
    id: int
    version_no: int
    blob_path: str
    file_format: str
    is_current: bool
    uploaded_at: datetime
    uploaded_by: Optional[str] = None
    change_note: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class BalloonedDrawing(BaseModel):
    """Ballooned drawing information."""
    id: int
    doc_type: DocumentType
    title: str
    created_at: datetime
    current_version: Optional[DocumentVersionInfo] = None
    
    model_config = ConfigDict(from_attributes=True)


class QuantityReport(BaseModel):
    """Report for a specific quantity."""
    quantity: int
    balloons: List[BalloonWithMeasurements] = []
    total_measurements: int = 0
    go_count: int = 0
    no_go_count: int = 0


class PartReportResponse(BaseModel):
    """Complete part report response."""
    part_id: int
    part_no: str
    part_name: str
    rev: Optional[str] = None
    inspection_plan_status: bool
    created_at: datetime
    
    # BOC (Bill of Components) information
    boc: Optional[BOCInfo] = None
    
    # Ballooned drawing
    ballooned_drawing: Optional[BalloonedDrawing] = None
    
    # Reports by quantity
    quantity_reports: List[QuantityReport] = []
    
    # Consolidated summary (all quantities combined)
    consolidated_summary: Optional[dict] = None
    
    # Report metadata
    report_type: str  # "individual" or "consolidated"
    generated_at: datetime
