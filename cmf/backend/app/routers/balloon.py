"""
Balloon router with CRUD operations.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models.balloon import Balloon
from app.models.part import Part
from app.models.document import Document
from app.schemas.balloon import BalloonCreate, BalloonUpdate, BalloonResponse

router = APIRouter(prefix="/balloons", tags=["balloons"])


@router.post("/", response_model=BalloonResponse, status_code=status.HTTP_201_CREATED)
def create_balloon(balloon: BalloonCreate, db: Session = Depends(get_db)):
    """Create a new balloon."""
    # Validate part exists
    part = db.query(Part).filter(Part.id == balloon.part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {balloon.part_id} not found"
        )
    
    # Validate document exists if provided
    if balloon.document_id is not None:
        document = db.query(Document).filter(Document.id == balloon.document_id).first()
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID {balloon.document_id} not found"
            )
    
    # Check if balloon_id already exists for this part
    existing = db.query(Balloon).filter(
        Balloon.part_id == balloon.part_id,
        Balloon.balloon_id == balloon.balloon_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Balloon with ID '{balloon.balloon_id}' already exists for part {balloon.part_id}"
        )
    
    db_balloon = Balloon(**balloon.model_dump())
    db.add(db_balloon)
    db.commit()
    # Refresh not needed - object already has all values after commit
    # db.refresh(db_balloon)  # Removed to avoid SQLAlchemy type mapping issue
    return db_balloon


@router.get("/", response_model=List[BalloonResponse])
def list_balloons(
    part_id: Optional[int] = None,
    document_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List all balloons with optional filters.
    Returns balloons ordered by creation time to preserve existing order.
    Existing balloons (1-5) maintain their order, new balloons are added at the end.
    """
    query = db.query(Balloon)
    
    if part_id is not None:
        query = query.filter(Balloon.part_id == part_id)
    if document_id is not None:
        query = query.filter(Balloon.document_id == document_id)
    
    # Order by creation time to preserve existing balloon order
    # This ensures balloons 1-5 stay as 1-5, and new balloons are added at the end
    query = query.order_by(Balloon.created_at.asc())
    
    balloons = query.offset(skip).limit(limit).all()
    return balloons


@router.get("/{balloon_id}", response_model=BalloonResponse)
def get_balloon(balloon_id: int, db: Session = Depends(get_db)):
    """Get a balloon by ID."""
    balloon = db.query(Balloon).filter(Balloon.id == balloon_id).first()
    if not balloon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Balloon with ID {balloon_id} not found"
        )
    return balloon


@router.put("/{balloon_id}", response_model=BalloonResponse)
def update_balloon(
    balloon_id: int,
    balloon_update: BalloonUpdate,
    db: Session = Depends(get_db)
):
    """Update a balloon."""
    balloon = db.query(Balloon).filter(Balloon.id == balloon_id).first()
    if not balloon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Balloon with ID {balloon_id} not found"
        )
    
    update_data = balloon_update.model_dump(exclude_unset=True)
    
    # Validate part if being updated
    if "part_id" in update_data:
        part = db.query(Part).filter(Part.id == update_data["part_id"]).first()
        if not part:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Part with ID {update_data['part_id']} not found"
            )
    
    # Validate document if being updated (and provided)
    if "document_id" in update_data and update_data["document_id"] is not None:
        document = db.query(Document).filter(Document.id == update_data["document_id"]).first()
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID {update_data['document_id']} not found"
            )
    
    # Check balloon_id uniqueness if being updated
    if "balloon_id" in update_data:
        part_id_to_check = update_data.get("part_id", balloon.part_id)
        existing = db.query(Balloon).filter(
            Balloon.part_id == part_id_to_check,
            Balloon.balloon_id == update_data["balloon_id"],
            Balloon.id != balloon_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Balloon with ID '{update_data['balloon_id']}' already exists for part {part_id_to_check}"
            )
    
    for field, value in update_data.items():
        setattr(balloon, field, value)
    
    db.commit()
    # Refresh not needed - object already has all values after commit
    # db.refresh(balloon)  # Removed to avoid SQLAlchemy type mapping issue
    return balloon


@router.delete("/{balloon_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_balloon(balloon_id: int, db: Session = Depends(get_db)):
    """Delete a balloon."""
    balloon = db.query(Balloon).filter(Balloon.id == balloon_id).first()
    if not balloon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Balloon with ID {balloon_id} not found"
        )
    
    db.delete(balloon)
    db.commit()
    return None

