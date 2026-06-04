# """
# View extraction module for PDF regions.
# This module extracts a specific region from a PDF page and returns it as an image
# for viewing purposes.
# """
# import fitz  # PyMuPDF
# from typing import Dict, Optional, Tuple
# from pathlib import Path
# import logging
# import io
# import base64
# from PIL import Image
# import numpy as np

# logger = logging.getLogger(__name__)


# class ViewExtractor:
#     """Extract and convert PDF regions to viewable images."""
    
#     @staticmethod
#     def detect_text_orientation(image: Image.Image) -> int:
#         """
#         Detect the orientation of text in the image and return the required rotation angle.
#         Returns the rotation angle needed to make text horizontal and easily readable.
#         Tests 0°, 90°, 180°, and 270° rotations to find the best orientation.
#         Prefers 0° (no rotation) when scores are similar to avoid unnecessary rotations.
#         """
#         try:
#             # Convert to grayscale for analysis
#             gray = image.convert('L')
#             img_array = np.array(gray)
            
#             # Get image dimensions
#             height, width = img_array.shape
            
#             # Test different rotation angles: 0, 90, 180, 270
#             best_angle = 0
#             best_score = -1
#             scores = {}
            
#             for angle in [0, 90, 180, 270]:
#                 # Rotate the image array for testing
#                 if angle == 0:
#                     test_array = img_array
#                 elif angle == 90:
#                     test_array = np.rot90(img_array, k=1)
#                 elif angle == 180:
#                     test_array = np.rot90(img_array, k=2)
#                 else:  # 270
#                     test_array = np.rot90(img_array, k=3)
                
#                 # Calculate horizontal and vertical projections
#                 horizontal_projection = np.sum(test_array < 128, axis=1)  # Dark pixels per row
#                 vertical_projection = np.sum(test_array < 128, axis=0)    # Dark pixels per column
                
#                 # Calculate variance of projections to determine dominant direction
#                 horizontal_variance = np.var(horizontal_projection)
#                 vertical_variance = np.var(vertical_projection)
                
#                 # For readable text, we expect more variation horizontally (lines of text)
#                 # Score based on horizontal variance relative to vertical variance
#                 if vertical_variance > 0:
#                     score = horizontal_variance / vertical_variance
#                 else:
#                     score = horizontal_variance
                
#                 # Prefer orientations where horizontal variance is higher (text is horizontal)
#                 # Also consider the aspect ratio - wider images with high horizontal variance are better
#                 test_height, test_width = test_array.shape
#                 aspect_ratio = test_width / test_height if test_height > 0 else 1
                
#                 # Boost score for wider images with high horizontal variance (typical for horizontal text)
#                 if aspect_ratio > 1.0 and score > 1.0:
#                     score *= 1.2
                
#                 # Penalize 180° rotation - prefer 0° if scores are close (within 10%)
#                 # This prevents unnecessary upside-down rotations
#                 if angle == 180:
#                     score *= 0.9  # 10% penalty for 180° rotation
#                 elif angle == 0:
#                     score *= 1.1  # 10% bonus for no rotation
                
#                 scores[angle] = score
                
#                 if score > best_score:
#                     best_score = score
#                     best_angle = angle
            
#             # Additional check: if 0° and 180° have very similar scores, prefer 0°
#             # This prevents unnecessary upside-down rotations when the image is already upright
#             if 0 in scores and 180 in scores:
#                 score_0 = scores[0]
#                 score_180 = scores[180]
#                 # If scores are within 15% of each other, prefer 0° (no rotation)
#                 # This ensures we don't rotate when the image is already straight
#                 if abs(score_0 - score_180) / max(score_0, score_180, 1) < 0.15:
#                     best_angle = 0
#                     best_score = score_0
#                     logger.debug(f"Scores too close (0°: {score_0:.2f}, 180°: {score_180:.2f}), preferring 0° (no rotation)")
            
#             logger.debug(f"Detected best orientation: {best_angle}° (score: {best_score:.2f})")
#             return best_angle
                
#         except Exception as e:
#             logger.warning(f"Error in orientation detection: {str(e)}, using default orientation")
#             return 0
    
