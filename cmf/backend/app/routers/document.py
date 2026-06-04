"""
Document router with CRUD operations and file upload.
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models.document import Document, DocumentType
from app.models.assembly import Assembly
from app.models.part import Part
from app.models.document_version import DocumentVersion
from app.schemas.document import (
    DocumentCreate,
    DocumentUpdate,
    DocumentResponse,
    DocumentWithVersionResponse,
    DocumentVersionCreate,
    DocumentVersionResponse
)
from app.services.document_service import document_service
from app.services.blob_storage import blob_storage
import logging
import tempfile
import os

def get_file_size_formatted(blob_path: str) -> str:
    if not blob_path:
        return "-"
    try:
        from app.services.blob_storage import blob_storage
        file_path = blob_storage.get_file_path(blob_path)
        size_bytes = os.path.getsize(str(file_path))
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
    except Exception:
        return "-"

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


def _step_to_glb(data: bytes, version_id: int, log: logging.Logger):
    """Convert STEP bytes to GLB. Tries in-memory first, then temp-file fallback with relaxed meshing."""
    try:
        import cascadio
    except ImportError:
        log.error("cascadio not installed; pip install cascadio")
        return None

    # Determine if we use the old 'load' API or the new 'step_to_glb' API
    load_fn = getattr(cascadio, "load", None)
    step_to_glb_fn = getattr(cascadio, "step_to_glb", None)

    # 1) In-memory with default params (Old API)
    if load_fn:
        try:
            glb = load_fn(data, file_type="step")
            if glb and len(glb) > 0:
                return glb
        except Exception as e:
            log.warning("cascadio.load (default) failed for version %s: %s", version_id, e)

        # 2) In-memory with relaxed meshing (often fixes OCCT failures)
        try:
            glb = load_fn(
                data,
                file_type="step",
                tol_linear=0.1,
                tol_angular=1.0,
                merge_primitives=True,
                use_parallel=False,
            )
            if glb and len(glb) > 0:
                return glb
        except Exception as e:
            log.warning("cascadio.load (relaxed) failed for version %s: %s", version_id, e)

    # 3) File-based step_to_glb if available (Preferred in newer versions like 0.0.17)
    if callable(step_to_glb_fn):
        step_path = None
        glb_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".stp", delete=False) as step_f:
                step_f.write(data)
                step_path = step_f.name
            glb_path = step_path + ".glb"
            
            # Use relaxed settings for file conversion if it supports it
            step_to_glb_fn(step_path, glb_path)
            
            if os.path.isfile(glb_path):
                with open(glb_path, "rb") as f:
                    glb = f.read()
                if glb and len(glb) > 0:
                    return glb
        except Exception as e:
            log.warning("cascadio.step_to_glb failed for version %s: %s", version_id, e)
        finally:
            for p in (glb_path, step_path):
                if p and os.path.isfile(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
    return None


def parse_optional_int(value: Optional[str]) -> Optional[int]:
    """Parse optional integer from form data, handling empty strings."""
    if value is None or value == "" or value == "null" or value == "none":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


@router.post("/", response_model=List[DocumentResponse], status_code=status.HTTP_201_CREATED)
async def create_document(
    file_2d: UploadFile = File(..., description="2D document file (PDF, DWG, etc.) - REQUIRED"),
    file_3d: Optional[UploadFile] = File(None, description="3D document file (STEP, STP, etc.) - OPTIONAL"),
    title: str = Form(...),
    assembly_id: Optional[str] = Form(None),
    part_id: Optional[str] = Form(None),
    file_format_2d: str = Form(..., description="File format for 2D document (e.g., pdf, dwg)"),
    file_format_3d: Optional[str] = Form(None, description="File format for 3D document (e.g., step, stp)"),
    pdf_content_type_2d: Optional[str] = Form("normal", description="For 2D PDF: 'normal' (text layer) or 'scanned' (OCR)"),
    uploaded_by: Optional[str] = Form(None),
    change_note: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Create documents and upload their versions.
    2D document is REQUIRED, 3D document is OPTIONAL.
    Requires exactly one of assembly_id or part_id.
    """
    # Parse optional integers from form strings
    assembly_id_int = parse_optional_int(assembly_id)
    part_id_int = parse_optional_int(part_id)
    
    # Validate that exactly one of assembly_id or part_id is provided
    if assembly_id_int is None and part_id_int is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either assembly_id or part_id must be provided"
        )
    if assembly_id_int is not None and part_id_int is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only one of assembly_id or part_id can be provided"
        )
    
    # Validate assembly exists if provided
    if assembly_id_int is not None:
        assembly = db.query(Assembly).filter(Assembly.id == assembly_id_int).first()
        if not assembly:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Assembly with ID {assembly_id_int} not found"
            )
    
    # Validate part exists if provided
    if part_id_int is not None:
        part = db.query(Part).filter(Part.id == part_id_int).first()
        if not part:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Part with ID {part_id_int} not found"
            )
    
    # Read file contents
    file_2d_content = await file_2d.read()
    file_3d_content = None
    if file_3d:
        file_3d_content = await file_3d.read()
    
    # Determine file extensions
    file_extension_2d = file_format_2d.lower()
    if file_2d.filename:
        if "." in file_2d.filename:
            file_extension_2d = file_2d.filename.split(".")[-1].lower()
    
    file_extension_3d = None
    if file_3d and file_format_3d:
        file_extension_3d = file_format_3d.lower()
        if file_3d.filename and "." in file_3d.filename:
            file_extension_3d = file_3d.filename.split(".")[-1].lower()
    
    created_documents = []
    
    try:
        # Normalize pdf_content_type for 2D (only "normal" or "scanned")
        pdf_type_2d = (pdf_content_type_2d or "normal").strip().lower()
        if pdf_type_2d not in ("normal", "scanned"):
            pdf_type_2d = "normal"

        # Create 2D document
        doc_2d = Document(
            doc_type=DocumentType.TWO_D,
            title=title,
            assembly_id=assembly_id_int,
            part_id=part_id_int,
            pdf_content_type=pdf_type_2d
        )
        db.add(doc_2d)
        db.flush()
        
        # Save 2D file to blob storage
        blob_path_2d = blob_storage.save_file(
            file_content=file_2d_content,
            file_extension=file_extension_2d,
            subfolder="document_versions"
        )
        
        # Create 2D version
        version_2d = DocumentVersion(
            document_id=doc_2d.id,
            version_no=1,
            blob_path=blob_path_2d,
            file_format=file_format_2d,
            is_current=True,
            uploaded_by=uploaded_by,
            change_note=change_note
        )
        db.add(version_2d)
        
        # Create 3D document only if file is provided
        doc_3d = None
        if file_3d and file_3d_content and file_extension_3d:
            doc_3d = Document(
                doc_type=DocumentType.THREE_D,
                title=title,
                assembly_id=assembly_id_int,
                part_id=part_id_int
            )
            db.add(doc_3d)
            db.flush()
            
            # Save 3D file to blob storage
            blob_path_3d = blob_storage.save_file(
                file_content=file_3d_content,
                file_extension=file_extension_3d,
                subfolder="document_versions"
            )
            
            # Create 3D version
            version_3d = DocumentVersion(
                document_id=doc_3d.id,
                version_no=1,
                blob_path=blob_path_3d,
                file_format=file_format_3d,
                is_current=True,
                uploaded_by=uploaded_by,
                change_note=change_note
            )
            db.add(version_3d)
        
        # Commit all changes
        db.commit()
        db.refresh(doc_2d)
        if doc_3d:
            db.refresh(doc_3d)
        
        # Return created documents
        created_documents = [doc_2d]
        if doc_3d:
            created_documents.append(doc_3d)
        
        if doc_3d:
            logger.info(f"Created 2D document {doc_2d.id} and 3D document {doc_3d.id} with first versions")
        else:
            logger.info(f"Created 2D document {doc_2d.id} with first version (no 3D document)")
        return created_documents
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating documents with versions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating documents: {str(e)}"
        )


