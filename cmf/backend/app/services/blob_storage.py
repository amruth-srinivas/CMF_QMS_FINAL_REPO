"""
Blob storage service for file handling.
Uses local filesystem as blob store.
"""
import os
import uuid
import shutil
from pathlib import Path
from typing import Optional
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


class BlobStorage:
    """Blob storage service for managing files on local filesystem."""
    
    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize blob storage.
        
        Args:
            base_path: Base path for blob storage. Defaults to settings.BLOB_STORAGE_PATH.
        """
        self.base_path = Path(base_path or settings.BLOB_STORAGE_PATH)
        self._ensure_directory_exists()
    
    def _ensure_directory_exists(self):
        """Ensure the blob storage directory exists."""
        try:
            self.base_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Blob storage directory ensured: {self.base_path}")
        except Exception as e:
            logger.error(f"Error creating blob storage directory: {e}")
            raise
    
    def save_file(self, file_content: bytes, file_extension: str, subfolder: Optional[str] = None) -> str:
        """
        Save a file to blob storage.
        
        Args:
            file_content: Binary content of the file
            file_extension: File extension (e.g., "pdf", "step")
            subfolder: Optional subfolder to organize files (e.g., "documents", "versions")
        
        Returns:
            Relative blob path (relative to base_path) that can be stored in database
        """
        try:
            # Create subfolder if specified
            storage_path = self.base_path
            if subfolder:
                storage_path = storage_path / subfolder
                storage_path.mkdir(parents=True, exist_ok=True)
            
            # Generate unique filename
            unique_id = str(uuid.uuid4())
            filename = f"{unique_id}.{file_extension}"
            file_path = storage_path / filename
            
            # Write file
            with open(file_path, "wb") as f:
                f.write(file_content)
            
            # Return relative path for storage in database
            relative_path = file_path.relative_to(self.base_path)
            blob_path = str(relative_path).replace("\\", "/")  # Normalize path separators
            
            logger.info(f"File saved to blob storage: {blob_path}")
            return blob_path
        except Exception as e:
            logger.error(f"Error saving file to blob storage: {e}")
            raise
    
    def get_file_path(self, blob_path: str) -> Path:
        """
        Get the full filesystem path for a blob path.
        
        Args:
            blob_path: Relative blob path stored in database
        
        Returns:
            Full Path object to the file
        """
        # Normalize path separators
        normalized_path = blob_path.replace("\\", "/")
        full_path = self.base_path / normalized_path
        
        if not full_path.exists():
            raise FileNotFoundError(f"Blob file not found: {blob_path}")
        
        return full_path
    
    def delete_file(self, blob_path: str) -> bool:
        """
        Delete a file from blob storage.
        
        Args:
            blob_path: Relative blob path stored in database
        
        Returns:
            True if file was deleted, False if it didn't exist
        """
        try:
            file_path = self.get_file_path(blob_path)
            file_path.unlink()
            logger.info(f"File deleted from blob storage: {blob_path}")
            return True
        except FileNotFoundError:
            logger.warning(f"File not found for deletion: {blob_path}")
            return False
        except Exception as e:
            logger.error(f"Error deleting file from blob storage: {e}")
            raise
    
    def file_exists(self, blob_path: str) -> bool:
        """
        Check if a file exists in blob storage.
        
        Args:
            blob_path: Relative blob path stored in database
        
        Returns:
            True if file exists, False otherwise
        """
        try:
            normalized_path = blob_path.replace("\\", "/")
            full_path = self.base_path / normalized_path
            return full_path.exists()
        except Exception:
            return False


# Global blob storage instance
blob_storage = BlobStorage()

