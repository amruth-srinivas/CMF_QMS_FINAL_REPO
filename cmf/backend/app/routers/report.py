"""
Reports router for generating comprehensive part reports.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List, Dict
from datetime import datetime, timezone
from collections import defaultdict

from app.database import get_db
from app.models.part import Part
from app.models.part_location import PartLocation
from app.models.project import Project
from app.models.assembly import Assembly
from app.models.balloon import Balloon
from app.models.measurement import Measurement
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.schemas.report import (
    PartReportResponse,
    BOCInfo,
    ProjectInfo,
    AssemblyInfo,
    BalloonInfo,
    MeasurementInfo,
    BalloonWithMeasurements,
    QuantityReport,
    BalloonedDrawing,
    DocumentVersionInfo
)

router = APIRouter(prefix="/reports", tags=["reports"])


def get_boc_info(db: Session, part_id: int) -> Optional[BOCInfo]:
    """Get Bill of Components information for a part."""
    part_location = db.query(PartLocation).filter(
        PartLocation.part_id == part_id
    ).first()
    
    if not part_location:
        return None
    
    project_info = None
    assembly_info = None
    
    if part_location.project_id:
        project = db.query(Project).filter(Project.id == part_location.project_id).first()
        if project:
            project_info = ProjectInfo(
                id=project.id,
                project_number=project.project_number,
                name=project.name,
                reference_no=project.reference_no,
                customer_details=project.customer_details,
                created_at=project.created_at
            )
    
    if part_location.assembly_id:
        assembly = db.query(Assembly).filter(Assembly.id == part_location.assembly_id).first()
        if assembly:
            assembly_info = AssemblyInfo(
                id=assembly.id,
                name=assembly.name,
                project_id=assembly.project_id,
                parent_assembly_id=assembly.parent_assembly_id,
                created_at=assembly.created_at
            )
    
    return BOCInfo(
        project=project_info,
        assembly=assembly_info,
        quantity=part_location.quantity
    )


def get_ballooned_drawing(db: Session, part_id: int) -> Optional[BalloonedDrawing]:
    """Get ballooned drawing (document with balloons) for a part."""
    # Find documents linked to this part
    documents = db.query(Document).filter(
        Document.part_id == part_id
    ).all()
    
    # Find document with balloons (prefer 2D documents)
    # Check which documents have balloons by querying balloons separately
    ballooned_doc = None
    for doc in documents:
        # Check if this document has balloons
        balloon_count = db.query(Balloon).filter(
            Balloon.document_id == doc.id
        ).count()
        
        if balloon_count > 0:
            # Prefer 2D documents for ballooned drawings
            if doc.doc_type.value == "2D":
                ballooned_doc = doc
                break
            elif not ballooned_doc:
                ballooned_doc = doc
    
    if not ballooned_doc:
        return None
    
    # Get current version
    current_version = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == ballooned_doc.id,
        DocumentVersion.is_current == True
    ).first()
    
    version_info = None
    if current_version:
        version_info = DocumentVersionInfo(
            id=current_version.id,
            version_no=current_version.version_no,
            blob_path=current_version.blob_path,
            file_format=current_version.file_format,
            is_current=current_version.is_current,
            uploaded_at=current_version.uploaded_at,
            uploaded_by=current_version.uploaded_by,
            change_note=current_version.change_note
        )
    
    return BalloonedDrawing(
        id=ballooned_doc.id,
        doc_type=ballooned_doc.doc_type,
        title=ballooned_doc.title,
        created_at=ballooned_doc.created_at,
        current_version=version_info
    )


@router.get("/parts/{part_id}", response_model=PartReportResponse)
def get_part_report(
    part_id: int,
    quantity: Optional[int] = Query(None, description="Specific quantity to report on. If not provided, returns consolidated report for all quantities."),
    db: Session = Depends(get_db)
):
    """
    Generate comprehensive report for a part.
    
    Returns:
    - Part details (id, part_no, name)
    - BOC (Bill of Components) information (project, assembly, quantity)
    - Ballooned drawing with current version
    - Measurements grouped by quantity
    - Individual quantity reports or consolidated summary
    
    Query Parameters:
    - quantity: Optional. If provided, returns report for that specific quantity only.
                 If not provided, returns consolidated report for all quantities.
    """
    # Get part
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {part_id} not found"
        )
    
    # Get BOC info
    boc = get_boc_info(db, part_id)
    
    # Get ballooned drawing
    ballooned_drawing = get_ballooned_drawing(db, part_id)
    
    # Get all balloons for this part using raw SQL to avoid VARCHAR type mapping issues
    # Cast VARCHAR columns to TEXT to match SQLAlchemy expectations
    balloon_query = text("""
        SELECT 
            id, part_id, document_id, balloon_id,
            x, y, width, height, page,
            nominal,
            utol::TEXT as utol,
            ltol::TEXT as ltol,
            type::TEXT as type,
            zone::TEXT as zone,
            measuring_instrument::TEXT as measuring_instrument,
            op_no::TEXT as op_no,
            created_at, updated_at
        FROM balloons
        WHERE part_id = :part_id
        ORDER BY created_at ASC
    """)
    balloon_result = db.execute(balloon_query, {"part_id": part_id})
    balloon_rows = balloon_result.fetchall()
    
    # Get all measurements for this part
    measurements_query = db.query(Measurement).filter(Measurement.part_id == part_id)
    
    # Filter by quantity if specified
    if quantity is not None:
        measurements_query = measurements_query.filter(Measurement.quantity == quantity)
    
    measurements = measurements_query.order_by(Measurement.measured_at.desc()).all()
    
    # Group measurements by balloon_id and quantity
    measurements_by_balloon_quantity: Dict[int, Dict[int, List[Measurement]]] = defaultdict(lambda: defaultdict(list))
    
    for measurement in measurements:
        measurements_by_balloon_quantity[measurement.balloon_id][measurement.quantity or 1].append(measurement)
    
    # Determine all quantities to report: from measurements, from BOC, and from query param (so we include all dimensions even with 0 measurements)
    if quantity is not None:
        quantities_to_report = [quantity]  # Report only requested quantity, with all dimensions
    else:
        quantities_to_report = set(m.quantity or 1 for m in measurements)
        if boc is not None and boc.quantity is not None:
            quantities_to_report.add(boc.quantity)
        if not quantities_to_report:
            quantities_to_report = {1}  # Default to quantity 1 if no data
        quantities_to_report = sorted(quantities_to_report)
    
    # Build quantity reports: one report per quantity with ALL dimensions (balloons), each with its measurements (go/no_go or empty)
    quantity_reports: Dict[int, QuantityReport] = {}
    for qty in quantities_to_report:
        quantity_reports[qty] = QuantityReport(
            quantity=qty,
            balloons=[],
            total_measurements=0,
            go_count=0,
            no_go_count=0
        )
    
    # Process each balloon (dimension) - include ALL dimensions for each quantity, with their measurements
    for row in balloon_rows:
        balloon_info = BalloonInfo(
            id=row.id,
            balloon_id=row.balloon_id,
            document_id=row.document_id,
            x=row.x,
            y=row.y,
            width=row.width,
            height=row.height,
            page=row.page,
            nominal=row.nominal,
            utol=row.utol,
            ltol=row.ltol,
            type=row.type,
            zone=row.zone,
            measuring_instrument=row.measuring_instrument,
            op_no=row.op_no,
            created_at=row.created_at,
            updated_at=row.updated_at
        )
        
        # For each quantity, add this dimension (balloon) with its measurements for that quantity (if any)
        for qty in quantities_to_report:
            qty_measurements = measurements_by_balloon_quantity.get(row.id, {}).get(qty, [])
            
            measurement_infos = [
                MeasurementInfo(
                    id=m.id,
                    balloon_id=m.balloon_id,
                    quantity=m.quantity,
                    m1=m.m1,
                    m2=m.m2,
                    m3=m.m3,
                    mean=m.mean,
                    go_or_no_go=m.go_or_no_go,
                    measured_by=m.measured_by,
                    measured_at=m.measured_at,
                    notes=m.notes
                )
                for m in qty_measurements
            ]
            
            balloon_with_measurements = BalloonWithMeasurements(
                balloon=balloon_info,
                measurements=measurement_infos
            )
            
            quantity_reports[qty].balloons.append(balloon_with_measurements)
            quantity_reports[qty].total_measurements += len(measurement_infos)
            
            for m in qty_measurements:
                if m.go_or_no_go:
                    if m.go_or_no_go.value == "GO":
                        quantity_reports[qty].go_count += 1
                    elif m.go_or_no_go.value == "NO_GO":
                        quantity_reports[qty].no_go_count += 1
    
    # Convert to list and sort by quantity
    quantity_reports_list = sorted(quantity_reports.values(), key=lambda x: x.quantity)
    
    # Build consolidated summary if quantity not specified
    consolidated_summary = None
    report_type = "individual" if quantity is not None else "consolidated"
    
    if quantity is None:
        # Calculate consolidated statistics
        total_balloons = len(balloon_rows)
        total_measurements = len(measurements)
        total_go = sum(1 for m in measurements if m.go_or_no_go and m.go_or_no_go.value == "GO")
        total_no_go = sum(1 for m in measurements if m.go_or_no_go and m.go_or_no_go.value == "NO_GO")
        
        # Get unique quantities
        unique_quantities = sorted(set(m.quantity or 1 for m in measurements))
        
        consolidated_summary = {
            "total_balloons": total_balloons,
            "total_measurements": total_measurements,
            "total_go": total_go,
            "total_no_go": total_no_go,
            "quantities_measured": unique_quantities,
            "total_quantities": len(unique_quantities)
        }
    
    return PartReportResponse(
        part_id=part.id,
        part_no=part.part_no,
        part_name=part.name,
        rev=getattr(part, "rev", None),
        inspection_plan_status=part.inspection_plan_status,
        created_at=part.created_at,
        boc=boc,
        ballooned_drawing=ballooned_drawing,
        quantity_reports=quantity_reports_list,
        consolidated_summary=consolidated_summary,
        report_type=report_type,
        generated_at=datetime.now(timezone.utc)
    )