@router.get("/", response_model=List[DocumentWithVersionResponse])
def list_documents(
    assembly_id: Optional[int] = None,
    part_id: Optional[int] = None,
    doc_type: Optional[DocumentType] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List all documents with optional filters, including current version information."""
    from sqlalchemy.orm import joinedload
    
    query = db.query(Document)
    
    if assembly_id is not None:
        query = query.filter(Document.assembly_id == assembly_id)
    if part_id is not None:
        query = query.filter(Document.part_id == part_id)
    if doc_type is not None:
        query = query.filter(Document.doc_type == doc_type)
    
    # Eager load versions to avoid N+1 queries
    documents = query.options(joinedload(Document.versions)).offset(skip).limit(limit).all()
    
    # Build response with current version info
    result = []
    for doc in documents:
        # Find current version
        current_version = next((v for v in doc.versions if v.is_current), None)
        
        # Build response data
        doc_size = get_file_size_formatted(current_version.blob_path) if current_version else None
        doc_data = {
            "id": doc.id,
            "doc_type": doc.doc_type,
            "title": doc.title,
            "assembly_id": doc.assembly_id,
            "part_id": doc.part_id,
            "created_at": doc.created_at,
            "pdf_content_type": getattr(doc, "pdf_content_type", None) or "normal",
            "blob_path": current_version.blob_path if current_version else None,
            "file_format": current_version.file_format if current_version else None,
            "version_no": current_version.version_no if current_version else None,
            "version_id": current_version.id if current_version else None,
            "download_url": f"/api/v1/documents/versions/{current_version.id}/download" if current_version else None,
            "preview_3d_url": f"/api/v1/documents/versions/{current_version.id}/preview-3d" if current_version and doc.doc_type == DocumentType.THREE_D else None,
            "size": doc_size
        }
        result.append(doc_data)
    
    return result


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: int, db: Session = Depends(get_db)):
    """Get a document by ID."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found"
        )
    return document


