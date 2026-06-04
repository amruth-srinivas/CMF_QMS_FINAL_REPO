"""
Pydantic schemas for Assembly model.
"""
from pydantic import BaseModel, ConfigDict, field_validator
from datetime import datetime
from typing import Optional


class AssemblyBase(BaseModel):
    """Base schema for Assembly."""
    name: str
    no: Optional[str] = None
    rev: Optional[str] = None
    project_id: int
    parent_assembly_id: Optional[int] = None
    quantity: Optional[int] = 1
    
    model_config = ConfigDict(
        # Allow None values for optional fields
        populate_by_name=True,
    )
    
    @field_validator("parent_assembly_id", mode="before")
    @classmethod
    def validate_parent_assembly_id(cls, v):
        """Explicitly allow None/null values."""
        if v is None or v == "null" or v == "none":
            return None
        return v


class AssemblyCreate(AssemblyBase):
    """Schema for creating a new assembly."""
    pass


class AssemblyUpdate(BaseModel):
    """Schema for updating an assembly."""
    name: Optional[str] = None
    no: Optional[str] = None
    rev: Optional[str] = None
    project_id: Optional[int] = None
    parent_assembly_id: Optional[int] = None
    quantity: Optional[int] = None
    
    @field_validator("parent_assembly_id")
    @classmethod
    def validate_parent_assembly(cls, v):
        """Allow setting parent_assembly_id to None explicitly."""
        return v


class AssemblyResponse(AssemblyBase):
    """Schema for assembly response."""
    id: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

