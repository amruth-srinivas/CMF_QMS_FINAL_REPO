from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
import io
import logging

from app.database import get_db
from app.models.report_template import ReportTemplate
from app.schemas.report_template import (
    ReportTemplateCreate,
    ReportTemplateUpdate,
    ReportTemplateResponse,
    ReportTemplateListResponse,
)
import subprocess
from functools import lru_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report-templates", tags=["report-templates"])


class TemplateExportRequest(BaseModel):
    name: str = "Untitled Template"
    header_html: str = ""
    footer_html: str = ""
    description: str = ""


@router.post("/export/{fmt}")
def export_template(fmt: str, body: TemplateExportRequest):
    """Export a report template as PDF, DOCX, or XLSX."""
    from app.services.template_export import export_pdf, export_docx, export_xlsx

    fmt = fmt.lower()
    MIME = {
        'pdf': 'application/pdf',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }
    if fmt not in MIME:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}. Use pdf, docx, or xlsx.")

    try:
        if fmt == 'pdf':
            data = export_pdf(body.header_html, body.footer_html, body.description, body.name)
        elif fmt == 'docx':
            data = export_docx(body.header_html, body.footer_html, body.description, body.name)
        else:
            data = export_xlsx(body.header_html, body.footer_html, body.description, body.name)
    except Exception as e:
        logger.error(f"Export failed ({fmt}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

    safe_name = body.name.replace('"', '_')
    return StreamingResponse(
        io.BytesIO(data),
        media_type=MIME[fmt],
        headers={
            'Content-Disposition': f'attachment; filename="{safe_name}.{fmt}"'
        }
    )

@router.get("/available-fonts", response_model=List[str])
@lru_cache(maxsize=1)
def get_available_fonts():
    """Get list of fonts installed on the system (Windows)."""
    try:
        # Use PowerShell to get installed font family names
        cmd = [
            "powershell", 
            "-Command", 
            "[System.Reflection.Assembly]::LoadWithPartialName('System.Drawing'); (New-Object System.Drawing.Text.InstalledFontCollection).Families.Name"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        fonts = [f.strip() for f in result.stdout.split('\n') if f.strip()]
        # Remove duplicates and sort
        return sorted(list(set(fonts)))
    except Exception as e:
        # Fallback to standard web-safe fonts if system query fails
        return ["Arial", "Helvetica", "Times New Roman", "Courier New", "Verdana", "Georgia", "Tahoma", "Trebuchet MS"]

@router.get("/", response_model=List[ReportTemplateListResponse])
def list_templates(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all report templates."""
    return db.query(ReportTemplate).order_by(ReportTemplate.id).offset(skip).limit(limit).all()


@router.get("/{template_id}", response_model=ReportTemplateResponse)
def get_template(template_id: int, db: Session = Depends(get_db)):
    """Get a report template by id."""
    template = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report template not found")
    return template


@router.post("/", response_model=ReportTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(body: ReportTemplateCreate, db: Session = Depends(get_db)):
    """Create a new report template."""
    # If this is set as default, unset others first
    if body.is_default:
        db.query(ReportTemplate).update({ReportTemplate.is_default: False})

    template = ReportTemplate(
        name=body.name,
        description=body.description,
        header_html=body.header_html,
        footer_html=body.footer_html,
        is_default=body.is_default,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.patch("/{template_id}", response_model=ReportTemplateResponse)
def update_template(template_id: int, body: ReportTemplateUpdate, db: Session = Depends(get_db)):
    """Update a report template."""
    template = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report template not found")

    if body.is_default is True:
        db.query(ReportTemplate).update({ReportTemplate.is_default: False})

    if body.name is not None:
        template.name = body.name
    if body.description is not None:
        template.description = body.description
    if body.header_html is not None:
        template.header_html = body.header_html
    if body.footer_html is not None:
        template.footer_html = body.footer_html
    if body.is_default is not None:
        template.is_default = body.is_default

    db.commit()
    db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: int, db: Session = Depends(get_db)):
    """Delete a report template."""
    template = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report template not found")
    db.delete(template)
    db.commit()
    return None
