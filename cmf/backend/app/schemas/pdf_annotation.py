"""
Pydantic schemas for PDF annotation requests.
"""
from pydantic import BaseModel
from typing import List, Dict, Optional


class BoundingBox(BaseModel):
    """Bounding box coordinates."""
    x: float
    y: float
    width: float
    height: float
    page: int


class SaveBoundingBoxRequest(BaseModel):
    """Request to save a bounding box."""
    part_id: int  # Required - Part ID to link the balloon to
    pdf_id: Optional[str] = None  # Optional - Document ID for reference
    bounding_box: BoundingBox
    label: str = ""


class ExtractTextRequest(BaseModel):
    """Request to extract text from a region."""
    part_id: int  # Required - Part ID
    pdf_id: Optional[str] = None  # Optional - Document ID for PDF access
    bounding_box: BoundingBox
    scale_factor: float = 2.0
    include_image: bool = True
    check_overlaps: bool = False
    existing_boxes: Optional[List[List[List[float]]]] = None
    iou_threshold: float = 0.3
    rotation_angle: Optional[int] = None


class ProcessDimensionsRequest(BaseModel):
    """Request to process dimensions from a region."""
    part_id: int  # Required - Part ID
    pdf_id: Optional[str] = None  # Optional - Document ID for PDF access
    bounding_box: BoundingBox
    scale_factor: float = 2.0
    include_image: bool = True
    check_overlaps: bool = False
    existing_boxes: Optional[List[List[List[float]]]] = None
    iou_threshold: float = 0.3
    rotation_angle: Optional[int] = None


class UpdateBoundingBoxRequest(BaseModel):
    """Request to update a bounding box with extracted data."""
    text_data: Optional[List[Dict]] = None
    gdt_data: Optional[List[Dict]] = None
    dimension_data: Optional[List[Dict]] = None
    measuring_instrument: Optional[str] = None
    sampling: Optional[int] = None


class BatchDeleteRequest(BaseModel):
    """Request to delete multiple balloons."""
    part_id: int
    balloon_ids: List[str]  # List of string labels (balloon_id column)


class BatchUpdateBoundingBoxRequest(BaseModel):
    """Request to update multiple balloons at once."""
    part_id: int
    balloon_ids: List[str]
    measuring_instrument: Optional[str] = None
    sampling: Optional[int] = None
