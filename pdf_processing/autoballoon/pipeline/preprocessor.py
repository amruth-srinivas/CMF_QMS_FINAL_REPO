"""
Image Preprocessor
===================
Handles image preprocessing steps to improve OCR and GD&T detection accuracy
on engineering drawings (both clean CAD-output and scanned).

Preprocessing chain:
  1. Grayscale conversion
  2. Optional CLAHE contrast enhancement (helps low-contrast / scanned drawings)
  3. Optional denoising (bilateral filter — preserves edges while reducing noise)
  4. Binarization: Otsu (global) or adaptive (local, better for uneven lighting)
  5. Convert back to 3-channel BGR (PaddleOCR / YOLO both expect BGR)
"""

import cv2
import numpy as np


class Preprocessor:
    """Preprocesses images for OCR and GD&T symbol detection."""

    def preprocess(
        self,
        img: np.ndarray,
        binary: bool = False,
        adaptive: bool = False,
        clahe: bool = True,
        denoise: bool = False,
    ) -> np.ndarray:
        """
        Enhance an engineering drawing image for downstream inference.

        :param img:      Input BGR (or grayscale) image.
        :param binary:   Apply global Otsu binarization (good for clean CAD PDFs).
        :param adaptive: Apply adaptive (local) thresholding instead of Otsu.
                         Overrides `binary=True`. Best for scanned/uneven drawings.
        :param clahe:    Apply CLAHE contrast enhancement before thresholding.
                         Recommended for scanned drawings; safe to leave on for all.
        :param denoise:  Apply bilateral filter to reduce scan noise while keeping
                         sharp edges. Adds ~30ms on a 3000×2000 image. Off by default.
        :return:         Preprocessed 3-channel BGR image.
        """
        # ── Step 1: Convert to grayscale ─────────────────────────────────
        if len(img.shape) == 3 and img.shape[2] == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        elif len(img.shape) == 3 and img.shape[2] == 4:
            gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
        else:
            gray = img.copy()

        # ── Step 2: Optional denoising ───────────────────────────────────
        # Bilateral filter preserves edges (dimension lines, symbol outlines)
        # while smoothing compression artefacts from scanned/JPEG drawings.
        if denoise:
            gray = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)

        # ── Step 3: CLAHE contrast enhancement ───────────────────────────
        # Particularly useful when a scanned drawing has uneven illumination
        # (darker corners, faded regions). CLAHE works on small tiles so it
        # enhances local contrast without over-brightening bright areas.
        if clahe:
            clahe_obj = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe_obj.apply(gray)

        # ── Step 4: Binarization ─────────────────────────────────────────
        if adaptive:
            # Adaptive Gaussian thresholding: each pixel's threshold is
            # computed from a local neighbourhood.  Better than Otsu when
            # drawing regions have different average brightness levels.
            block = max(11, (gray.shape[0] // 200) | 1)  # must be odd
            block = block if block % 2 == 1 else block + 1
            gray = cv2.adaptiveThreshold(
                gray, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                block, 10,
            )
        elif binary:
            _, gray = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )

        # ── Step 5: Convert back to 3-channel BGR ────────────────────────
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    def preprocess_for_gdt(self, img: np.ndarray) -> np.ndarray:
        """
        Lighter preprocessing variant optimised for YOLO GD&T detection.

        YOLO is trained on colour images and is generally robust enough;
        we only apply CLAHE without binarizing so fine symbol lines are
        not accidentally thinned or broken.
        """
        return self.preprocess(img, binary=False, adaptive=False, clahe=True, denoise=False)

    def preprocess_for_ocr(self, img: np.ndarray, is_scanned: bool = False) -> np.ndarray:
        """
        Preprocessing variant tuned for PaddleOCR.

        For clean CAD/vector-rasterised drawings: CLAHE only (binary=False).
        For scanned drawings: CLAHE + adaptive thresholding for best accuracy.
        """
        if is_scanned:
            return self.preprocess(img, binary=False, adaptive=True, clahe=True, denoise=True)
        return self.preprocess(img, binary=False, adaptive=False, clahe=True, denoise=False)