@router.put("/{document_id}", response_model=DocumentResponse)
def update_document(
    document_id: int,
    document_update: DocumentUpdate,
    db: Session = Depends(get_db)
):
    """Update a document."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found"
        )
    
    update_data = document_update.model_dump(exclude_unset=True)
    
    # Validate exactly one owner if being updated
    new_assembly_id = update_data.get("assembly_id", document.assembly_id)
    new_part_id = update_data.get("part_id", document.part_id)
    
    if new_assembly_id is None and new_part_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either assembly_id or part_id must be provided"
        )
    if new_assembly_id is not None and new_part_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only one of assembly_id or part_id can be provided"
        )
    
    # Validate assembly exists if being updated
    if "assembly_id" in update_data and update_data["assembly_id"] is not None:
        assembly = db.query(Assembly).filter(Assembly.id == update_data["assembly_id"]).first()
        if not assembly:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Assembly with ID {update_data['assembly_id']} not found"
            )
    
    # Validate part exists if being updated
    if "part_id" in update_data and update_data["part_id"] is not None:
        part = db.query(Part).filter(Part.id == update_data["part_id"]).first()
        if not part:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Part with ID {update_data['part_id']} not found"
            )
    
    for field, value in update_data.items():
        setattr(document, field, value)
    
    db.commit()
    db.refresh(document)
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, db: Session = Depends(get_db)):
    """Delete a document and all its versions."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found"
        )
    
    # Delete all version files from blob storage
    for version in document.versions:
        try:
            blob_storage.delete_file(version.blob_path)
        except Exception as e:
            logger.warning(f"Error deleting blob file for version {version.id}: {e}")
    
    db.delete(document)
    db.commit()
    return None


