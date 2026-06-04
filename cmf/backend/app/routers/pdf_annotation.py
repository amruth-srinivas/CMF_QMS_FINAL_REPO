"""
PDF Annotation router for extracting text, GDT, and dimensions from PDFs.
Works with balloons stored in the database.
"""
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional, Dict
from pathlib import Path
import logging
import json
import os
import tempfile
import re
import fitz  # PyMuPDF
import traceback
import numpy as np
import cv2

from app.database import get_db
from app.models.document import Document, DocumentType
from app.models.document_version import DocumentVersion
from app.models.balloon import Balloon
from app.qms.zone import ZoneDetector
from app.services.blob_storage import blob_storage
from app.services import autoballoon_service
from app.schemas.pdf_annotation import (
    BoundingBox,
    ExtractTextRequest,
    ProcessDimensionsRequest,
    SaveBoundingBoxRequest,
    UpdateBoundingBoxRequest,
    BatchDeleteRequest,
    BatchUpdateBoundingBoxRequest
)

# DPI constants for coordinate scaling
PIPELINE_DPI = 250.0
PDF_POINT_DPI = 72.0

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pdf-annotation", tags=["pdf_annotation"])


def get_pdf_path_from_document(document_id: int, db: Session) -> str:

    """Get PDF file path from document ID."""
    # Get current version of document
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found"
        )
    
    # Get current version
    current_version = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == document_id,
        DocumentVersion.is_current == True
    ).first()
    
    if not current_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No current version found for document {document_id}"
        )
    
    # Get file path from blob storage
    try:
        file_path = blob_storage.get_file_path(current_version.blob_path)
        return str(file_path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found for document version {current_version.id}"
        )


@router.post("/extract-text")
async def extract_text(request: ExtractTextRequest, db: Session = Depends(get_db)):
    """
    Extract text from a region using the unified pipeline.
    Scaling is handled automatically.
    """
    from app.models.part import Part
    part = db.query(Part).filter(Part.id == request.part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {request.part_id} not found"
        )
    
    try:
        document_id = int(request.pdf_id)
        file_path = get_pdf_path_from_document(document_id, db)
        page_index = request.bounding_box.page - 1
        
        user_region = [
            request.bounding_box.x,
            request.bounding_box.y,
            request.bounding_box.width,
            request.bounding_box.height
        ]

        # Run pipeline with region
        pipeline_result = autoballoon_service.run_pipeline(
            file_path,
            page_index=page_index,
            user_region=user_region,
            max_ocr_dim=2048,
            include_image=request.include_image
        )
        
        # classified_detections contains the raw text results
        detections = pipeline_result.get("classified_detections", [])
        
        # Scale back to points
        inv_scale = PDF_POINT_DPI / PIPELINE_DPI
        for det in detections:
            if "bbox" in det:
                det["box"] = [v * inv_scale for v in det["bbox"]]

        return {
            "success": True,
            "results": detections,
            "count": len(detections)
        }

    except Exception as e:
        logger.error(f"Error extracting text: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error extracting text: {str(e)}")


@router.post("/extract-gdt")
async def extract_gdt(request: ExtractTextRequest, db: Session = Depends(get_db)):
    """
    Detect GDT symbols in a region using the unified pipeline.
    """
    from app.models.part import Part
    part = db.query(Part).filter(Part.id == request.part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {request.part_id} not found"
        )
    
    try:
        document_id = int(request.pdf_id)
        file_path = get_pdf_path_from_document(document_id, db)
        page_index = request.bounding_box.page - 1
        
        user_region = [
            request.bounding_box.x,
            request.bounding_box.y,
            request.bounding_box.width,
            request.bounding_box.height
        ]

        # Run pipeline with region
        pipeline_result = autoballoon_service.run_pipeline(
            file_path,
            page_index=page_index,
            user_region=user_region,
            max_ocr_dim=2048,
            include_image=request.include_image
        )
        
        detections = pipeline_result.get("gdt_detections", [])
        
        # Scale back to points
        inv_scale = PDF_POINT_DPI / PIPELINE_DPI
        for det in detections:
            if "bbox" in det:
                det["box"] = [v * inv_scale for v in det["bbox"]]

        return {
            "success": True,
            "detections": detections,
            "count": len(detections)
        }

    except Exception as e:
        logger.error(f"Error detecting GDT: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error detecting GDT: {str(e)}")



