"""
DocumentVersion model.
Represents a version of a document with blob storage path.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class DocumentVersion(Base):
    """DocumentVersion model representing a version of a document."""
    
    __tablename__ = "document_versions"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version_no = Column(Integer, nullable=False, index=True)
    blob_path = Column(String(512), nullable=False)  # Path or key in blob storage
    file_format = Column(String(50), nullable=False)  # e.g., "pdf", "step", "dwg"
    is_current = Column(Boolean, nullable=False, default=False, index=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    uploaded_by = Column(String(255), nullable=True)
    change_note = Column(String(1000), nullable=True)
    
    # Relationships
    document = relationship("Document", back_populates="versions")
    
    # Unique constraint: one document can only have one current version
    __table_args__ = (
        # Note: The constraint that only one version per document can be current
        # is enforced at the application level in the document service
    )

