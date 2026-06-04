"""
Document model.
Represents a document (2D or 3D) linked to either an assembly or a part.
Enforces CHECK constraint: exactly one of assembly_id or part_id must be non-null.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum, CheckConstraint, func
from sqlalchemy.orm import relationship
import enum
from app.database import Base


class DocumentType(str, enum.Enum):
    """Document type enumeration."""
    TWO_D = "2D"
    THREE_D = "3D"


class Document(Base):
    """
    Document model.
    Represents a document (2D or 3D) linked to either an ItemRevision, an Assembly, or a Part.
    """
    
    __tablename__ = "documents"
    
    id = Column(Integer, primary_key=True, index=True)
    item_revision_id = Column(Integer, ForeignKey("item_revisions.id", ondelete="CASCADE"), nullable=True, index=True)
    assembly_id = Column(Integer, ForeignKey("assemblies.id", ondelete="CASCADE"), nullable=True, index=True)
    part_id = Column(Integer, ForeignKey("parts.id", ondelete="CASCADE"), nullable=True, index=True)
    
    doc_type = Column(SQLEnum(DocumentType), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    # For 2D (PDF) documents: "normal" = text layer, "scanned" = image-only (OCR used for text extraction)
    pdf_content_type = Column(String(20), nullable=True, default="normal", server_default="normal")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    item_revision = relationship("ItemRevision", back_populates="documents")
    assembly = relationship("Assembly", back_populates="documents")
    part = relationship("Part", back_populates="documents")
    
    versions = relationship("DocumentVersion", back_populates="document", cascade="all, delete-orphan", order_by="DocumentVersion.version_no", passive_deletes=True)
    balloons = relationship("Balloon", back_populates="document", cascade="all, delete-orphan", passive_deletes=True)
    notes = relationship("Note", back_populates="document", cascade="all, delete-orphan", passive_deletes=True)

    # CHECK constraint: at least one link must be provided
    __table_args__ = (
        CheckConstraint(
            "(item_revision_id IS NOT NULL) OR (assembly_id IS NOT NULL) OR (part_id IS NOT NULL)",
            name="check_document_owner"
        ),
    )

