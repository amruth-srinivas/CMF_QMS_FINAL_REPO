"""
Tolerance clustering for dimension detection.
Merges nominal values with nearby tolerance text (+x / -y) on the same axis
so that "123.2", "+0.2", "-0.2" become a single dimension "123.2 +0.2 -0.2" with one bbox.
Based on PyQt5 ClusterDetector.cluster_tolerances logic.
"""
import logging
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)


def _box_bounds(box: list) -> tuple:
    """Return (min_x, min_y, max_x, max_y) for a box (list of [x,y] points or flat [x0,y0,x1,y1])."""
    if not box or len(box) < 2:
        return 0, 0, 0, 0
    if isinstance(box[0], (list, tuple)):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
    else:
        xs = [box[0], box[2]] if len(box) > 2 else [box[0]]
        ys = [box[1], box[3]] if len(box) > 3 else [box[1]]
    return min(xs), min(ys), max(xs), max(ys)


def _box_center(box: list) -> tuple:
    x1, y1, x2, y2 = _box_bounds(box)
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def _combined_box(boxes: List[list]) -> list:
    """Return axis-aligned combined bbox as [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]."""
    all_x, all_y = [], []
    for box in boxes:
        if not box:
            continue
        if isinstance(box[0], (list, tuple)):
            for p in box:
                all_x.append(p[0])
                all_y.append(p[1])
        else:
            if len(box) >= 2:
                all_x.append(box[0])
                all_y.append(box[1])
            if len(box) >= 4:
                all_x.append(box[2])
                all_y.append(box[3])
    if not all_x:
        return [[0, 0], [0, 0], [0, 0], [0, 0]]
    x1, x2 = min(all_x), max(all_x)
    y1, y2 = min(all_y), max(all_y)
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def cluster_tolerances(
    text_results: List[Dict[str, Any]],
    is_dimensional_value: Callable[[str], bool],
    parse_dimension: Optional[Callable[[str], tuple]] = None,
) -> List[Dict[str, Any]]:
    """
    Cluster text detections that lie on the same horizontal or vertical axis
    and merge nominal + tolerance (+x / -y) into single entries with combined text and bbox.
    Returns a list of dicts with keys: text, box, confidence?, angle?, and optionally
    upper_tol, lower_tol for pre-parsed combined entries.
    """
    if not text_results:
        return []

    # Normalize: ensure each item has 'box' as list of points
    items = []
    for r in text_results:
        text = (r.get("text") or r.get("content") or "").strip()
        if not text or text == "+":
            continue
        box = r.get("box") or r.get("bbox") or []
        if not box or len(box) < 2:
            continue
        if not isinstance(box[0], (list, tuple)) and len(box) >= 4:
            box = [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]]
        items.append({
            "text": text,
            "box": box,
            "confidence": r.get("confidence", 0.0),
            "angle": r.get("angle", 0),
        })
    if not items:
        return []

    def is_on_same_x_axis(box1: list, box2: list, text_height: float) -> bool:
        x1_1, y1_1, x2_1, y2_1 = _box_bounds(box1)
        x1_2, y1_2, _, _ = _box_bounds(box2)
        return abs(x1_1 - x1_2) < 2 and abs(y1_1 - y1_2) <= text_height * 1.5

    def is_on_same_y_axis(box1: list, box2: list, text_width: float) -> bool:
        x1_1, y1_1, x2_1, y2_1 = _box_bounds(box1)
        x1_2, y1_2, _, _ = _box_bounds(box2)
        return abs(y1_1 - y1_2) < 2 and abs(x1_1 - x1_2) <= text_width * 1.5

    processed_indices = set()
    clustered = []

    for i, det1 in enumerate(items):
        if i in processed_indices:
            continue
        box1 = det1["box"]
        x1_1, y1_1, x2_1, y2_1 = _box_bounds(box1)
        text_height = y2_1 - y1_1 if y2_1 > y1_1 else 10
        text_width = x2_1 - x1_1 if x2_1 > x1_1 else 10

        # Orientation: horizontal if box width >= height
        orientation = (x2_1 - x1_1) >= (y2_1 - y1_1)

        cluster = [det1]
        cluster_boxes = [box1]
        processed_indices.add(i)

        for j, det2 in enumerate(items):
            if j in processed_indices:
                continue
            box2 = det2["box"]
            same_axis = False
            if orientation:
                same_axis = is_on_same_x_axis(box1, box2, text_height)
            else:
                same_axis = is_on_same_y_axis(box1, box2, text_width)
            if same_axis:
                cluster.append(det2)
                cluster_boxes.append(box2)
                processed_indices.add(j)

        # If cluster has exactly 2 items (e.g. two tolerances +0.2 and -0.2), find closest nominal and merge
        if len(cluster) == 2:
            fb_min_x, fb_min_y, fb_max_x, fb_max_y = _box_bounds(cluster[0]["box"])
            for c in cluster[1:]:
                a, b, c_, d = _box_bounds(c["box"])
                fb_min_x, fb_min_y = min(fb_min_x, a), min(fb_min_y, b)
                fb_max_x, fb_max_y = max(fb_max_x, c_), max(fb_max_y, d)
            closest_det = None
            closest_j = None
            for j, det2 in enumerate(items):
                if j in processed_indices:
                    continue
                if (det2.get("text") or "").strip() == "+":
                    continue
                if not is_dimensional_value((det2.get("text") or "").strip()):
                    continue
                x3_1, y3_1, x3_2, y3_2 = _box_bounds(det2["box"])
                if orientation:
                    # Horizontal: nominal often left of tolerances; cluster is to the right
                    x_dist = fb_min_x - x3_2  # gap from nominal right to cluster left
                    y_dist = (fb_min_y + fb_max_y) / 2 - (y3_1 + y3_2) / 2
                    if 1 <= x_dist < 80 and abs(y_dist) < 15:
                        closest_det = det2
                        closest_j = j
                else:
                    # Vertical: nominal often above tolerances
                    y_dist = y3_2 - fb_max_y  # gap from nominal bottom to cluster top
                    x_center_cluster = (fb_min_x + fb_max_x) / 2
                    x_center_nom = (x3_1 + x3_2) / 2
                    if 1 <= y_dist < 80 and abs(x_center_cluster - x_center_nom) < 15:
                        closest_det = det2
                        closest_j = j

            if closest_det is not None and closest_j is not None:
                processed_indices.add(closest_j)
                item_1 = min(cluster, key=lambda d: _box_bounds(d["box"])[1] if orientation else _box_bounds(d["box"])[0])
                item_2 = max(cluster, key=lambda d: _box_bounds(d["box"])[1] if orientation else _box_bounds(d["box"])[0])
                combined_text = closest_det["text"].strip()
                t1 = item_1["text"].strip().lstrip("+").lstrip("-").strip()
                t2 = item_2["text"].strip().lstrip("+").lstrip("-").strip()
                upper_tol = "+" + t1 if item_1["text"].strip().startswith("+") else "-" + t1
                lower_tol = "-" + t2 if item_2["text"].strip().startswith("-") else "+" + t2
                if upper_tol.startswith("-") and lower_tol.startswith("+"):
                    upper_tol, lower_tol = lower_tol, upper_tol
                combined_box = _combined_box([closest_det["box"], item_1["box"], item_2["box"]])
                clustered.append({
                    "text": f"{combined_text} {upper_tol} {lower_tol}",
                    "box": combined_box,
                    "confidence": det1.get("confidence", 0.0),
                    "angle": det1.get("angle", 0),
                })
                continue
            # Two items but no nominal found: add each so they can still be parsed or matched to GDT
            for c in cluster:
                clustered.append(c)
            continue

        # Single or non-2 cluster: add first item (or combined if multiple)
        if len(cluster) == 1:
            clustered.append(cluster[0])
        else:
            combined_text = " ".join(d["text"].strip() for d in cluster)
            combined_box = _combined_box(cluster_boxes)
            clustered.append({
                "text": combined_text,
                "box": combined_box,
                "confidence": max(d.get("confidence", 0) for d in cluster),
                "angle": cluster[0].get("angle", 0),
            })

    # Add any remaining items not in any cluster
    for i, det in enumerate(items):
        if i not in processed_indices:
            clustered.append(det)

    logger.info(f"Tolerance clustering: {len(text_results)} text items -> {len(clustered)} clustered entries")
    return clustered