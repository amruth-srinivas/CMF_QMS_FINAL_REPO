"""
Router for handling PDF region view extraction.
This router provides endpoints to extract specific regions from PDF pages as images.
"""
from fastapi import APIRouter, HTTPException, Query, Path as FastAPIPath
from typing import Dict, Optional
from pydantic import BaseModel
import logging
from pathlib import Path

from app.services.view_extractor import ViewExtractor
from app.services.document_service import DocumentService
from app.services.blob_storage import blob_storage
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class ViewRegionResponse(BaseModel):
    """Response model for view region endpoint."""
    success: bool
    message: str
    data: Optional[Dict] = None
    image_base64: Optional[str] = None


def get_pdf_path(pdf_id: str) -> Path:
    """
    Get PDF file path from ID.
    Handles both file-based and database-stored PDFs.
    
    Args:
        pdf_id: The ID of the PDF
        
    Returns:
        Path to the PDF file
        
    Raises:
        FileNotFoundError: If PDF file is not found
        ValueError: If pdf_id is invalid
    """
    try:
        from app.database import get_db
        
        # Try to get PDF from database first (document versions)
        db = next(get_db())
        try:
            # Try to get current document version
            current_version = DocumentService.get_current_version(db, int(pdf_id))
            if current_version and current_version.blob_path:
                # Get the actual file path from blob storage
                blob_file_path = blob_storage.get_file_path(current_version.blob_path)
                if blob_file_path and blob_file_path.exists():
                    logger.info(f"Found PDF in database storage: {blob_file_path}")
                    return blob_file_path
        except (ValueError, TypeError):
            # pdf_id might not be a valid integer, continue to other methods
            pass
        finally:
            db.close()
        
        # If not found in database, try blob storage directly
        blob_path = Path(settings.BLOB_STORAGE_PATH) / f"{pdf_id}.pdf"
        if blob_path.exists():
            logger.info(f"Found PDF in blob storage: {blob_path}")
            return blob_path
        
        # Try direct file path if pdf_id looks like a path
        if "/" in pdf_id or "\\" in pdf_id:
            direct_path = Path(pdf_id)
            if direct_path.exists() and direct_path.suffix.lower() == '.pdf':
                logger.info(f"Found PDF at direct path: {direct_path}")
                return direct_path
        
        # If still not found, raise error
        raise FileNotFoundError(f"PDF file not found for ID: {pdf_id}")
        
    except Exception as e:
        logger.error(f"Error retrieving PDF path for ID {pdf_id}: {str(e)}")
        raise


@router.get("/view-region/{pdf_id}", response_model=ViewRegionResponse)
async def view_pdf_region(
    pdf_id: str = FastAPIPath(..., description="PDF file ID"),
    page: int = Query(..., ge=1, description="Page number (1-indexed from frontend)"),
    x: float = Query(..., ge=0, description="X coordinate of the region"),
    y: float = Query(..., ge=0, description="Y coordinate of the region"),
    width: float = Query(..., gt=0, description="Width of the region"),
    height: float = Query(..., gt=0, description="Height of the region"),
    zoom_factor: float = Query(default=2.0, ge=0.5, le=5.0, description="Zoom factor for extraction quality"),
    auto_rotate: bool = Query(default=True, description="Whether to auto-rotate for readability"),
    crop: bool = Query(default=True, description="Whether to crop white space around the region")
):
    """
    Extract a specific region from a PDF page and return it as a base64-encoded image.
    
    Args:
        pdf_id: ID of the PDF file
        page: Page number (1-indexed from frontend, will be converted to 0-indexed)
        x: X coordinate of the region in PDF coordinates
        y: Y coordinate of the region in PDF coordinates
        width: Width of the region in PDF coordinates
        height: Height of the region in PDF coordinates
        zoom_factor: Zoom factor for better quality (default 2.0)
        auto_rotate: Whether to automatically rotate for readability (default True)
    
    Returns:
        JSON response with success status, base64 image, and region data
    """
    try:
        # Validate input parameters
        if width <= 0 or height <= 0:
            raise HTTPException(status_code=400, detail="Width and height must be positive values")
        
        # Get PDF file path
        try:
            pdf_path = get_pdf_path(pdf_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        # Convert page from 1-indexed (frontend) to 0-indexed (backend)
        page_zero_indexed = page - 1
        if page_zero_indexed < 0:
            raise HTTPException(status_code=400, detail="Page number must be 1 or greater")
        
        # Prepare region dictionary
        region = {
            'x': x,
            'y': y,
            'width': width,
            'height': height
        }
        
        logger.info(f"Extracting region from PDF {pdf_id}, page {page_zero_indexed} (original: {page}): {region}")
        
        # Extract region using ViewExtractor
        image_base64 = ViewExtractor.extract_region_as_base64(
            pdf_path=str(pdf_path),
            page_number=page_zero_indexed,
            region=region,
            zoom_factor=zoom_factor,
            scale_factor=1.0,  # Coordinates are already in PDF space
            auto_rotate=auto_rotate,
            crop=crop
        )
        
        if image_base64 is None:
            raise HTTPException(
                status_code=500, 
                detail="Failed to extract region from PDF"
            )
        
        # Prepare response data
        response_data = {
            'pdf_id': pdf_id,
            'page': page,  # Return original page number for frontend consistency
            'page_zero_indexed': page_zero_indexed,  # For debugging
            'region': region,
            'zoom_factor': zoom_factor,
            'auto_rotate': auto_rotate,
            'image_size': len(image_base64)
        }
        
        logger.info(f"Successfully extracted region from PDF {pdf_id}, page {page_zero_indexed}")
        
        return ViewRegionResponse(
            success=True,
            message="Region extracted successfully",
            data=response_data,
            image_base64=image_base64
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Unexpected error extracting region from PDF {pdf_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error while extracting region: {str(e)}"
        )


@router.get("/view-region/{pdf_id}/info", response_model=ViewRegionResponse)
async def get_pdf_info(
    pdf_id: str = FastAPIPath(..., description="PDF file ID")
):
    """
    Get information about a PDF file, including number of pages and dimensions.
    
    Args:
        pdf_id: ID of the PDF file
    
    Returns:
        JSON response with PDF information
    """
    try:
        # Get PDF file path using the same logic as view_pdf_region
        try:
            pdf_path = get_pdf_path(pdf_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        # Open PDF and get info
        import fitz
        doc = fitz.open(str(pdf_path))
        
        page_info = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            rect = page.rect
            page_info.append({
                'page_number': page_num,
                'width': rect.width,
                'height': rect.height
            })
        
        doc.close()
        
        response_data = {
            'pdf_id': pdf_id,
            'total_pages': len(page_info),
            'pages': page_info
        }
        
        return ViewRegionResponse(
            success=True,
            message="PDF information retrieved successfully",
            data=response_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting PDF info for {pdf_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error while getting PDF info: {str(e)}"
        )
