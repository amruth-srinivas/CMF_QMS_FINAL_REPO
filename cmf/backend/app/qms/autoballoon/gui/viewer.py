"""
Image Viewer
==============
Custom QGraphicsView with zoom, pan, boundary overlays, zone grid rendering,
and engineering-balloon label overlays.
"""

import numpy as np

from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsSimpleTextItem, QGraphicsRectItem, QGraphicsEllipseItem,
    QGraphicsLineItem,
)
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QBrush, QColor, QFont, QFontMetrics,
)
from PySide6.QtCore import Qt, QRectF, QPropertyAnimation, QEasingCurve, Property


class ImageViewer(QGraphicsView):
    """Zoomable image viewer with overlay layers for balloons, boundaries, and zones."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)

        # Separate overlay layers
        self._balloon_items = []
        self._boundary_item = None
        self._zone_items = []

        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self._zoom = 0
        self._animation = None
        self.setStyleSheet("background-color: #000000; border: 1px solid #444;")

    # ------------------------------------------------------------------
    # Viewport animation
    # ------------------------------------------------------------------

    def get_viewport_rect(self) -> QRectF:
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def set_viewport_rect(self, rect: QRectF):
        self.fitInView(rect, Qt.KeepAspectRatio)

    viewport_rect = Property(QRectF, get_viewport_rect, set_viewport_rect)

    def animate_to_rect(self, rect: QRectF):
        if self._animation and self._animation.state() == QPropertyAnimation.State.Running:
            self._animation.stop()

        self._animation = QPropertyAnimation(self, b"viewport_rect")
        self._animation.setDuration(400)
        self._animation.setStartValue(self.get_viewport_rect())
        self._animation.setEndValue(rect)
        self._animation.setEasingCurve(QEasingCurve.InOutCubic)
        self._animation.start()

    # ------------------------------------------------------------------
    # Pixmap management
    # ------------------------------------------------------------------

    def set_pixmap(self, pixmap: QPixmap):
        self.clear_all()
        self._pixmap_item.setPixmap(pixmap)
        self._scene.setSceneRect(pixmap.rect())
        self.resetTransform()
        self._zoom = 0
        if not pixmap.isNull():
            self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    # ------------------------------------------------------------------
    # Layer clearing
    # ------------------------------------------------------------------

    def clear_all(self):
        self.clear_balloons()
        self.clear_boundary()
        self.clear_zones()

    def clear_balloons(self):
        for item in self._balloon_items:
            try: self._scene.removeItem(item)
            except: pass
        self._balloon_items = []

    def clear_overlays(self):  # Alias for clear_balloons for compatibility
        self.clear_balloons()

    def clear_boundary(self):
        if self._boundary_item:
            try: self._scene.removeItem(self._boundary_item)
            except: pass
            self._boundary_item = None

    def clear_zones(self):
        for item in self._zone_items:
            try: self._scene.removeItem(item)
            except: pass
        self._zone_items = []

    # ------------------------------------------------------------------
    # Boundary overlay (ROI shading)
    # ------------------------------------------------------------------

    def set_boundary_overlay(self, mask, color_bgr=(228, 202, 72), alpha=0.25):
        """Draw boundary shading (mask==0 regions) using a GraphicsPixmapItem."""
        self.clear_boundary()
        if mask is None: return

        h, w = mask.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[mask == 0] = [color_bgr[2], color_bgr[1], color_bgr[0], int(alpha * 255)]

        qimg = QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()
        pixmap = QPixmap.fromImage(qimg)
        self._boundary_item = QGraphicsPixmapItem(pixmap)
        self._boundary_item.setZValue(5)
        self._scene.addItem(self._boundary_item)

    # ------------------------------------------------------------------
    # Zone grid overlay
    # ------------------------------------------------------------------

    def set_zone_grid(self, zone_info, color_bgr=(228, 202, 72), alpha=0.45, thickness=1):
        """Draw zone lines and labels using GraphicsLineItems and SimpleTextItems."""
        self.clear_zones()
        if not zone_info: return
        zone_grid_info = zone_info

        pen_color = QColor(color_bgr[2], color_bgr[1], color_bgr[0], int(alpha * 255))
        pen = QPen(pen_color)
        pen.setWidth(thickness)
        pen.setCosmetic(True)

        font = QFont("Roboto Mono", 10)
        font.setBold(True)

        # Column lines
        for bx in zone_grid_info.col_boundaries:
            line = QGraphicsLineItem(bx, zone_grid_info.roi_bbox[1], bx, zone_grid_info.roi_bbox[3])
            line.setPen(pen)
            line.setZValue(6)
            self._scene.addItem(line)
            self._zone_items.append(line)

        # Row lines
        for by in zone_grid_info.row_boundaries:
            line = QGraphicsLineItem(zone_grid_info.roi_bbox[0], by, zone_grid_info.roi_bbox[2], by)
            line.setPen(pen)
            line.setZValue(6)
            self._scene.addItem(line)
            self._zone_items.append(line)

        # Column labels (top)
        for i, label in enumerate(zone_grid_info.col_labels):
            if i + 1 < len(zone_grid_info.col_boundaries):
                cx = (zone_grid_info.col_boundaries[i] + zone_grid_info.col_boundaries[i + 1]) // 2
                cy = zone_grid_info.roi_bbox[1] - 15
                txt = QGraphicsSimpleTextItem(label)
                txt.setFont(font)
                txt.setBrush(QBrush(pen_color))
                rect = txt.boundingRect()
                txt.setPos(cx - rect.width()/2, cy - rect.height()/2)
                txt.setZValue(7)
                self._scene.addItem(txt)
                self._zone_items.append(txt)

        # Row labels (left)
        for i, label in enumerate(zone_grid_info.row_labels):
            if i + 1 < len(zone_grid_info.row_boundaries):
                cy = (zone_grid_info.row_boundaries[i] + zone_grid_info.row_boundaries[i + 1]) // 2
                cx = zone_grid_info.roi_bbox[0] - 20
                txt = QGraphicsSimpleTextItem(label)
                txt.setFont(font)
                txt.setBrush(QBrush(pen_color))
                rect = txt.boundingRect()
                txt.setPos(cx - rect.width()/2, cy - rect.height()/2)
                txt.setZValue(7)
                self._scene.addItem(txt)
                self._zone_items.append(txt)

    # ------------------------------------------------------------------
    # Engineering balloon overlays
    # ------------------------------------------------------------------

    def _create_label_overlay(self, label, x2, y1, base_size, color, z,
                             font_scale=0.6, bold=True, alpha=255, font=None):
        """Opaque engineering balloon with sub-pixel centering precision."""
        label_font = font if font else QFont("Roboto Mono")
        label_font.setPointSizeF(base_size * font_scale)
        label_font.setBold(bold)

        fm = QFontMetrics(label_font)
        text_str = str(label)
        tight_rect = fm.tightBoundingRect(text_str)
        ascent = fm.ascent()

        lx, ly = x2, y1 - base_size

        if isinstance(color, (list, tuple)):
            theme_color = QColor(int(color[0]), int(color[1]), int(color[2]), 255)
        elif isinstance(color, QColor):
            theme_color = QColor(color)
            theme_color.setAlpha(255)
        else:
            theme_color = QColor(230, 57, 70, 255)

        rect_size = base_size / 2
        bg_rect = QGraphicsRectItem(0, rect_size, rect_size, rect_size)
        bg_rect.setPen(Qt.NoPen)
        bg_rect.setBrush(QBrush(theme_color))
        bg_rect.setPos(lx, ly)
        bg_rect.setZValue(z + 7)

        bg_outer = QGraphicsEllipseItem(0, 0, base_size, base_size)
        bg_outer.setPen(Qt.NoPen)
        bg_outer.setBrush(QBrush(theme_color))
        bg_outer.setPos(lx, ly)
        bg_outer.setZValue(z + 8)

        padding = base_size * 0.1
        bg_inner = QGraphicsEllipseItem(padding, padding, base_size - (2*padding), base_size - (2*padding))
        bg_inner.setPen(Qt.NoPen)
        bg_inner.setBrush(QBrush(QColor(255, 255, 255, 255)))
        bg_inner.setPos(lx, ly)
        bg_inner.setZValue(z + 9)

        text_item = QGraphicsSimpleTextItem(text_str)
        text_item.setFont(label_font)
        text_item.setBrush(QBrush(QColor(0, 0, 0, 255)))

        circle_center = base_size / 2.0
        ink_x_offset = tight_rect.x() + (tight_rect.width() / 2.0)
        final_x = circle_center - ink_x_offset
        ink_y_offset = tight_rect.y() + (tight_rect.height() / 2.0)
        final_y = circle_center - (ascent + ink_y_offset)

        text_item.setPos(lx + final_x, ly + final_y)
        text_item.setZValue(z + 10)

        items = [bg_rect, bg_outer, bg_inner, text_item]
        for item in items:
            self._scene.addItem(item)
            self._balloon_items.append(item)
        return items

    def set_overlays(self, overlays, font=None):
        """Renamed logically to set_balloons internally, but kept name for compat."""
        self.clear_balloons()
        if not overlays: return

        pixmap = self._pixmap_item.pixmap()
        if pixmap.isNull():
            base_size = 24
        else:
            img_w, img_h = pixmap.width(), pixmap.height()
            base_size = int(max(15, min(img_w, img_h) * 0.015))
            base_size = min(base_size, 40)

        for ov in overlays:
            base_color = ov.get("color") or (230, 57, 70)
            if isinstance(base_color, (list, tuple)) and len(base_color) >= 3:
                c = QColor(int(base_color[0]), int(base_color[1]), int(base_color[2]))
            elif isinstance(base_color, QColor): c = base_color
            else: c = QColor(230, 57, 70)

            c.setAlpha(50)
            item_pen = Qt.NoPen
            item_brush = QBrush(c)
            z = float(ov.get("z", 10))

            if "bbox" in ov and ov["bbox"] and len(ov["bbox"]) == 4:
                x1, y1, x2, y2 = ov["bbox"]
                w, h = x2 - x1, y2 - y1
                rect_item = QGraphicsRectItem(x1, y1, w, h)
                rect_item.setPen(item_pen)
                rect_item.setBrush(item_brush)
                rect_item.setZValue(z)
                self._scene.addItem(rect_item)
                self._balloon_items.append(rect_item)

            label = ov.get("label")
            if not label: continue

            self._create_label_overlay(label=label, x2=ov["bbox"][2], y1=ov["bbox"][1],
                                      base_size=base_size, color=c, z=z,
                                      font_scale=0.4, bold=True, alpha=255, font=font)

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------

    def wheelEvent(self, event):
        if self._pixmap_item.pixmap().isNull(): return
        angle = event.angleDelta().y()
        if angle == 0: return
        step = 1 if angle > 0 else -1
        next_zoom = self._zoom + step
        if next_zoom < -10 or next_zoom > 30: return
        factor = 1.25 if step > 0 else 0.8
        self._zoom = next_zoom
        self.scale(factor, factor)
