"""
Note router with CRUD operations.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models.note import Note
from app.models.part import Part
from app.models.document import Document
from app.schemas.note import NoteCreate, NoteUpdate, NoteResponse

router = APIRouter(prefix="/notes", tags=["notes"])


@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
def create_note(note: NoteCreate, db: Session = Depends(get_db)):
    """Create a new note."""
    # Validate part exists
    part = db.query(Part).filter(Part.id == note.part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {note.part_id} not found"
        )
    
    # Validate document exists if provided
    if note.document_id is not None:
        document = db.query(Document).filter(Document.id == note.document_id).first()
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID {note.document_id} not found"
            )
    
    db_note = Note(**note.model_dump())
    db.add(db_note)
    db.commit()
    db.refresh(db_note)
    return db_note


@router.get("/", response_model=List[NoteResponse])
def list_notes(
    part_id: Optional[int] = None,
    document_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List all notes with optional filters."""
    query = db.query(Note)
    
    if part_id is not None:
        query = query.filter(Note.part_id == part_id)
    if document_id is not None:
        query = query.filter(Note.document_id == document_id)
    
    notes = query.offset(skip).limit(limit).all()
    return notes


@router.get("/part/{part_id}", response_model=List[NoteResponse])
def get_notes_by_part(part_id: int, db: Session = Depends(get_db)):
    """Get all notes for a specific part."""
    # Validate part exists
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {part_id} not found"
        )
    
    notes = db.query(Note).filter(Note.part_id == part_id).all()
    return notes


@router.get("/{note_id}", response_model=NoteResponse)
def get_note(note_id: int, db: Session = Depends(get_db)):
    """Get a note by ID."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note with ID {note_id} not found"
        )
    return note


@router.put("/{note_id}", response_model=NoteResponse)
def update_note(
    note_id: int,
    note_update: NoteUpdate,
    db: Session = Depends(get_db)
):
    """Update a note."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note with ID {note_id} not found"
        )
    
    update_data = note_update.model_dump(exclude_unset=True)
    
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
    
    for field, value in update_data.items():
        setattr(note, field, value)
    
    db.commit()
    db.refresh(note)
    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: int, db: Session = Depends(get_db)):
    """Delete a note."""
    note = db.query(Note).filter(Note.id == note_id).first()
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note with ID {note_id} not found"
        )
    
    db.delete(note)
    db.commit()
    return None


@router.delete("/part/{part_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_notes_for_part(part_id: int, db: Session = Depends(get_db)):
    """Delete all notes for a specific part."""
    # Validate part exists
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {part_id} not found"
        )
    
    # Delete all notes for this part
    db.query(Note).filter(Note.part_id == part_id).delete()
    db.commit()
    return None