@router.post(
    "/{document_id}/versions",
    response_model=DocumentVersionResponse,
    status_code=status.HTTP_201_CREATED
)
async def upload_document_version(
    document_id: int,
    file: UploadFile = File(...),
    version_no: Optional[int] = Form(None),
    file_format: str = Form(...),
    uploaded_by: Optional[str] = Form(None),
    change_note: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Upload a new version of a document."""
    # Validate document exists
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found"
        )
    
    # Read file content
    file_content = await file.read()
    
    # Determine file extension from filename or file_format
    file_extension = file_format.lower()
    if file.filename:
        # Try to extract extension from filename
        if "." in file.filename:
            file_extension = file.filename.split(".")[-1].lower()
    
    # Create version data
    version_data = DocumentVersionCreate(
        version_no=version_no,
        file_format=file_format,
        uploaded_by=uploaded_by,
        change_note=change_note
    )
    
    # Create version using service
    try:
        new_version = document_service.create_document_version(
            db=db,
            document_id=document_id,
            version_data=version_data,
            file_content=file_content,
            file_extension=file_extension
        )
        return new_version
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/{document_id}/versions", response_model=List[DocumentVersionResponse])
def list_document_versions(document_id: int, db: Session = Depends(get_db)):
    """List all versions of a document."""
    # Validate document exists
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found"
        )
    
    versions = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == document_id
    ).order_by(DocumentVersion.version_no.desc()).all()
    
    return versions


@router.get("/{document_id}/versions/current", response_model=DocumentVersionResponse)
def get_current_version(document_id: int, db: Session = Depends(get_db)):
    """Get the current version of a document."""
    # Validate document exists
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found"
        )
    
    current_version = document_service.get_current_version(db, document_id)
    if not current_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No versions found for document {document_id}"
        )
    
    return current_version


@router.post("/3d-only", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_3d_document_only(
    file_3d: UploadFile = File(..., description="3D document file (STEP, STP, etc.)"),
    title: str = Form(...),
    assembly_id: Optional[str] = Form(None),
    part_id: Optional[str] = Form(None),
    file_format_3d: str = Form(..., description="File format for 3D document (e.g., step, stp)"),
    uploaded_by: Optional[str] = Form(None),
    change_note: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Create a 3D document and upload its first version.
    This endpoint is used to add 3D documents after 2D documents have been created.
    Requires exactly one of assembly_id or part_id.
    """
    # Parse optional integers from form strings
    assembly_id_int = parse_optional_int(assembly_id)
    part_id_int = parse_optional_int(part_id)
    
    # Validate that exactly one of assembly_id or part_id is provided
    if assembly_id_int is None and part_id_int is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either assembly_id or part_id must be provided"
        )
    if assembly_id_int is not None and part_id_int is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only one of assembly_id or part_id can be provided"
        )
    
    # Validate assembly exists if provided
    if assembly_id_int is not None:
        assembly = db.query(Assembly).filter(Assembly.id == assembly_id_int).first()
        if not assembly:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Assembly with ID {assembly_id_int} not found"
            )
    
    # Validate part exists if provided
    if part_id_int is not None:
        part = db.query(Part).filter(Part.id == part_id_int).first()
        if not part:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Part with ID {part_id_int} not found"
            )
    
    # Read file contents
    file_3d_content = await file_3d.read()
    
    # Determine file extension
    file_extension_3d = file_format_3d.lower()
    if file_3d.filename and "." in file_3d.filename:
        file_extension_3d = file_3d.filename.split(".")[-1].lower()
    
    try:
        # Create 3D document
        doc_3d = Document(
            doc_type=DocumentType.THREE_D,
            title=title,
            assembly_id=assembly_id_int,
            part_id=part_id_int
        )
        db.add(doc_3d)
        db.flush()
        
        # Save 3D file to blob storage
        blob_path_3d = blob_storage.save_file(
            file_content=file_3d_content,
            file_extension=file_extension_3d,
            subfolder="document_versions"
        )
        
        # Create 3D version
        version_3d = DocumentVersion(
            document_id=doc_3d.id,
            version_no=1,
            blob_path=blob_path_3d,
            file_format=file_format_3d,
            is_current=True,
            uploaded_by=uploaded_by,
            change_note=change_note
        )
        db.add(version_3d)
        
        # Commit all changes
        db.commit()
        db.refresh(doc_3d)
        
        logger.info(f"Created 3D document {doc_3d.id} with first version")
        return doc_3d
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating 3D document with version: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating 3D document: {str(e)}"
        )


