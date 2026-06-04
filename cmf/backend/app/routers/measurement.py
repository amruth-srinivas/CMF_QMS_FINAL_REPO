"""
Measurement router with CRUD operations.
"""
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from sqlalchemy import func, text
from app.database import get_db
from app.models.measurement import Measurement, GoNoGoStatus
from app.models.balloon import Balloon
from app.models.part import Part
from app.schemas.measurement import MeasurementCreate, MeasurementUpdate, MeasurementResponse

router = APIRouter(prefix="/measurements", tags=["measurements"])


def calculate_mean(m1: Optional[float], m2: Optional[float], m3: Optional[float]) -> Optional[float]:
    """Calculate mean of m1, m2, m3 if all are provided."""
    values = [v for v in [m1, m2, m3] if v is not None]
    if len(values) > 0:
        return sum(values) / len(values)
    return None


def _parse_tolerance_value(tol: Optional[str]) -> float:
    """
    Parse a tolerance string like '+0.2' or '-0.2' to a float.
    Returns 0.0 when value is empty, '-', '0', or invalid.
    """
    if not tol:
        return 0.0
    tol = tol.strip()
    if tol in {"-", "0", "+0", "-0"}:
        return 0.0
    try:
        # Remove explicit + sign; float will handle minus sign
        tol_clean = tol.replace("+", "")
        return float(tol_clean)
    except (TypeError, ValueError):
        return 0.0


def calculate_go_no_go(
    nominal: Optional[float],
    utol: Optional[str],
    ltol: Optional[str],
    actual_value: Optional[float],
) -> Optional[GoNoGoStatus]:
    """
    Determine GO / NO_GO status based on balloon nominal, utol, ltol and the actual value (mean).
    Mirrors the tolerance logic used in the legacy frontend:
    - lower tolerance is applied below nominal,
    - upper tolerance is applied above nominal,
    - inclusive range check.
    """
    if actual_value is None or nominal is None:
        return None

    nominal_val = float(nominal)
    upper_tol = _parse_tolerance_value(utol)
    lower_tol = _parse_tolerance_value(ltol)

    # In JS, lower tolerance strings like "-0.2" become negative numbers;
    # here we already parse the sign correctly, so just add directly.
    min_value = nominal_val + lower_tol
    max_value = nominal_val + upper_tol

    if min_value <= actual_value <= max_value:
        return GoNoGoStatus.GO
    return GoNoGoStatus.NO_GO


@router.post("/", response_model=MeasurementResponse, status_code=status.HTTP_201_CREATED)
def create_measurement(measurement: MeasurementCreate, db: Session = Depends(get_db)):
    """Create a new measurement."""
    # Validate balloon exists (use raw SQL to avoid type-mapping issues)
    balloon_query = text(
        """
        SELECT 
            id,
            nominal,
            utol::TEXT as utol,
            ltol::TEXT as ltol
        FROM balloons
        WHERE id = :balloon_id
        LIMIT 1
        """
    )
    balloon_result = db.execute(balloon_query, {"balloon_id": measurement.balloon_id}).fetchone()
    if not balloon_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Balloon with ID {measurement.balloon_id} not found",
        )
    
    # Validate part if provided
    if measurement.part_id is not None:
        part = db.query(Part).filter(Part.id == measurement.part_id).first()
        if not part:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Part with ID {measurement.part_id} not found"
            )
    
    # Calculate mean if not provided
    measurement_data = measurement.model_dump()
    if measurement_data.get("mean") is None:
        mean = calculate_mean(measurement.m1, measurement.m2, measurement.m3)
        if mean is not None:
            measurement_data["mean"] = mean
    else:
        mean = measurement_data.get("mean")

    # Auto-calculate GO / NO_GO status when we have nominal and tolerances
    if measurement_data.get("go_or_no_go") is None:
        status_value = calculate_go_no_go(
            balloon_result.nominal,
            balloon_result.utol,
            balloon_result.ltol,
            mean,
        )
        if status_value is not None:
            measurement_data["go_or_no_go"] = status_value
    
    db_measurement = Measurement(**measurement_data)
    db.add(db_measurement)
    db.commit()
    db.refresh(db_measurement)
    
    # Populate instrument_code for response
    if db_measurement.instrument_id:
        from app.models.instrument_setup import LibraryInstrument
        inst = db.query(LibraryInstrument).filter(LibraryInstrument.id == db_measurement.instrument_id).first()
        if inst:
            db_measurement.instrument_code = inst.instrument_code
            
    return db_measurement