@router.post("/process-dimensions")
async def process_dimensions(request: ProcessDimensionsRequest, db: Session = Depends(get_db)):
    """
    Process dimensions using the unified OCR pipeline.
    Expects a region in PDF points (72 DPI).
    """
    # Validate part exists
    from app.models.part import Part
    part = db.query(Part).filter(Part.id == request.part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {request.part_id} not found"
        )
    
    try:
        if not request.pdf_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="pdf_id is required for dimension processing"
            )
        try:
            document_id = int(request.pdf_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="pdf_id must be a valid document ID (integer)"
            )
        
        file_path = get_pdf_path_from_document(document_id, db)
        page_index = request.bounding_box.page - 1
        
        # User region from frontend [x, y, w, h] in points (72 DPI)
        user_region = [
            request.bounding_box.x,
            request.bounding_box.y,
            request.bounding_box.width,
            request.bounding_box.height
        ]

        logger.info(f"Processing dimensions for region {user_region} on page {page_index}")
        
        # Run the unified pipeline
        pipeline_result = autoballoon_service.run_pipeline(
            file_path,
            page_index=page_index,
            user_region=user_region,
            max_ocr_dim=2048,  # Lower for region-based OCR speed
            include_image=request.include_image
        )
        
        parsed_dims = pipeline_result.get("parsed_dimensions", [])
        
        # Map pipeline results (DPI 250 pixels) -> Points (DPI 72)
        inv_scale = PDF_POINT_DPI / PIPELINE_DPI  # ≈ 0.288
        
        mapped_dimensions = []
        for dim in parsed_dims:
            bbox = dim.get("bbox", [0, 0, 0, 0])
            parsed = dim.get("parsed", {})
            
            mapped_dimensions.append({
                "text": dim.get("text", ""),
                "nominal_value": str(parsed.get("nominal", "")),
                "upper_tolerance": str(parsed.get("max_tol", "")),
                "lower_tolerance": str(parsed.get("min_tol", "")),
                "dimension_type": parsed.get("type", "Dimension"),
                "bbox": [v * inv_scale for v in bbox] 
            })

        # Material fallback
        material_entries = []
        # If no dimensions found, check for material-like strings in raw detections
        classified = pipeline_result.get("classified_detections", [])
        for det in classified:
            text_val = det.get("text", "").lower()
            if "material" in text_val or re.match(r'^(en[a-z0-9]+|ms|ss|gi|ci)\b', text_val):
                bbox = det.get("bbox", [0, 0, 0, 0])
                material_entries.append({
                    "text": det.get("text", ""),
                    "nominal_value": "",
                    "upper_tolerance": "",
                    "lower_tolerance": "",
                    "dimension_type": "Material",
                    "bbox": [v * inv_scale for v in bbox] 
                })
        
        all_results = mapped_dimensions + material_entries
        
        return {
            "success": True,
            "dimensions": all_results,
            "count": len(all_results),
            "annotated_image": pipeline_result.get("annotated_image_b64"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing dimensions: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing dimensions: {str(e)}")



@router.post("/auto-ballooning")
async def auto_ballooning(request: ProcessDimensionsRequest, db: Session = Depends(get_db)):
    """
    Run the full autoballoon OCR pipeline on a document and create
    balloon records for each detected dimension / GD&T symbol.

    This is a clean-slate operation: all existing balloons for the part
    are deleted before the new ones are inserted.
    """
    from app.models.part import Part
    from app.services import autoballoon_service

    # ── Validate inputs ──────────────────────────────────────────────
    part = db.query(Part).filter(Part.id == request.part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {request.part_id} not found",
        )

    if not request.pdf_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pdf_id is required for auto-ballooning",
        )

    try:
        document_id = int(request.pdf_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pdf_id must be a valid document ID (integer)",
        )

    file_path = get_pdf_path_from_document(document_id, db)
    page_index = request.bounding_box.page - 1  # 0-based for the pipeline

    # ── Detect Region vs Full ────────────────────────────────────────
    user_region = [
        request.bounding_box.x,
        request.bounding_box.y,
        request.bounding_box.width,
        request.bounding_box.height
    ]
    
    # Frontend sends 2000x2000 for a full scan.
    # We treat anything covering the whole page (or explicitly large) as full scan.
    is_full_scan = (user_region[0] == 0 and user_region[1] == 0 and 
                    user_region[2] >= 1999 and user_region[3] >= 1999)
    # If width/height are 0, it's also effectively full scan or invalid - let's treat as full.
    if user_region[2] == 0 or user_region[3] == 0:
        is_full_scan = True

    # ── Run the pipeline ─────────────────────────────────────────────
    logger.info(f"Auto-ballooning: running pipeline on document {document_id}, page {page_index} (is_full={is_full_scan})")
    try:
        pipeline_result = autoballoon_service.run_pipeline(
            file_path, 
            page_index=page_index,
            user_region=None if is_full_scan else user_region,
            include_image=request.include_image
        )
    except Exception as e:
        logger.error(f"Autoballoon pipeline error: {e}", exc_info=True)
        print(traceback.format_exc()) # Debugging to console
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline execution failed: {str(e)}",
        )

    parsed_dims = pipeline_result.get("parsed_dimensions", [])
    if not parsed_dims:
        logger.warning("Auto-ballooning: pipeline returned 0 dimensions.")
        return {
            "success": True,
            "balloons_created": 0,
            "dimensions": [],
            "annotated_image": pipeline_result.get("annotated_image_b64"),
        }

    # ── Map pipeline results → Balloon dicts ─────────────────────────
    balloon_dicts = autoballoon_service.map_to_balloons(
        parsed_dims,
        part_id=request.part_id,
        document_id=document_id,
        page=request.bounding_box.page,     # 1-indexed for the DB
        is_pdf=file_path.lower().endswith(".pdf"),
        dynamic_scale=pipeline_result.get("fitz_scale"),
    )

    # ── Save to DB ───────────────────────────────────────────────────
    if is_full_scan:
        # Clean-slate: delete existing balloons for this part
        delete_query = text("DELETE FROM balloons WHERE part_id = :part_id")
        db.execute(delete_query, {"part_id": request.part_id})
        logger.info(f"Auto-ballooning: deleted existing balloons for part {request.part_id}")
    else:
        logger.info(f"Region-ballooning: appending {len(balloon_dicts)} new balloons to part {request.part_id}")

    # Bulk-insert new balloons
    insert_query = text("""
        INSERT INTO balloons
            (part_id, document_id, balloon_id, x, y, width, height, page,
             nominal, utol, ltol, type, zone)
        VALUES
            (:part_id, :document_id, :balloon_id, :x, :y, :width, :height, :page,
             :nominal, :utol, :ltol, :type, :zone)
    """)
    for b in balloon_dicts:
        db.execute(insert_query, b)

    db.commit()

    # ── Re-sequence ALL balloons for this part ───────────────────────
    # This ensures IDs (1, 2, 3...) remain sequential and spatially sorted
    # even after adding new ones in a region.
    logger.info(f"Re-sequencing IDs for part {request.part_id}...")
    
    # Fetch all balloons for this part
    all_balloons_query = text("""
        SELECT id, balloon_id, x, y, width, height, zone
        FROM balloons
        WHERE part_id = :part_id
    """)
    all_rows = db.execute(all_balloons_query, {"part_id": request.part_id}).fetchall()
    
    # Sort and re-sequence using the service helper
    # Convert rows to dicts for the helper
    balloon_objs = [dict(row._mapping) for row in all_rows]
    updated_balloons = autoballoon_service.resequence_balloon_ids(balloon_objs)
    
    # Update IDs in DB only if they changed
    for b in updated_balloons:
        # Find the original row to compare
        original = next((r for r in all_rows if r.id == b["id"]), None)
        if original and original.balloon_id != b["balloon_id"]:
            update_query = text("UPDATE balloons SET balloon_id = :new_id WHERE id = :db_id")
            db.execute(update_query, {"new_id": b["balloon_id"], "db_id": b["id"]})
    
    db.commit()
    logger.info(f"Auto-ballooning: finished processing {len(updated_balloons)} total balloons")

    # ── Build serialisable dimensions list for the response ──────────
    response_dims = []
    for dim, bdict in zip(parsed_dims, balloon_dicts):
        parsed = dim.get("parsed", {})
        response_dims.append({
            "balloon_id": bdict["balloon_id"],
            "text": dim.get("text", ""),
            "nominal": bdict["nominal"],
            "utol": bdict["utol"],
            "ltol": bdict["ltol"],
            "type": bdict["type"],
            "zone": bdict["zone"],
            "bbox": {
                "x": bdict["x"],
                "y": bdict["y"],
                "width": bdict["width"],
                "height": bdict["height"],
                "page": bdict["page"],
            },
            "source": dim.get("source", ""),
            "score": dim.get("score", 0),
        })

    # Fetch all balloons for this part to return to frontend
    all_updated_query = text("""
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
        ORDER BY CAST(balloon_id AS INTEGER) ASC
    """)
    updated_rows = db.execute(all_updated_query, {"part_id": request.part_id}).fetchall()
    
    bounding_boxes = []
    for row in updated_rows:
        bbox_data = {
            "id": row.balloon_id,
            "balloon_db_id": row.id,
            "x": row.x,
            "y": row.y,
            "width": row.width,
            "height": row.height,
            "page": row.page or 1,
            "label": row.type or "",
            "zone": row.zone,
            "nominal": row.nominal,
            "utol": row.utol,
            "ltol": row.ltol,
            "type": row.type,
            "measuring_instrument": row.measuring_instrument,
            "op_no": row.op_no,
            "part_id": row.part_id,
            "document_id": row.document_id
        }
        bounding_boxes.append(bbox_data)

    return {
        "success": True,
        "balloons_created": len(balloon_dicts),
        "dimensions": response_dims, # Still return newly created ones for specific feedback
        "bounding_boxes": bounding_boxes, # Return ALL balloons for state synchronization
        "annotated_image": pipeline_result.get("annotated_image_b64"),
    }

