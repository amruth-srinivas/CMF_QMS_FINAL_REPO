"""
Report configuration (template) router.
CRUD for report_config and report_config_fields, logo upload, lock.
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
from pathlib import Path
import os
import uuid
import logging

from app.database import get_db
from app.models.report_config import ReportConfig, ReportConfigField
from app.schemas.report_config import (
    ReportConfigCreate,
    ReportConfigUpdate,
    ReportConfigResponse,
    ReportConfigListResponse,
    ReportConfigFieldCreate,
    ReportConfigFieldUpdate,
    ReportConfigFieldResponse,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report-config", tags=["report-config"])

LOGO_SUBDIR = "logos"
ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


def _logos_dir() -> Path:
    blob = Path(settings.BLOB_STORAGE_PATH)
    logos = blob / LOGO_SUBDIR
    logos.mkdir(parents=True, exist_ok=True)
    return logos


def _check_not_locked(config: ReportConfig):
    if config.is_locked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Template is locked. Unlock before making changes.",
        )


# ---------- Report config CRUD ----------


@router.get("/", response_model=List[ReportConfigListResponse])
def list_configs(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    """List all report configurations."""
    return db.query(ReportConfig).order_by(ReportConfig.id).offset(skip).limit(limit).all()


@router.get("/default", response_model=ReportConfigResponse)
def get_or_create_default(db: Session = Depends(get_db)):
    """Get the default (first) report config, or create one if none exist."""
    config = db.query(ReportConfig).first()
    if config:
        return config
    config = ReportConfig(report_name="Inspection Report", company_name="")
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.get("/{config_id}", response_model=ReportConfigResponse)
def get_config(config_id: int, db: Session = Depends(get_db)):
    """Get a report configuration by id with all fields."""
    config = db.query(ReportConfig).filter(ReportConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report config not found")
    return config


@router.post("/", response_model=ReportConfigResponse, status_code=status.HTTP_201_CREATED)
def create_config(body: ReportConfigCreate, db: Session = Depends(get_db)):
    """Create a new report configuration."""
    config = ReportConfig(
        report_name=body.report_name,
        company_name=body.company_name,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.patch("/{config_id}", response_model=ReportConfigResponse)
def update_config(config_id: int, body: ReportConfigUpdate, db: Session = Depends(get_db)):
    """Update report configuration. Blocked if template is locked."""
    config = db.query(ReportConfig).filter(ReportConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report config not found")
    _check_not_locked(config)
    if body.report_name is not None:
        config.report_name = body.report_name
    if body.company_name is not None:
        config.company_name = body.company_name
    if body.is_locked is not None:
        config.is_locked = body.is_locked
    db.commit()
    db.refresh(config)
    return config


@router.post("/{config_id}/lock", response_model=ReportConfigResponse)
def lock_config(config_id: int, db: Session = Depends(get_db)):
    """Lock the template so it cannot be edited."""
    config = db.query(ReportConfig).filter(ReportConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report config not found")
    config.is_locked = True
    db.commit()
    db.refresh(config)
    return config


@router.post("/{config_id}/unlock", response_model=ReportConfigResponse)
def unlock_config(config_id: int, db: Session = Depends(get_db)):
    """Unlock the template for editing."""
    config = db.query(ReportConfig).filter(ReportConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report config not found")
    config.is_locked = False
    db.commit()
    db.refresh(config)
    return config


# ---------- Logo upload ----------


@router.post("/{config_id}/logo", response_model=ReportConfigResponse)
def upload_logo(config_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload company logo. Replaces existing logo. Blocked if template is locked."""
    config = db.query(ReportConfig).filter(ReportConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report config not found")
    _check_not_locked(config)

    suffix = Path(file.filename or "logo").suffix.lower()
    if suffix not in ALLOWED_LOGO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Allowed logo extensions: {', '.join(ALLOWED_LOGO_EXTENSIONS)}",
        )

    content = file.file.read()
    if len(content) > 5 * 1024 * 1024:  # 5 MB
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Logo file too large (max 5 MB)")

    logos_dir = _logos_dir()
    safe_name = f"{uuid.uuid4().hex}{suffix}"
    path = logos_dir / safe_name
    path.write_bytes(content)

    # Store path relative to blob root so URL is /blob/logos/xxx.png
    config.logo_path = f"{LOGO_SUBDIR}/{safe_name}"
    db.commit()
    db.refresh(config)
    return config


@router.delete("/{config_id}/logo", response_model=ReportConfigResponse)
def delete_logo(config_id: int, db: Session = Depends(get_db)):
    """Remove company logo. Blocked if template is locked."""
    config = db.query(ReportConfig).filter(ReportConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report config not found")
    _check_not_locked(config)
    if config.logo_path:
        blob_root = Path(settings.BLOB_STORAGE_PATH)
        full = blob_root / config.logo_path
        if full.exists():
            try:
                full.unlink()
            except OSError as e:
                logger.warning("Could not delete logo file %s: %s", full, e)
    config.logo_path = None
    db.commit()
    db.refresh(config)
    return config


# ---------- Fields CRUD ----------


@router.post("/{config_id}/fields", response_model=ReportConfigFieldResponse, status_code=status.HTTP_201_CREATED)
def add_field(config_id: int, body: ReportConfigFieldCreate, db: Session = Depends(get_db)):
    """Add a header or footer field. Blocked if template is locked."""
    config = db.query(ReportConfig).filter(ReportConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report config not found")
    _check_not_locked(config)
    if body.section not in ("header", "footer"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="section must be 'header' or 'footer'")
    field = ReportConfigField(
        report_id=config_id,
        section=body.section,
        field_label=body.field_label,
        backend_key=body.backend_key,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return field


@router.patch("/{config_id}/fields/{field_id}", response_model=ReportConfigFieldResponse)
def update_field(
    config_id: int, field_id: int, body: ReportConfigFieldUpdate, db: Session = Depends(get_db)
):
    """Update a field. Blocked if template is locked."""
    config = db.query(ReportConfig).filter(ReportConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report config not found")
    _check_not_locked(config)
    field = db.query(ReportConfigField).filter(
        ReportConfigField.id == field_id,
        ReportConfigField.report_id == config_id,
    ).first()
    if not field:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found")
    if body.section is not None:
        if body.section not in ("header", "footer"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="section must be 'header' or 'footer'")
        field.section = body.section
    if body.field_label is not None:
        field.field_label = body.field_label
    if body.backend_key is not None:
        field.backend_key = body.backend_key
    db.commit()
    db.refresh(field)
    return field


@router.delete("/{config_id}/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_field(config_id: int, field_id: int, db: Session = Depends(get_db)):
    """Delete a field. Blocked if template is locked."""
    config = db.query(ReportConfig).filter(ReportConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report config not found")
    _check_not_locked(config)
    field = db.query(ReportConfigField).filter(
        ReportConfigField.id == field_id,
        ReportConfigField.report_id == config_id,
    ).first()
    if not field:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found")
    db.delete(field)
    db.commit()
    return None
