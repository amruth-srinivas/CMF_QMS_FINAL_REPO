"""
Find the innermost boundary (main technical drawing area) in a page image.
Used by auto-ballooning to restrict detections to the drawing content only,
excluding title bar, sidebars, title block, and other PDF chrome.
"""
import logging
from typing import Tuple, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Minimum fraction of page width/height that the main drawing must be inset from each edge
# (excludes title bar, sidebars, title block that touch or sit at the edge)
MIN_EDGE_MARGIN = 0.015  # 1.5%
# Aspect ratio range for "main drawing" (rejects tall narrow sidebars and wide thin strips)
MIN_ASPECT = 0.25
MAX_ASPECT = 4.0
# Minimum size as fraction of page (rejects small noise rectangles)
MIN_SIZE_FRAC = 0.08
# Maximum area as fraction of page (rejects full-sheet contour if we ever include it)
MAX_AREA_FRAC = 0.98


def find_innermost_boundary(image: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[tuple]]:
    """
    Find the innermost boundary rectangle that contains the main technical drawing.
    Title bar, sidebars, title block, and other PDF chrome are excluded so that
    only content inside this boundary is used for auto-ballooning.

    Returns:
        (mask, main_rect): mask is a uint8 image with 255 inside the boundary;
            main_rect is (x, y, w, h). Returns (None, None) if no suitable boundary is found.
    """
    if image is None or image.size == 0:
        return None, None

    try:
        if len(image.shape) == 2:
            gray = image
        else:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    except Exception as e:
        logger.warning("find_innermost_boundary: failed to convert to grayscale: %s", e)
        return None, None

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 11, 2
    )

    contours, hierarchy = cv2.findContours(
        thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
    )
    height, width = image.shape[:2]
    page_area = width * height
    min_margin_x = width * MIN_EDGE_MARGIN
    min_margin_y = height * MIN_EDGE_MARGIN
    min_w = width * MIN_SIZE_FRAC
    min_h = height * MIN_SIZE_FRAC
    max_area = page_area * MAX_AREA_FRAC

    valid_rectangles = []

    for i, cnt in enumerate(contours):
        epsilon = 0.01 * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, epsilon, True)
        x, y, w, h = cv2.boundingRect(cnt)
        area = cv2.contourArea(cnt)
        rect_area = w * h

        # Must be at least 4-sided, minimum size, and roughly rectangular
        if len(approx) < 4 or w < min_w or h < min_h:
            continue
        if rect_area <= 0 or (abs(area - rect_area) / rect_area) > 0.4:
            continue
        if x < 0 or y < 0 or (x + w) > width or (y + h) > height:
            continue
        if area > max_area:
            continue

        aspect = w / h if h else 0
        if aspect < MIN_ASPECT or aspect > MAX_ASPECT:
            continue

        # Require inset from all four edges (excludes title bar, sidebars, title block)
        inset_left = x >= min_margin_x
        inset_right = (x + w) <= (width - min_margin_x)
        inset_top = y >= min_margin_y
        inset_bottom = (y + h) <= (height - min_margin_y)
        has_margin = inset_left and inset_right and inset_top and inset_bottom

        valid_rectangles.append({
            "contour": cnt,
            "area": area,
            "rect": (x, y, w, h),
            "has_margin": has_margin,
        })

    if not valid_rectangles:
        return None, None

    # Prefer rectangles that have margin (central drawing area); then by area descending
    valid_rectangles.sort(key=lambda r: (not r["has_margin"], -r["area"]))
    best = valid_rectangles[0]

    # If no candidate had margin, still apply aspect and size; we already filtered above
    main_rect = best["rect"]
    main_cnt = best["contour"]

    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.drawContours(mask, [main_cnt], -1, 255, -1)

    return mask, main_rect


def is_inside_boundary(bbox: list, main_rect: tuple) -> bool:
    """
    Return True if the detection bbox (list of [x,y] points or [x0,y0,x1,y1]) 
    lies entirely or by center inside main_rect (x, y, w, h).
    Used to filter detections to only those inside the innermost boundary.
    """
    if not main_rect or len(main_rect) != 4:
        return True  # no boundary -> allow all
    x0, y0, w, h = main_rect
    x1, y1 = x0 + w, y0 + h

    if not bbox or len(bbox) < 2:
        return False
    # Center of bbox
    if isinstance(bbox[0], (list, tuple)):
        cx = (bbox[0][0] + (bbox[2][0] if len(bbox) > 2 else bbox[0][0])) / 2
        cy = (bbox[0][1] + (bbox[2][1] if len(bbox) > 2 else bbox[0][1])) / 2
    else:
        cx = (bbox[0] + bbox[2]) / 2 if len(bbox) > 2 else bbox[0]
        cy = (bbox[1] + bbox[3]) / 2 if len(bbox) > 3 else bbox[1]
    return x0 <= cx <= x1 and y0 <= cy <= y1
