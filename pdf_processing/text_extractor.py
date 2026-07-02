"""
Text extraction module using PyMuPDF (fitz) to extract text from PDF regions.
This module implements the same logic as the PyQt5 application for text extraction.
"""
import fitz  # PyMuPDF
from typing import List, Dict, Tuple, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class TextExtractor:
    """Extract text from PDF files using PyMuPDF with region clipping support."""
    
    @staticmethod
    def extract_text_from_region(
        pdf_path: str,
        page_number: int,
        region: Dict[str, float],
        scale_factor: float = 2.0
    ) -> List[Dict]:
        """
        Extract text from a specific region of a PDF page.
        
        Args:
            pdf_path: Path to the PDF file
            page_number: Page number (0-indexed in PyMuPDF, so 0 = first page)
            region: Dictionary with keys 'x', 'y', 'width', 'height' in scene coordinates
            scale_factor: Factor to scale coordinates (default 2.0 to match PyQt5 logic)
        
        Returns:
            List of dictionaries with keys: 'text', 'box', 'confidence', 'rotation'
            Each 'box' is in format: [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
        """
        try:
            pdf_path = Path(pdf_path)
            if not pdf_path.exists():
                logger.error(f"PDF file not found: {pdf_path}")
                return []
            
            # Open PDF document
            doc = fitz.open(str(pdf_path))
            
            if page_number < 0 or page_number >= len(doc):
                logger.error(f"Invalid page number: {page_number}, PDF has {len(doc)} pages")
                doc.close()
                return []
            
            # Get the specified page
            page = doc[page_number]

            # Coordinates from frontend are already in PDF point space (scale_factor=1.0)
            # Only apply scale_factor if coordinates are in scene coordinates (for PyQt5 compatibility)
            if scale_factor != 1.0 and scale_factor > 0:
                # Convert scene coordinates to PDF coordinates
                x0 = region['x'] / scale_factor
                y0 = region['y'] / scale_factor
                x1 = (region['x'] + region['width']) / scale_factor
                y1 = (region['y'] + region['height']) / scale_factor
            else:
                # Coordinates are already in PDF point space
                x0 = region['x']
                y0 = region['y']
                x1 = region['x'] + region['width']
                y1 = region['y'] + region['height']

            # User selection boxes are often only ~10–15 pt tall; PyMuPDF clip misses spans
            # that extend slightly outside. Inflate + intersect with page.
            user_rect = fitz.Rect(x0, y0, x1, y1).normalize()
            rw = max(user_rect.width, 0.5)
            rh = max(user_rect.height, 0.5)
            pad_x = max(4.0, rw * 0.2)
            pad_y = max(8.0, rh * 0.5)
            clip_rect = fitz.Rect(
                max(0, user_rect.x0 - pad_x),
                max(0, user_rect.y0 - pad_y),
                min(page.rect.x1, user_rect.x1 + pad_x),
                min(page.rect.y1, user_rect.y1 + pad_y),
            )

            logger.debug(
                "Extracting text region user=%s padded=%s page=%s",
                user_rect,
                clip_rect,
                page_number,
            )

            def _append_span(span: dict, out: List[Dict]) -> None:
                text = span.get('text', '').strip()
                if not text:
                    return
                bbox = span.get('bbox', [])
                if not bbox or len(bbox) != 4:
                    return
                if scale_factor != 1.0 and scale_factor > 0:
                    scaled_bbox = [coord * scale_factor for coord in bbox]
                else:
                    scaled_bbox = bbox
                scene_box = [
                    [scaled_bbox[0], scaled_bbox[1]],
                    [scaled_bbox[2], scaled_bbox[1]],
                    [scaled_bbox[2], scaled_bbox[3]],
                    [scaled_bbox[0], scaled_bbox[3]],
                ]
                out.append({
                    'text': text,
                    'box': scene_box,
                    'confidence': 1.0,
                    'rotation': 0,
                })

            pdf_results: List[Dict] = []
            fitz_dict = page.get_text("dict", clip=clip_rect)
            for block in fitz_dict.get('blocks', []):
                if 'lines' not in block:
                    continue
                for line in block['lines']:
                    for span in line.get('spans', []):
                        _append_span(span, pdf_results)

            # If clip is empty (thin box, or PyMuPDF quirk), scan full page and keep spans
            # that intersect the user's original rectangle (not only the padded clip).
            if not pdf_results:
                for block in page.get_text("dict").get('blocks', []):
                    if 'lines' not in block:
                        continue
                    for line in block['lines']:
                        for span in line.get('spans', []):
                            bbox = span.get('bbox', [])
                            if not bbox or len(bbox) != 4:
                                continue
                            sr = fitz.Rect(bbox[0], bbox[1], bbox[2], bbox[3]).normalize()
                            if sr.intersects(user_rect):
                                _append_span(span, pdf_results)
                if pdf_results:
                    logger.info(
                        "Full-page text fallback: %s spans intersect user rect %s",
                        len(pdf_results),
                        user_rect,
                    )

            doc.close()
            logger.info(f"Extracted {len(pdf_results)} text detections from region")
            return pdf_results
            
        except Exception as e:
            logger.error(f"Error extracting text from region: {str(e)}", exc_info=True)
            return []
    
    @staticmethod
    def extract_text_from_page(
        pdf_path: str,
        page_number: int,
        scale_factor: float = 2.0
    ) -> List[Dict]:
        """
        Extract all text from a specific PDF page.
        
        Args:
            pdf_path: Path to the PDF file
            page_number: Page number (0-indexed)
            scale_factor: Factor to scale coordinates (default 2.0)
        
        Returns:
            List of dictionaries with text detections
        """
        try:
            pdf_path = Path(pdf_path)
            if not pdf_path.exists():
                logger.error(f"PDF file not found: {pdf_path}")
                return []
            
            doc = fitz.open(str(pdf_path))
            
            if page_number < 0 or page_number >= len(doc):
                logger.error(f"Invalid page number: {page_number}")
                doc.close()
                return []
            
            page = doc[page_number]
            
            # Extract text from entire page
            fitz_dict = page.get_text("dict")
            
            pdf_results = []
            
            # Process text blocks
            for block in fitz_dict.get('blocks', []):
                if 'lines' not in block:
                    continue
                
                for line in block['lines']:
                    for span in line.get('spans', []):
                        text = span.get('text', '').strip()
                        if not text:
                            continue
                        
                        bbox = span.get('bbox', [])
                        if not bbox or len(bbox) != 4:
                            continue
                        
                        # Scale coordinates
                        scaled_bbox = [coord * scale_factor for coord in bbox]
                        
                        scene_box = [
                            [scaled_bbox[0], scaled_bbox[1]],
                            [scaled_bbox[2], scaled_bbox[1]],
                            [scaled_bbox[2], scaled_bbox[3]],
                            [scaled_bbox[0], scaled_bbox[3]]
                        ]
                        
                        pdf_results.append({
                            'text': text,
                            'box': scene_box,
                            'confidence': 1.0,
                            'rotation': 0
                        })
            
            doc.close()
            logger.info(f"Extracted {len(pdf_results)} text detections from page {page_number}")
            return pdf_results
            
        except Exception as e:
            logger.error(f"Error extracting text from page: {str(e)}", exc_info=True)
            return []
    
    @staticmethod
    def extract_text_with_overlap_check(
        pdf_path: str,
        page_number: int,
        region: Dict[str, float],
        existing_boxes: List[List],
        iou_threshold: float = 0.3,
        scale_factor: float = 2.0
    ) -> List[Dict]:
        """
        Extract text from a region while checking for overlaps with existing boxes.
        
        Args:
            pdf_path: Path to the PDF file
            page_number: Page number (0-indexed)
            region: Dictionary with 'x', 'y', 'width', 'height'
            existing_boxes: List of existing bounding boxes to check against
            iou_threshold: IoU threshold for overlap detection (default 0.3)
            scale_factor: Factor to scale coordinates (default 2.0)
        
        Returns:
            List of text detections that don't overlap with existing boxes
        """
        try:
            # Extract all text from region
            all_results = TextExtractor.extract_text_from_region(
                pdf_path, page_number, region, scale_factor
            )
            
            if not existing_boxes:
                return all_results
            
            # Calculate IoU between each detection and existing boxes
            non_overlapping = []
            
            for result in all_results:
                result_box = result['box']
                is_overlapping = False
                
                for existing_box in existing_boxes:
                    iou = TextExtractor._calculate_iou(result_box, existing_box)
                    if iou > iou_threshold:
                        logger.debug(f"Skipping detection '{result['text']}' - overlaps with existing box (IoU: {iou})")
                        is_overlapping = True
                        break
                
                if not is_overlapping:
                    non_overlapping.append(result)
            
            logger.info(f"Filtered {len(non_overlapping)} non-overlapping detections from {len(all_results)} total")
            return non_overlapping
            
        except Exception as e:
            logger.error(f"Error in extract_text_with_overlap_check: {str(e)}", exc_info=True)
            return []
    
    @staticmethod
    def _calculate_iou(box1: List[List[float]], box2: List[List[float]]) -> float:
        """
        Calculate Intersection over Union (IoU) between two bounding boxes.
        
        Args:
            box1: First box in format [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
            box2: Second box in same format
        
        Returns:
            IoU value between 0 and 1
        """
        try:
            # Get bounds of box1
            x1_min = min(p[0] for p in box1)
            y1_min = min(p[1] for p in box1)
            x1_max = max(p[0] for p in box1)
            y1_max = max(p[1] for p in box1)
            
            # Get bounds of box2
            x2_min = min(p[0] for p in box2)
            y2_min = min(p[1] for p in box2)
            x2_max = max(p[0] for p in box2)
            y2_max = max(p[1] for p in box2)
            
            # Calculate intersection
            inter_x_min = max(x1_min, x2_min)
            inter_y_min = max(y1_min, y2_min)
            inter_x_max = min(x1_max, x2_max)
            inter_y_max = min(y1_max, y2_max)
            
            if inter_x_max <= inter_x_min or inter_y_max <= inter_y_min:
                return 0.0
            
            inter_area = (inter_x_max - inter_x_min) * (inter_y_max - inter_y_min)
            
            # Calculate areas
            area1 = (x1_max - x1_min) * (y1_max - y1_min)
            area2 = (x2_max - x2_min) * (y2_max - y2_min)
            
            # Calculate IoU
            union_area = area1 + area2 - inter_area
            return inter_area / union_area if union_area > 0 else 0.0
            
        except Exception as e:
            logger.error(f"Error calculating IoU: {str(e)}")
            return 0.0

