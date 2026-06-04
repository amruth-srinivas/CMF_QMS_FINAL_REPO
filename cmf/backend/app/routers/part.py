"""
Part router with CRUD operations.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timezone
from app.database import get_db
from app.models.part import Part
from app.models.part_location import PartLocation
from app.models.project import Project
from app.models.assembly import Assembly
from app.models.note import Note
from app.models.balloon import Balloon
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.schemas.part import PartCreate, PartUpdate, PartResponse, PartWithLocationResponse

router = APIRouter(prefix="/parts", tags=["parts"])


@router.post("", response_model=PartResponse, status_code=status.HTTP_201_CREATED)
def create_part(part: PartCreate, db: Session = Depends(get_db)):
    """Create a new part with optional location."""
    # Check if part_no already exists
    existing = db.query(Part).filter(Part.part_no == part.part_no).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Part with part_no '{part.part_no}' already exists"
        )
    
    # Extract location data before creating part
    part_data = part.model_dump()
    project_id = part_data.pop("project_id", None)
    assembly_id = part_data.pop("assembly_id", None)
    quantity = part_data.pop("quantity", 1)
    
    # Create the part
    if part_data.get("inspection_plan_status"):
        part_data["inspection_plan_approved_at"] = datetime.now(timezone.utc)
        
    db_part = Part(**part_data)
    db.add(db_part)
    db.flush()  # Flush to get the part ID without committing
    
    # Create part location if provided
    if project_id is not None or assembly_id is not None:
        # Validate project exists if provided
        if project_id is not None:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Project with ID {project_id} not found"
                )
        
        # Validate assembly exists if provided
        if assembly_id is not None:
            assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
            if not assembly:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Assembly with ID {assembly_id} not found"
                )
        
        # Create part location
        part_location = PartLocation(
            part_id=db_part.id,
            project_id=project_id,
            assembly_id=assembly_id,
            quantity=quantity
        )
        db.add(part_location)
    
    db.commit()
    db.refresh(db_part)
    return db_part


@router.get("", response_model=List[PartResponse])
def list_parts(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all parts with pagination."""
    parts = db.query(Part).offset(skip).limit(limit).all()
    return parts


@router.get("/{part_id}", response_model=PartResponse)
def get_part(part_id: int, db: Session = Depends(get_db)):
    """Get a part by ID."""
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {part_id} not found"
        )
    return part


@router.get("/{part_id}/with-location", response_model=PartWithLocationResponse)
def get_part_with_location(part_id: int, db: Session = Depends(get_db)):
    """Get a part by ID with location and quantity information."""
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {part_id} not found"
        )
    
    # Get part location to fetch quantity
    part_location = db.query(PartLocation).filter(PartLocation.part_id == part_id).first()
    
    # Build response with location info
    response_data = {
        "id": part.id,
        "part_no": part.part_no,
        "name": part.name,
        "rev": getattr(part, "rev", None),
        "created_at": part.created_at,
        "inspection_plan_status": part.inspection_plan_status,
        "priority_component": getattr(part, "priority_component", False),
        "project_id": part_location.project_id if part_location else None,
        "assembly_id": part_location.assembly_id if part_location else None,
        "quantity": part_location.quantity if part_location else 1
    }
    
    return response_data


@router.put("/{part_id}", response_model=PartResponse)
def update_part(
    part_id: int,
    part_update: PartUpdate,
    db: Session = Depends(get_db)
):
    """Update a part."""
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {part_id} not found"
        )
    
    update_data = part_update.model_dump(exclude_unset=True)
    quantity = update_data.pop("quantity", None)
    
    # Check if part_no is being changed and if it conflicts
    if "part_no" in update_data:
        existing = db.query(Part).filter(
            Part.part_no == update_data["part_no"],
            Part.id != part_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Part with part_no '{update_data['part_no']}' already exists"
            )
    
    for field, value in update_data.items():
        setattr(part, field, value)
    
    # Update quantity in PartLocation (quantity is stored there, not on Part)
    if quantity is not None:
        qty = max(1, int(quantity))
        part_locations = db.query(PartLocation).filter(PartLocation.part_id == part_id).all()
        for pl in part_locations:
            pl.quantity = qty
            
    # Update approved_at if status changed
    if "inspection_plan_status" in update_data:
        if update_data["inspection_plan_status"]:
            part.inspection_plan_approved_at = datetime.now(timezone.utc)
        else:
            part.inspection_plan_approved_at = None
    
    db.commit()
    db.refresh(part)
    return part


@router.patch("/{part_id}/toggle-inspection-plan", response_model=PartResponse)
def toggle_inspection_plan_status(part_id: int, db: Session = Depends(get_db)):
    """Toggle the inspection plan status for a part."""
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {part_id} not found"
        )
    
    # Toggle the status
    part.inspection_plan_status = not part.inspection_plan_status
    if part.inspection_plan_status:
        part.inspection_plan_approved_at = datetime.now(timezone.utc)
    else:
        part.inspection_plan_approved_at = None
        
    db.commit()
    db.refresh(part)
    return part


@router.delete("/{part_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_part(part_id: int, db: Session = Depends(get_db)):
    """Delete a part and its dependent records (notes, balloons, part_locations, documents) that may not have DB-level CASCADE."""
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {part_id} not found"
        )
    # Delete dependent records first (DB may not have ON DELETE CASCADE). Order matters for FKs.
    db.query(Note).filter(Note.part_id == part_id).delete(synchronize_session=False)
    db.query(Balloon).filter(Balloon.part_id == part_id).delete(synchronize_session=False)
    db.query(PartLocation).filter(PartLocation.part_id == part_id).delete(synchronize_session=False)
    doc_ids = [r[0] for r in db.query(Document.id).filter(Document.part_id == part_id).all()]
    for doc_id in doc_ids:
        db.query(DocumentVersion).filter(DocumentVersion.document_id == doc_id).delete(synchronize_session=False)
    db.query(Document).filter(Document.part_id == part_id).delete(synchronize_session=False)
    db.delete(part)
    db.commit()
    return None

