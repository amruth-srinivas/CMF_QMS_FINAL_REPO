"""
GDT (Geometric Dimensioning and Tolerancing) symbol detection using YOLO.
This module implements YOLO-based GDT symbol detection similar to the PyQt5 application.
"""
import cv2
import numpy as np
from typing import List, Dict, Optional
from pathlib import Path
import logging
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    logger.warning("YOLO (ultralytics) not available. GDT detection will not work.")


class GDTDetector:
    """Detect GDT symbols using YOLO model."""
    
    def __init__(self, model_path: str = 'best2.pt'):
        """
        Initialize GDT detector with YOLO model.
        
        Args:
            model_path: Path to YOLO model file (.pt)
        """
        self.model = None
        self.model_path = model_path
        
        if not YOLO_AVAILABLE:
            logger.error("YOLO library not available. Install with: pip install ultralytics")
            return
            
        try:
            model_file = Path(model_path)
            if model_file.exists():
                self.model = YOLO(str(model_file))
                logger.info(f"YOLO model loaded from {model_path}")
                logger.info(f"Model classes: {self.model.names}")
            else:
                logger.warning(f"YOLO model file not found: {model_path}. GDT detection will not work.")
        except Exception as e:
            logger.error(f"Error loading YOLO model: {str(e)}")
    
    def detect_gdt_symbols_from_pdf_region(
        self,
        pdf_path: str,
        page_number: int,
        region: Dict[str, float],
        confidence_threshold: float = 0.5,
        scale_factor: float = 1.0
    ) -> List[Dict]:
        """
        Detect GDT symbols from a specific region of a PDF page.
        
        Args:
            pdf_path: Path to the PDF file
            page_number: Page number (0-indexed)
            region: Dictionary with keys 'x', 'y', 'width', 'height' in PDF coordinates
            confidence_threshold: Minimum confidence for detections (default 0.5)
            scale_factor: Factor to scale coordinates (default 1.0 for PDF coordinates)
        
        Returns:
            List of dictionaries with keys: 'box', 'confidence', 'class', 'class_name'
        """
        if not self.model:
            logger.warning("YOLO model not loaded. Cannot detect GDT symbols.")
            return []
        
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
            
            # Convert region coordinates to PDF coordinates
            x0 = region['x']
            y0 = region['y']
            x1 = region['x'] + region['width']
            y1 = region['y'] + region['height']
            
            # Expand region upward to catch diameter symbols above the text
            # Diameter symbols (Ø) are typically placed above the dimension text
            expanded_height = region['height'] * 1.5  # Increase height by 50%
            y0_expanded = y0 - (region['height'] * 0.3)  # Move up by 30% of original height
            y0 = max(0, y0_expanded)  # Ensure we don't go above page boundary
            y1 = y0 + expanded_height
            
            # Create clipping rectangle in PDF coordinates
            clip_rect = fitz.Rect(x0, y0, x1, y1)
            
            # Render the PDF region as an image
            mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better quality
            pix = page.get_pixmap(matrix=mat, clip=clip_rect)
            
            # Convert PyMuPDF pixmap to numpy array
            # pix.samples is a bytes object containing RGB pixels
            img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            
            # Convert RGB to BGR for OpenCV
            if pix.n == 4:  # RGBA
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
            elif pix.n == 3:  # RGB
                img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
            elif pix.n == 1:  # Grayscale
                img_np = cv2.cvtColor(img_np, cv2.COLOR_GRAY2BGR)
            
            if img_np is None or img_np.size == 0:
                logger.error("Failed to convert PDF image to numpy array")
                doc.close()
                return []
            
            logger.debug(f"Running YOLO detection on image shape: {img_np.shape}")
            logger.debug(f"Image dtype: {img_np.dtype}, min/max values: {img_np.min()}/{img_np.max()}")
            logger.debug(f"Region: x={x0}, y={y0}, w={x1-x0}, h={y1-y0}")
            
            # Save debug image
            debug_dir = Path("debug_images")
            debug_dir.mkdir(exist_ok=True)
            debug_path = debug_dir / f"gdt_debug_page{page_number}_{x0}_{y0}.png"
            cv2.imwrite(str(debug_path), img_np)
            logger.info(f"Debug image saved to: {debug_path}")
            
            # Run YOLO detection
            results = self.model(img_np, verbose=True)  # Enable verbose output to see model details
            
            gdt_results = []
            
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    conf = box.conf.item()
                    if conf >= confidence_threshold:
                        # Get coordinates in image space and convert to Python floats
                        x1_img, y1_img, x2_img, y2_img = box.xyxy[0].cpu().numpy()
                        x1_img, y1_img, x2_img, y2_img = float(x1_img), float(y1_img), float(x2_img), float(y2_img)
                        
                        # Convert from image coordinates back to PDF coordinates
                        # Account for the 2x zoom factor and clip rect offset
                        scale_back = 1.0 / 2.0  # Reverse the 2x zoom
                        x1_pdf = float(x0) + (x1_img * scale_back)
                        y1_pdf = float(y0) + (y1_img * scale_back)
                        x2_pdf = float(x0) + (x2_img * scale_back)
                        y2_pdf = float(y0) + (y2_img * scale_back)
                        
                        # Convert to standard format: [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
                        pdf_box = [
                            [x1_pdf, y1_pdf],
                            [x2_pdf, y1_pdf],
                            [x2_pdf, y2_pdf],
                            [x1_pdf, y2_pdf]
                        ]
                        
                        class_id = int(box.cls)
                        class_name = result.names[class_id]
                        
                        # Convert all numpy types to Python native types for JSON serialization
                        gdt_results.append({
                            'box': [[float(p[0]), float(p[1])] for p in pdf_box],  # Convert numpy to float
                            'confidence': float(conf),  # Convert numpy.float32 to float
                            'class': int(class_id),  # Ensure int
                            'class_name': str(class_name)  # Ensure string
                        })
                        
                        logger.debug(f"Detected GDT symbol: {class_name} (confidence: {conf:.2f})")
            
            doc.close()
            logger.info(f"Detected {len(gdt_results)} GDT symbols in region")
            return gdt_results
            
        except Exception as e:
            logger.error(f"Error detecting GDT symbols: {str(e)}", exc_info=True)
            return []
    
    def detect_gdt_symbols_from_image(
        self,
        image: np.ndarray,
        region: Optional[Dict[str, float]] = None,
        confidence_threshold: float = 0.5
    ) -> List[Dict]:
        """
        Detect GDT symbols from a numpy image array.
        
        Args:
            image: NumPy array image (BGR format)
            region: Optional region dict with 'x', 'y', 'width', 'height' to crop image
            confidence_threshold: Minimum confidence for detections
        
        Returns:
            List of detection dictionaries
        """
        if not self.model:
            logger.warning("YOLO model not loaded. Cannot detect GDT symbols.")
            return []
        
        try:
            # Crop image if region specified
            if region:
                x = int(region['x'])
                y = int(region['y'])
                w = int(region['width'])
                h = int(region['height'])
                img_crop = image[y:y+h, x:x+w]
            else:
                img_crop = image
            
            if img_crop.size == 0:
                logger.warning("Empty image region")
                return []
            
            # Run YOLO detection
            results = self.model(img_crop)
            
            gdt_results = []
            
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    conf = box.conf.item()
                    if conf >= confidence_threshold:
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        # Convert numpy types to Python floats
                        x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
                        
                        # Adjust coordinates if region was cropped
                        if region:
                            x1 += float(region['x'])
                            y1 += float(region['y'])
                            x2 += float(region['x'])
                            y2 += float(region['y'])
                        
                        # Convert to standard format
                        det_box = [
                            [x1, y1],
                            [x2, y1],
                            [x2, y2],
                            [x1, y2]
                        ]
                        
                        class_id = int(box.cls)
                        class_name = result.names[class_id]
                        
                        # Convert all numpy types to Python native types for JSON serialization
                        gdt_results.append({
                            'box': [[float(p[0]), float(p[1])] for p in det_box],  # Convert numpy to float
                            'confidence': float(conf),  # Convert numpy.float32 to float
                            'class': int(class_id),  # Ensure int
                            'class_name': str(class_name)  # Ensure string
                        })
            
            logger.info(f"Detected {len(gdt_results)} GDT symbols")
            return gdt_results
            
        except Exception as e:
            logger.error(f"Error detecting GDT symbols from image: {str(e)}", exc_info=True)
            return []


# Global detector instance
_gdt_detector = None


def get_gdt_detector(model_path: str = 'best2.pt') -> GDTDetector:
    """Get or create the global GDT detector instance."""
    global _gdt_detector
    if _gdt_detector is None:
        _gdt_detector = GDTDetector(model_path)
    return _gdt_detector

