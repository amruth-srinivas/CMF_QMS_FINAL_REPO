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
            
            # Coordinates from frontend are already in PDF point space
            # Only apply scale_factor if coordinates are in scene coordinates (for PyQt5 compatibility)
            # For web app, coordinates are already normalized to PDF dimensions
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
            
            # Create clipping rectangle in PDF coordinates
            clip_rect = fitz.Rect(x0, y0, x1, y1)
            
            logger.debug(f"Extracting text from region: {clip_rect} on page {page_number}")
            
            # Extract text using dictionary format with clipping
            fitz_dict = page.get_text("dict", clip=clip_rect)
            
            pdf_results = []
            
            # Process text blocks
            for block in fitz_dict.get('blocks', []):
                if 'lines' not in block:
                    continue
                
                for line in block['lines']:
                    for span in line.get('spans', []):
                        text = span.get('text', '').strip()
                        if not text:  # Skip empty text
                            continue
                        
                        # Get bounding box from span
                        bbox = span.get('bbox', [])
                        if not bbox or len(bbox) != 4:
                            continue
                        
                        # Scale coordinates back to scene coordinates (only if scale_factor was applied)
                        if scale_factor != 1.0 and scale_factor > 0:
                            scaled_bbox = [coord * scale_factor for coord in bbox]
                        else:
                            # Coordinates are already in PDF point space, use as is
                            scaled_bbox = bbox
                        
                        # Convert to standard format: [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
                        scene_box = [
                            [scaled_bbox[0], scaled_bbox[1]],  # top-left
                            [scaled_bbox[2], scaled_bbox[1]],  # top-right
                            [scaled_bbox[2], scaled_bbox[3]],  # bottom-right
                            [scaled_bbox[0], scaled_bbox[3]]   # bottom-left
                        ]
                        
                        pdf_results.append({
                            'text': text,
                            'box': scene_box,
                            'confidence': 1.0,  # PyMuPDF doesn't provide confidence scores
                            'rotation': 0
                        })
            
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

