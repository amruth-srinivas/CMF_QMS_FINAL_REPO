"""
Pydantic schemas for Document and DocumentVersion models.
"""
from pydantic import BaseModel, ConfigDict, model_validator
from datetime import datetime
from typing import Optional
from app.models.document import DocumentType


class DocumentBase(BaseModel):
    """Base schema for Document."""
    doc_type: DocumentType
    title: str
    assembly_id: Optional[int] = None
    part_id: Optional[int] = None
    pdf_content_type: Optional[str] = None  # For 2D docs: "normal" or "scanned"
    
    @model_validator(mode="after")
    def validate_exactly_one_owner(self):
        """Validate that exactly one of assembly_id or part_id is provided."""
        if self.assembly_id is None and self.part_id is None:
            raise ValueError("Either assembly_id or part_id must be provided")
        if self.assembly_id is not None and self.part_id is not None:
            raise ValueError("Only one of assembly_id or part_id can be provided")
        return self


class DocumentCreate(DocumentBase):
    """Schema for creating a new document."""
    pass


class DocumentUpdate(BaseModel):
    """Schema for updating a document."""
    doc_type: Optional[DocumentType] = None
    title: Optional[str] = None
    assembly_id: Optional[int] = None
    part_id: Optional[int] = None
    pdf_content_type: Optional[str] = None  # For 2D docs: "normal" or "scanned"
    
    @model_validator(mode="after")
    def validate_exactly_one_owner(self):
        """Validate that exactly one of assembly_id or part_id is provided when updating."""
        # Only validate if both are being set (not None)
        if self.assembly_id is not None and self.part_id is not None:
            raise ValueError("Only one of assembly_id or part_id can be provided")
        return self


class DocumentResponse(DocumentBase):
    """Schema for document response."""
    id: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class DocumentWithVersionResponse(DocumentBase):
    """Schema for document response with current version information."""
    id: int
    created_at: datetime
    pdf_content_type: Optional[str] = None
    blob_path: Optional[str] = None
    file_format: Optional[str] = None
    version_no: Optional[int] = None
    download_url: Optional[str] = None
    size: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentVersionCreate(BaseModel):
    """Schema for creating a new document version."""
    version_no: Optional[int] = None  # Auto-incremented if not provided
    file_format: str
    uploaded_by: Optional[str] = None
    change_note: Optional[str] = None


class DocumentVersionResponse(BaseModel):
    """Schema for document version response."""
    id: int
    document_id: int
    version_no: int
    blob_path: str
    file_format: str
    is_current: bool
    uploaded_at: datetime
    uploaded_by: Optional[str] = None
    change_note: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

