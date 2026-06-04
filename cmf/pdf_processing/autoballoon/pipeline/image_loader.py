"""
Image Loader
=============
Handles loading images from file paths (JPEG, PNG, TIFF, etc.) and PDF pages.
"""

import os
import cv2
import numpy as np
try:
    import fitz
except Exception:
    fitz = None


class ImageLoader:
    """Loads images and PDF pages into NumPy arrays."""

    def load(self, image_input, page_index=0):
        """
        Load an image from a file path, PDF path, or pass through a numpy array.

        :param image_input: File path (str) or image array (numpy.ndarray)
        :param page_index: Page index for PDF files (0-based)
        :return: BGR numpy array
        :raises FileNotFoundError: If file path does not exist
        :raises ValueError: If input type is invalid or loading fails
        """
        if isinstance(image_input, str):
            abs_path = os.path.abspath(image_input)
            if not os.path.exists(abs_path):
                raise FileNotFoundError(f"File not found: {abs_path}")

            if abs_path.lower().endswith(".pdf"):
                img = self.load_pdf_page(abs_path, page_index)
            else:
                img = cv2.imread(abs_path)

            if img is None:
                raise ValueError(f"Failed to load image/PDF at {abs_path}")
            return img

        elif isinstance(image_input, np.ndarray):
            return image_input.copy()

        else:
            raise ValueError("Input must be a file path string or a numpy array.")

    def load_pdf_page(self, pdf_path, page_index=0, dpi=250):
        """
        Load a specific page from a PDF file as a NumPy array (BGR format).

        :param pdf_path: Path to the PDF file.
        :param page_index: 0-based index of the page to load.
        :param dpi: Resolution for rendering the PDF page.
        :return: NumPy array representing the image of the page, or None if failed.
        """
        if fitz is None:
            raise ImportError("PyMuPDF is not available in this Python environment.")
        try:
            doc = fitz.open(pdf_path)
            if not (0 <= page_index < doc.page_count):
                raise IndexError(
                    f"Page index {page_index} out of range for PDF with {doc.page_count} pages."
                )

            page = doc[page_index]
            pix = page.get_pixmap(dpi=dpi)
            img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )

            if pix.n == 4:  # RGBA
                img_array = cv2.cvtColor(img_array, cv2.COLOR_RGBA2BGR)
            elif pix.n == 3:  # RGB
                img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

            doc.close()
            return img_array
        except Exception as e:
            print(f"Error loading PDF page {page_index} from {pdf_path}: {e}")
            return None

    def get_pdf_page_count(self, pdf_path):
        """Return the number of pages in a PDF file."""
        if fitz is None:
            return 0
        try:
            doc = fitz.open(pdf_path)
            count = doc.page_count
            doc.close()
            return count
        except Exception:
            return 0