@router.get("/", response_model=List[MeasurementResponse])
def list_measurements(
    balloon_id: Optional[int] = None,
    part_id: Optional[int] = None,
    quantity: Optional[int] = None,  # Filter by part instance (quantity)
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List all measurements with optional filters."""
    # Join with LibraryInstrument to get instrument_code
    from app.models.instrument_setup import LibraryInstrument
    query = db.query(
        Measurement, 
        LibraryInstrument.instrument_code.label("instrument_code")
    ).outerjoin(LibraryInstrument, Measurement.instrument_id == LibraryInstrument.id)

    if balloon_id is not None:
        query = query.filter(Measurement.balloon_id == balloon_id)
    if part_id is not None:
        query = query.filter(Measurement.part_id == part_id)
    if quantity is not None:
        query = query.filter(Measurement.quantity == quantity)
    
    results = query.order_by(Measurement.measured_at.desc()).offset(skip).limit(limit).all()
    
    measurements = []
    for m, code in results:
        m.instrument_code = code
        measurements.append(m)
        
    return measurements


@router.get("/{measurement_id}", response_model=MeasurementResponse)
def get_measurement(measurement_id: int, db: Session = Depends(get_db)):
    """Get a measurement by ID."""
    measurement = db.query(Measurement).filter(Measurement.id == measurement_id).first()
    if not measurement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Measurement with ID {measurement_id} not found"
        )
    
    # Populate instrument_code for response
    if measurement.instrument_id:
        from app.models.instrument_setup import LibraryInstrument
        inst = db.query(LibraryInstrument).filter(LibraryInstrument.id == measurement.instrument_id).first()
        if inst:
            measurement.instrument_code = inst.instrument_code
            
    return measurement


@router.put("/{measurement_id}", response_model=MeasurementResponse)
def update_measurement(
    measurement_id: int,
    measurement_update: MeasurementUpdate,
    db: Session = Depends(get_db)
):
    """Update a measurement."""
    measurement = db.query(Measurement).filter(Measurement.id == measurement_id).first()
    if not measurement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Measurement with ID {measurement_id} not found"
        )
    
    update_data = measurement_update.model_dump(exclude_unset=True)
    
    # Validate balloon if being updated
    if "balloon_id" in update_data:
        balloon = db.query(Balloon).filter(Balloon.id == update_data["balloon_id"]).first()
        if not balloon:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Balloon with ID {update_data['balloon_id']} not found"
            )
    
    # Validate part if being updated
    if "part_id" in update_data and update_data["part_id"] is not None:
        part = db.query(Part).filter(Part.id == update_data["part_id"]).first()
        if not part:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Part with ID {update_data['part_id']} not found"
            )
    
    # Recalculate mean if measurements changed
    m1 = update_data.get("m1", measurement.m1)
    m2 = update_data.get("m2", measurement.m2)
    m3 = update_data.get("m3", measurement.m3)
    
    if "mean" not in update_data or update_data.get("mean") is None:
        mean = calculate_mean(m1, m2, m3)
        if mean is not None:
            update_data["mean"] = mean
    else:
        mean = update_data.get("mean")

    # Auto-calculate GO / NO_GO status when we have nominal and tolerances
    # Determine which balloon to use: updated or existing, using raw SQL
    balloon_id_value = update_data.get("balloon_id", measurement.balloon_id)
    balloon_query = text(
        """
        SELECT 
            id,
            nominal,
            utol::TEXT as utol,
            ltol::TEXT as ltol
        FROM balloons
        WHERE id = :balloon_id
        LIMIT 1
        """
    )
    balloon_result = db.execute(balloon_query, {"balloon_id": balloon_id_value}).fetchone()
    if balloon_result:
        status_value = calculate_go_no_go(
            balloon_result.nominal,
            balloon_result.utol,
            balloon_result.ltol,
            mean,
        )
        if status_value is not None:
            update_data["go_or_no_go"] = status_value
    
    for field, value in update_data.items():
        setattr(measurement, field, value)
    
    db.commit()
    db.refresh(measurement)
    
    # Populate instrument_code for response
    if measurement.instrument_id:
        from app.models.instrument_setup import LibraryInstrument
        inst = db.query(LibraryInstrument).filter(LibraryInstrument.id == measurement.instrument_id).first()
        if inst:
            measurement.instrument_code = inst.instrument_code
            
    return measurement


@router.delete("/{measurement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_measurement(measurement_id: int, db: Session = Depends(get_db)):
    """Delete a measurement."""
    measurement = db.query(Measurement).filter(Measurement.id == measurement_id).first()
    if not measurement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Measurement with ID {measurement_id} not found"
        )
    
    db.delete(measurement)
    db.commit()
    return None

