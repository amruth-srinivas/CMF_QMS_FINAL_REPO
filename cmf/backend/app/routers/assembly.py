"""
Assembly router with CRUD operations.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models.assembly import Assembly
from app.models.project import Project
from app.schemas.assembly import AssemblyCreate, AssemblyUpdate, AssemblyResponse

router = APIRouter(prefix="/assemblies", tags=["assemblies"])


@router.post("", response_model=AssemblyResponse, status_code=status.HTTP_201_CREATED)
def create_assembly(assembly: AssemblyCreate, db: Session = Depends(get_db)):
    """Create a new assembly."""
    # Validate project exists
    project = db.query(Project).filter(Project.id == assembly.project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {assembly.project_id} not found"
        )
    
    # Validate parent assembly exists if provided
    if assembly.parent_assembly_id is not None:
        parent = db.query(Assembly).filter(Assembly.id == assembly.parent_assembly_id).first()
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Parent assembly with ID {assembly.parent_assembly_id} not found"
            )
        # Ensure parent belongs to same project
        if parent.project_id != assembly.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent assembly must belong to the same project"
            )
    
    # Create assembly, ensuring None values are properly handled
    assembly_data = assembly.model_dump()
    db_assembly = Assembly(**assembly_data)
    db.add(db_assembly)
    db.commit()
    db.refresh(db_assembly)
    return db_assembly


@router.get("", response_model=List[AssemblyResponse])
def list_assemblies(
    project_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List all assemblies with optional project filter."""
    query = db.query(Assembly)
    if project_id is not None:
        query = query.filter(Assembly.project_id == project_id)
    assemblies = query.offset(skip).limit(limit).all()
    return assemblies


@router.get("/{assembly_id}", response_model=AssemblyResponse)
def get_assembly(assembly_id: int, db: Session = Depends(get_db)):
    """Get an assembly by ID."""
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assembly with ID {assembly_id} not found"
        )
    return assembly


@router.put("/{assembly_id}", response_model=AssemblyResponse)
def update_assembly(
    assembly_id: int,
    assembly_update: AssemblyUpdate,
    db: Session = Depends(get_db)
):
    """Update an assembly."""
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assembly with ID {assembly_id} not found"
        )
    
    update_data = assembly_update.model_dump(exclude_unset=True)
    
    # Validate project if being updated
    if "project_id" in update_data:
        project = db.query(Project).filter(Project.id == update_data["project_id"]).first()
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project with ID {update_data['project_id']} not found"
            )
    
    # Validate parent assembly if being updated
    if "parent_assembly_id" in update_data and update_data["parent_assembly_id"] is not None:
        parent = db.query(Assembly).filter(Assembly.id == update_data["parent_assembly_id"]).first()
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Parent assembly with ID {update_data['parent_assembly_id']} not found"
            )
        # Prevent circular reference
        if update_data["parent_assembly_id"] == assembly_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Assembly cannot be its own parent"
            )
    
    for field, value in update_data.items():
        setattr(assembly, field, value)
    
    db.commit()
    db.refresh(assembly)
    return assembly


@router.delete("/{assembly_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assembly(assembly_id: int, db: Session = Depends(get_db)):
    """Delete an assembly."""
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assembly with ID {assembly_id} not found"
        )
    
    db.delete(assembly)
    db.commit()
    return None

