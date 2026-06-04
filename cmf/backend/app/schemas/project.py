"""
Pydantic schemas for Project model.
"""
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List, Any


class ProjectBase(BaseModel):
    """Base schema for Project."""
    project_number: str
    name: str
    customer_details: Optional[str] = None
    reference_no: Optional[str] = None
    is_completed: Optional[bool] = False


class ProjectCreate(ProjectBase):
    """Schema for creating a new project."""
    pass


class ProjectUpdate(BaseModel):
    """Schema for updating a project."""
    project_number: Optional[str] = None
    name: Optional[str] = None
    customer_details: Optional[str] = None
    reference_no: Optional[str] = None
    is_completed: Optional[bool] = None


class ProjectResponse(ProjectBase):
    """Schema for project response."""
    id: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ProjectDetailResponse(ProjectBase):
    """Schema for project detail response with assemblies and parts."""
    id: int
    created_at: datetime
    assemblies: List[Any] = []  # List of AssemblyResponse objects
    parts: List[Any] = []  # List of PartWithLocationResponse objects
    
    model_config = ConfigDict(from_attributes=True)