@router.get("/bounding-boxes/part/{part_id}")
async def get_bounding_boxes_by_part(part_id: int, db: Session = Depends(get_db)):
    """Get all balloons (bounding boxes) for a part."""
    # Validate part exists
    from app.models.part import Part
    part = db.query(Part).filter(Part.id == part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {part_id} not found"
        )
    
    # Get all balloons for this part using raw SQL to avoid VARCHAR type mapping issues
    # Cast VARCHAR columns to TEXT to match SQLAlchemy expectations
    # Order by creation time to preserve existing balloon order (balloons 1-5 stay as 1-5)
    # New balloons are added at the end, maintaining stable numbering
    query = text("""
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
        ORDER BY CAST(balloon_id AS INTEGER) ASC
    """)
    result = db.execute(query, {"part_id": part_id})
    rows = result.fetchall()
    
    # Convert to bounding box format
    # NOTE:
    # - "id" is the external balloon identifier (balloon_id column) used by the frontend
    # - "balloon_db_id" exposes the internal numeric primary key so other APIs
    #   (like /measurements) that reference balloons by integer ID can be used
    bounding_boxes = []
    for row in rows:
        bbox_data = {
            "id": row.balloon_id,
            "balloon_db_id": row.id,
            "x": row.x,
            "y": row.y,
            "width": row.width,
            "height": row.height,
            "page": row.page or 1,
            "label": row.type or "",
            "zone": row.zone,
            "nominal": row.nominal,
            "utol": row.utol,
            "ltol": row.ltol,
            "type": row.type,
            "measuring_instrument": row.measuring_instrument,
            "op_no": row.op_no,
            "part_id": row.part_id,
            "document_id": row.document_id
        }
        bounding_boxes.append(bbox_data)
    
    return {"bounding_boxes": bounding_boxes}


