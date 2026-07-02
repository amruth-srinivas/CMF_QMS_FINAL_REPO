"""
PDF Annotation router for extracting text, GDT, dimensions, and engineering notes from PDFs.
CMF: PDFs are loaded from MinIO via oms.documents.document_url; processing utilities live in pdf_processing/.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Callable
from pathlib import Path
import logging
import os
import tempfile
import re
import fitz  # PyMuPDF
import numpy as np
import cv2
import base64

from DB.database import get_db
from DB.models.oms import Document as DocumentModel, Part, OperationDocument as OperationDocumentModel
from DB.minio_client import get_minio_client
from DB.schemas.pdf_annotation import (
    BoundingBox,
    ExtractTextRequest,
    ExtractZonesBulkRequest,
    ProcessDimensionsRequest,
    RenderPageRequest,
)

try:
    from pdf_processing.text_extractor import TextExtractor as PyMuPDFTextExtractor
except ImportError as e:
    logging.warning("PyMuPDF text extractor not available: %s", e)
    PyMuPDFTextExtractor = None

BackendOCRTextExtractor = None
_OCR_EXTRACTOR_LOAD_ATTEMPTED = False

try:
    from pdf_processing.region_text_extraction import extract_text_from_region_hybrid
except ImportError as e:
    logging.warning("Hybrid text extraction not available: %s", e)
    extract_text_from_region_hybrid = None


def _load_ocr_extractor_class():
    """Lazy-load PaddleOCR extractor from pdf_processing/autoballoon (avoids blocking startup)."""
    global BackendOCRTextExtractor, _OCR_EXTRACTOR_LOAD_ATTEMPTED
    if _OCR_EXTRACTOR_LOAD_ATTEMPTED:
        return
    _OCR_EXTRACTOR_LOAD_ATTEMPTED = True
    try:
        from pdf_processing.backend_ocr_extractor import TextExtractor as _BackendOCRTextExtractor
        BackendOCRTextExtractor = _BackendOCRTextExtractor
    except ImportError as e:
        logging.warning(
            "Backend PaddleOCR extractor not available (install paddleocr/paddlepaddle): %s",
            e,
        )
        BackendOCRTextExtractor = None


try:
    from pdf_processing.gdt_detector import get_gdt_detector
    from pdf_processing.dimension_parser import DimensionParser
except ImportError as e:
    logging.warning("GDT/dimension utils not available: %s", e)
    get_gdt_detector = None
    DimensionParser = None

try:
    from pdf_processing.qms.zone import ZoneDetector
except ImportError as e:
    logging.debug("ZoneDetector not available: %s", e)
    ZoneDetector = None

try:
    from pdf_processing.drawing_boundary import find_innermost_boundary, is_inside_boundary
except ImportError as e:
    logging.debug("drawing_boundary not available: %s", e)
    find_innermost_boundary = None
    is_inside_boundary = None

try:
    from pdf_processing.dimension_clustering import cluster_tolerances
except ImportError as e:
    logging.debug("dimension_clustering not available: %s", e)
    cluster_tolerances = None

_CMF_ROOT = Path(__file__).resolve().parent.parent


def _gdt_model_search_paths() -> List[Path]:
    w = _CMF_ROOT / "pdf_processing" / "weights"
    autoballoon_gdt = _CMF_ROOT / "pdf_processing" / "autoballoon" / "models" / "gdt_model_2.pt"
    return [
        autoballoon_gdt,
        w / "best2.pt",
        w / "best.pt",
        _CMF_ROOT / "pdf_processing" / "best2.pt",
        Path("best2.pt"),
    ]


TextExtractor = PyMuPDFTextExtractor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pdf-annotation", tags=["pdf_annotation"])

# OCR extractor singleton for scanned PDFs
_ocr_extractor_instance = None


def get_ocr_extractor():
    """Get or create PaddleOCR extractor (pdf_processing/autoballoon pipeline)."""
    global _ocr_extractor_instance
    _load_ocr_extractor_class()
    if _ocr_extractor_instance is None and BackendOCRTextExtractor is not None:
        try:
            _ocr_extractor_instance = BackendOCRTextExtractor()
            logger.info("Backend PaddleOCR extractor initialized")
        except Exception as e:
            logger.error("Failed to initialize PaddleOCR extractor: %s", e, exc_info=True)
    return _ocr_extractor_instance


def _extract_region_text(
    *,
    pdf_path: str,
    page_number: int,
    region: dict,
    scale_factor: float,
    check_overlaps: bool,
    existing_boxes: Optional[List],
    iou_threshold: float,
    rotation_angles: Optional[List[int]],
    confidence_threshold: float = 0.3,
) -> List[Dict]:
    """OCR first (Paddle), PyMuPDF fallback when OCR yields no text."""
    if extract_text_from_region_hybrid is None:
        if not PyMuPDFTextExtractor:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Text extraction service not available",
            )
        if check_overlaps and existing_boxes:
            return PyMuPDFTextExtractor.extract_text_with_overlap_check(
                pdf_path=pdf_path,
                page_number=page_number,
                region=region,
                existing_boxes=existing_boxes,
                iou_threshold=iou_threshold,
                scale_factor=scale_factor,
            )
        return PyMuPDFTextExtractor.extract_text_from_region(
            pdf_path=pdf_path,
            page_number=page_number,
            region=region,
            scale_factor=scale_factor,
        )

    return extract_text_from_region_hybrid(
        pdf_path,
        page_number,
        region,
        scale_factor=scale_factor,
        check_overlaps=check_overlaps,
        existing_boxes=existing_boxes,
        iou_threshold=iou_threshold,
        rotation_angles=rotation_angles,
        confidence_threshold=confidence_threshold,
        get_ocr_extractor=get_ocr_extractor,
        pymupdf_extractor=PyMuPDFTextExtractor,
    )


def _process_dimensions_via_autoballoon(
    file_path: str,
    page_number: int,
    region: dict,
) -> Optional[Dict]:
    """
    Run the full autoballoon pipeline for a region.
    Returns API payload on success, or None to fall back to legacy PyMuPDF + parser flow.
    """
    try:
        from services import autoballoon_service
    except ImportError:
        return None

    if not autoballoon_service.is_pipeline_available():
        return None

    user_region = [region["x"], region["y"], region["width"], region["height"]]
    try:
        pipeline_result = autoballoon_service.run_pipeline(
            str(file_path),
            page_index=page_number,
            user_region=user_region,
            max_ocr_dim=2048,
            include_image=False,
        )
    except Exception as exc:
        logger.warning("Autoballoon pipeline failed, using legacy dimension flow: %s", exc)
        return None

    inv_scale = 72.0 / 250.0
    mapped_dimensions = autoballoon_service.map_pipeline_dimensions_to_api(
        pipeline_result.get("parsed_dimensions", []),
        inv_scale,
    )
    # Exclude title-block material / alloy lines (not in user selection scope).
    mapped_dimensions = [
        d
        for d in mapped_dimensions
        if str(d.get("dimension_type", "")).strip().lower() != "material"
    ]

    def _flat_bbox_to_quad(flat_bbox: List[float]) -> List[List[float]]:
        if not flat_bbox or len(flat_bbox) < 4:
            return []
        x1, y1, x2, y2 = [float(v) for v in flat_bbox[:4]]
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    for dim in mapped_dimensions:
        bbox = dim.get("bbox")
        if isinstance(bbox, list) and len(bbox) >= 4 and isinstance(bbox[0], (int, float)):
            dim["bbox"] = _flat_bbox_to_quad(bbox)

    all_dimensions = mapped_dimensions
    if not all_dimensions:
        logger.info("Autoballoon pipeline returned no dimensions; using legacy flow")
        return None

    text_results = autoballoon_service.map_classified_detections_to_text_api(
        pipeline_result.get("classified_detections", []),
        inv_scale,
    )
    gdt_results = []
    for gdt in pipeline_result.get("gdt_detections", []):
        bbox = gdt.get("bbox")
        if not bbox:
            continue
        scaled = [float(v) * inv_scale for v in bbox]
        gdt_results.append(
            {
                "class_name": gdt.get("class", gdt.get("class_name", "Unknown")),
                "confidence": float(gdt.get("score", gdt.get("confidence", 0.0))),
                "box": [
                    [scaled[0], scaled[1]],
                    [scaled[2], scaled[1]],
                    [scaled[2], scaled[3]],
                    [scaled[0], scaled[3]],
                ],
            }
        )

    logger.info(
        "Autoballoon pipeline: %s dimension(s), %s text detection(s), %s GDT detection(s)",
        len(all_dimensions),
        len(text_results),
        len(gdt_results),
    )

    return {
        "success": True,
        "dimensions": all_dimensions,
        "count": len(all_dimensions),
        "text_dimensions": len(mapped_dimensions),
        "gdt_dimensions": sum(
            1 for d in mapped_dimensions if "gdt" in str(d.get("dimension_type", "")).lower()
        ),
        "material_dimensions": 0,
        "text_detections": text_results,
        "gdt_detections": gdt_results,
        "dimension_parsing": all_dimensions,
        "notes": [],
        "note_count": 0,
        "source": "autoballoon_pipeline",
    }


def get_pdf_type(document_id: int, db: Session) -> str:
    """Heuristic: normal vs scanned. CMF stores type in document_type string."""
    document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
    if not document:
        return "normal"
    t = (document.document_type or "").lower()
    if "scan" in t or "scanned" in t or "ocr" in t:
        return "scanned"
    return "normal"


def get_pdf_path_from_document(document_id: int, db: Session) -> tuple[str, Callable[[], None]]:
    """
    Download PDF from MinIO to a temp file. Looks in oms.documents first, then
    falls back to oms.operation_documents. Caller must invoke the returned cleanup
    in a finally block to delete the temp file.
    """
    document = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
    src = "oms.documents"
    if not document:
        document = db.query(OperationDocumentModel).filter(OperationDocumentModel.id == document_id).first()
        src = "oms.operation_documents"
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in documents or operation_documents"
        )
    logger.info(
        "PDF for processing: id=%s source=%s name=%s",
        document_id,
        src,
        getattr(document, "document_name", None) or getattr(document, "name", "") or "",
    )
    minio = get_minio_client()
    url = document.document_url or ""
    marker = f"/{minio.bucket_name}/"
    if marker not in url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document URL is missing MinIO object path"
        )
    object_name = url.split(marker, 1)[1]
    data = minio.download_file(object_name)
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.write(fd, data)
    finally:
        os.close(fd)

    def _cleanup() -> None:
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass

    return path, _cleanup


def _region_from_quad(quad: Optional[List[List[float]]]) -> Optional[Dict[str, float]]:
    if not quad or len(quad) < 2:
        return None
    try:
        xs = [float(p[0]) for p in quad]
        ys = [float(p[1]) for p in quad]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        w = max_x - min_x
        h = max_y - min_y
        if w <= 0 or h <= 0:
            return None
        return {"x": min_x, "y": min_y, "width": w, "height": h}
    except Exception:
        return None


def _detect_zone_label(pdf_path: str, page_number: int, region: Dict[str, float], scale_factor: float = 1.0) -> Optional[str]:
    if ZoneDetector is None:
        return None
    try:
        z = ZoneDetector.extract_zone_from_region(
            pdf_path=pdf_path,
            page_number=page_number,
            region=region,
            scale_factor=scale_factor,
        )
        if z and isinstance(z, list):
            zone = (z[0] or {}).get("zone")
            if zone:
                return str(zone).strip().upper()
    except Exception:
        logger.debug("Zone extraction failed", exc_info=True)
    return None


@router.post("/extract-text")
async def extract_text(request: ExtractTextRequest, db: Session = Depends(get_db)):
    """Extract text from a region: PaddleOCR first, PyMuPDF vector text as fallback."""
    part = db.query(Part).filter(Part.id == request.part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {request.part_id} not found"
        )
    
    cleanup_pdf: Optional[Callable[[], None]] = None
    try:
        if not request.pdf_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="pdf_id is required for text extraction"
            )
        try:
            document_id = int(request.pdf_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="pdf_id must be a valid document ID (integer)"
            )
        file_path, cleanup_pdf = get_pdf_path_from_document(document_id, db)
        pdf_type = (request.pdf_content_type or "").strip().lower() or get_pdf_type(document_id, db)
        if pdf_type not in ("normal", "scanned"):
            pdf_type = "normal"
        logger.info(f"PDF type: {pdf_type} for document {document_id}")
        
        page_number = request.bounding_box.page - 1
        region = {
            "x": request.bounding_box.x,
            "y": request.bounding_box.y,
            "width": request.bounding_box.width,
            "height": request.bounding_box.height,
        }
        
        rotation_angles = (
            [request.rotation_angle]
            if request.rotation_angle is not None
            else ([0, 90, 180, 270] if pdf_type == "scanned" else None)
        )
        if not get_ocr_extractor() and not PyMuPDFTextExtractor:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Text extraction unavailable. Install paddleocr/paddlepaddle or ensure PyMuPDF is available.",
            )
        results = _extract_region_text(
            pdf_path=str(file_path),
            page_number=page_number,
            region=region,
            scale_factor=request.scale_factor,
            check_overlaps=bool(request.check_overlaps and request.existing_boxes),
            existing_boxes=request.existing_boxes,
            iou_threshold=request.iou_threshold,
            rotation_angles=rotation_angles,
            confidence_threshold=0.3,
        )
        
        return {"success": True, "detections": results, "count": len(results)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extracting text: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error extracting text: {str(e)}")
    finally:
        if cleanup_pdf:
            try:
                cleanup_pdf()
            except Exception:
                pass


@router.post("/extract-gdt")
async def extract_gdt(request: ExtractTextRequest, db: Session = Depends(get_db)):
    """Detect GDT symbols from a specific region of a PDF page."""
    if not get_gdt_detector:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GDT detection service not available"
        )
    
    part = db.query(Part).filter(Part.id == request.part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {request.part_id} not found"
        )
    
    cleanup_pdf: Optional[Callable[[], None]] = None
    try:
        # Get PDF path from document if provided
        if not request.pdf_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="pdf_id is required for GDT extraction"
            )
        
        try:
            document_id = int(request.pdf_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="pdf_id must be a valid document ID (integer)"
            )
        file_path, cleanup_pdf = get_pdf_path_from_document(document_id, db)
        
        model_paths = [str(p) for p in _gdt_model_search_paths()]
        model_path = None
        for path in model_paths:
            if Path(path).exists():
                model_path = path
                logger.info(f"Found GDT model at: {model_path}")
                break
        
        if not model_path:
            logger.warning("GDT model not found in any of these locations: %s", model_paths)
            model_path = str(_CMF_ROOT / "pdf_processing" / "weights" / "best2.pt")
        
        gdt_detector = get_gdt_detector(model_path)
        
        if not gdt_detector or not gdt_detector.model:
            raise HTTPException(
                status_code=503,
                detail=f"GDT detection not available. YOLO model not loaded. Tried paths: {model_paths}"
            )
        
        page_number = request.bounding_box.page - 1
        region = {
            'x': request.bounding_box.x,
            'y': request.bounding_box.y,
            'width': request.bounding_box.width,
            'height': request.bounding_box.height
        }
        
        # Detect GDT symbols with confidence threshold
        logger.info(f"Detecting GDT symbols in region: {region} on page {page_number}")
        logger.debug(f"PDF path: {file_path}, scale_factor: {request.scale_factor}")
        
        results = gdt_detector.detect_gdt_symbols_from_pdf_region(
            pdf_path=str(file_path),
            page_number=page_number,
            region=region,
            confidence_threshold=0.3,  # Lower confidence threshold for better detection
            scale_factor=request.scale_factor
        )
        
        logger.info(f"GDT detection completed. Found {len(results)} symbols")
        if results:
            logger.debug(f"GDT symbols detected: {[r.get('class_name', 'unknown') for r in results]}")
        
        return {
            "success": True,
            "detections": results,
            "count": len(results)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error detecting GDT: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error detecting GDT: {str(e)}")
    finally:
        if cleanup_pdf:
            try:
                cleanup_pdf()
            except Exception:
                pass


@router.post("/process-dimensions")
async def process_dimensions(request: ProcessDimensionsRequest, db: Session = Depends(get_db)):
    """
    Process dimensions: Extract text, detect GDT, and parse dimensions.
    Uses PaddleOCR first, then PyMuPDF when OCR returns no text.
    """
    import re
    
    if not DimensionParser:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dimension parsing service not available"
        )
    
    part = db.query(Part).filter(Part.id == request.part_id).first()
    if not part:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Part with ID {request.part_id} not found"
        )
    
    cleanup_pdf: Optional[Callable[[], None]] = None
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
        file_path, cleanup_pdf = get_pdf_path_from_document(document_id, db)
        pdf_type = (request.pdf_content_type or "").strip().lower() or get_pdf_type(document_id, db)
        if pdf_type not in ("normal", "scanned"):
            pdf_type = "normal"
        logger.info(f"PDF type: {pdf_type} for document {document_id}")
        
        page_number = request.bounding_box.page - 1
        region = {
            "x": request.bounding_box.x,
            "y": request.bounding_box.y,
            "width": request.bounding_box.width,
            "height": request.bounding_box.height,
        }
        
        # Debug: dump PDF page size vs region so we can spot coordinate mismatches
        try:
            _dbg_doc = fitz.open(str(file_path))
            _dbg_page = _dbg_doc[page_number]
            logger.info(
                f"📐 PDF page rect={_dbg_page.rect}, rotation={_dbg_page.rotation}, "
                f"mediabox={_dbg_page.mediabox} | scale_factor={request.scale_factor}"
            )
            _dbg_doc.close()
        except Exception as _e:
            logger.warning(f"Debug page info failed: {_e}")

        pipeline_payload = _process_dimensions_via_autoballoon(
            str(file_path), page_number, region
        )
        if pipeline_payload is not None:
            for dim in pipeline_payload.get("dimensions", []):
                dim["page"] = page_number + 1
                dim_bbox = dim.get("bbox")
                dim_region = _region_from_quad(dim_bbox) if isinstance(dim_bbox, list) else None
                if dim_region:
                    zone_label = _detect_zone_label(
                        pdf_path=str(file_path),
                        page_number=page_number,
                        region=dim_region,
                        scale_factor=request.scale_factor,
                    )
                    if zone_label:
                        dim["zone"] = zone_label
            return pipeline_payload
        
        # Step 1: Extract text (PaddleOCR first, PyMuPDF fallback)
        logger.info("Step 1: Extracting text (legacy hybrid flow)...")
        logger.info(f"Region coordinates: x={region['x']:.2f}, y={region['y']:.2f}, width={region['width']:.2f}, height={region['height']:.2f}")

        rotation_angles = (
            [request.rotation_angle]
            if request.rotation_angle is not None
            else ([0, 90, 180, 270] if pdf_type == "scanned" else None)
        )
        if not get_ocr_extractor() and not PyMuPDFTextExtractor:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Text extraction unavailable. Install paddleocr/paddlepaddle or ensure PyMuPDF is available.",
            )
        text_results = _extract_region_text(
            pdf_path=str(file_path),
            page_number=page_number,
            region=region,
            scale_factor=request.scale_factor,
            check_overlaps=bool(request.check_overlaps and request.existing_boxes),
            existing_boxes=request.existing_boxes,
            iou_threshold=request.iou_threshold,
            rotation_angles=rotation_angles,
            confidence_threshold=0.3,
        )
        logger.info(f"✓ Extracted {len(text_results)} text detections")
        
        if len(text_results) == 0:
            logger.warning("⚠ No text found in the selected region. Check if coordinates are correct.")
        else:
            # Log first few text items for debugging
            sample_texts = [item.get('text', '') or item.get('content', '') for item in text_results[:5]]
            logger.info(f"Sample extracted texts: {sample_texts}")
        
        # Step 1b: Cluster tolerances (nominal + upper/lower tol on same axis) for accurate dimension parsing
        text_for_dimensions = text_results
        if cluster_tolerances and DimensionParser:
            try:
                text_for_dimensions = cluster_tolerances(
                    text_results,
                    is_dimensional_value=DimensionParser.is_dimensional_value,
                )
                logger.info(f"✓ Tolerance clustering: {len(text_results)} -> {len(text_for_dimensions)} entries for dimension parsing")
            except Exception as e:
                logger.warning(f"Tolerance clustering failed: {e}, using raw text results")
        
        # Step 2: Detect GDT symbols
        logger.info("Step 2: Detecting GDT symbols...")
        gdt_results = []
        try:
            if get_gdt_detector:
                model_paths = [str(p) for p in _gdt_model_search_paths()]
                model_path = None
                for path in model_paths:
                    if Path(path).exists():
                        model_path = path
                        logger.info(f"Found GDT model at: {model_path}")
                        break
                
                if not model_path:
                    logger.warning("GDT model not found in any of these locations: %s", model_paths)
                    model_path = str(_CMF_ROOT / "pdf_processing" / "weights" / "best2.pt")
                
                gdt_detector = get_gdt_detector(model_path)
                
                if gdt_detector and gdt_detector.model:
                    gdt_results = gdt_detector.detect_gdt_symbols_from_pdf_region(
                        pdf_path=str(file_path),
                        page_number=page_number,
                        region=region,
                        confidence_threshold=0.3,
                        scale_factor=request.scale_factor
                    )
                    logger.info(f"Detected {len(gdt_results)} GDT symbols")
                else:
                    logger.warning("GDT detector model not available, skipping GDT detection")
            else:
                logger.warning("GDT detector not available, skipping GDT detection")
        except Exception as e:
            logger.warning(f"GDT detection failed: {str(e)}, continuing without GDT data")
        
        # Step 3: Parse dimensions from extracted text (using clustered list when available)
        logger.info("Step 3: Parsing dimensions from extracted text...")
        dimension_results = []
        processed_texts = set()
        
        for text_item in text_for_dimensions:
            text_content = text_item.get('text', '') or text_item.get('content', '')
            if not text_content or not text_content.strip():
                continue
            
            text_content = text_content.strip()
            
            # Skip if already processed
            if text_content in processed_texts:
                continue
            
            logger.debug(f"Checking text for dimension: '{text_content}'")
            
            # Check if this text is a dimensional value
            is_dim = DimensionParser.is_dimensional_value(text_content)
            
            if is_dim:
                try:
                    dim_type, upper_tol, lower_tol, nominal_value = DimensionParser.parse_dimension(text_content)
                    logger.info(f"✓ Parsed dimension: '{text_content}' -> type={dim_type}, nominal={nominal_value}, utol={upper_tol}, ltol={lower_tol}")
                    dimension_results.append({
                        'text': text_content,
                        'nominal_value': nominal_value,
                        'upper_tolerance': upper_tol,
                        'lower_tolerance': lower_tol,
                        'dimension_type': dim_type,
                        'bbox': text_item.get('box', text_item.get('bbox', []))
                    })
                    processed_texts.add(text_content)
                except Exception as e:
                    logger.error(f"Error parsing dimension '{text_content}': {str(e)}")
        
        logger.info(f"✓ Parsed {len(dimension_results)} dimensions from {len(text_for_dimensions)} text items")
        
        # Step 4: Process GDT symbols as dimensions
        logger.info("Step 4: Processing GDT symbols as dimensions...")
        gdt_dimension_results = []
        gdt_associated_texts = set()  # Track text items associated with GDT symbols
        
        for gdt_item in gdt_results:
            gdt_symbol = gdt_item.get('class_name', 'Unknown')
            gdt_box = gdt_item.get('box', [])
            gdt_confidence = gdt_item.get('confidence', 0.0)
            
            # When best2.pt detects a diameter symbol, we will use dimension_type "Diameter"
            gdt_symbol_stripped = (gdt_symbol or '').strip()
            diameter_chars = ('ø', 'Ø', '∅', '⌀')
            is_diameter_gdt = (
                any(gdt_symbol_stripped.startswith(c) for c in diameter_chars)
                or any(c in gdt_symbol_stripped for c in diameter_chars)
                or 'diameter' in gdt_symbol_stripped.lower()
                or gdt_symbol_stripped.lower() == 'dia'
                or (len(gdt_symbol_stripped) <= 4 and 'dia' in gdt_symbol_stripped.lower())
                or gdt_symbol_stripped == 'Diameter'
            )
            
            # Try to find associated tolerance value near the GDT symbol (or for diameter: full dimension text like "83 ±0.15")
            tolerance_value = None
            tolerance_text = None
            associated_text_item = None
            diameter_nominal = None
            diameter_upper_tol = ''
            diameter_lower_tol = ''
            
            if gdt_box and len(gdt_box) >= 2:
                # Get bounding box of GDT symbol
                gdt_x_coords = [p[0] for p in gdt_box]
                gdt_y_coords = [p[1] for p in gdt_box]
                gdt_min_x = min(gdt_x_coords)
                gdt_max_x = max(gdt_x_coords)
                gdt_min_y = min(gdt_y_coords)
                gdt_max_y = max(gdt_y_coords)
                gdt_center_x = sum(gdt_x_coords) / len(gdt_x_coords)
                gdt_center_y = sum(gdt_y_coords) / len(gdt_y_coords)
                
                # Expand search area: larger for diameter so we catch vertical callouts (e.g. "Ø 78 ±0.15" stacked)
                search_distance = 350 if is_diameter_gdt else 100
                # For vertical diameter callouts: same column = within this horizontal band
                vertical_column_x_tolerance = 80
                vertical_column_y_range = 400
                
                # For diameter GDT: find nearby text that looks like a dimension (e.g. "83 ±0.15", "86 ±0.15")
                # so we use its nominal and tolerances instead of treating it as a separate Length dimension
                if is_diameter_gdt:
                    closest_diameter_distance = float('inf')
                    for text_item in text_results:
                        text_box = text_item.get('box', [])
                        if not text_box or len(text_box) < 2:
                            continue
                        text_content = (text_item.get('text', '') or text_item.get('content', '') or '').strip()
                        if not text_content:
                            continue
                        if not DimensionParser.is_dimensional_value(text_content):
                            continue
                        try:
                            _dim_type, _upper, _lower, _nominal = DimensionParser.parse_dimension(text_content)
                        except Exception:
                            continue
                        try:
                            nom_float = float(str(_nominal).replace(',', '.'))
                        except (ValueError, TypeError):
                            continue
                        # Reasonable diameter nominal (e.g. 1.5, 14, 83, 86, 104)
                        if nom_float < 0.5:
                            continue
                        text_center_x = sum([p[0] for p in text_box]) / len(text_box)
                        text_center_y = sum([p[1] for p in text_box]) / len(text_box)
                        distance = ((text_center_x - gdt_center_x) ** 2 + (text_center_y - gdt_center_y) ** 2) ** 0.5
                        # For vertical callouts: also accept text in same column (similar X, different Y)
                        in_vertical_column = (abs(text_center_x - gdt_center_x) <= vertical_column_x_tolerance
                                              and abs(text_center_y - gdt_center_y) <= vertical_column_y_range)
                        if (distance < search_distance or in_vertical_column) and distance < closest_diameter_distance:
                            closest_diameter_distance = distance
                            diameter_nominal = _nominal
                            diameter_upper_tol = _upper or ''
                            diameter_lower_tol = _lower or ''
                            tolerance_value = _nominal
                            tolerance_text = text_content.strip()
                            associated_text_item = text_item
                    if diameter_nominal is not None:
                        logger.info(f"✓ Diameter GDT '{gdt_symbol}' associated with dimension text: nominal={diameter_nominal}, utol={diameter_upper_tol}, ltol={diameter_lower_tol}")
                    
                    # Fallback for vertical diameter: combine vertically stacked text (e.g. "78" and "±0.15" in same column)
                    if diameter_nominal is None and text_results:
                        stack_items = []
                        for text_item in text_results:
                            text_box = text_item.get('box', [])
                            if not text_box or len(text_box) < 2:
                                continue
                            text_content = (text_item.get('text', '') or text_item.get('content', '') or '').strip()
                            if not text_content:
                                continue
                            tc_x = sum([p[0] for p in text_box]) / len(text_box)
                            tc_y = sum([p[1] for p in text_box]) / len(text_box)
                            if abs(tc_x - gdt_center_x) <= vertical_column_x_tolerance and abs(tc_y - gdt_center_y) <= vertical_column_y_range:
                                stack_items.append((tc_y, text_content, text_item))
                        if stack_items:
                            stack_items.sort(key=lambda t: t[0])
                            combined = ' '.join(t[1] for t in stack_items)
                            # Remove diameter symbols from combined so parse sees "78 ±0.15"
                            for sym in ('ø', 'Ø', '∅', '⌀'):
                                combined = combined.replace(sym, '').strip()
                            combined = ' '.join(combined.split())
                            if combined and DimensionParser.is_dimensional_value(combined):
                                try:
                                    _dt, _ut, _lt, _nom = DimensionParser.parse_dimension(combined)
                                    nom_float = float(str(_nom).replace(',', '.'))
                                    if nom_float >= 0.5:
                                        diameter_nominal = _nom
                                        diameter_upper_tol = _ut or ''
                                        diameter_lower_tol = _lt or ''
                                        tolerance_value = _nom
                                        tolerance_text = combined
                                        associated_text_item = stack_items[0][2]
                                        logger.info(f"✓ Diameter GDT '{gdt_symbol}' from vertical stack: nominal={diameter_nominal}, combined='{combined}'")
                                except Exception:
                                    pass
                
                # Fallback for diameter: if no nearby text in text_results, match from parsed dimension_results by bbox
                if is_diameter_gdt and associated_text_item is None and dimension_results:
                    closest_dim_dist = float('inf')
                    for dim in dimension_results:
                        dim_bbox = dim.get('bbox') or []
                        if not dim_bbox or len(dim_bbox) < 2:
                            continue
                        try:
                            nom_float = float(str(dim.get('nominal_value', '')).replace(',', '.').strip())
                        except (ValueError, TypeError):
                            continue
                        if nom_float < 0.5:
                            continue
                        dim_cx = sum(p[0] for p in dim_bbox) / len(dim_bbox)
                        dim_cy = sum(p[1] for p in dim_bbox) / len(dim_bbox)
                        dist = ((dim_cx - gdt_center_x) ** 2 + (dim_cy - gdt_center_y) ** 2) ** 0.5
                        in_col = (abs(dim_cx - gdt_center_x) <= vertical_column_x_tolerance
                                  and abs(dim_cy - gdt_center_y) <= vertical_column_y_range)
                        if (dist < search_distance or in_col) and dist < closest_dim_dist:
                            closest_dim_dist = dist
                            diameter_nominal = dim.get('nominal_value')
                            diameter_upper_tol = dim.get('upper_tolerance') or ''
                            diameter_lower_tol = dim.get('lower_tolerance') or ''
                            tolerance_value = dim.get('nominal_value')
                            tolerance_text = dim.get('text', '')
                            if tolerance_text:
                                gdt_associated_texts.add(tolerance_text.strip())
                    if diameter_nominal is not None:
                        logger.info(f"✓ Diameter GDT '{gdt_symbol}' matched from dimension_results: nominal={diameter_nominal}")
                
                # Search for text near the GDT symbol (tolerance-only when not already set by diameter logic)
                closest_distance = float('inf')
                if associated_text_item is None:
                    for text_item in text_results:
                        text_box = text_item.get('box', [])
                        if not text_box or len(text_box) < 2:
                            continue
                        
                        # Get text bounding box
                        text_x_coords = [p[0] for p in text_box]
                        text_y_coords = [p[1] for p in text_box]
                        text_min_x = min(text_x_coords)
                        text_max_x = max(text_x_coords)
                        text_min_y = min(text_y_coords)
                        text_max_y = max(text_y_coords)
                        text_center_x = sum(text_x_coords) / len(text_x_coords)
                        text_center_y = sum(text_y_coords) / len(text_y_coords)
                        
                        # Calculate distance from GDT center to text center
                        distance = ((text_center_x - gdt_center_x) ** 2 + (text_center_y - gdt_center_y) ** 2) ** 0.5
                        
                        # Check if text box overlaps or is adjacent to GDT box
                        horizontal_overlap = not (text_max_x < gdt_min_x - search_distance or text_min_x > gdt_max_x + search_distance)
                        vertical_overlap = not (text_max_y < gdt_min_y - search_distance or text_min_y > gdt_max_y + search_distance)
                        
                        # If text is within search distance or overlaps
                        if distance < search_distance or (horizontal_overlap and vertical_overlap):
                            text_content = text_item.get('text', '') or text_item.get('content', '')
                            if not text_content:
                                continue
                            
                            text_content = text_content.strip()
                            
                            # Check if it's a numeric value (tolerance)
                            try:
                                parsed_value = float(text_content.replace(',', '.').strip())
                                if parsed_value > 0 and parsed_value < 10:  # Reasonable tolerance range
                                    if distance < closest_distance:
                                        closest_distance = distance
                                        tolerance_value = text_content.strip()
                                        tolerance_text = text_content.strip()
                                        associated_text_item = text_item
                                        logger.debug(f"Found tolerance value '{tolerance_value}' near GDT symbol '{gdt_symbol}' (distance: {distance:.1f})")
                            except ValueError:
                                # Not a simple number, try to extract number from text
                                number_match = re.search(r'(\d+\.?\d*)', text_content)
                                if number_match:
                                    try:
                                        extracted_value = float(number_match.group(1))
                                        if extracted_value > 0 and extracted_value < 10:
                                            if distance < closest_distance:
                                                closest_distance = distance
                                                tolerance_value = number_match.group(1)
                                                tolerance_text = text_content.strip()
                                                associated_text_item = text_item
                                                logger.debug(f"Extracted tolerance '{tolerance_value}' from text '{text_content}' near GDT symbol '{gdt_symbol}' (distance: {distance:.1f})")
                                    except ValueError:
                                        pass
                
                # If we found a tolerance value, log it
                if tolerance_value:
                    logger.info(f"✓ GDT '{gdt_symbol}' has tolerance value: {tolerance_value}")
                else:
                    logger.warning(f"⚠ No tolerance value found near GDT symbol '{gdt_symbol}'")
            
            # Mark associated text as used by GDT (to exclude from text dimensions)
            if associated_text_item:
                text_content = associated_text_item.get('text', '') or associated_text_item.get('content', '')
                if text_content:
                    gdt_associated_texts.add(text_content.strip())
            
            # Fallback search: look for tolerance values in entire extracted text
            if not tolerance_value and text_results:
                logger.debug(f"Fallback: Searching all extracted text for GDT '{gdt_symbol}' tolerance value...")
                
                text_candidates = []
                
                if gdt_box and len(gdt_box) >= 2:
                    gdt_center_x = sum([p[0] for p in gdt_box]) / len(gdt_box)
                    gdt_center_y = sum([p[1] for p in gdt_box]) / len(gdt_box)
                    
                    for text_item in text_results:
                        text_content = text_item.get('text', '') or text_item.get('content', '')
                        if not text_content:
                            continue
                        
                        text_box = text_item.get('box', [])
                        if text_box and len(text_box) >= 2:
                            text_center_x = sum([p[0] for p in text_box]) / len(text_box)
                            text_center_y = sum([p[1] for p in text_box]) / len(text_box)
                            distance = ((text_center_x - gdt_center_x) ** 2 + (text_center_y - gdt_center_y) ** 2) ** 0.5
                            text_candidates.append((distance, text_content.strip(), text_item))
                        else:
                            text_candidates.append((float('inf'), text_content.strip(), text_item))
                    
                    # Sort by distance (closest first)
                    text_candidates.sort(key=lambda x: x[0])
                
                # Search through candidates for tolerance values
                for distance, text_content, text_item in text_candidates:
                    # Look for small decimal numbers (common GDT tolerance format: 0.003, 0.005, etc.)
                    patterns = [
                        r'\b(0\.\d{2,4})\b',  # 0.003, 0.005, 0.025
                        r'\b(0\.0\d{1,3})\b',  # 0.003, 0.005
                        r'^(\d+\.?\d*)$',      # Simple number like "0.003"
                    ]
                    
                    for pattern in patterns:
                        number_match = re.search(pattern, text_content)
                        if number_match:
                            try:
                                extracted_value = float(number_match.group(1))
                                # GDT tolerances are typically small positive numbers (0.001 to 0.999)
                                if 0 < extracted_value < 1:
                                    tolerance_value = number_match.group(1)
                                    tolerance_text = text_content.strip()
                                    associated_text_item = text_item
                                    logger.info(f"✓ Fallback: Found tolerance '{tolerance_value}' in text '{text_content}' for GDT '{gdt_symbol}' (distance: {distance:.1f})")
                                    break
                            except ValueError:
                                pass
                    
                    if tolerance_value:
                        # Mark associated text as used by GDT
                        if associated_text_item:
                            text_content = associated_text_item.get('text', '') or associated_text_item.get('content', '')
                            if text_content:
                                gdt_associated_texts.add(text_content.strip())
                        break
            
            # Create dimension entry for GDT symbol
            nominal = tolerance_value if tolerance_value else gdt_symbol
            upper_tol = diameter_upper_tol if (is_diameter_gdt and diameter_nominal is not None) else ''
            lower_tol = diameter_lower_tol if (is_diameter_gdt and diameter_nominal is not None) else ''
            
            # Merge GDT symbol bbox with associated text bbox to include the tolerance value
            # This ensures the combined bbox covers both the symbol AND the nominal value
            combined_bbox = gdt_box
            if associated_text_item and gdt_box:
                text_box = associated_text_item.get('box', [])
                if text_box and len(text_box) >= 2 and len(gdt_box) >= 2:
                    # Get all x and y coordinates from both boxes
                    all_x_coords = [p[0] for p in gdt_box] + [p[0] for p in text_box]
                    all_y_coords = [p[1] for p in gdt_box] + [p[1] for p in text_box]
                    
                    # Calculate combined bounding box (min/max of both)
                    min_x = min(all_x_coords)
                    max_x = max(all_x_coords)
                    min_y = min(all_y_coords)
                    max_y = max(all_y_coords)
                    
                    # Create combined bbox in standard format: [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
                    combined_bbox = [
                        [min_x, min_y],  # top-left
                        [max_x, min_y],  # top-right
                        [max_x, max_y],  # bottom-right
                        [min_x, max_y]   # bottom-left
                    ]
                    logger.debug(f"Combined GDT bbox: symbol + text -> {combined_bbox}")
            
            dimension_type_for_gdt = "Diameter" if is_diameter_gdt else f"GDT-{gdt_symbol}"

            gdt_dimension = {
                'text': tolerance_text or gdt_symbol,
                'nominal_value': nominal,
                'upper_tolerance': upper_tol,
                'lower_tolerance': lower_tol,
                'dimension_type': dimension_type_for_gdt,
                'bbox': combined_bbox,
                'gdt_confidence': gdt_confidence,
                'gdt_class': gdt_item.get('class', 0)
            }
            gdt_dimension_results.append(gdt_dimension)
            logger.info(f"✓ Created GDT dimension: type={gdt_dimension['dimension_type']}, nominal={nominal}, tolerance={tolerance_value or 'N/A'}")
        
        # Deduplicate GDT dimensions: when multiple symbols refer to same callout,
        # keep only the one with highest detection confidence
        if len(gdt_dimension_results) > 1:
            deduped_gdt = []
            used = [False] * len(gdt_dimension_results)
            
            for i, dim_i in enumerate(gdt_dimension_results):
                if used[i]:
                    continue
                group_indices = [i]
                nom_i = str(dim_i.get('nominal_value', '')).strip()
                
                # Group all GDT dimensions that share the same nominal value
                for j in range(i + 1, len(gdt_dimension_results)):
                    if used[j]:
                        continue
                    dim_j = gdt_dimension_results[j]
                    nom_j = str(dim_j.get('nominal_value', '')).strip()
                    if nom_i != '' and nom_i == nom_j:
                        group_indices.append(j)
                        used[j] = True
                
                # From this group, keep the dimension with highest confidence
                best_idx = max(
                    group_indices,
                    key=lambda idx: float(gdt_dimension_results[idx].get('gdt_confidence', 0.0))
                )
                deduped_gdt.append(gdt_dimension_results[best_idx])
            
            if len(deduped_gdt) != len(gdt_dimension_results):
                logger.info(
                    f"Deduplicated GDT dimensions: {len(gdt_dimension_results)} -> {len(deduped_gdt)} "
                    f"(kept highest-confidence symbol per callout)"
                )
            gdt_dimension_results = deduped_gdt
        
        # Filter out text-based dimensions that are duplicates of GDT dimensions
        filtered_dimension_results = []
        gdt_nominal_values = {dim['nominal_value'] for dim in gdt_dimension_results if dim.get('nominal_value')}
        
        for dim in dimension_results:
            dim_nominal = dim.get('nominal_value', '')
            dim_text = dim.get('text', '')
            
            # Check if this dimension is associated with a GDT symbol
            is_gdt_associated = dim_text.strip() in gdt_associated_texts
            
            # Check if nominal value matches a GDT dimension
            is_duplicate = False
            if dim_nominal:
                # Exact match
                if dim_nominal in gdt_nominal_values:
                    is_duplicate = True
                else:
                    # Try numeric comparison
                    try:
                        dim_numeric = float(str(dim_nominal).replace(',', '.'))
                        for gdt_nominal in gdt_nominal_values:
                            try:
                                gdt_numeric = float(str(gdt_nominal).replace(',', '.'))
                                if abs(dim_numeric - gdt_numeric) < 0.0001:
                                    is_duplicate = True
                                    break
                            except (ValueError, TypeError):
                                pass
                    except (ValueError, TypeError):
                        pass
            
            # Exclude if it's associated with GDT or is a duplicate
            if is_gdt_associated or is_duplicate:
                logger.debug(f"Excluding text dimension '{dim_text}' (nominal: {dim_nominal}) - covered by GDT dimension")
                continue
            
            filtered_dimension_results.append(dim)
        
        logger.info(f"Filtered dimensions: {len(dimension_results)} -> {len(filtered_dimension_results)} (removed {len(dimension_results) - len(filtered_dimension_results)} duplicates)")
        
        # Combine filtered text-based dimensions and GDT-based dimensions
        # Prioritize GDT dimensions by putting them first
        all_dimension_results = gdt_dimension_results + filtered_dimension_results
        
        logger.info(f"✓ Total dimensions: {len(all_dimension_results)} ({len(filtered_dimension_results)} from text, {len(gdt_dimension_results)} from GDT)")

        all_dimension_results = [
            d
            for d in all_dimension_results
            if str(d.get("dimension_type", "")).strip().lower() != "material"
        ]

        # Find unused text items for note detection (exclude material/alloy lines)
        used_text_contents = set()
        for dim in all_dimension_results:
            if "text" in dim:
                used_text_contents.add(dim["text"].strip())

        unused_texts = []
        for text_item in text_results:
            text_content = (text_item.get("text", "") or text_item.get("content", "")).strip()
            if not text_content or text_content in used_text_contents:
                continue
            low = text_content.lower()
            if "material" in low or re.match(
                r"^(en[a-z0-9]+|ms|ss|gi|ci)\b", text_content, re.IGNORECASE
            ):
                continue
            unused_texts.append(
                {
                    "content": text_content,
                    "box": text_item.get("box", text_item.get("bbox", [])),
                }
            )

        note_detections = []
        for t in unused_texts:
            c = (t.get("content") or "").strip()
            if not c or len(c) < 2:
                continue
            low = c.lower()
            if re.search(
                r"(note|notes|general|unless|otherwise|ref|revision|rev\s|finish|roughness|surface|treat|heat|see\s+detail|typ\b|max\b|min\b)",
                low,
            ):
                note_detections.append({**t, "note_type": "keyword"})
            elif len(c) > 40 and len(c.split()) > 5:
                note_detections.append({**t, "note_type": "block"})

        for dim in all_dimension_results:
            dim["page"] = page_number + 1
            dim_bbox = dim.get("bbox")
            dim_region = _region_from_quad(dim_bbox) if isinstance(dim_bbox, list) else None
            if dim_region:
                zone_label = _detect_zone_label(
                    pdf_path=str(file_path),
                    page_number=page_number,
                    region=dim_region,
                    scale_factor=request.scale_factor,
                )
                if zone_label:
                    dim["zone"] = zone_label

        return {
            "success": True,
            "dimensions": all_dimension_results,
            "count": len(all_dimension_results),
            "text_dimensions": len(filtered_dimension_results),
            "gdt_dimensions": len(gdt_dimension_results),
            "material_dimensions": 0,
            "text_detections": text_results,
            "gdt_detections": gdt_results,
            "dimension_parsing": all_dimension_results,
            "notes": note_detections,
            "note_count": len(note_detections),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing dimensions: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing dimensions: {str(e)}")
    finally:
        if cleanup_pdf:
            try:
                cleanup_pdf()
            except Exception:
                pass


@router.post("/extract-zone")
async def extract_zone(request: ExtractTextRequest, db: Session = Depends(get_db)):
    """Extract border grid zone (e.g. C5) for a selected PDF region."""
    cleanup_pdf: Optional[Callable[[], None]] = None
    try:
        if not request.pdf_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="pdf_id is required for zone extraction")
        try:
            document_id = int(request.pdf_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="pdf_id must be a valid document ID (integer)")
        file_path, cleanup_pdf = get_pdf_path_from_document(document_id, db)
        page_number = request.bounding_box.page - 1
        region = {
            "x": request.bounding_box.x,
            "y": request.bounding_box.y,
            "width": request.bounding_box.width,
            "height": request.bounding_box.height,
        }
        zone = _detect_zone_label(str(file_path), page_number, region, request.scale_factor)
        return {"success": True, "zone": zone or "A1", "page": request.bounding_box.page}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extracting zone: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error extracting zone: {str(e)}")
    finally:
        if cleanup_pdf:
            try:
                cleanup_pdf()
            except Exception:
                pass


@router.post("/extract-zones-bulk")
async def extract_zones_bulk(request: ExtractZonesBulkRequest, db: Session = Depends(get_db)):
    """Extract border grid zones for multiple regions in one PDF pass."""
    cleanup_pdf: Optional[Callable[[], None]] = None
    try:
        if not request.pdf_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="pdf_id is required for zone extraction")
        try:
            document_id = int(request.pdf_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="pdf_id must be a valid document ID (integer)")
        file_path, cleanup_pdf = get_pdf_path_from_document(document_id, db)

        results = []
        for i, box in enumerate(request.bounding_boxes or []):
            page_number = box.page - 1
            region = {"x": box.x, "y": box.y, "width": box.width, "height": box.height}
            zone = _detect_zone_label(str(file_path), page_number, region, request.scale_factor) or "A1"
            results.append({"index": i, "zone": zone, "page": box.page})
        return {"success": True, "zones": results, "count": len(results)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extracting zones in bulk: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error extracting zones in bulk: {str(e)}")
    finally:
        if cleanup_pdf:
            try:
                cleanup_pdf()
            except Exception:
                pass


# --- Legacy balloon endpoints removed (CMF uses quality.master_boc). ---


@router.get("/info/{document_id}")
async def get_pdf_info(document_id: int, db: Session = Depends(get_db)):
    """Return page count and dimensions (width/height) for each page in the PDF."""
    cleanup_pdf = None
    try:
        file_path, cleanup_pdf = get_pdf_path_from_document(document_id, db)
        doc = fitz.open(str(file_path))
        pages = []
        for i in range(len(doc)):
            p = doc[i]
            pages.append({
                "page_number": i,
                "width": p.rect.width,
                "height": p.rect.height,
                "rotation": p.rotation
            })
        doc.close()
        return {"success": True, "pages": pages, "count": len(pages)}
    except Exception as e:
        logger.error(f"Error getting PDF info: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cleanup_pdf:
            cleanup_pdf()


@router.post("/render-page")
async def render_page(request: RenderPageRequest, db: Session = Depends(get_db)):
    """Render a specific PDF page region as a base64 image."""
    cleanup_pdf = None
    try:
        document_id = int(request.pdf_id)
        file_path, cleanup_pdf = get_pdf_path_from_document(document_id, db)
        doc = fitz.open(str(file_path))
        
        page_idx = request.page - 1
        if page_idx < 0 or page_idx >= len(doc):
            raise HTTPException(status_code=400, detail=f"Invalid page number {request.page}")
            
        page = doc[page_idx]
        
        # If no region specified, render the whole page
        if request.width <= 0 or request.height <= 0:
            mat = fitz.Matrix(request.scale, request.scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)
        else:
            # Render a specific region
            rect = fitz.Rect(request.x, request.y, request.x + request.width, request.y + request.height)
            mat = fitz.Matrix(request.scale, request.scale)
            pix = page.get_pixmap(matrix=mat, clip=rect, alpha=False)
            
        img_bytes = pix.tobytes("png")
        doc.close()
        
        if request.return_base64:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            return {"success": True, "image_base64": f"data:image/png;base64,{b64}"}
        else:
            # We could return a direct Response(content=img_bytes, media_type="image/png")
            # but the frontend InteractiveDrawing expects JSON with image_base64.
            pass
            
    except Exception as e:
        logger.error(f"Error rendering PDF page: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cleanup_pdf:
            cleanup_pdf()