@router.get("/versions/{version_id}/download")
def download_document_version(version_id: int, db: Session = Depends(get_db)):
    """Download a document version file."""
    version = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document version with ID {version_id} not found"
        )
    
    try:
        file_path = blob_storage.get_file_path(version.blob_path)
        ext = (version.file_format or "").lower()
        
        # Determine media type and disposition
        media_map = {
            "pdf": ("application/pdf", "inline"),
            "png": ("image/png", "inline"),
            "jpg": ("image/jpeg", "inline"),
            "jpeg": ("image/jpeg", "inline"),
            "webp": ("image/webp", "inline"),
            "txt": ("text/plain", "inline"),
        }
        
        media, disposition = media_map.get(ext, ("application/octet-stream", "attachment"))
        
        return FileResponse(
            path=str(file_path),
            filename=f"{version.document.title}_v{version.version_no}.{version.file_format}",
            media_type=media,
            content_disposition_type=disposition
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found for version {version_id}"
        )


@router.get("/versions/{version_id}/preview-3d")
def preview_3d_document_version(version_id: int, db: Session = Depends(get_db)):
    """
    Return 3D file suitable for web viewer. For STEP/STP, converts to GLB on the fly.
    For GLB/GLTF, returns the file as-is.
    """
    version = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document version with ID {version_id} not found"
        )
    fmt = (version.file_format or "").lower()
    try:
        file_path = blob_storage.get_file_path(version.blob_path)
        with open(file_path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found for version {version_id}"
        )

    if fmt in ("step", "stp"):
        glb_bytes = _step_to_glb(data, version_id, logger)
        if glb_bytes is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="STEP to GLB conversion failed. The file may be invalid or use unsupported geometry.",
            )
        return Response(
            content=glb_bytes,
            media_type="model/gltf-binary",
            headers={"Content-Disposition": f"inline; filename=\"{version.document.title}_v{version.version_no}.glb\""},
        )
    if fmt in ("glb", "gltf"):
        media = "model/gltf-binary" if fmt == "glb" else "model/gltf+json"
        return Response(
            content=data,
            media_type=media,
            headers={"Content-Disposition": f"inline; filename=\"{version.document.title}_v{version.version_no}.{version.file_format}\""},
        )
    # Unsupported 3D format: return original file so client can show a message
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"inline; filename=\"{version.document.title}_v{version.version_no}.{version.file_format}\""},
    )


@router.delete("/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_version(version_id: int, db: Session = Depends(get_db)):
    """Delete a document version."""
    success = document_service.delete_document_version(db, version_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document version with ID {version_id} not found"
        )
    return None

@router.post("/3d-only", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_3d_document_only(
    file_3d: UploadFile = File(...),
    title: str = Form(...),
    assembly_id: Optional[str] = Form(None),
    part_id: Optional[str] = Form(None),
    file_format_3d: str = Form("step"),
    uploaded_by: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Create a standalone 3D CAD document.
    """
    assembly_id_int = parse_optional_int(assembly_id)
    part_id_int = parse_optional_int(part_id)
    if assembly_id_int is None and part_id_int is None:
        raise HTTPException(400, "Either assembly_id or part_id must be provided")
        
    try:
        content = await file_3d.read()
        
        # Save file to blob storage
        from app.services.blob_storage import blob_storage
        blob_path = blob_storage.save_file(content, file_format_3d, "documents")
        
        db_doc = Document(
            doc_type=DocumentType.THREE_D,
            title=title,
            assembly_id=assembly_id_int,
            part_id=part_id_int
        )
        db.add(db_doc)
        db.flush()
        
        db_ver = DocumentVersion(
            document_id=db_doc.id,
            version_no=1,
            blob_path=blob_path,
            file_format=file_format_3d,
            is_current=True,
            uploaded_by=uploaded_by
        )
        db.add(db_ver)
        db.commit()
        db.refresh(db_doc)
        return db_doc
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))

