"""
Project router with CRUD operations.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)
from app.database import get_db
from app.models.project import Project
from app.models.assembly import Assembly
from app.models.part_location import PartLocation
from app.models.part import Part
from app.models.document import Document, DocumentType
from app.models.document_version import DocumentVersion
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse, ProjectDetailResponse
from app.schemas.assembly import AssemblyResponse
from app.schemas.part import PartWithLocationResponse
from pydantic import BaseModel

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCompletionValidation(BaseModel):
    """Schema for project completion validation response."""
    can_complete: bool
    incomplete_parts: List[Dict[str, Any]] = []
    message: str


@router.get("/{project_id}/validate-completion", response_model=ProjectCompletionValidation)
def validate_project_completion(project_id: int, db: Session = Depends(get_db)):
    """
    Validate if a project can be marked as complete.
    A project can be completed only if all its parts have inspection_plan_status = True.
    Returns the validation status and list of incomplete parts if any.
    """
    # Get project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found"
        )
    
    # Get all assemblies for this project
    assemblies = db.query(Assembly).filter(Assembly.project_id == project_id).all()
    assembly_ids = [a.id for a in assemblies]
    
    # Get all parts for this project (both direct and through assemblies)
    # Parts directly linked to project
    project_parts = db.query(PartLocation).filter(
        PartLocation.project_id == project_id
    ).options(joinedload(PartLocation.part)).all()
    
    # Parts linked through assemblies
    assembly_parts = []
    if assembly_ids:
        assembly_parts = db.query(PartLocation).filter(
            PartLocation.assembly_id.in_(assembly_ids)
        ).options(joinedload(PartLocation.part)).all()
    
    # Combine all part locations
    all_part_locations = project_parts + assembly_parts
    
    # Check for incomplete parts
    incomplete_parts = []
    for pl in all_part_locations:
        if not pl.part.inspection_plan_status:
            incomplete_parts.append({
                "id": pl.part.id,
                "part_no": pl.part.part_no,
                "name": pl.part.name,
                "inspection_plan_status": pl.part.inspection_plan_status,
                "project_id": pl.project_id,
                "assembly_id": pl.assembly_id
            })
    
    can_complete = len(incomplete_parts) == 0
    message = (
        "All parts have completed inspection status. Project can be marked as complete."
        if can_complete else
        f"Project cannot be marked as complete. {len(incomplete_parts)} part(s) have incomplete inspection status."
    )
    
    return ProjectCompletionValidation(
        can_complete=can_complete,
        incomplete_parts=incomplete_parts,
        message=message
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    """Create a new project."""
    db_project = Project(**project.model_dump())
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project


@router.get("", response_model=List[ProjectResponse])
def list_projects(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all projects with pagination."""
    projects = db.query(Project).offset(skip).limit(limit).all()
    return projects


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Session = Depends(get_db)):
    """Get a project by ID."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found"
        )
    return project


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    project_update: ProjectUpdate,
    db: Session = Depends(get_db)
):
    """Update a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found"
        )
    
    update_data = project_update.model_dump(exclude_unset=True)
    
    # If trying to mark project as complete, validate first
    if update_data.get("is_completed") is True:
        # Get all assemblies for this project
        assemblies = db.query(Assembly).filter(Assembly.project_id == project_id).all()
        assembly_ids = [a.id for a in assemblies]
        
        # Get all parts for this project (both direct and through assemblies)
        project_parts = db.query(PartLocation).filter(
            PartLocation.project_id == project_id
        ).options(joinedload(PartLocation.part)).all()
        
        assembly_parts = []
        if assembly_ids:
            assembly_parts = db.query(PartLocation).filter(
                PartLocation.assembly_id.in_(assembly_ids)
            ).options(joinedload(PartLocation.part)).all()
        
        all_part_locations = project_parts + assembly_parts
        
        # Check if all parts have completed inspection status
        incomplete_parts = [
            pl for pl in all_part_locations 
            if not pl.part.inspection_plan_status
        ]
        
        if incomplete_parts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot mark project as complete. {len(incomplete_parts)} part(s) have incomplete inspection status."
            )
    
    # Apply updates
    for field, value in update_data.items():
        setattr(project, field, value)
    
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    """Delete a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found"
        )
    
    db.delete(project)
    db.commit()
    return None


@router.get("/{project_id}/details", response_model=ProjectDetailResponse)
def get_project_details(project_id: int, db: Session = Depends(get_db)):
    """
    Get project details including all assemblies and parts.
    Refactored to use separate queries for stability.
    """
    # Get project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found"
        )
    
    # Get all assemblies for this project
    assemblies = db.query(Assembly).filter(Assembly.project_id == project_id).all()
    
    # Get all project documents in one go (optional optimization)
    # But for now let's just fetch them per item to be safe and simple
    
    def get_docs_for_owner(owner_type: str, owner_id: int):
        """Helper to get documents for a specific owner without complex eager loading."""
        try:
            docs = []
            if owner_type == "assembly":
                docs = db.query(Document).filter(Document.assembly_id == owner_id).all()
            elif owner_type == "part":
                docs = db.query(Document).filter(Document.part_id == owner_id).all()
            
            result = []
            for doc in docs:
                # Get current version for each document separately
                current_version = db.query(DocumentVersion).filter(
                    DocumentVersion.document_id == doc.id,
                    DocumentVersion.is_current == True
                ).first()
                
                result.append({
                    "id": str(doc.id),
                    "label": doc.title,
                    "doc_type": doc.doc_type.value if hasattr(doc.doc_type, "value") else str(doc.doc_type),
                    "kind": "3d_cad_model" if doc.doc_type == DocumentType.THREE_D else "engineering_drawing",
                    "format": current_version.file_format.upper() if current_version else "PDF",
                    "size": "N/A",
                    "url": f"/api/v1/documents/versions/{current_version.id}/download" if current_version else None,
                    "preview_3d_url": f"/api/v1/documents/versions/{current_version.id}/preview-3d" if current_version and doc.doc_type == DocumentType.THREE_D else None
                })
            return result
        except Exception as e:
            logger.error(f"Error getting documents for {owner_type} {owner_id}: {e}")
            return []

    assembly_responses = []
    for a in assemblies:
        assembly_responses.append({
            "id": a.id,
            "name": a.name,
            "no": getattr(a, "no", None),
            "rev": getattr(a, "rev", None),
            "project_id": a.project_id,
            "parent_assembly_id": a.parent_assembly_id,
            "created_at": a.created_at,
            "documents": get_docs_for_owner("assembly", a.id)
        })
    
    # Get all part locations
    project_parts = db.query(PartLocation).filter(PartLocation.project_id == project_id).all()
    
    assembly_ids = [a.id for a in assemblies]
    assembly_parts = []
    if assembly_ids:
        assembly_parts = db.query(PartLocation).filter(PartLocation.assembly_id.in_(assembly_ids)).all()
    
    all_part_locations = project_parts + assembly_parts
    
    part_responses = []
    processed_part_loc_ids = set()
    for pl in all_part_locations:
        if pl.id in processed_part_loc_ids:
            continue
        processed_part_loc_ids.add(pl.id)
        
        # Load part manually if not loaded
        part = pl.part
        if not part: continue

        part_responses.append({
            "id": part.id,
            "part_no": part.part_no,
            "name": part.name,
            "rev": getattr(part, "rev", None),
            "created_at": part.created_at,
            "inspection_plan_status": getattr(part, "inspection_plan_status", False),
            "inspection_plan_approved_at": getattr(part, "inspection_plan_approved_at", None),
            "priority_component": getattr(part, "priority_component", False),
            "project_id": pl.project_id,
            "assembly_id": pl.assembly_id,
            "quantity": pl.quantity,
            "documents": get_docs_for_owner("part", part.id)
        })
    
    return {
        "id": project.id,
        "project_number": project.project_number,
        "name": project.name,
        "customer_details": project.customer_details,
        "reference_no": project.reference_no,
        "created_at": project.created_at,
        "assemblies": assembly_responses,
        "parts": part_responses
    }