#     @staticmethod
#     def auto_rotate_for_readability(image: Image.Image) -> Image.Image:
#         """
#         Automatically rotate image to make text horizontal and easily readable.
#         Handles 0°, 90°, 180°, and 270° rotations.
#         """
#         try:
#             # First, try to detect orientation
#             rotation_angle = ViewExtractor.detect_text_orientation(image)
            
#             if rotation_angle != 0:
#                 logger.info(f"Auto-rotating image by {rotation_angle} degrees for better readability")
#                 # Rotate with white background and high-quality resampling
#                 # PIL's rotate() rotates counter-clockwise
#                 # Our detection tests rotations: 0° (k=0), 90° CCW (k=1), 180° CCW (k=2), 270° CCW (k=3)
#                 # If detection returns 90°, it means rotating the array 90° CCW looks best
#                 # So we need to rotate the original image 90° CCW = rotate(90)
#                 # If detection returns 180°, we need to rotate 180° CCW = rotate(180)
#                 # If detection returns 270°, we need to rotate 270° CCW = rotate(270)
#                 # So we can use the angle directly
#                 image = image.rotate(
#                     rotation_angle, 
#                     expand=True, 
#                     resample=Image.BICUBIC, 
#                     fillcolor=(255, 255, 255)
#                 )
            
#             return image
            
#         except Exception as e:
#             logger.warning(f"Error in auto-rotation: {str(e)}, returning original image")
#             return image
    
#     @staticmethod
#     def extract_region_as_image(
#         pdf_path: str,
#         page_number: int,
#         region: Dict[str, float],
#         zoom_factor: float = 2.0,
#         scale_factor: float = 1.0,
#         auto_rotate: bool = True
#     ) -> Optional[bytes]:
#         """
#         Extract a region from a PDF page and convert it to an image.
        
#         Args:
#             pdf_path: Path to the PDF file
#             page_number: Page number (0-indexed in PyMuPDF)
#             region: Dictionary with keys 'x', 'y', 'width', 'height' in PDF coordinates
#             zoom_factor: Factor to zoom the region (default 2.0 for better quality)
#             scale_factor: Factor to scale coordinates (default 1.0)
#             auto_rotate: Whether to automatically rotate for readability (default True)
        
#         Returns:
#             PNG image bytes, or None if extraction fails
#         """
#         try:
#             pdf_path = Path(pdf_path)
#             if not pdf_path.exists():
#                 logger.error(f"PDF file not found: {pdf_path}")
#                 return None
            
#             # Open PDF document
#             doc = fitz.open(str(pdf_path))
            
#             if page_number < 0 or page_number >= len(doc):
#                 logger.error(f"Invalid page number: {page_number}, PDF has {len(doc)} pages")
#                 doc.close()
#                 return None
            
#             # Get the specified page
#             page = doc[page_number]
            
#             # Get page dimensions
#             page_rect = page.rect
#             page_width = page_rect.width
#             page_height = page_rect.height
            
#             logger.debug(f"Page dimensions: {page_width} x {page_height}")
#             logger.debug(f"Region: x={region['x']}, y={region['y']}, w={region['width']}, h={region['height']}")
            
#             # Coordinates from frontend are already in PDF point space
#             if scale_factor != 1.0 and scale_factor > 0:
#                 # Convert scene coordinates to PDF coordinates
#                 x0 = region['x'] / scale_factor
#                 y0 = region['y'] / scale_factor
#                 x1 = (region['x'] + region['width']) / scale_factor
#                 y1 = (region['y'] + region['height']) / scale_factor
#             else:
#                 # Coordinates are already in PDF point space
#                 x0 = region['x']
#                 y0 = region['y']
#                 x1 = region['x'] + region['width']
#                 y1 = region['y'] + region['height']
            
#             # Ensure coordinates are within page bounds
#             x0 = max(0, min(x0, page_width))
#             y0 = max(0, min(y0, page_height))
#             x1 = max(x0, min(x1, page_width))
#             y1 = max(y0, min(y1, page_height))
            
#             # Create clipping rectangle in PDF coordinates
#             clip_rect = fitz.Rect(x0, y0, x1, y1)
            
#             logger.debug(f"Extracting region as image: {clip_rect}")
            
#             # Calculate matrix for rendering with zoom
#             # The matrix transforms from PDF coordinates to image pixels
#             # zoom_factor determines the resolution (e.g., 2.0 = 2x resolution)
#             mat = fitz.Matrix(zoom_factor, zoom_factor)
            