@router.get("/bounding-boxes/document/{document_id}")
async def get_bounding_boxes_by_document(document_id: int, db: Session = Depends(get_db)):
    """Get all balloons (bounding boxes) for a document (optional filter)."""
    # Get all balloons for this document using raw SQL to avoid VARCHAR type mapping issues
    # Cast VARCHAR columns to TEXT to match SQLAlchemy expectations
    # Order by creation time to preserve existing balloon order (balloons 1-5 stay as 1-5)
    # New balloons are added at the end, maintaining stable numbering
    query = text("""
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
        WHERE document_id = :document_id
        ORDER BY CAST(balloon_id AS INTEGER) ASC
    """)
    result = db.execute(query, {"document_id": document_id})
    rows = result.fetchall()
    
    # Convert to bounding box format
    bounding_boxes = []
    for row in rows:
        bbox_data = {
            "id": row.balloon_id,
            "balloon_db_id": row.id,
            "x": row.x,
            "y": row.y,
            "width": row.width,
            "height": row.height,
            "page": row.page or 1,
            "label": row.type or "",
            "zone": row.zone,
            "nominal": row.nominal,
            "utol": row.utol,
            "ltol": row.ltol,
            "type": row.type,
            "measuring_instrument": row.measuring_instrument,
            "op_no": row.op_no,
            "part_id": row.part_id,
            "document_id": row.document_id
        }
        bounding_boxes.append(bbox_data)
    
    return {"bounding_boxes": bounding_boxes}


@router.post("/bounding-box")
async def save_bounding_box(request: SaveBoundingBoxRequest, db: Session = Depends(get_db)):
    """Save a bounding box (balloon) to the database."""
    from app.models.part import Part
    import time
    
    # Validate part exists
    part = db.query(Part).filter(Part.id == request.part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {request.part_id} not found"
        )
    
    # Validate document if provided
    document_id = None
    if request.pdf_id:
        try:
            document_id = int(request.pdf_id)
            document = db.query(Document).filter(Document.id == document_id).first()
            if not document:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Document with ID {document_id} not found"
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="pdf_id must be a valid document ID (integer)"
            )
    
    # Generate unique balloon_id
    balloon_id = str(int(time.time() * 1000000))
    
    # Detect zone for this bounding box
    zone_label = None
    if ZoneDetector and document_id:
        try:
            # Get PDF path from document
            file_path = get_pdf_path_from_document(document_id, db)
            if file_path and Path(file_path).exists():
                # Convert page number to 0-indexed (PyMuPDF uses 0-indexed pages)
                page_number = request.bounding_box.page - 1
                region = {
                    'x': request.bounding_box.x,
                    'y': request.bounding_box.y,
                    'width': request.bounding_box.width,
                    'height': request.bounding_box.height
                }
                zone_results = ZoneDetector.extract_zone_from_region(
                    pdf_path=str(file_path),
                    page_number=page_number,
                    region=region,
                    scale_factor=1.0
                )
                if zone_results and len(zone_results) > 0:
                    zone_label = zone_results[0].get('zone')
                    logger.info(f"Detected zone: {zone_label} for bounding box")
        except Exception as e:
            logger.warning(f"Could not detect zone for bounding box: {str(e)}")
    
    # Insert balloon using raw SQL to avoid VARCHAR type mapping issues
    insert_query = text("""
        INSERT INTO balloons (part_id, document_id, balloon_id, x, y, width, height, page, type, zone)
        VALUES (:part_id, :document_id, :balloon_id, :x, :y, :width, :height, :page, :type, :zone)
        RETURNING id
    """)
    result = db.execute(insert_query, {
        "part_id": request.part_id,
        "document_id": document_id,
        "balloon_id": balloon_id,
        "x": request.bounding_box.x,
        "y": request.bounding_box.y,
        "width": request.bounding_box.width,
        "height": request.bounding_box.height,
        "page": request.bounding_box.page,
        "type": request.label,
        "zone": zone_label
    })
    
    # Get the inserted ID BEFORE committing (cursor closes after commit)
    inserted_id = result.fetchone().id
    db.commit()
    
    return {
        "message": "Bounding box saved successfully",
        "id": balloon_id,
        "balloon": {
            "id": inserted_id,
            "balloon_id": balloon_id,
            "part_id": request.part_id,
            "document_id": document_id,
            "zone": zone_label
        }
    }


