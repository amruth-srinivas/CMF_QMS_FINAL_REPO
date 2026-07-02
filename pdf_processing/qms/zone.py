
"""Zone detection module for engineering drawings.
This module identifies zones (A-F, 1-8) from drawing borders and determines
which zone a selected region belongs to."""

import fitz  # PyMuPDF
from typing import List, Dict, Tuple, Optional
from pathlib import Path
import logging
import re

logger = logging.getLogger(__name__)


class ZoneDetector:
    """Detect zones from engineering drawing borders and identify zone for regions."""
    
    # Valid zone labels
    VALID_LETTERS = ['A', 'B', 'C', 'D', 'E', 'F']
    VALID_NUMBERS = ['1', '2', '3', '4', '5', '6', '7', '8']
    
    @staticmethod
    def extract_zone_from_region(
        pdf_path: str,
        page_number: int,
        region: Dict[str, float],
        scale_factor: float = 1.0
    ) -> List[Dict]:
        """
        Extract zone information for a selected region.
        
        Args:
            pdf_path: Path to the PDF file
            page_number: Page number (0-indexed in PyMuPDF)
            region: Dictionary with keys 'x', 'y', 'width', 'height' in PDF coordinates
            scale_factor: Factor to scale coordinates (default 1.0)
        
        Returns:
            List of dictionaries with zone information
            Format: [{'zone': 'A1', 'confidence': 1.0, 'box': [[x1,y1], ...]}]
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
            
            # Get page dimensions
            page_rect = page.rect
            page_width = page_rect.width
            page_height = page_rect.height
            
            logger.debug(f"Page dimensions: {page_width} x {page_height}")
            logger.debug(f"Region: x={region['x']}, y={region['y']}, w={region['width']}, h={region['height']}")
            
            # Calculate region center
            region_center_x = region['x'] + region['width'] / 2
            region_center_y = region['y'] + region['height'] / 2
            
            # Determine if page is portrait or landscape
            is_portrait = page_height > page_width
            
            if is_portrait:
                # Portrait: 4x4 grid (D-A, 4-1)
                num_letters = 4  # D-A (top to bottom)
                num_numbers = 4  # 4-1 (left to right)
            else:
                # Landscape: 8x6 grid (F-A, 8-1)
                num_letters = 6  # F-A (top to bottom)
                num_numbers = 8  # 8-1 (left to right)
            
            # Calculate zone based on position
            # For letters: 0 = top (D/F), num_letters-1 = bottom (A)
            letter_idx = num_letters - 1 - min(int(region_center_y / page_height * num_letters), num_letters - 1)
            # For numbers: 0 = left (4/8), num_numbers-1 = right (1)
            number_idx = num_numbers - 1 - min(int(region_center_x / page_width * num_numbers), num_numbers - 1)
            
            # Convert to zone label
            # Letters go from 'A' (bottom) to 'D' or 'F' (top)
            zone_letter = chr(ord('A') + letter_idx)
            # Numbers are highest on left, decreasing to 1 on right
            zone_number = str(number_idx + 1)
            zone_label = f"{zone_letter}{zone_number}"
            
            logger.info(f"Identified zone: {zone_label} for region at ({region_center_x}, {region_center_y})")
            
            # Create result in same format as other extractors
            result = [{
                'zone': zone_label,
                'letter': zone_letter,
                'number': zone_number,
                'confidence': 1.0,  # Zone detection is deterministic
                'box': [[region['x'], region['y']],
                       [region['x'] + region['width'], region['y']],
                       [region['x'] + region['width'], region['y'] + region['height']],
                       [region['x'], region['y'] + region['height']]],
                'center': {'x': region_center_x, 'y': region_center_y}
            }]
            
            doc.close()
            return result
            
        except Exception as e:
            logger.error(f"Error extracting zone from region: {str(e)}", exc_info=True)
            return []
    
    @staticmethod
    def extract_all_zones_from_page(
        pdf_path: str,
        page_number: int,
        scale_factor: float = 1.0
    ) -> Dict[str, List[Dict]]:
        """
        Extract all zone labels from a page.
        Useful for debugging and visualization.
        
        Args:
            pdf_path: Path to the PDF file
            page_number: Page number (0-indexed)
            scale_factor: Factor to scale coordinates
        
        Returns:
            Dictionary with 'letters' and 'numbers' keys containing zone label positions
        """
        try:
            pdf_path = Path(pdf_path)
            if not pdf_path.exists():
                logger.error(f"PDF file not found: {pdf_path}")
                return {'letters': [], 'numbers': []}
            
            doc = fitz.open(str(pdf_path))
            
            if page_number < 0 or page_number >= len(doc):
                logger.error(f"Invalid page number: {page_number}")
                doc.close()
                return {'letters': [], 'numbers': []}
            
            page = doc[page_number]
            page_rect = page.rect
            page_width = page_rect.width
            page_height = page_rect.height
            
            all_text = page.get_text("dict")
            
            letter_zones = []
            number_zones = []
            margin_threshold = min(page_width, page_height) * 0.05
            
            for block in all_text.get("blocks", []):
                if "lines" not in block:
                    continue
                    
                for line in block["lines"]:
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        bbox = span.get("bbox", [])
                        
                        if not text or len(bbox) != 4:
                            continue
                        
                        x0, y0, x1, y1 = bbox
                        center_x = (x0 + x1) / 2
                        center_y = (y0 + y1) / 2
                        
                        text_upper = text.upper()
                        
                        if text_upper in ZoneDetector.VALID_LETTERS:
                            if x0 < margin_threshold or x1 > (page_width - margin_threshold):
                                letter_zones.append({
                                    'label': text_upper,
                                    'x': center_x,
                                    'y': center_y,
                                    'bbox': bbox
                                })
                        elif text in ZoneDetector.VALID_NUMBERS:
                            if y0 < margin_threshold or y1 > (page_height - margin_threshold):
                                number_zones.append({
                                    'label': text,
                                    'x': center_x,
                                    'y': center_y,
                                    'bbox': bbox
                                })
            
            doc.close()
            
            return {
                'letters': letter_zones,
                'numbers': number_zones
            }
            
        except Exception as e:
            logger.error(f"Error extracting all zones from page: {str(e)}", exc_info=True)
            return {'letters': [], 'numbers': []}