#             # Render the clipped region to a pixmap (image)
#             pix = page.get_pixmap(matrix=mat, clip=clip_rect)
            
#             # Convert pixmap to PNG bytes first
#             img_bytes = pix.tobytes("png")
            
#             doc.close()
            
#             # Load image with PIL to crop white space and apply rotation
#             try:
#                 image = Image.open(io.BytesIO(img_bytes))
                
#                 # Convert to RGB if needed (in case of RGBA or other formats)
#                 if image.mode != 'RGB':
#                     # Create a white background
#                     rgb_image = Image.new('RGB', image.size, (255, 255, 255))
#                     if image.mode == 'RGBA':
#                         # Paste with alpha channel handling
#                         rgb_image.paste(image, mask=image.split()[3] if len(image.split()) > 3 else None)
#                     else:
#                         rgb_image.paste(image)
#                     image = rgb_image
                
#                 # Get bounding box of non-white content using aggressive threshold approach
#                 # Convert to grayscale for better white space detection
#                 # This finds pixels that are not "close to white" 
#                 # Using a high threshold (252) to be very aggressive in removing white space
#                 width, height = image.size
#                 pixels = image.load()
                
#                 # Convert to grayscale for brightness-based detection
#                 gray_image = image.convert('L')
#                 gray_pixels = gray_image.load()
                
#                 # Find the bounding box of non-white content
#                 min_x = width
#                 min_y = height
#                 max_x = 0
#                 max_y = 0
                
#                 # Very aggressive white threshold - pixels brighter than this are considered white
#                 # Using both RGB and grayscale checks for maximum accuracy
#                 # Lower threshold (250) to catch more edge cases and ensure tight cropping
#                 white_threshold_rgb = 250  # High threshold for RGB channels
#                 white_threshold_gray = 250  # Brightness threshold
#                 found_content = False
                
#                 # Scan through all pixels to find content boundaries
#                 for y in range(height):
#                     for x in range(width):
#                         r, g, b = pixels[x, y]
#                         gray_value = gray_pixels[x, y]
                        
#                         # Pixel is considered content if:
#                         # 1. Any RGB channel is below threshold, OR
#                         # 2. Grayscale brightness is below threshold
#                         # This ensures we catch all non-white pixels
#                         is_content = (
#                             r < white_threshold_rgb or 
#                             g < white_threshold_rgb or 
#                             b < white_threshold_rgb or
#                             gray_value < white_threshold_gray
#                         )
                        
#                         if is_content:
#                             found_content = True
#                             min_x = min(min_x, x)
#                             min_y = min(min_y, y)
#                             max_x = max(max_x, x)
#                             max_y = max(max_y, y)
                
#                 if found_content:
#                     # No padding - crop exactly to content boundaries for tight cropping
#                     # User wants "just the data" with all edges cut
#                     min_x = max(0, min_x)
#                     min_y = max(0, min_y)
#                     max_x = min(width, max_x + 1)  # +1 because crop is exclusive on right/bottom
#                     max_y = min(height, max_y + 1)
                    
#                     # Crop the image to remove white space
#                     image = image.crop((min_x, min_y, max_x, max_y))
                    
#                     logger.debug(f"Cropped image from {width}x{height} to {max_x-min_x}x{max_y-min_y}")
#                 else:
#                     # If no content found, the image is entirely white/light
#                     logger.debug("No content found in image (all white), returning minimal crop")
#                     # Return a small portion of the center as fallback
#                     center_x, center_y = width // 2, height // 2
#                     crop_size = min(width, height, 50)  # At least show something
#                     left = max(0, center_x - crop_size // 2)
#                     upper = max(0, center_y - crop_size // 2)
#                     right = min(width, left + crop_size)
#                     lower = min(height, upper + crop_size)
#                     image = image.crop((left, upper, right, lower))
                
#                 # Apply automatic rotation for readability if enabled
#                 if auto_rotate:
#                     image = ViewExtractor.auto_rotate_for_readability(image)
#                     # After rotation, crop again to remove any white space introduced by rotation
#                     width, height = image.size
#                     gray_image = image.convert('L')
#                     gray_pixels = gray_image.load()
                    
