"""
Text extraction module using EasyOCR to extract text from PDF regions.

This module implements OCR-based text extraction for scanned PDFs.
Backend2 standalone copy - no dependency on backend package.
"""
import easyocr
import cv2
import numpy as np
import fitz  # PyMuPDF
from typing import List, Dict, Tuple, Optional
from pathlib import Path
import logging
import tempfile
import os

logger = logging.getLogger(__name__)

# Higher DPI for scanned engineering drawings (small text); 200 was often too low
DPI_OCR = 300

class TextExtractor:
    """Extract text from PDF files using EasyOCR with region clipping and multiple orientations support."""
    
    def __init__(self, languages: List[str] = ['en'], gpu: bool = False):
        """
        Initialize EasyOCR reader.
        
        Args:
            languages: List of languages for OCR (default: ['en'])
            gpu: Whether to use GPU (default: False)
        """
        self.languages = languages
        self.gpu = gpu
        self.reader = easyocr.Reader(languages, gpu=gpu)
        logger.info(f"EasyOCR reader initialized with languages: {languages}, GPU: {gpu}")
    
    @staticmethod
    def rotate_image(image: np.ndarray, angle: float) -> np.ndarray:
        """
        Rotate an image by the specified angle.
        
        Args:
            image: Input image as numpy array
            angle: Rotation angle in degrees
        
        Returns:
            Rotated image
        """
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(image, M, (w, h))
        return rotated
    
    @staticmethod
    def enhance_image(image: np.ndarray) -> np.ndarray:
        """
        Enhance the contrast and sharpness of the image.
        
        Args:
            image: Input image as numpy array
        
        Returns:
            Enhanced image
        """
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray_image = image
        
        # Increase contrast using CLAHE
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced_image = clahe.apply(gray_image)
        
        # Sharpen the image using Gaussian Blur and Unsharp Masking
        gaussian_blur = cv2.GaussianBlur(enhanced_image, (5, 5), 0)
        sharpened_image = cv2.addWeighted(enhanced_image, 1.5, gaussian_blur, -0.5, 0)
        
        return sharpened_image
    
    def pdf_page_to_image(self, pdf_path: str, page_number: int, dpi: int = None) -> Optional[np.ndarray]:
        """
        Convert PDF page to image.
        
        Args:
            pdf_path: Path to PDF file
            page_number: Page number (0-indexed)
            dpi: Resolution for rendering (default: DPI_OCR, 300 for better small text)
        
        Returns:
            Image as numpy array or None if conversion fails
        """
        if dpi is None:
            dpi = DPI_OCR
        try:
            doc = fitz.open(pdf_path)
            if page_number < 0 or page_number >= len(doc):
                logger.error(f"Invalid page number: {page_number}")
                doc.close()
                return None
            
            page = doc[page_number]
            mat = fitz.Matrix(dpi / 72, dpi / 72)  # Convert from points to pixels
            pix = page.get_pixmap(matrix=mat)
            
            # Convert to numpy array
            img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            
            # Convert RGB to BGR for OpenCV
            if pix.n == 3:  # RGB
                img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
            elif pix.n == 4:  # RGBA
                img_array = cv2.cvtColor(img_array, cv2.COLOR_RGBA2BGR)
            
            doc.close()
            return img_array
            
        except Exception as e:
            logger.error(f"Error converting PDF page to image: {str(e)}")
            return None
    
    def extract_text_from_region(
        self,
        pdf_path: str,
        page_number: int,
        region: Dict[str, float],
        scale_factor: float = 2.0,
        confidence_threshold: float = 0.5,
        rotation_angles: List[int] = None
    ) -> List[Dict]:
        """
        Extract text from a specific region of a PDF page using OCR.
        
        Args:
            pdf_path: Path to the PDF file
            page_number: Page number (0-indexed)
            region: Dictionary with keys 'x', 'y', 'width', 'height' in scene coordinates
            scale_factor: Factor to scale coordinates (default 2.0)
            confidence_threshold: Minimum confidence for text detection (default: 0.5 for engineering text)
            rotation_angles: List of rotation angles to try (default: [0, 90, 180, 270])
        
        Returns:
            List of dictionaries with keys: 'text', 'box', 'confidence', 'rotation'
        """
        if rotation_angles is None:
            rotation_angles = [0, 90, 180, 270]
        
        try:
            # Convert PDF page to image at higher DPI for small text
            full_image = self.pdf_page_to_image(pdf_path, page_number)
            if full_image is None:
                logger.error("Failed to convert PDF page to image")
                return []
            
            img_height, img_width = full_image.shape[:2]
            dpi = DPI_OCR
            points_to_pixels = dpi / 72
            
            # Region in image pixels
            x0 = (region['x'] / scale_factor) * points_to_pixels
            y0 = (region['y'] / scale_factor) * points_to_pixels
            x1 = ((region['x'] + region['width']) / scale_factor) * points_to_pixels
            y1 = ((region['y'] + region['height']) / scale_factor) * points_to_pixels
            
            # Small padding so we don't clip character edges (helps small regions)
            pad = 5
            x0 = max(0, x0 - pad)
            y0 = max(0, y0 - pad)
            x1 = min(img_width, x1 + pad)
            y1 = min(img_height, y1 + pad)
            
            x0, x1 = int(x0), int(x1)
            y0, y1 = int(y0), int(y1)
            if x1 <= x0 or y1 <= y0:
                logger.warning("Region has no area after clamp")
                return []
            
            region_image = full_image[y0:y1, x0:x1]
            orig_region_h, orig_region_w = region_image.shape[0], region_image.shape[1]
            upscale = 1.0
            
            # Upscale small regions so EasyOCR can read dense engineering text
            min_side = min(region_image.shape[0], region_image.shape[1])
            if min_side < 80:
                upscale = 2.0
                new_w = max(1, int(region_image.shape[1] * upscale))
                new_h = max(1, int(region_image.shape[0] * upscale))
                region_image = cv2.resize(region_image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            
            if region_image.size == 0:
                logger.warning("Region image is empty")
                return []
            
            # Perform OCR on region with multiple orientations
            # Stop after first rotation that finds detections to avoid duplicates
            all_detections = []
            
            for angle in rotation_angles:
                # Rotate image
                rotated_image = self.rotate_image(region_image, angle)
                
                # Enhance image
                enhanced_image = self.enhance_image(rotated_image)
                
                # Perform OCR
                results = self.reader.readtext(enhanced_image)
                
                # Process results
                rotation_detections = []
                for (box, text, confidence) in results:
                    if confidence >= confidence_threshold:
                        # If we upscaled, box is in upscaled region space; scale back to crop space
                        if upscale != 1.0:
                            box = [[p[0] / upscale, p[1] / upscale] for p in box]
                        region_shape = (orig_region_h, orig_region_w)
                        global_box = self._convert_box_to_global_coordinates(
                            box, x0, y0, angle, region_shape
                        )
                        pdf_box = self._convert_image_to_pdf_coordinates(
                            global_box, scale_factor, dpi
                        )
                        
                        rotation_detections.append({
                            'text': text.strip(),
                            'box': pdf_box,
                            'confidence': float(confidence),
                            'rotation': angle
                        })
                
                # If we found detections in this rotation, use them and stop
                if rotation_detections:
                    all_detections = rotation_detections
                    logger.info(f"Extracted {len(all_detections)} text detections from region using OCR at rotation {angle}°")
                    break
            
            if not all_detections:
                logger.info("No text detections found in any rotation")
            return all_detections
            
        except Exception as e:
            logger.error(f"Error extracting text from region using OCR: {str(e)}", exc_info=True)
            return []
    
    def _convert_box_to_global_coordinates(
        self, 
        box: List[List[float]], 
        region_x: float, 
        region_y: float, 
        angle: int,
        region_shape: Tuple[int, int]
    ) -> List[List[float]]:
        """
        Convert bounding box coordinates from region space to global image space.
        """
        region_height, region_width = region_shape[:2]
        
        if angle != 0:
            center = (region_width // 2, region_height // 2)
            M = cv2.getRotationMatrix2D(center, -angle, 1.0)
            global_box = []
            for point in box:
                point_homo = np.array([point[0], point[1], 1])
                rotated_point = M @ point_homo
                global_point = [rotated_point[0] + region_x, rotated_point[1] + region_y]
                global_box.append(global_point)
        else:
            global_box = [[point[0] + region_x, point[1] + region_y] for point in box]
        
        return global_box
    
    def _convert_image_to_pdf_coordinates(
        self, 
        box: List[List[float]], 
        scale_factor: float,
        dpi: int = 200
    ) -> List[List[float]]:
        """Convert bounding box from image coordinates to PDF coordinates."""
        pixels_to_points = 72 / dpi
        pdf_box = []
        for point in box:
            pdf_x = point[0] * pixels_to_points * scale_factor
            pdf_y = point[1] * pixels_to_points * scale_factor
            pdf_box.append([pdf_x, pdf_y])
        return pdf_box
    
    def extract_text_with_overlap_check(
        self,
        pdf_path: str,
        page_number: int,
        region: Dict[str, float],
        existing_boxes: List[List],
        iou_threshold: float = 0.3,
        scale_factor: float = 2.0,
        confidence_threshold: float = 0.7,
        rotation_angles: List[int] = None
    ) -> List[Dict]:
        """
        Extract text from a region using OCR while checking for overlaps with existing boxes.
        """
        try:
            all_results = self.extract_text_from_region(
                pdf_path, page_number, region, scale_factor, 
                confidence_threshold, rotation_angles
            )
            
            if not existing_boxes:
                return all_results
            
            non_overlapping = []
            for result in all_results:
                result_box = result['box']
                is_overlapping = False
                for existing_box in existing_boxes:
                    iou = self._calculate_iou(result_box, existing_box)
                    if iou > iou_threshold:
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
        """Calculate Intersection over Union (IoU) between two bounding boxes."""
        try:
            x1_min = min(p[0] for p in box1)
            y1_min = min(p[1] for p in box1)
            x1_max = max(p[0] for p in box1)
            y1_max = max(p[1] for p in box1)
            x2_min = min(p[0] for p in box2)
            y2_min = min(p[1] for p in box2)
            x2_max = max(p[0] for p in box2)
            y2_max = max(p[1] for p in box2)
            inter_x_min = max(x1_min, x2_min)
            inter_y_min = max(y1_min, y2_min)
            inter_x_max = min(x1_max, x2_max)
            inter_y_max = min(y1_max, y2_max)
            if inter_x_max <= inter_x_min or inter_y_max <= inter_y_min:
                return 0.0
            inter_area = (inter_x_max - inter_x_min) * (inter_y_max - inter_y_min)
            area1 = (x1_max - x1_min) * (y1_max - y1_min)
            area2 = (x2_max - x2_min) * (y2_max - y2_min)
            union_area = area1 + area2 - inter_area
            return inter_area / union_area if union_area > 0 else 0.0
        except Exception as e:
            logger.error(f"Error calculating IoU: {str(e)}")
            return 0.0
