"""
Pydantic schemas for Note model.
"""
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional


class NoteBase(BaseModel):
    """Base schema for Note."""
    part_id: int  # Required
    document_id: Optional[int] = None  # Optional
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    page: Optional[int] = 1
    note_text: Optional[str] = None


class NoteCreate(NoteBase):
    """Schema for creating a new note."""
    pass


class NoteUpdate(BaseModel):
    """Schema for updating a note."""
    part_id: Optional[int] = None
    document_id: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    page: Optional[int] = None
    note_text: Optional[str] = None


class NoteResponse(NoteBase):
    """Schema for note response."""
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)