#                     # Find the bounding box of non-white content after rotation
#                     # Use same aggressive threshold as initial crop
#                     min_x = width
#                     min_y = height
#                     max_x = 0
#                     max_y = 0
#                     found_content = False
#                     white_threshold_gray = 250  # Same threshold as initial crop
                    
#                     for y in range(height):
#                         for x in range(width):
#                             gray_value = gray_pixels[x, y]
#                             if gray_value < white_threshold_gray:
#                                 found_content = True
#                                 min_x = min(min_x, x)
#                                 min_y = min(min_y, y)
#                                 max_x = max(max_x, x)
#                                 max_y = max(max_y, y)
                    
#                     if found_content:
#                         # No padding - crop exactly to content boundaries
#                         # User wants "just the data" with all edges cut
#                         min_x = max(0, min_x)
#                         min_y = max(0, min_y)
#                         max_x = min(width, max_x + 1)  # +1 because crop is exclusive on right/bottom
#                         max_y = min(height, max_y + 1)
                        
#                         # Crop the image to remove white space after rotation
#                         image = image.crop((min_x, min_y, max_x, max_y))
#                         logger.debug(f"Re-cropped image after rotation from {width}x{height} to {max_x-min_x}x{max_y-min_y}")
                
#                 # Convert back to PNG bytes
#                 output = io.BytesIO()
#                 image.save(output, format='PNG')
#                 cropped_bytes = output.getvalue()
                
#                 logger.info(f"Successfully extracted, cropped, and auto-rotated region as image ({len(cropped_bytes)} bytes)")
#                 return cropped_bytes
                
#             except Exception as e:
#                 logger.warning(f"Error during image cropping/rotation, returning original: {str(e)}")
#                 # If cropping fails, return the original image
#                 return img_bytes
            
#         except Exception as e:
#             logger.error(f"Error extracting region as image: {str(e)}", exc_info=True)
#             return None
    
#     @staticmethod
#     def extract_region_as_base64(
#         pdf_path: str,
#         page_number: int,
#         region: Dict[str, float],
#         zoom_factor: float = 2.0,
#         scale_factor: float = 1.0,
#         auto_rotate: bool = True
#     ) -> Optional[str]:
#         """
#         Extract a region from a PDF page and return it as a base64-encoded image.
        
#         Args:
#             pdf_path: Path to the PDF file
#             page_number: Page number (0-indexed)
#             region: Dictionary with keys 'x', 'y', 'width', 'height'
#             zoom_factor: Factor to zoom the region
#             scale_factor: Factor to scale coordinates
#             auto_rotate: Whether to automatically rotate for readability (default True)
        
#         Returns:
#             Base64-encoded PNG image string (data URI format), or None if extraction fails
#         """
#         img_bytes = ViewExtractor.extract_region_as_image(
#             pdf_path=pdf_path,
#             page_number=page_number,
#             region=region,
#             zoom_factor=zoom_factor,
#             scale_factor=scale_factor,
#             auto_rotate=auto_rotate
#         )
        
#         if img_bytes is None:
#             return None
        
#         # Encode to base64 and return as data URI
#         base64_str = base64.b64encode(img_bytes).decode('utf-8')
#         return f"data:image/png;base64,{base64_str}"

"""
View extraction module for PDF regions.
This module extracts a specific region from a PDF page and returns it as an image
for viewing purposes.
"""
import fitz  # PyMuPDF
from typing import Dict, Optional, Tuple
from pathlib import Path
import logging
import io
import base64
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)


