"""
GD&T Detector
==============
YOLO-based GD&T symbol detection with support for full-image and tiled inference.
Includes class-aware NMS with containment suppression for tile fragment fusion.

Key improvements over v1:
  - max_working_dim raised to 4096 (reduces scale-factor-induced size loss on A1/A0).
  - Tile overlap increased to 96 px (30 %) to reduce tile-edge blind spots.
  - border_margin reduced to 1 px (less aggressive edge clipping).
  - Two-pass strategy: tiled pass at primary conf_thresh, then a second full-image
    pass at reduced threshold (conf_thresh - 0.15).  Second-pass detections that
    are NOT already covered by first-pass results are appended after NMS.
  - Blank-tile skip criterion tightened slightly (std threshold raised to 6).
  - Minimum detection area filter added (rejects single-pixel noise boxes).
"""

import os
import cv2
import numpy as np
from collections import defaultdict


# Absolute minimum area (px²) for a valid GD&T detection at working resolution.
_MIN_BOX_AREA = 64   # 8×8 px — anything smaller is almost certainly noise


class GDTDetector:
    """Detects GD&T symbols using a YOLO model with optional tiled inference."""

    def __init__(self, model_path: str, conf_thresh: float = 0.70):
        """
        :param model_path:  Path to the YOLO .pt model file.
        :param conf_thresh: Primary confidence threshold.
        """
        self.conf_thresh = conf_thresh
        self.model = None

        if os.path.exists(model_path):
            from ultralytics import YOLO
            print(f"Loading GD&T Model: {model_path}")
            self.model = YOLO(model_path)
        else:
            print(f"Warning: GD&T Model not found at {model_path}")

    @property
    def available(self) -> bool:
        """Whether the YOLO model was loaded successfully."""
        return self.model is not None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_full(self, image: np.ndarray, roi_rect=None, roi_mask=None) -> list:
        """
        Single-shot full-image GD&T detection.

        Preferred for images where max(h,w) <= 2048 px.  Also used as the
        second-pass fallback in detect_tiled().
        """
        if not self.model:
            return []

        h, w = image.shape[:2]
        imgsz = max(h, w)
        results = self.model.predict(
            [image], imgsz=imgsz, conf=self.conf_thresh, verbose=False
        )
        return self._parse_results(results, image.shape, roi_mask=roi_mask)

    def detect_tiled(
        self,
        image: np.ndarray,
        roi_rect=None,
        roi_mask=None,
        tile_size: int = 320,
        overlap: int = 96,          # ← increased from 64
        max_working_dim: int = 4096, # ← increased from 3072
        max_tiles: int = 512,
    ) -> list:
        """
        Two-pass GD&T detection:
          Pass 1 — tiled inference at primary conf_thresh.
          Pass 2 — full-image inference at (conf_thresh - 0.15) to catch
                   symbols that tiling missed due to tile-boundary effects
                   or scale loss.  Pass-2 results that overlap existing
                   pass-1 boxes (IoU ≥ 0.30) are suppressed.

        Coordinates are always returned in the original image space.
        """
        if not self.model:
            return []

        orig_h, orig_w = image.shape[:2]

        # ── 1. Smart down-scale ─────────────────────────────────────────
        scale_factor = 1.0
        work_img = image
        if max(orig_h, orig_w) > max_working_dim:
            scale_factor = max_working_dim / float(max(orig_h, orig_w))
            new_w = int(orig_w * scale_factor)
            new_h = int(orig_h * scale_factor)
            work_img = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
            print(f"  GD&T: Down-scaled {orig_w}×{orig_h} → {new_w}×{new_h}")
        else:
            new_w, new_h = orig_w, orig_h

        if roi_rect:
            rx, ry, rw, rh = [int(v * scale_factor) for v in roi_rect]
        else:
            rx, ry, rw, rh = 0, 0, new_w, new_h

        work_mask = None
        if roi_mask is not None:
            work_mask = cv2.resize(
                roi_mask, (new_w, new_h), interpolation=cv2.INTER_NEAREST
            )

        work_h, work_w = work_img.shape[:2]

        # ── 2. Adaptive stride / tile cap ───────────────────────────────
        base_stride = tile_size - overlap
        roi_area_w = rw + overlap
        roi_area_h = rh + overlap

        cols_count = max(1, (roi_area_w + base_stride - 1) // base_stride)
        rows_count = max(1, (roi_area_h + base_stride - 1) // base_stride)
        naive_count = cols_count * rows_count

        stride = base_stride
        if naive_count > max_tiles:
            area_per_tile = (roi_area_w * roi_area_h) / max_tiles
            stride = max(stride, int(np.sqrt(area_per_tile)))
            print(f"  GD&T: Capping tiles {naive_count}→~{max_tiles} (stride={stride})")

        # ── 3. Tile collection ───────────────────────────────────────────
        tiles, tile_coords = [], []
        y_start = max(0, ry - overlap // 2)
        x_start = max(0, rx - overlap // 2)
        y_end = min(work_h, ry + rh)
        x_end = min(work_w, rx + rw)

        for top in range(y_start, y_end, stride):
            for left in range(x_start, x_end, stride):
                t_bottom = min(top + tile_size, work_h)
                t_right  = min(left + tile_size, work_w)
                tile = work_img[top:t_bottom, left:t_right]
                if tile.size == 0:
                    continue

                gray_tile = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY)
                if np.mean(gray_tile) > 250 and np.std(gray_tile) < 6:
                    continue  # truly blank tile

                # Pad undersized edge tiles
                th, tw = tile.shape[:2]
                if th < tile_size or tw < tile_size:
                    padded = np.full((tile_size, tile_size, 3), 255, dtype=np.uint8)
                    padded[:th, :tw] = tile
                    tile = padded

                tiles.append(tile)
                tile_coords.append((top, left, t_bottom, t_right))

        if not tiles:
            return []

        # ── 4. Batch inference ───────────────────────────────────────────
        print(f"  GD&T: Running {len(tiles)} tiles at {work_w}×{work_h}")
        results = self.model.predict(
            tiles,
            imgsz=tile_size,
            conf=self.conf_thresh,
            verbose=False,
            batch=32,
        )

        all_boxes, all_scores, all_class_ids = [], [], []
        border_margin = 1  # ← reduced from 2

        for i, res in enumerate(results):
            t_top, t_left, t_bottom, t_right = tile_coords[i]
            for box in res.boxes:
                coords = box.xyxy[0].cpu().numpy()
                conf   = float(box.conf[0].cpu().numpy())
                cls_id = int(box.cls[0].cpu().numpy())

                gx1 = coords[0] + t_left
                gy1 = coords[1] + t_top
                gx2 = coords[2] + t_left
                gy2 = coords[3] + t_top

                # Minimum area filter
                if (gx2 - gx1) * (gy2 - gy1) < _MIN_BOX_AREA:
                    continue

                # Border-clamp filter (only truly edge-touching boxes)
                is_clamped = (
                    (t_left > x_start and coords[0] < border_margin) or
                    (t_top  > y_start and coords[1] < border_margin) or
                    (t_right < work_w  and coords[2] > (t_right - t_left) - border_margin) or
                    (t_bottom < work_h and coords[3] > (t_bottom - t_top) - border_margin)
                )
                if is_clamped:
                    continue

                # ROI mask filter
                if work_mask is not None:
                    gcx, gcy = int((gx1 + gx2) / 2), int((gy1 + gy2) / 2)
                    gcx = max(0, min(gcx, new_w - 1))
                    gcy = max(0, min(gcy, new_h - 1))
                    if work_mask[gcy, gcx] != 255:
                        continue

                class_name = self.model.names[cls_id].strip()
                if len(class_name) == 1 and class_name.isalpha():
                    continue

                all_boxes.append([gx1, gy1, gx2, gy2])
                all_scores.append(conf)
                all_class_ids.append(cls_id)

        if not all_boxes:
            return []

        # ── 5. Global NMS ────────────────────────────────────────────────
        pass1_detections = self._nms_merge(
            all_boxes, all_scores, all_class_ids,
            iou_thresh=0.45, contain_thresh=0.60, score_thresh=self.conf_thresh,
        )

        # ── 6. Scale back to original image space ────────────────────────
        rev_sf = 1.0 / scale_factor
        for det in pass1_detections:
            det["bbox"] = [b * rev_sf for b in det["bbox"]]

        # ── 7. Second pass: full-image at lower confidence ───────────────
        # Only run if the image is not too large (cap at 2048 for the full pass)
        pass2_detections = []
        secondary_conf = max(0.40, self.conf_thresh - 0.20)
        if secondary_conf < self.conf_thresh:
            full_pass_img = work_img
            if max(work_h, work_w) > 2048:
                p2_scale = 2048 / float(max(work_h, work_w))
                pw, ph = int(work_w * p2_scale), int(work_h * p2_scale)
                full_pass_img = cv2.resize(work_img, (pw, ph), interpolation=cv2.INTER_AREA)
            else:
                p2_scale = 1.0

            imgsz = max(full_pass_img.shape[0], full_pass_img.shape[1])
            p2_results = self.model.predict(
                [full_pass_img], imgsz=imgsz, conf=secondary_conf, verbose=False
            )
            p2_boxes, p2_scores, p2_cls = [], [], []
            for res in p2_results:
                for box in res.boxes:
                    coords = box.xyxy[0].cpu().numpy()
                    conf   = float(box.conf[0].cpu().numpy())
                    cls_id = int(box.cls[0].cpu().numpy())
                    class_name = self.model.names[cls_id].strip()
                    if len(class_name) == 1 and class_name.isalpha():
                        continue
                    bx1, by1, bx2, by2 = [v / p2_scale * rev_sf for v in coords]
                    if (bx2 - bx1) * (by2 - by1) < _MIN_BOX_AREA:
                        continue
                    p2_boxes.append([bx1, by1, bx2, by2])
                    p2_scores.append(conf)
                    p2_cls.append(cls_id)

            # Keep only pass-2 boxes that don't overlap pass-1 boxes (IoU < 0.30)
            # AND are within the ROI mask
            pass2_roi_mask = None
            if roi_mask is not None:
                pw, ph = full_pass_img.shape[1], full_pass_img.shape[0]
                pass2_roi_mask = cv2.resize(roi_mask, (pw, ph), interpolation=cv2.INTER_NEAREST)

            for j, (p2b, p2s, p2c) in enumerate(zip(p2_boxes, p2_scores, p2_cls)):
                # Mask check (scaled coordinates)
                if pass2_roi_mask is not None:
                    bx1, by1, bx2, by2 = p2b
                    gcx = int((bx1 + bx2) / 2 * scale_factor * p2_scale)
                    gcy = int((by1 + by2) / 2 * scale_factor * p2_scale)
                    gcx = max(0, min(gcx, pass2_roi_mask.shape[1]-1))
                    gcy = max(0, min(gcy, pass2_roi_mask.shape[0]-1))
                    if pass2_roi_mask[gcy, gcx] != 255:
                        continue

                class_name = self.model.names[p2c]
                pass2_detections.append({
                    "bbox": p2b,
                    "score": p2s,
                    "class": class_name,
                    "class_id": p2c,
                    "from_pass2": True,
                })

        # ── 8. Cross-pass suppression ────────────────────────────────────
        # Combine detections from both passes and keep the higher confidence one
        # if they overlap significantly (IoU >= 0.30).
        combined = pass1_detections + pass2_detections
        combined.sort(key=lambda d: d["score"], reverse=True)
        
        final_detections = []
        for det in combined:
            is_overlap = False
            for kept in final_detections:
                # Class-agnostic overlap check: if two detections compete for the
                # same spot, the highest score wins regardless of class pass.
                if self._iou(det["bbox"], kept["bbox"]) >= 0.30:
                    is_overlap = True
                    break
            if not is_overlap:
                final_detections.append(det)

        if len(final_detections) < len(combined):
            suppressed = len(combined) - len(final_detections)
            print(f"  GD&T: Suppressed {suppressed} redundant cross-pass detections.")

        return final_detections

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_results(self, results, img_shape, roi_mask=None) -> list:
        """Parse YOLO results into detection dicts, applying optional ROI mask."""
        h, w = img_shape[:2]
        all_boxes, all_scores, all_class_ids = [], [], []

        for res in results:
            for box in res.boxes:
                coords = box.xyxy[0].cpu().numpy()
                conf   = float(box.conf[0].cpu().numpy())
                cls_id = int(box.cls[0].cpu().numpy())
                gx1, gy1, gx2, gy2 = coords

                if (gx2 - gx1) * (gy2 - gy1) < _MIN_BOX_AREA:
                    continue

                if roi_mask is not None:
                    gcx = int(max(0, min((gx1 + gx2) / 2, w - 1)))
                    gcy = int(max(0, min((gy1 + gy2) / 2, h - 1)))
                    if roi_mask[gcy, gcx] != 255:
                        continue

                class_name = self.model.names[cls_id].strip()
                if len(class_name) == 1 and class_name.isalpha():
                    continue

                all_boxes.append([gx1, gy1, gx2, gy2])
                all_scores.append(conf)
                all_class_ids.append(cls_id)

        if not all_boxes:
            return []

        return self._nms_merge(all_boxes, all_scores, all_class_ids)

    @staticmethod
    def _iou(a: list, b: list) -> float:
        """Compute IoU between two [x1,y1,x2,y2] boxes."""
        ix1 = max(a[0], b[0]); iy1 = max(a[1], b[1])
        ix2 = min(a[2], b[2]); iy2 = min(a[3], b[3])
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        inter = (ix2 - ix1) * (iy2 - iy1)
        area_a = max((a[2]-a[0])*(a[3]-a[1]), 1e-6)
        area_b = max((b[2]-b[0])*(b[3]-b[1]), 1e-6)
        return inter / (area_a + area_b - inter)

    def _nms_merge(
        self,
        boxes: list,
        scores: list,
        class_ids: list,
        iou_thresh: float = 0.45,
        contain_thresh: float = 0.60,
        score_thresh: float = None,
    ) -> list:
        """
        Class-aware NMS with two-pass containment suppression.

        Pass 1: per-class OpenCV NMS (IoU-based).
        Pass 2: same-class containment suppression for tile fragment fusion.
        """
        if score_thresh is None:
            score_thresh = self.conf_thresh
        if not boxes:
            return []

        # ── Pass 1: per-class NMS ────────────────────────────────────────
        cls_groups: dict = defaultdict(list)
        for idx, cid in enumerate(class_ids):
            cls_groups[cid].append(idx)

        kept_indices = []
        for cid, idxs in cls_groups.items():
            g_boxes  = [boxes[i] for i in idxs]
            g_scores = [scores[i] for i in idxs]
            cv_boxes = [[b[0], b[1], b[2]-b[0], b[3]-b[1]] for b in g_boxes]
            nms_idxs = cv2.dnn.NMSBoxes(cv_boxes, g_scores, score_thresh, iou_thresh)
            if len(nms_idxs) > 0:
                for ni in nms_idxs.flatten():
                    kept_indices.append(idxs[ni])

        if not kept_indices:
            return []

        kept_indices.sort()
        kept_boxes  = [boxes[i]  for i in kept_indices]
        kept_scores = [scores[i] for i in kept_indices]
        kept_cls    = [class_ids[i] for i in kept_indices]

        # ── Pass 2: same-class containment suppression ───────────────────
        order = sorted(range(len(kept_scores)), key=lambda i: kept_scores[i], reverse=True)
        final_flags = [True] * len(kept_boxes)

        for a_pos in range(len(order)):
            a = order[a_pos]
            if not final_flags[a]:
                continue
            a_cls = kept_cls[a]
            ax1, ay1, ax2, ay2 = kept_boxes[a]
            a_area = max((ax2-ax1)*(ay2-ay1), 1e-6)

            for b_pos in range(a_pos + 1, len(order)):
                b = order[b_pos]
                if not final_flags[b] or kept_cls[b] != a_cls:
                    continue
                bx1, by1, bx2, by2 = kept_boxes[b]
                b_area = max((bx2-bx1)*(by2-by1), 1e-6)

                ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
                ix2 = min(ax2, bx2); iy2 = min(ay2, by2)
                if ix2 > ix1 and iy2 > iy1:
                    inter = (ix2-ix1)*(iy2-iy1)
                    if max(inter/a_area, inter/b_area) >= contain_thresh:
                        final_flags[b] = False

        result = []
        for i, flag in enumerate(final_flags):
            if flag:
                result.append({
                    "bbox":     kept_boxes[i],
                    "score":    kept_scores[i],
                    "class":    self.model.names[kept_cls[i]],
                    "class_id": kept_cls[i],
                })
        return result