@router.put("/bounding-box/part/{part_id}/{balloon_id}")
async def update_bounding_box(
    part_id: int,
    balloon_id: str,
    request: UpdateBoundingBoxRequest,
    db: Session = Depends(get_db)
):
    """Update a balloon with extracted data."""
    # Find balloon by balloon_id and part_id using raw SQL to avoid VARCHAR type mapping issues
    query = text("""
        SELECT id, part_id, document_id, balloon_id,
               x, y, width, height, page,
               nominal,
               utol::TEXT as utol,
               ltol::TEXT as ltol,
               type::TEXT as type,
               zone::TEXT as zone,
               measuring_instrument::TEXT as measuring_instrument,
               op_no::TEXT as op_no
        FROM balloons
        WHERE part_id = :part_id AND balloon_id = :balloon_id
        LIMIT 1
    """)
    result = db.execute(query, {"part_id": part_id, "balloon_id": balloon_id})
    row = result.fetchone()
    
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Balloon {balloon_id} not found for part {part_id}"
        )
    
    # Update balloon with dimension data if provided using raw SQL
    update_fields = []
    update_params = {"balloon_id": row.id}
    
    if request.dimension_data and len(request.dimension_data) > 0:
        dim = request.dimension_data[0]
        if "nominal_value" in dim:
            update_fields.append("nominal = :nominal")
            update_params["nominal"] = float(dim["nominal_value"]) if dim["nominal_value"] else None
        if "upper_tolerance" in dim:
            update_fields.append("utol = :utol")
            update_params["utol"] = dim["upper_tolerance"]
        if "lower_tolerance" in dim:
            update_fields.append("ltol = :ltol")
            update_params["ltol"] = dim["lower_tolerance"]
        if "dimension_type" in dim:
            update_fields.append("type = :type")
            update_params["type"] = dim["dimension_type"]
    
    if request.measuring_instrument is not None:
        update_fields.append("measuring_instrument = :measuring_instrument")
        update_params["measuring_instrument"] = request.measuring_instrument
    
    if request.sampling is not None:
        update_fields.append("sampling = :sampling")
        update_params["sampling"] = request.sampling
    
    if update_fields:
        update_query = text(f"""
            UPDATE balloons
            SET {', '.join(update_fields)}
            WHERE id = :balloon_id
        """)
        db.execute(update_query, update_params)
        db.commit()
    
    # Fetch updated values using raw SQL
    fetch_query = text("""
        SELECT id, balloon_id, nominal,
               utol::TEXT as utol,
               ltol::TEXT as ltol,
               type::TEXT as type,
               zone::TEXT as zone,
               sampling
        FROM balloons
        WHERE id = :balloon_id
    """)
    result = db.execute(fetch_query, {"balloon_id": row.id})
    updated_row = result.fetchone()
    
    return {
        "message": "Balloon updated successfully",
        "balloon": {
            "id": updated_row.id,
            "balloon_id": updated_row.balloon_id,
            "nominal": updated_row.nominal,
            "utol": updated_row.utol,
            "ltol": updated_row.ltol,
            "type": updated_row.type,
            "zone": updated_row.zone,
            "sampling": updated_row.sampling
        }
    }


@router.delete("/bounding-box/part/{part_id}/{balloon_id}")
async def delete_bounding_box(part_id: int, balloon_id: str, db: Session = Depends(get_db)):
    """Delete a balloon."""
    # Check if balloon exists using raw SQL to avoid VARCHAR type mapping issues
    check_query = text("""
        SELECT id FROM balloons
        WHERE part_id = :part_id AND balloon_id = :balloon_id
        LIMIT 1
    """)
    result = db.execute(check_query, {"part_id": part_id, "balloon_id": balloon_id})
    row = result.fetchone()
    
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Balloon {balloon_id} not found for part {part_id}"
        )
    
    # Delete using raw SQL
    delete_query = text("""
        DELETE FROM balloons
        WHERE id = :id
    """)
    db.execute(delete_query, {"id": row.id})
    
    # Re-sequence remaining balloons for this part to close the gap
    # Order by created_at to preserve the intent of the original sequence
    remaining_query = text("""
        SELECT id FROM balloons
        WHERE part_id = :part_id
        ORDER BY id ASC
    """)
    remaining = db.execute(remaining_query, {"part_id": part_id}).fetchall()
    
    for i, r in enumerate(remaining):
        # Update balloon_id to be its 1-based index (string label)
        new_label = str(i + 1)
        update_query = text("""
            UPDATE balloons
            SET balloon_id = :new_label
            WHERE id = :id
        """)
        db.execute(update_query, {"new_label": new_label, "id": r.id})
    
    db.commit()
    
    # Return updated list
    return await get_bounding_boxes_by_part(part_id, db)


@router.post("/bounding-boxes/delete-batch")
async def delete_balloons_batch(request: BatchDeleteRequest, db: Session = Depends(get_db)):
    """Delete multiple balloons and re-sequence."""
    if not request.balloon_ids:
        return {"status": "noop", "deleted_count": 0}

    # Delete the specified balloons
    delete_query = text("""
        DELETE FROM balloons
        WHERE part_id = :part_id AND balloon_id IN :ids
    """)
    # Note: SQLAlchemy expansion for IN clause
    db.execute(delete_query, {"part_id": request.part_id, "ids": tuple(request.balloon_ids)})
    
    # Re-sequence remaining balloons
    remaining_query = text("""
        SELECT id FROM balloons
        WHERE part_id = :part_id
        ORDER BY id ASC
    """)
    remaining = db.execute(remaining_query, {"part_id": request.part_id}).fetchall()
    
    for i, r in enumerate(remaining):
        new_label = str(i + 1)
        update_query = text("""
            UPDATE balloons
            SET balloon_id = :new_label
            WHERE id = :id
        """)
        db.execute(update_query, {"new_label": new_label, "id": r.id})
    
    db.commit()
    
    # Return updated list
    return await get_bounding_boxes_by_part(request.part_id, db)


def get_pdf_path(pdf_id: str, db: Session) -> str:
    """Get PDF file path from document ID (pdf_id is document_id)."""
    return get_pdf_path_from_document(int(pdf_id), db)


def cleanup_temp_file(file_path: str):
    """Clean up temporary file."""
    try:
        import os
        if os.path.exists(file_path):
            os.unlink(file_path)
    except Exception as e:
        logger.warning(f"Failed to cleanup temp file {file_path}: {e}")