class ViewExtractor:
    """Extract and convert PDF regions to viewable images."""
    
    @staticmethod
    def detect_text_orientation(image: Image.Image) -> int:
        """
        Detect the orientation of text in the image and return the required rotation angle.
        Returns the rotation angle needed to make text horizontal and easily readable.
        For the Region View use case we keep this intentionally simple and stable:
        - If the cropped region is taller than it is wide (vertical), rotate 90°.
        - Otherwise keep it at 0°.
        This guarantees a horizontal final image without diagonal angles.
        """
        try:
            # Use the dimensions of the (already cropped) image to decide orientation.
            width, height = image.size

            # If the region is clearly vertical (height > width), rotate 270° to
            # make it horizontal and upright in the Region View. Otherwise keep it as-is.
            if height > width:
                logger.debug(
                    f"Region is vertical (w={width}, h={height}), selecting 270° rotation"
                )
                return 270

            logger.debug(
                f"Region is horizontal or square (w={width}, h={height}), using 0° rotation"
            )
            return 0
                
        except Exception as e:
            logger.warning(f"Error in orientation detection: {str(e)}, using default orientation")
            return 0
    
    @staticmethod
    def auto_rotate_for_readability(image: Image.Image) -> Image.Image:
        """
        Automatically rotate image to make text horizontal and easily readable.
        First applies a coarse 0°/90°/180°/270° orientation, then performs a
        small-angle deskew (±15°) to straighten slightly tilted content.
        """
        try:
            # First, coarse orientation using the simple 0°/270° detector
            rotation_angle = ViewExtractor.detect_text_orientation(image)
            if rotation_angle != 0:
                logger.info(f"Auto-rotating image by {rotation_angle} degrees for coarse alignment")
                image = image.rotate(
                    rotation_angle,
                    expand=True,
                    resample=Image.BICUBIC,
                    fillcolor=(255, 255, 255),
                )

            # Second, fine deskew: search small angles around 0° to remove slight tilt
            try:
                gray = image.convert("L")
                max_dim = max(gray.size)
                if max_dim > 600:
                    scale = 600.0 / max_dim
                    new_size = (int(gray.width * scale), int(gray.height * scale))
                    gray = gray.resize(new_size, Image.BILINEAR)

                full_array = np.array(gray)
                h, w = full_array.shape

                # Focus the scoring on the central horizontal band where the text
                # is most likely located. This reduces the influence of slanted
                # dimension lines or arrows above/below the text.
                band_top = int(h * 0.25)
                band_bottom = int(h * 0.75)
                if band_bottom <= band_top:
                    band_top = 0
                    band_bottom = h

                base_array = full_array[band_top:band_bottom, :]
                best_angle = 0
                best_score = -1.0

                for angle in range(-15, 16):  # -15° to +15°
                    if angle == 0:
                        test_array = base_array
                    else:
                        rotated = gray.rotate(angle, expand=True, resample=Image.BILINEAR)
                        rotated_array = np.array(rotated)
                        rh, rw = rotated_array.shape
                        rt = int(rh * 0.25)
                        rb = int(rh * 0.75)
                        if rb <= rt:
                            rt = 0
                            rb = rh
                        test_array = rotated_array[rt:rb, :]

                    dark_mask = test_array < 180
                    horizontal_projection = np.sum(dark_mask, axis=1)
                    vertical_projection = np.sum(dark_mask, axis=0)

                    horizontal_variance = float(np.var(horizontal_projection))
                    vertical_variance = float(np.var(vertical_projection))

                    if vertical_variance > 0:
                        score = horizontal_variance / vertical_variance
                    else:
                        score = horizontal_variance

                    # Prefer small adjustments – penalise larger angles softly
                    score *= max(0.4, 1.0 - (abs(angle) / 30.0))

                    if score > best_score:
                        best_score = score
                        best_angle = angle

                if best_angle != 0:
                    logger.info(f"Applying fine deskew by {best_angle} degrees for straightening")
                    image = image.rotate(
                        best_angle,
                        expand=True,
                        resample=Image.BICUBIC,
                        fillcolor=(255, 255, 255),
                    )

            except Exception as inner_e:
                logger.debug(f"Fine deskew step failed, keeping coarse rotation only: {inner_e}")

            return image
            
        except Exception as e:
            logger.warning(f"Error in auto-rotation: {str(e)}, returning original image")
            return image
    
    @staticmethod
    def extract_region_as_image(
        pdf_path: str,
        page_number: int,
        region: Dict[str, float],
        zoom_factor: float = 2.0,
        scale_factor: float = 1.0,
        auto_rotate: bool = True
    ) -> Optional[bytes]:
        """
        Extract a region from a PDF page and convert it to an image.
        
        Args:
            pdf_path: Path to the PDF file
            page_number: Page number (0-indexed in PyMuPDF)
            region: Dictionary with keys 'x', 'y', 'width', 'height' in PDF coordinates
            zoom_factor: Factor to zoom the region (default 2.0 for better quality)
            scale_factor: Factor to scale coordinates (default 1.0)
            auto_rotate: Whether to automatically rotate for readability (default True)
        
        Returns:
            PNG image bytes, or None if extraction fails
        """
        try:
            pdf_path = Path(pdf_path)
            if not pdf_path.exists():
                logger.error(f"PDF file not found: {pdf_path}")
                return None
            
            # Open PDF document
            doc = fitz.open(str(pdf_path))
            
            if page_number < 0 or page_number >= len(doc):
                logger.error(f"Invalid page number: {page_number}, PDF has {len(doc)} pages")
                doc.close()
                return None
            
            # Get the specified page
            page = doc[page_number]
            
            # Get page dimensions
            page_rect = page.rect
            page_width = page_rect.width
            page_height = page_rect.height
            
            logger.debug(f"Page dimensions: {page_width} x {page_height}")
            logger.debug(f"Region: x={region['x']}, y={region['y']}, w={region['width']}, h={region['height']}")
            
            # Coordinates from frontend are already in PDF point space
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
            
            # Ensure coordinates are within page bounds
            x0 = max(0, min(x0, page_width))
            y0 = max(0, min(y0, page_height))
            x1 = max(x0, min(x1, page_width))
            y1 = max(y0, min(y1, page_height))
            
            # Create clipping rectangle in PDF coordinates
            clip_rect = fitz.Rect(x0, y0, x1, y1)
            
            logger.debug(f"Extracting region as image: {clip_rect}")
            
            # Calculate matrix for rendering with zoom
            # The matrix transforms from PDF coordinates to image pixels
            # zoom_factor determines the resolution (e.g., 2.0 = 2x resolution)
            mat = fitz.Matrix(zoom_factor, zoom_factor)
            
            # Render the clipped region to a pixmap (image)
            pix = page.get_pixmap(matrix=mat, clip=clip_rect)
            
            # Convert pixmap to PNG bytes first
            img_bytes = pix.tobytes("png")
            
            doc.close()
            
            # Load image with PIL to crop white space and apply rotation
            try:
                image = Image.open(io.BytesIO(img_bytes))
                
                # Convert to RGB if needed (in case of RGBA or other formats)
                if image.mode != 'RGB':
                    # Create a white background
                    rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                    if image.mode == 'RGBA':
                        # Paste with alpha channel handling
                        rgb_image.paste(image, mask=image.split()[3] if len(image.split()) > 3 else None)
                    else:
                        rgb_image.paste(image)
                    image = rgb_image
                
                # Get bounding box of non-white content using aggressive threshold approach
                # Convert to grayscale for better white space detection
                # This finds pixels that are not "close to white" 
                # Using a high threshold (252) to be very aggressive in removing white space
                width, height = image.size
                pixels = image.load()
                
                # Convert to grayscale for brightness-based detection
                gray_image = image.convert('L')
                gray_pixels = gray_image.load()
                
                # Find the bounding box of non-white content
                min_x = width
                min_y = height
                max_x = 0
                max_y = 0
                
                # White threshold - pixels brighter than this are considered background/white.
                # Slightly lower values here (e.g. 240) treat very light gray paper as white
                # so the crop hugs the actual ink (text/box) more tightly.
                white_threshold_rgb = 240
                white_threshold_gray = 240
                found_content = False
                
                # Scan through all pixels to find content boundaries
                for y in range(height):
                    for x in range(width):
                        r, g, b = pixels[x, y]
                        gray_value = gray_pixels[x, y]
                        
                        # Pixel is considered content if:
                        # 1. Any RGB channel is below threshold, OR
                        # 2. Grayscale brightness is below threshold
                        # This ensures we catch all non-white pixels
                        is_content = (
                            r < white_threshold_rgb or 
                            g < white_threshold_rgb or 
                            b < white_threshold_rgb or
                            gray_value < white_threshold_gray
                        )
                        
                        if is_content:
                            found_content = True
                            min_x = min(min_x, x)
                            min_y = min(min_y, y)
                            max_x = max(max_x, x)
                            max_y = max(max_y, y)
                
                if found_content:
                    # No padding - crop exactly to content boundaries for tight cropping
                    # User wants "just the data" with all edges cut
                    min_x = max(0, min_x)
                    min_y = max(0, min_y)
                    max_x = min(width, max_x + 1)  # +1 because crop is exclusive on right/bottom
                    max_y = min(height, max_y + 1)
                    
                    # Crop the image to remove white space
                    image = image.crop((min_x, min_y, max_x, max_y))
                    
                    logger.debug(f"Cropped image from {width}x{height} to {max_x-min_x}x{max_y-min_y}")
                else:
                    # If no content found, the image is entirely white/light
                    logger.debug("No content found in image (all white), returning minimal crop")
                    # Return a small portion of the center as fallback
                    center_x, center_y = width // 2, height // 2
                    crop_size = min(width, height, 50)  # At least show something
                    left = max(0, center_x - crop_size // 2)
                    upper = max(0, center_y - crop_size // 2)
                    right = min(width, left + crop_size)
                    lower = min(height, upper + crop_size)
                    image = image.crop((left, upper, right, lower))
                
                # Apply automatic rotation for readability if enabled
                if auto_rotate:
                    image = ViewExtractor.auto_rotate_for_readability(image)
                    # After rotation, crop again to remove any white space introduced by rotation
                    width, height = image.size
                    gray_image = image.convert('L')
                    gray_pixels = gray_image.load()
                    
                    # Find the bounding box of non-white content after rotation
                    # Use same threshold as initial crop so behaviour is consistent
                    min_x = width
                    min_y = height
                    max_x = 0
                    max_y = 0
                    found_content = False
                    white_threshold_gray = 240
                    
                    for y in range(height):
                        for x in range(width):
                            gray_value = gray_pixels[x, y]
                            if gray_value < white_threshold_gray:
                                found_content = True
                                min_x = min(min_x, x)
                                min_y = min(min_y, y)
                                max_x = max(max_x, x)
                                max_y = max(max_y, y)
                    
                    if found_content:
                        # No padding - crop exactly to content boundaries
                        # User wants "just the data" with all edges cut
                        min_x = max(0, min_x)
                        min_y = max(0, min_y)
                        max_x = min(width, max_x + 1)  # +1 because crop is exclusive on right/bottom
                        max_y = min(height, max_y + 1)
                        
                        # Crop the image to remove white space after rotation
                        image = image.crop((min_x, min_y, max_x, max_y))
                        logger.debug(f"Re-cropped image after rotation from {width}x{height} to {max_x-min_x}x{max_y-min_y}")
                
                # Convert back to PNG bytes
                output = io.BytesIO()
                image.save(output, format='PNG')
                cropped_bytes = output.getvalue()
                
                logger.info(f"Successfully extracted, cropped, and auto-rotated region as image ({len(cropped_bytes)} bytes)")
                return cropped_bytes
                
            except Exception as e:
                logger.warning(f"Error during image cropping/rotation, returning original: {str(e)}")
                # If cropping fails, return the original image
                return img_bytes
            
        except Exception as e:
            logger.error(f"Error extracting region as image: {str(e)}", exc_info=True)
            return None
    
    @staticmethod
    def extract_region_as_base64(
        pdf_path: str,
        page_number: int,
        region: Dict[str, float],
        zoom_factor: float = 2.0,
        scale_factor: float = 1.0,
        auto_rotate: bool = True
    ) -> Optional[str]:
        """
        Extract a region from a PDF page and return it as a base64-encoded image.
        
        Args:
            pdf_path: Path to the PDF file
            page_number: Page number (0-indexed)
            region: Dictionary with keys 'x', 'y', 'width', 'height'
            zoom_factor: Factor to zoom the region
            scale_factor: Factor to scale coordinates
            auto_rotate: Whether to automatically rotate for readability (default True)
        
        Returns:
            Base64-encoded PNG image string (data URI format), or None if extraction fails
        """
        img_bytes = ViewExtractor.extract_region_as_image(
            pdf_path=pdf_path,
            page_number=page_number,
            region=region,
            zoom_factor=zoom_factor,
            scale_factor=scale_factor,
            auto_rotate=auto_rotate
        )
        
        if img_bytes is None:
            return None
        
        # Encode to base64 and return as data URI
        base64_str = base64.b64encode(img_bytes).decode('utf-8')
        return f"data:image/png;base64,{base64_str}"
