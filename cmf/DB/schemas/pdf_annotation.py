"""
Pydantic schemas for PDF annotation requests (CMF / quality module).
"""
from pydantic import BaseModel
from typing import List, Dict, Optional


class BoundingBox(BaseModel):
    """Bounding box coordinates (PDF space, same as react-pdf overlay)."""
    x: float
    y: float
    width: float
    height: float
    page: int


class SaveBoundingBoxRequest(BaseModel):
    """Legacy name — not used when CMF has no balloons table; kept for API compatibility."""
    part_id: int
    pdf_id: Optional[str] = None
    bounding_box: BoundingBox
    label: str = ""


class ExtractTextRequest(BaseModel):
    """Request to extract text from a region."""
    part_id: int
    pdf_id: Optional[str] = None
    bounding_box: BoundingBox
    scale_factor: float = 2.0
    check_overlaps: bool = False
    existing_boxes: Optional[List[List[List[float]]]] = None
    iou_threshold: float = 0.3
    rotation_angle: Optional[int] = None
    pdf_content_type: Optional[str] = None  # "normal" | "scanned" — overrides document heuristics


class ProcessDimensionsRequest(BaseModel):
    """Request to process dimensions (clustering + GDT + parsing) from a region."""
    part_id: int
    pdf_id: Optional[str] = None
    bounding_box: BoundingBox
    scale_factor: float = 2.0
    check_overlaps: bool = False
    existing_boxes: Optional[List[List[List[float]]]] = None
    iou_threshold: float = 0.3
    rotation_angle: Optional[int] = None
    pdf_content_type: Optional[str] = None


class ExtractZonesBulkRequest(BaseModel):
    """Request to extract zones for multiple regions in one PDF load."""
    part_id: Optional[int] = None
    pdf_id: Optional[str] = None
    bounding_boxes: List[BoundingBox]
    scale_factor: float = 1.0


class UpdateBoundingBoxRequest(BaseModel):
    """Optional payload when updating stored inspection rows."""
    text_data: Optional[List[Dict]] = None
    gdt_data: Optional[List[Dict]] = None
    dimension_data: Optional[List[Dict]] = None


class RenderPageRequest(BaseModel):
    """Request to render a specific PDF page as an image."""
    pdf_id: str
    page: int
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    scale: float = 1.5
    is_scanned: bool = False
    return_base64: bool = True
