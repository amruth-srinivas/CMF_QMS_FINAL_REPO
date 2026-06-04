"""
Pydantic schemas for Part model.
"""
from pydantic import BaseModel, ConfigDict, model_validator
from datetime import datetime
from typing import Optional


class PartBase(BaseModel):
    """Base schema for Part."""
    part_no: str
    name: str
    rev: Optional[str] = None
    inspection_plan_status: bool = False  # Inspection plan status (toggleable)
    priority_component: bool = False  # Priority component flag (star/balloon)
    inspection_plan_approved_at: Optional[datetime] = None


class PartCreate(PartBase):
    """Schema for creating a new part with optional location."""
    # Location fields (optional - if provided, exactly one must be set)
    project_id: Optional[int] = None
    assembly_id: Optional[int] = None
    quantity: Optional[int] = 1  # Default quantity is 1
    
    @model_validator(mode="after")
    def validate_location(self):
        """Validate that if location is provided, exactly one of project_id or assembly_id is set."""
        has_project = self.project_id is not None
        has_assembly = self.assembly_id is not None
        
        # If both are provided, raise error
        if has_project and has_assembly:
            raise ValueError("Only one of project_id or assembly_id can be provided")
        # If neither is provided, that's fine (part without location)
        return self


class PartUpdate(BaseModel):
    """Schema for updating a part."""
    part_no: Optional[str] = None
    name: Optional[str] = None
    rev: Optional[str] = None
    inspection_plan_status: Optional[bool] = None  # Toggleable inspection plan status
    priority_component: Optional[bool] = None  # Toggleable priority component status
    inspection_plan_approved_at: Optional[datetime] = None
    quantity: Optional[int] = None  # Updates PartLocation.quantity (clamped to >= 1)


class PartResponse(PartBase):
    """Schema for part response."""
    id: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class PartWithLocationResponse(PartBase):
    """Schema for part response with location information."""
    id: int
    created_at: datetime
    inspection_plan_status: bool = False
    project_id: Optional[int] = None
    assembly_id: Optional[int] = None
    quantity: int = 1
    inspection_plan_approved_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