@router.post("/bounding-boxes/update-batch")
async def update_balloons_batch(request: BatchUpdateBoundingBoxRequest, db: Session = Depends(get_db)):
    """Update multiple balloons at once (e.g., assign same instrument)."""
    if not request.balloon_ids:
        return {"status": "noop", "updated_count": 0}

    update_fields = []
    update_params = {"part_id": request.part_id, "ids": tuple(request.balloon_ids)}

    if request.measuring_instrument is not None:
        update_fields.append("measuring_instrument = :measuring_instrument")
        update_params["measuring_instrument"] = request.measuring_instrument
        
    if request.sampling is not None:
        update_fields.append("sampling = :sampling")
        update_params["sampling"] = request.sampling

    if not update_fields:
        return {"status": "noop", "updated_count": 0}

    update_query = text(f"""
        UPDATE balloons
        SET {', '.join(update_fields)}
        WHERE part_id = :part_id AND balloon_id IN :ids
    """)
    
    result = db.execute(update_query, update_params)
    db.commit()
    
    return {
        "message": f"Successfully updated {result.rowcount} balloons",
        "updated_count": result.rowcount,
        "bounding_boxes": (await get_bounding_boxes_by_part(request.part_id, db))["bounding_boxes"]
    }


@router.get("/pdf/{pdf_id}/download-ballooned")
async def download_ballooned_pdf(pdf_id: str, db: Session = Depends(get_db)):
    """Download PDF with teardrop balloon annotations overlaid"""
    logger.info(f"Generating ballooned PDF for: {pdf_id}")

    # ── Fetch PDF ─────────────────────────────────────────────────────────────
    pdf_path = get_pdf_path(pdf_id, db)
    if not pdf_path or not Path(pdf_path).exists():
        raise HTTPException(status_code=404, detail="PDF not found")

    # ── Fetch balloons from DB ────────────────────────────────────────────────
    bounding_boxes = []
    try:
        result = db.execute(
            text("""
                SELECT balloon_id, x, y, width, height, page, type::TEXT as type
                FROM balloons
                WHERE document_id = :document_id
                ORDER BY id
            """),
            {"document_id": int(pdf_id)},
        )
        for row in result.fetchall():
            bounding_boxes.append({
                "balloon_id": row.balloon_id,
                "x":          float(row.x),
                "y":          float(row.y),
                "width":      float(row.width),
                "height":     float(row.height),
                "page":       row.page,
                "type":       row.type,
            })
    except Exception as e:
        logger.warning(f"Could not load balloons from DB: {e}")

    # ── Constants ─────────────────────────────────────────────────────────────
    BALLOON_COLOR = (0.055, 0.647, 0.914)  # sky-500
    BALLOON_SIZE  = 18.0   # outer balloon square (pts)

    # ── Font resolution (JetBrains Mono Bold → Courier fallback) ─────────────
    JBMONO_PATHS = [
        str(Path(__file__).parent.parent / "fonts" / "JetBrainsMono-Bold.ttf"),
    ]
    jbmono_file: str | None = next(
        (p for p in JBMONO_PATHS if Path(p).exists()), None
    )
    if jbmono_file:
        logger.info(f"Using JetBrains Mono font from: {jbmono_file}")
    else:
        logger.warning("JetBrains Mono font not found, falling back to Courier")

    def register_font(page) -> str:
        """Insert JetBrains Mono into the page resource dict if available."""
        if jbmono_file:
            page.insert_font(fontname="jbmono", fontfile=jbmono_file)
            return "jbmono"
        return "cour"  # built-in Courier — always available, monospace

    # ── Teardrop balloon ──────────────────────────────────────────────────────
    def draw_balloon(page, px: float, py: float,
                     b_size: float, color: tuple,
                     label: str, fontname: str) -> None:
        """
        Draw a teardrop balloon matching the React component:
            border-radius: 50% 50% 50% 0%   (bottom-left is the sharp tip)
            positioned with: left-full  -translate-y-full

        (px, py) = bottom-left SHARP corner of the balloon square,
                   which maps to the TOP-RIGHT corner of the bounding box.

        PyMuPDF path API used:
            shape.draw_line(p1, p2)
            shape.draw_bezier(start, ctrl1, ctrl2, end)
        """
        k = 0.5523          # cubic-bezier constant for a 90° arc approximation
        r = b_size / 2.0

        # Midpoints of each side (where adjacent 50%-radius arcs meet)
        bl        = fitz.Point(px,           py)           # sharp tip
        left_mid  = fitz.Point(px,           py - r)
        top_mid   = fitz.Point(px + r,       py - b_size)
        right_mid = fitz.Point(px + b_size,  py - r)
        bot_mid   = fitz.Point(px + r,       py)

        # ── 1. Outer teardrop (solid colour fill) ─────────────────────────────
        sh = page.new_shape()

        sh.draw_line(bl, left_mid)                          # sharp tip → left mid

        sh.draw_bezier(                                     # top-left arc
            left_mid,
            fitz.Point(px,            py - r*(1+k)),
            fitz.Point(px + r*(1-k),  py - b_size),
            top_mid,
        )
        sh.draw_bezier(                                     # top-right arc
            top_mid,
            fitz.Point(px + r*(1+k),  py - b_size),
            fitz.Point(px + b_size,   py - r*(1+k)),
            right_mid,
        )
        sh.draw_bezier(                                     # bottom-right arc
            right_mid,
            fitz.Point(px + b_size,   py - r*(1-k)),
            fitz.Point(px + r*(1+k),  py),
            bot_mid,
        )

        sh.draw_line(bot_mid, bl)                           # bottom mid → sharp tip

        sh.finish(color=color, fill=color, fill_opacity=1.0, width=0, closePath=False)
        sh.commit()

        # ── 2. Inner white circle ─────────────────────────────────────────────
        cx     = px + r
        cy     = py - r          # geometric centre of the balloon square
        inner_r = r * 0.78       # mirrors innerCircleSize / balloonBaseSize in React

        sh2 = page.new_shape()
        sh2.draw_circle(fitz.Point(cx, cy), inner_r)
        sh2.finish(color=(1, 1, 1), fill=(1, 1, 1), width=0)
        sh2.commit()

        # ── 3. Number label ───────────────────────────────────────────────────
        # insert_text(point) places the baseline at `point`.
        # For JetBrains Mono / Courier the advance width ≈ 0.58 × fontsize.
        # Baseline offset above centre ≈ 0.30 × fontsize (≈ cap-height / 2).
        fs     = 8.5 if len(label) <= 2 else 6.5
        text_w = len(label) * fs * 0.58        # estimated total text width
        tx     = cx - text_w / 2              # x: horizontally centred
        ty     = cy + fs * 0.30               # y: baseline for vertical centre

        page.insert_text(
            fitz.Point(tx, ty),
            label,
            fontsize=fs,
            fontname=fontname,
            color=(0.05, 0.05, 0.05),          # near-black (slate-900)
            render_mode=0,
        )

    # ── Render balloons onto each page ────────────────────────────────────────
    try:
        doc = fitz.open(pdf_path)
        
        # If it's an image (JPG, PNG), convert to PDF to allow annotations
        if not doc.is_pdf:
            pdf_bytes = doc.convert_to_pdf()
            doc.close()
            doc = fitz.open("pdf", pdf_bytes)

        # Group boxes by 0-indexed page number
        boxes_by_page: dict[int, list] = {}
        for bbox in bounding_boxes:
            p = bbox.get("page", 1) - 1
            boxes_by_page.setdefault(p, []).append(bbox)

        for page_num, boxes in boxes_by_page.items():
            if page_num >= len(doc):
                continue

            page     = doc[page_num]
            fontname = register_font(page)

            for idx, bbox in enumerate(boxes):
                x = bbox.get("x", 0)
                y = bbox.get("y", 0)
                w = bbox.get("width", 0)
                label = str(bbox.get("balloon_id", idx + 1))

                # Anchor: bottom-left (sharp tip) at the bbox's top-right corner
                draw_balloon(page, x + w, y, BALLOON_SIZE, BALLOON_COLOR, label, fontname)

        # ── Save & return ─────────────────────────────────────────────────────
        fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="ballooned_")
        os.close(fd)
        doc.save(tmp_path)
        doc.close()

        from fastapi import BackgroundTasks
        bg = BackgroundTasks()
        bg.add_task(cleanup_temp_file, tmp_path)

        return FileResponse(
            tmp_path,
            filename=f"ballooned_{pdf_id}.pdf",
            media_type="application/pdf",
            background=bg,
        )

    except Exception as e:
        import traceback
        logger.error(f"Error generating ballooned PDF: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


async def filter_and_create_balloons(
    page_result: dict, part_id: str, pdf_id: str, db: Session, main_rect: Optional[tuple] = None
) -> dict:
    """
    Filter detections based on exclusion zones and create balloons.
    When main_rect is provided (innermost drawing boundary), only detections inside it are ballooned.
    """
    try:
        created = 0
        skipped = 0
        
        # Create balloons only from dimension_parsing (clustered + GDT-associated dimensions).
        # This avoids duplicate balloons from raw text_detections and ensures one balloon per dimension.
        for detection in page_result.get("dimension_parsing", []):
            if should_create_balloon(detection, main_rect=main_rect, source="dimension"):
                bbox = create_bbox_from_detection(detection)
                label = f"{detection.get('dimension_type', 'Dimension')}: {detection.get('nominal_value', '')}"
                await save_balloon(db, part_id, pdf_id, bbox, label, dimension=detection)
                created += 1
            else:
                skipped += 1
        
        return {"created": created, "skipped": skipped}
        
    except Exception as e:
        logger.error(f"Error in filter_and_create_balloons: {str(e)}", exc_info=True)
        return {"created": 0, "skipped": 0}


def _bbox_xywh(bbox: list) -> tuple:
    """Return (x, y, width, height) from bbox (list of points or flat coords)."""
    if not bbox or len(bbox) < 2:
        return 0, 0, 50, 30
    if isinstance(bbox[0], (list, tuple)):
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
    else:
        xs = [bbox[0], bbox[2]] if len(bbox) > 2 else [bbox[0]]
        ys = [bbox[1], bbox[3]] if len(bbox) > 3 else [bbox[1]]
    x, x2 = min(xs), max(xs)
    y, y2 = min(ys), max(ys)
    return x, y, max(1, x2 - x), max(1, y2 - y)


def should_create_balloon(detection: dict, main_rect: Optional[tuple] = None, source: str = "dimension") -> bool:
    """
    Check if a balloon should be created for this detection.
    When main_rect is set, only detections inside the innermost drawing boundary are allowed.
    source='dimension' means detection is from dimension_parsing (already validated).
    """
    try:
        bbox = detection.get("bbox", detection.get("box", []))
        if not bbox or len(bbox) < 2:
            return False
        
        # When innermost boundary is available and reasonable size, only allow detections inside it
        if main_rect is not None and is_inside_boundary is not None and len(main_rect) == 4:
            mx, my, mw, mh = main_rect
            page_area = 595 * 842
            main_area = mw * mh
            if main_area >= page_area * 0.15:  # use boundary only if it covers at least 15% of page
                if not is_inside_boundary(bbox, main_rect):
                    return False
        
        x, y, width, height = _bbox_xywh(bbox)
        page_width = 595
        page_height = 842
        
        # Exclusion zones (title block, tables, top notes)
        if x > page_width * 0.75 and y > page_height * 0.75:
            return False
        if x < page_width * 0.2 and y > page_height * 0.8:
            return False
        if page_width * 0.3 < x < page_width * 0.7 and y < page_height * 0.08:
            return False
        
        # Skip only very tiny noise (dimensions often have small bbox when parsed)
        if width < 3 and height < 3:
            return False
        
        # For dimension_parsing we already have valid dimensions; skip irrelevant only for obvious metadata
        text = (detection.get("text") or detection.get("content") or "").strip()
        if text and isinstance(text, str) and source == "dimension":
            # Only skip clear non-drawing text
            if re.search(r"page\s*\d+|fig\.\s*\d+|©|all rights reserved", text, re.IGNORECASE):
                return False
        elif text and isinstance(text, str):
            irrelevant_patterns = [
                r"^M\d+$", r"THRU", r"PCD", r"DEPTH",
                r"page\s*\d+", r"fig\.\s*\d+", r"REF$", r"TYP$", r"©", r"all rights reserved"
            ]
            for pattern in irrelevant_patterns:
                if re.search(pattern, text.strip(), re.IGNORECASE):
                    return False
        
        return True
        
    except Exception as e:
        logger.error(f"Error in should_create_balloon: {str(e)}")
        return False


def create_bbox_from_detection(detection: dict) -> dict:
    """
    Create bounding box object from detection (x, y, width, height, page).
    """
    try:
        bbox = detection.get("bbox", detection.get("box", []))
        page = detection.get("page", 1)
        
        if bbox and len(bbox) >= 2:
            x, y, width, height = _bbox_xywh(bbox)
            return {
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "page": page
            }
        
        # Fallback
        return {
            "x": 0,
            "y": 0,
            "width": 50,
            "height": 30,
            "page": page
        }
        
    except Exception as e:
        logger.error(f"Error in create_bbox_from_detection: {str(e)}")
        return {
            "x": 0,
            "y": 0,
            "width": 50,
            "height": 30,
            "page": 1
        }


async def save_balloon(db: Session, part_id: str, pdf_id: str, bbox: dict, label: str, dimension: dict | None = None):
    """
    Save balloon to database
    """
    try:
        import time
        from app.models.document import Document

        # Convert / validate part_id
        part_id_int = int(part_id)

        # Resolve pdf_id (document) if provided
        document_id = None
        if pdf_id is not None:
            try:
                document_id_int = int(pdf_id)
                document = db.query(Document).filter(Document.id == document_id_int).first()
                if document:
                    document_id = document.id
                else:
                    logger.warning(f"save_balloon: Document with ID {document_id_int} not found; saving balloon without document_id")
            except (TypeError, ValueError):
                logger.warning(f"save_balloon: Invalid pdf_id '{pdf_id}', saving balloon without document_id")

        # Generate unique external balloon identifier (same style as manual save_bounding_box)
        balloon_id = str(int(time.time() * 1000000))

        # Extract dimensional fields if provided
        nominal_value = None
        utol_value: str | None = None
        ltol_value: str | None = None
        dim_type_value: str | None = None

        if dimension:
            try:
                raw_nominal = dimension.get("nominal_value")
                if raw_nominal not in (None, ""):
                    # Store numeric nominal for BOM/measurements
                    nominal_value = float(str(raw_nominal).replace(",", "."))
            except (ValueError, TypeError):
                nominal_value = None

            utol_value = dimension.get("upper_tolerance")
            ltol_value = dimension.get("lower_tolerance")
            dim_type_value = dimension.get("dimension_type") or None

        # Map to Balloon ORM fields (note: there is no 'pdf_id' or 'label' column)
        balloon = Balloon(
            part_id=part_id_int,
            document_id=document_id,
            balloon_id=balloon_id,
            x=bbox["x"],
            y=bbox["y"],
            width=bbox["width"],
            height=bbox["height"],
            page=bbox.get("page", 1),
            nominal=nominal_value,
            utol=str(utol_value) if utol_value not in (None, "") else None,
            ltol=str(ltol_value) if ltol_value not in (None, "") else None,
            type=dim_type_value or label,
        )
        
        db.add(balloon)
        db.flush()  # assign id before commit
        saved_id = balloon.id
        db.commit()
        # Do not refresh or touch balloon after commit: the object is expired and loading
        # it would SELECT from DB, where some columns are VARCHAR (PG 1043) but the ORM
        # maps them as Float, causing "Unknown PG numeric type: 1043".
        logger.info(
            f"Auto-balloon saved: id={saved_id}, balloon_id={balloon_id}, "
            f"part_id={part_id_int}, document_id={document_id}, "
            f"page={bbox.get('page', 1)}, x={bbox['x']}, y={bbox['y']}, "
            f"width={bbox['width']}, height={bbox['height']}, type={dim_type_value or label}"
        )
        # Return a simple result object; do not use the ORM balloon after commit.
        result = type("SavedBalloon", (), {"id": saved_id, "balloon_id": balloon_id})()
        return result
        
    except Exception as e:
        logger.error(f"Error saving balloon: {str(e)}")
        db.rollback()
        raise

