"""
Instrument setup: category tree and per-category library instruments.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.instrument_setup import InstrumentSetupCategory, LibraryInstrument
from app.models.bluetooth_device import BluetoothDevice

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/instrument-setup", tags=["instrument-setup"])


class CategoryTreeDTO(BaseModel):
    id: int
    name: str
    device_count: int
    children: List["CategoryTreeDTO"] = []


CategoryTreeDTO.model_rebuild()


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: Optional[int] = None


class CategoryCreateResponse(BaseModel):
    id: int
    name: str
    parent_id: Optional[int]


class LibraryInstrumentDTO(BaseModel):
    id: int
    category_id: int
    instrument_code: str
    instrument_name: Optional[str] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    serial_number: Optional[str] = None
    range: Optional[str] = None
    resolution: Optional[str] = None
    accuracy: Optional[str] = None
    last_calibration_date: Optional[str] = None
    calibration: Optional[str] = None # Next Cal Date
    calibration_interval: Optional[int] = None
    status: Optional[str] = None
    location: Optional[str] = None
    available_qty: int
    equipment_no: Optional[str] = None

class LibraryInstrumentCreate(BaseModel):
    category_id: int
    instrument_code: str = Field(..., min_length=1, max_length=120)
    instrument_name: Optional[str] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    serial_number: Optional[str] = None
    range: Optional[str] = None
    resolution: Optional[str] = None
    accuracy: Optional[str] = None
    last_calibration_date: Optional[str] = None
    calibration: Optional[str] = None
    calibration_interval: Optional[int] = None
    status: Optional[str] = "Active"
    location: Optional[str] = None
    available_qty: int = Field(1, ge=0)
    equipment_no: Optional[str] = None

class LibraryInstrumentUpdate(BaseModel):
    instrument_code: Optional[str] = Field(None, min_length=1, max_length=120)
    instrument_name: Optional[str] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    serial_number: Optional[str] = None
    range: Optional[str] = None
    resolution: Optional[str] = None
    accuracy: Optional[str] = None
    last_calibration_date: Optional[str] = None
    calibration: Optional[str] = None
    calibration_interval: Optional[int] = None
    status: Optional[str] = None
    location: Optional[str] = None
    available_qty: Optional[int] = Field(None, ge=0)
    equipment_no: Optional[str] = None




def _count_instruments(db: Session, category_id: int) -> int:
    return (
        db.query(LibraryInstrument)
        .filter(LibraryInstrument.category_id == category_id)
        .count()
    )


def _build_tree(db: Session, nodes: List[InstrumentSetupCategory]) -> List[CategoryTreeDTO]:
    out: List[CategoryTreeDTO] = []
    for n in nodes:
        kids = (
            db.query(InstrumentSetupCategory)
            .filter(InstrumentSetupCategory.parent_id == n.id)
            .order_by(InstrumentSetupCategory.id.asc())
            .all()
        )
        out.append(
            CategoryTreeDTO(
                id=n.id,
                name=n.name,
                device_count=_count_instruments(db, n.id),
                children=_build_tree(db, kids),
            )
        )
    return out


@router.get("/categories/tree", response_model=List[CategoryTreeDTO])
def get_category_tree(db: Session = Depends(get_db)):
    roots = (
        db.query(InstrumentSetupCategory)
        .filter(InstrumentSetupCategory.parent_id.is_(None))
        .order_by(InstrumentSetupCategory.id.asc())
        .all()
    )
    return _build_tree(db, roots)


@router.post("/categories", response_model=CategoryCreateResponse, status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryCreate, db: Session = Depends(get_db)):
    if body.parent_id is not None:
        p = db.query(InstrumentSetupCategory).filter(InstrumentSetupCategory.id == body.parent_id).first()
        if not p:
            raise HTTPException(status_code=400, detail="Parent category not found")
    row = InstrumentSetupCategory(name=body.name.strip(), parent_id=body.parent_id)
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
    except Exception as e:
        logger.exception("create_category")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    return CategoryCreateResponse(id=row.id, name=row.name, parent_id=row.parent_id)


def _delete_category_subtree(db: Session, category_id: int) -> None:
    children = db.query(InstrumentSetupCategory).filter(InstrumentSetupCategory.parent_id == category_id).all()
    for c in children:
        _delete_category_subtree(db, c.id)
    rows = db.query(LibraryInstrument).filter(LibraryInstrument.category_id == category_id).all()
    linked_codes = [r.instrument_code for r in rows if (r.instrument_code or "").strip()]
    if linked_codes:
        db.query(BluetoothDevice).filter(BluetoothDevice.device_id.in_(linked_codes)).delete(
            synchronize_session=False
        )
    db.query(LibraryInstrument).filter(LibraryInstrument.category_id == category_id).delete()
    db.query(InstrumentSetupCategory).filter(InstrumentSetupCategory.id == category_id).delete()


@router.delete("/categories/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    row = db.query(InstrumentSetupCategory).filter(InstrumentSetupCategory.id == category_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Category not found")
    _delete_category_subtree(db, category_id)
    db.commit()
    return {"ok": True}


@router.get("/categories/{category_id}/instruments", response_model=List[LibraryInstrumentDTO])
def list_instruments(category_id: int, db: Session = Depends(get_db)):
    cat = db.query(InstrumentSetupCategory).filter(InstrumentSetupCategory.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    rows = (
        db.query(LibraryInstrument)
        .filter(LibraryInstrument.category_id == category_id)
        .order_by(LibraryInstrument.id.asc())
        .all()
    )
    return [
        LibraryInstrumentDTO(
            id=r.id,
            category_id=r.category_id,
            instrument_code=r.instrument_code,
            instrument_name=r.instrument_name,
            manufacturer=r.manufacturer,
            model_number=r.model_number,
            serial_number=r.serial_number,
            range=r.range,
            resolution=r.resolution,
            accuracy=r.accuracy,
            last_calibration_date=r.last_calibration_date,
            calibration=r.calibration,
            calibration_interval=r.calibration_interval,
            status=r.status,
            location=r.location,
            available_qty=r.available_qty,
            equipment_no=r.equipment_no,
        )
        for r in rows
    ]


@router.post("/instruments", response_model=LibraryInstrumentDTO, status_code=status.HTTP_201_CREATED)
def create_instrument(body: LibraryInstrumentCreate, db: Session = Depends(get_db)):
    cat = db.query(InstrumentSetupCategory).filter(InstrumentSetupCategory.id == body.category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    code = body.instrument_code.strip()
    row = LibraryInstrument(
        category_id=body.category_id,
        instrument_code=code,
        instrument_name=body.instrument_name,
        manufacturer=body.manufacturer,
        model_number=body.model_number,
        serial_number=body.serial_number,
        range=body.range,
        resolution=body.resolution,
        accuracy=body.accuracy,
        last_calibration_date=body.last_calibration_date,
        calibration=body.calibration,
        calibration_interval=body.calibration_interval,
        status=body.status,
        location=body.location,
        available_qty=body.available_qty,
        equipment_no=body.equipment_no,
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
    except Exception as e:
        logger.exception("create_instrument")
        db.rollback()
        if "uq_library_instrument_code_per_category" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail="Instrument code already exists in this category")
        raise HTTPException(status_code=500, detail=str(e))
    return LibraryInstrumentDTO(
        id=row.id,
        category_id=row.category_id,
        instrument_code=row.instrument_code,
        instrument_name=row.instrument_name,
        manufacturer=row.manufacturer,
        model_number=row.model_number,
        serial_number=row.serial_number,
        range=row.range,
        resolution=row.resolution,
        accuracy=row.accuracy,
        last_calibration_date=row.last_calibration_date,
        calibration=row.calibration,
        calibration_interval=row.calibration_interval,
        status=row.status,
        location=row.location,
        available_qty=row.available_qty,
        equipment_no=row.equipment_no,
    )


@router.patch("/instruments/{instrument_id}", response_model=LibraryInstrumentDTO)
def update_instrument(instrument_id: int, body: LibraryInstrumentUpdate, db: Session = Depends(get_db)):
    row = db.query(LibraryInstrument).filter(LibraryInstrument.id == instrument_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Instrument not found")
    if body.instrument_code is not None:
        row.instrument_code = body.instrument_code.strip()
    if body.instrument_name is not None:
        row.instrument_name = body.instrument_name
    if body.manufacturer is not None:
        row.manufacturer = body.manufacturer
    if body.model_number is not None:
        row.model_number = body.model_number
    if body.serial_number is not None:
        row.serial_number = body.serial_number
    if body.range is not None:
        row.range = body.range
    if body.resolution is not None:
        row.resolution = body.resolution
    if body.accuracy is not None:
        row.accuracy = body.accuracy
    if body.last_calibration_date is not None:
        row.last_calibration_date = body.last_calibration_date
    if body.calibration is not None:
        row.calibration = body.calibration
    if body.calibration_interval is not None:
        row.calibration_interval = body.calibration_interval
    if body.status is not None:
        row.status = body.status
    if body.location is not None:
        row.location = body.location
    if body.available_qty is not None:
        row.available_qty = body.available_qty
    if body.equipment_no is not None:
        row.equipment_no = body.equipment_no
    try:
        db.commit()
        db.refresh(row)
    except Exception as e:
        logger.exception("update_instrument")
        db.rollback()
        if "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail="Instrument code already exists in this category")
        raise HTTPException(status_code=500, detail=str(e))
    return LibraryInstrumentDTO(
        id=row.id,
        category_id=row.category_id,
        instrument_code=row.instrument_code,
        instrument_name=row.instrument_name,
        manufacturer=row.manufacturer,
        model_number=row.model_number,
        serial_number=row.serial_number,
        range=row.range,
        resolution=row.resolution,
        accuracy=row.accuracy,
        last_calibration_date=row.last_calibration_date,
        calibration=row.calibration,
        calibration_interval=row.calibration_interval,
        status=row.status,
        location=row.location,
        available_qty=row.available_qty,
        equipment_no=row.equipment_no,
    )


@router.delete("/instruments/{instrument_id}")
def delete_instrument(instrument_id: int, db: Session = Depends(get_db)):
    row = db.query(LibraryInstrument).filter(LibraryInstrument.id == instrument_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Instrument not found")
    code = (row.instrument_code or "").strip()
    if code:
        db.query(BluetoothDevice).filter(BluetoothDevice.device_id == code).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.delete("/categories/{category_id}/instruments")
def clear_instruments_for_category(category_id: int, db: Session = Depends(get_db)):
    cat = db.query(InstrumentSetupCategory).filter(InstrumentSetupCategory.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    rows = db.query(LibraryInstrument).filter(LibraryInstrument.category_id == category_id).all()
    linked_codes = [r.instrument_code for r in rows if (r.instrument_code or "").strip()]
    if linked_codes:
        db.query(BluetoothDevice).filter(BluetoothDevice.device_id.in_(linked_codes)).delete(
            synchronize_session=False
        )
    db.query(LibraryInstrument).filter(LibraryInstrument.category_id == category_id).delete()
    db.commit()
    return {"ok": True}
