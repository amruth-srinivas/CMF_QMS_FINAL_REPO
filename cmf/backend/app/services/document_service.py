"""
Document service for handling document versioning logic.
"""
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import Optional
import logging
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.schemas.document import DocumentVersionCreate
from app.services.blob_storage import blob_storage

logger = logging.getLogger(__name__)


class DocumentService:
    """Service for document versioning operations."""
    
    @staticmethod
    def get_next_version_no(db: Session, document_id: int) -> int:
        """
        Get the next version number for a document.
        
        Args:
            db: Database session
            document_id: ID of the document
        
        Returns:
            Next version number (1 if no versions exist)
        """
        max_version = db.query(DocumentVersion.version_no).filter(
            DocumentVersion.document_id == document_id
        ).order_by(DocumentVersion.version_no.desc()).first()
        
        if max_version is None:
            return 1
        return max_version[0] + 1
    
    @staticmethod
    def create_document_version(
        db: Session,
        document_id: int,
        version_data: DocumentVersionCreate,
        file_content: bytes,
        file_extension: str
    ) -> DocumentVersion:
        """
        Create a new document version.
        Sets previous versions to is_current=False and new version to is_current=True.
        Auto-increments version_no if not provided.
        
        Args:
            db: Database session
            document_id: ID of the document
            version_data: Version creation data
            file_content: Binary content of the file
            file_extension: File extension (e.g., "pdf", "step")
        
        Returns:
            Created DocumentVersion instance
        """
        # Get or determine version number
        if version_data.version_no is None:
            version_no = DocumentService.get_next_version_no(db, document_id)
        else:
            version_no = version_data.version_no
            # Check if version already exists
            existing = db.query(DocumentVersion).filter(
                and_(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.version_no == version_no
                )
            ).first()
            if existing:
                raise ValueError(f"Version {version_no} already exists for document {document_id}")
        
        # Set all previous versions to is_current=False
        db.query(DocumentVersion).filter(
            and_(
                DocumentVersion.document_id == document_id,
                DocumentVersion.is_current == True
            )
        ).update({"is_current": False})
        
        # Save file to blob storage
        blob_path = blob_storage.save_file(
            file_content=file_content,
            file_extension=file_extension,
            subfolder="document_versions"
        )
        
        # Create new version
        new_version = DocumentVersion(
            document_id=document_id,
            version_no=version_no,
            blob_path=blob_path,
            file_format=version_data.file_format,
            is_current=True,
            uploaded_by=version_data.uploaded_by,
            change_note=version_data.change_note
        )
        
        db.add(new_version)
        db.commit()
        db.refresh(new_version)
        
        logger.info(f"Created document version {version_no} for document {document_id}")
        return new_version
    
    @staticmethod
    def get_current_version(db: Session, document_id: int) -> Optional[DocumentVersion]:
        """
        Get the current version of a document.
        
        Args:
            db: Database session
            document_id: ID of the document
        
        Returns:
            Current DocumentVersion or None if no versions exist
        """
        return db.query(DocumentVersion).filter(
            and_(
                DocumentVersion.document_id == document_id,
                DocumentVersion.is_current == True
            )
        ).first()
    
    @staticmethod
    def delete_document_version(db: Session, version_id: int) -> bool:
        """
        Delete a document version and its associated file.
        
        Args:
            db: Database session
            version_id: ID of the version to delete
        
        Returns:
            True if deleted, False if not found
        """
        version = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
        if not version:
            return False
        
        # Delete file from blob storage
        try:
            blob_storage.delete_file(version.blob_path)
        except Exception as e:
            logger.warning(f"Error deleting blob file for version {version_id}: {e}")
        
        # Delete version record
        db.delete(version)
        db.commit()
        
        logger.info(f"Deleted document version {version_id}")
        return True


document_service = DocumentService()

