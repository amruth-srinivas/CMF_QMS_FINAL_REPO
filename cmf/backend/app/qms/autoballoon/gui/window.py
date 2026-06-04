"""
Main Application Window
========================
OCRWindow — the primary PySide6 window that ties together the image viewer,
results table, and OCR pipeline controls.
"""

import os
import time
import copy

import cv2
import numpy as np
from tabulate import tabulate

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QProgressBar,
    QTableWidget, QTableWidgetItem,
    QFrame, QCheckBox, QHeaderView, QComboBox,
    QSlider, QSpinBox,
)
from PySide6.QtGui import QPixmap, QImage, QPainter, QFont, QShortcut, QKeySequence
from PySide6.QtCore import Qt, QRectF, QTimer

from pipeline import OCREngine, DimParser
from .viewer import ImageViewer
from .worker import OCRWorker
from .fonts import load_app_fonts


class OCRWindow(QMainWindow):
    """Main application window for the OCR pipeline GUI."""

    def __init__(self, ocr_engine=None):
        super().__init__()
        self.setWindowTitle("ED OCR Engine")
        self.resize(1280, 820)

        self.ocr = ocr_engine if ocr_engine else OCREngine()
        self.current_image_path = None
        self.original_image = None
        self.display_image = None
        self._boxes_in_display_space = False
        self.processed_image = None
        self.ocr_results = []
        self.filtered_results = []
        self._last_page_result = None
        self._all_overlays = []
        self._visible_overlays = []
        self._gdt_detections = []
        self._parsed_dimensions = []
        self._overlays_visible = True
        self._zones_visible = True
        self._zone_info = None
        self._roi_boundary = None
        self._roi_zones = []
        self.current_page = 0
        self.total_pages = 1

        fonts = load_app_fonts()
        self._main_font = fonts["main"]
        self._main_font_bold = fonts["main_bold"]
        self._mono_font = fonts["mono"]
        self._mono_font_bold = fonts["mono_bold"]
        self._qt_label_font = fonts["mono"]

        self._init_ui()

    # ==================================================================
    # UI SETUP
    # ==================================================================

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        top_bar = QHBoxLayout()
        self.btn_open = QPushButton("Open")
        self.btn_open.setFont(self._main_font)
        self.btn_open.clicked.connect(self.open_image_dialog)

        self.btn_save = QPushButton("Save")
        self.btn_save.setFont(self._main_font)
        self.btn_save.clicked.connect(self.save_processed_image)

        self.btn_toggle_overlays = QPushButton("Hide Overlays")
        self.btn_toggle_overlays.setFont(self._main_font)
        self.btn_toggle_overlays.clicked.connect(self.toggle_overlays)
        self.btn_toggle_overlays.setEnabled(False)

        self.btn_toggle_zones = QPushButton("Hide Zones")
        self.btn_toggle_zones.setFont(self._main_font)
        self.btn_toggle_zones.clicked.connect(self.toggle_zones)
        self.btn_toggle_zones.setEnabled(False)

        # ── Tiled GD&T checkbox ──────────────────────────────────────────
        self.chk_tiled_gdt = QCheckBox("Tiled GD&T")
        self.chk_tiled_gdt.setFont(self._main_font)
        self.chk_tiled_gdt.setChecked(True)
        self.chk_tiled_gdt.setToolTip(
            "Enable tiled GD&T detection.\n"
            "Runs the YOLO model on image tiles — better accuracy for large drawings.\n"
            "Disable to run a single full-image inference (faster)."
        )
        self.chk_tiled_gdt.stateChanged.connect(self._on_tiled_gdt_toggled)

        # ── AUTOBALLOON button ───────────────────────────────────────────
        self.btn_autoballoon = QPushButton("AUTOBALLOON")
        self.btn_autoballoon.setFont(self._main_font)
        self.btn_autoballoon.setStyleSheet("QPushButton { background-color: #000000; color: white; } QPushButton:disabled { background-color: #efefef; color: #bbbbbb; }")
        self.btn_autoballoon.clicked.connect(self.run_ocr_on_current_image)
        self.btn_autoballoon.setEnabled(False)

        # Confidence threshold slider
        self.conf_slider = QSlider(Qt.Horizontal)
        self.conf_slider.setMinimum(0)
        self.conf_slider.setMaximum(100)
        self.conf_slider.setValue(85)
        self.conf_slider.setMaximumWidth(120)
        self.conf_slider.valueChanged.connect(self.on_conf_threshold_changed)

        # Inflation factor slider (clustering reach)
        self.inflation_slider = QSlider(Qt.Horizontal)
        self.inflation_slider.setMinimum(0)
        self.inflation_slider.setMaximum(100)
        self.inflation_slider.setValue(15)
        self.inflation_slider.setMaximumWidth(120)
        self.inflation_slider.valueChanged.connect(self.on_inflation_factor_changed)

        # Page navigation
        self.page_label = QLabel("Page: 1/1")
        self.page_label.setFont(self._main_font)
        self.page_label.setVisible(False)

        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.setVisible(False)
        self.page_spin.valueChanged.connect(self.on_page_changed)

        self.conf_label = QLabel("Conf: 0.85")
        self.conf_label.setFont(self._main_font)
        self.conf_label.setStyleSheet("color: #000000; padding: 4px 8px;")

        self.inflation_label = QLabel("Inf: 0.15")
        self.inflation_label.setFont(self._main_font)
        self.inflation_label.setStyleSheet("color: #000000; padding: 4px 8px;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximum(0)
        self.progress_bar.setMinimumHeight(26)
        self.progress_bar.setMaximumWidth(150)

        self.timing_label = QLabel("Compute Time:")
        self.timing_label.setFont(self._main_font)
        self.timing_label.setStyleSheet("color: #000000; padding: 4px 8px;")

        self.image_info_label = QLabel("Size:")
        self.image_info_label.setFont(self._main_font)
        self.image_info_label.setStyleSheet("color: #000000; padding: 4px 8px;")

        # Timing frame
        self.timing_frame = QFrame()
        self.timing_frame.setFrameStyle(QFrame.Box)
        timing_layout = QHBoxLayout(self.timing_frame)
        timing_layout.setContentsMargins(0, 0, 0, 0)
        timing_layout.addWidget(self.timing_label)

        # Image info frame
        self.image_info_frame = QFrame()
        self.image_info_frame.setFrameStyle(QFrame.Box)
        image_info_layout = QHBoxLayout(self.image_info_frame)
        image_info_layout.setContentsMargins(0, 0, 0, 0)
        image_info_layout.addWidget(self.image_info_label)

        # Separator
        self.separator = QFrame()
        self.separator.setFrameShape(QFrame.VLine)
        self.separator.setStyleSheet("QFrame { margin: 0 10px; }")

        top_bar.addWidget(self.btn_open)
        top_bar.addWidget(self.btn_save)
        top_bar.addWidget(self.btn_toggle_overlays)
        top_bar.addWidget(self.btn_toggle_zones)
        top_bar.addWidget(self.separator)
        top_bar.addWidget(self.chk_tiled_gdt)
        top_bar.addWidget(self.btn_autoballoon)
        top_bar.addWidget(self.conf_label)
        top_bar.addWidget(self.conf_slider)
        top_bar.addWidget(self.inflation_label)
        top_bar.addWidget(self.inflation_slider)
        top_bar.addWidget(self.page_label)
        top_bar.addWidget(self.page_spin)
        top_bar.addWidget(self.image_info_frame)
        top_bar.addWidget(self.timing_frame)
        top_bar.addWidget(self.progress_bar)
        top_bar.addStretch()
        main_layout.addLayout(top_bar)

        content_layout = QHBoxLayout()
        left_panel = QVBoxLayout()
        left_panel.addWidget(QLabel("Detection Result", font=self._main_font_bold))
        self.view_result = ImageViewer()
        left_panel.addWidget(self.view_result, stretch=1)

        right_panel = QVBoxLayout()

        right_header = QHBoxLayout()
        self.lbl_results = QLabel("Results  (0 items)", font=self._main_font_bold)
        right_header.addWidget(self.lbl_results)

        right_header.addStretch()

        self.combo_filter = QComboBox()
        self.combo_filter.setFont(self._main_font)
        self.combo_filter.addItems(["All", "GD&T", "Linear", "Angular", "Diameter", "Radius", "Other"])
        self.combo_filter.setMinimumWidth(80)
        self.combo_filter.currentTextChanged.connect(self.show_text_results)
        right_header.addWidget(self.combo_filter)

        self.btn_delete_item = QPushButton("Delete")
        self.btn_delete_item.setFont(self._main_font)
        self.btn_delete_item.setStyleSheet("color: #ffffff; padding: 2px 10px; background-color: #f44336; border-color: #f44336;")
        self.btn_delete_item.clicked.connect(self.delete_selected_items)
        right_header.addWidget(self.btn_delete_item)

        right_panel.addLayout(right_header)

        self.table_results = QTableWidget()
        self.table_results.setColumnCount(7)
        self.table_results.setHorizontalHeaderLabels(["ID", "Conf", "Zone", "Type", "Nominal", "- Tol", "+ Tol"])
        self.table_results.setFont(self._mono_font)
        self.table_results.setColumnWidth(0, 40)
        self.table_results.setColumnWidth(1, 50)
        self.table_results.setColumnWidth(2, 50)
        self.table_results.setColumnWidth(3, 80)
        self.table_results.setColumnWidth(4, 100)
        self.table_results.setColumnWidth(5, 70)
        self.table_results.setColumnWidth(6, 70)
        self.table_results.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table_results.verticalHeader().setVisible(False)
        self.table_results.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_results.setAlternatingRowColors(True)
        self.table_results.itemSelectionChanged.connect(self.on_table_selection_changed)
        right_panel.addWidget(self.table_results, stretch=1)

        # Keyboard shortcut for table items deletion
        self.shortcut_delete = QShortcut(QKeySequence("Delete"), self.table_results)
        self.shortcut_delete.activated.connect(self.delete_selected_items)

        content_layout.addLayout(left_panel, stretch=70)
        content_layout.addLayout(right_panel, stretch=25)
        main_layout.addLayout(content_layout, stretch=1)

    # ==================================================================
    # IMAGE LOADING
    # ==================================================================

    def open_image_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Image or PDF", "",
            "All Files (*.png *.jpg *.jpeg *.bmp *.tiff *.webp *.pdf);;Images (*.png *.jpg *.jpeg *.bmp *.tiff *.webp);;PDF Files (*.pdf)"
        )
        if file_path:
            self.current_image_path = file_path
            self.current_page = 0

            if file_path.lower().endswith('.pdf'):
                self.total_pages = self.ocr.get_pdf_page_count(file_path)
                self.page_label.setText(f"Page: 1/{self.total_pages}")
                self.page_label.setVisible(True)
                self.page_spin.setMaximum(self.total_pages)
                self.page_spin.setValue(1)
                self.page_spin.setVisible(self.total_pages > 1)
                self.original_image = self.ocr.load_pdf_page(file_path, 0)
            else:
                self.total_pages = 1
                self.page_label.setVisible(False)
                self.page_spin.setVisible(False)
                self.original_image = cv2.imread(file_path)

            if self.original_image is not None:
                self.display_image = self.original_image
                self._boxes_in_display_space = False
                self.btn_autoballoon.setEnabled(True)
                self.btn_save.setEnabled(True)
                rgb = cv2.cvtColor(self.original_image, cv2.COLOR_BGR2RGB)
                h, w = rgb.shape[:2]
                qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
                self.view_result.set_pixmap(QPixmap.fromImage(qimg))
                self.view_result.clear_all()
                self.table_results.setRowCount(0)
                self.btn_toggle_overlays.setEnabled(False)
                self.btn_toggle_zones.setEnabled(False)
                self._overlays_visible = True
                self._zones_visible = True
                self.btn_toggle_overlays.setText("Hide Overlays")
                self.btn_toggle_zones.setText("Hide Zones")
                self.image_info_label.setText(f"Size: {w} x {h} px ({w*h:,} total)")

    # ==================================================================
    # OCR PROCESSING
    # ==================================================================

    def run_ocr_on_current_image(self):
        if self.current_image_path:
            self._ocr_start_time = time.time()
            print(f"\n{'='*50}")
            print(f"OCR Processing Started (Page {self.current_page + 1}) at: {time.strftime('%H:%M:%S', time.localtime(self._ocr_start_time))}")
            self.timing_label.setText("Time: 0:00")
            if not hasattr(self, '_elapsed_timer'):
                self._elapsed_timer = QTimer(self)
                self._elapsed_timer.setInterval(1000)
                self._elapsed_timer.timeout.connect(self._tick_elapsed)
            self._elapsed_timer.start()
            self.process_image(self.current_image_path, self.current_page)

    def process_image(self, path, page_index=0):
        if self.original_image is None: return
        self.display_image = self.original_image
        self._boxes_in_display_space = False
        self.progress_bar.setVisible(True)
        self.btn_open.setEnabled(False)
        self.btn_autoballoon.setEnabled(False)
        self.page_spin.setEnabled(False)
        self.table_results.setRowCount(0)
        self.view_result.clear_all()
        self.worker = OCRWorker(self.ocr, path, page_index)
        self.worker.finished.connect(self.on_ocr_finished)
        self.worker.error.connect(self.on_ocr_error)
        self.worker.start()

    def on_ocr_finished(self, result_data):
        # Stop the live timer
        if hasattr(self, '_elapsed_timer'):
            self._elapsed_timer.stop()

        # Calculate compute time
        compute_time = time.time() - self._ocr_start_time
        compute_time_str = f"{int(compute_time // 60)}:{int(compute_time % 60):02d}" if compute_time >= 60 else f"{compute_time:.1f}s"

        self.progress_bar.setVisible(False)
        self.btn_open.setEnabled(True)
        self.btn_autoballoon.setEnabled(True)
        self.btn_toggle_overlays.setEnabled(True)
        self.btn_toggle_zones.setEnabled(True)
        self.page_spin.setEnabled(True)

        # Handle both old tuple format and new dict format
        if isinstance(result_data, dict):
            self.original_image = result_data['original_image']
            self.ocr_results = result_data['all_detections']
            self._roi_boundary = result_data.get('roi_boundary', None)
            self._zone_info = result_data.get('zone_info', None)
            self._gdt_detections = result_data.get('gdt_detections', [])
            self._raw_gdt_detections = result_data.get('raw_gdt_detections', [])
            self._raw_ocr_detections = result_data.get('raw_ocr_detections', []) # Unmerged raw OCR
            self._parsed_dimensions = result_data.get('parsed_dimensions', [])

            self.filtered_results = result_data.get('roi_detections', [])
            excluded = result_data.get('excluded_detections', [])

            # Build zone labels for each ROI detection
            self._roi_zones = []
            if self._zone_info:
                for box, (text, score) in self.filtered_results:
                    pts = np.array(box, dtype=np.float32).reshape(-1, 2)
                    cx = int(pts[:, 0].mean())
                    cy = int(pts[:, 1].mean())
                    zone = self._zone_info.get_zone_label(cx, cy)
                    self._roi_zones.append(zone)
            else:
                self._roi_zones = [None] * len(self.filtered_results)

            print(f"\nROI detections: {len(self.filtered_results)}")
            print(f"Excluded detections: {len(excluded)}")

            title_detections = result_data.get('title_block_detections', [])
            if title_detections:
                print(f"Title Block detections: {len(title_detections)}")

            if self._zone_info:
                print(f"\nZone Grid: {len(self._zone_info.col_labels)} cols x {len(self._zone_info.row_labels)} rows")
                print(f"  Columns: {self._zone_info.col_labels}")
                print(f"  Rows: {self._zone_info.row_labels}")

            if self._roi_boundary:
                rx, ry, rw, rh = self._roi_boundary['rect']
                print(f"\nROI Boundary: ({rx}, {ry}) -> ({rx+rw}, {ry+rh})  [{rw}x{rh}]")
        elif isinstance(result_data, tuple) and len(result_data) == 2:
            raw_result, self.original_image = result_data
            self.ocr_results = self.ocr.parse_results(raw_result)
            self.filtered_results = self.ocr.filter_results_by_confidence(self.ocr_results)
            self._zone_info = None
            self._roi_boundary = None
            self._roi_zones = []
        else:
            raw_result = result_data
            self.ocr_results = self.ocr.parse_results(raw_result)
            self.filtered_results = self.ocr.filter_results_by_confidence(self.ocr_results)
            self._zone_info = None
            self._roi_boundary = None
            self._roi_zones = []
            if self.original_image is None:
                print("Warning: OCR finished but original image is missing.")

        self.timing_label.setText(f"Time: {compute_time_str}")

        print(f"\nOCR Processing Completed at: {time.strftime('%H:%M:%S', time.localtime())}")
        print(f"Total Compute Time: {compute_time_str}")

        if self.original_image is not None:
            height, width = self.original_image.shape[:2]
            print(f"Image Dimensions: {width} x {height} pixels ({width*height:,} total pixels)")

        print(f"Original detections: {len(self.ocr_results)}")
        print(f"ROI detections (shown): {len(self.filtered_results)}")
        print(f"{'='*50}\n")

        self.display_image = self.original_image
        self._boxes_in_display_space = False

        self.show_text_results()

    # ==================================================================
    # CONFIDENCE THRESHOLD
    # ==================================================================

    def on_conf_threshold_changed(self, value):
        """Handle confidence threshold slider change."""
        conf_value = value / 100.0
        self.conf_label.setText(f"Conf: {conf_value:.2f}")
        self.ocr.conf_thresh = conf_value

        if hasattr(self, 'ocr_results') and self.ocr_results:
            conf_filtered = self.ocr.filter_results_by_confidence(self.ocr_results)

            roi_boundary = getattr(self, '_roi_boundary', None)
            if roi_boundary and roi_boundary.get('mask') is not None:
                mask = roi_boundary['mask']
                self.filtered_results = []
                for box, (text, score) in conf_filtered:
                    pts = np.array(box, dtype=np.float32).reshape(-1, 2)
                    cx = int(pts[:, 0].mean())
                    cy = int(pts[:, 1].mean())
                    cy = max(0, min(cy, mask.shape[0] - 1))
                    cx = max(0, min(cx, mask.shape[1] - 1))
                    if mask[cy, cx] == 255:
                        self.filtered_results.append([box, (text, score)])
            else:
                self.filtered_results = conf_filtered

            # Re-run grouping with clean GD&T detections
            all_raw_gdt = copy.deepcopy(getattr(self, '_raw_gdt_detections', []))

            diameter_dets = [d for d in all_raw_gdt if 'diameter' in d.get('class', '').lower()]
            gdt_only = [d for d in all_raw_gdt if 'diameter' not in d.get('class', '').lower()]

            # Diameter grouping runs FIRST
            diam_ocr_indices, diam_dims = self.ocr._group_diameter_symbols(self.filtered_results, diameter_dets)
            if diam_ocr_indices:
                self.filtered_results = [det for i, det in enumerate(self.filtered_results) if i not in diam_ocr_indices]

            # Then FCF grouping
            self._gdt_detections = gdt_only
            ocr_indices_to_remove = self.ocr._group_feature_control_frames(self.filtered_results, self._gdt_detections)
            if ocr_indices_to_remove:
                self.filtered_results = [det for i, det in enumerate(self.filtered_results) if i not in ocr_indices_to_remove]

            # Re-parse all remaining OCR dimensions
            self._parsed_dimensions = []
            for box, (text, score) in self.filtered_results:
                parsed = DimParser.parse(text)
                if parsed["is_dim"]:
                    pts = np.array(box).reshape(-1, 2)
                    x1, y1 = pts.min(axis=0)
                    x2, y2 = pts.max(axis=0)
                    self._parsed_dimensions.append({
                        'bbox': [float(x1), float(y1), float(x2), float(y2)],
                        'score': score,
                        'text': text.strip(),
                        'parsed': parsed,
                        'source': 'ocr',
                    })
            for dd in diam_dims:
                self._parsed_dimensions.append(dd)

            # Rebuild zone labels
            self._roi_zones = []
            zone_info = getattr(self, '_zone_info', None)
            if zone_info:
                for box, (text, score) in self.filtered_results:
                    pts = np.array(box, dtype=np.float32).reshape(-1, 2)
                    cx = int(pts[:, 0].mean())
                    cy = int(pts[:, 1].mean())
                    self._roi_zones.append(zone_info.get_zone_label(cx, cy))
            else:
                self._roi_zones = [None] * len(self.filtered_results)

            self.show_text_results()

            print(f"Confidence threshold updated to {conf_value:.2f}")
            print(f"Showing {len(self.filtered_results)} ROI detections")

    def on_inflation_factor_changed(self, value):
        """Handle inflation factor slider change (live re-clustering)."""
        factor = value / 100.0
        self.inflation_label.setText(f"Inf: {factor:.2f}")
        self.ocr.inflation_factor = factor

        if hasattr(self, '_raw_ocr_detections') and self._raw_ocr_detections:
            # 1. Re-cluster raw detections from scratch
            clustered = self.ocr._group_by_inflation(self._raw_ocr_detections, factor)
            self.ocr_results = clustered

            # 2. Re-apply confidence filtering
            conf_filtered = self.ocr.filter_results_by_confidence(self.ocr_results)

            # 3. Re-apply ROI boundary filtering
            roi_boundary = getattr(self, '_roi_boundary', None)
            if roi_boundary and roi_boundary.get('mask') is not None:
                mask = roi_boundary['mask']
                self.filtered_results = []
                for box, (text, score) in conf_filtered:
                    pts = np.array(box).reshape(-1, 2)
                    cx = int(pts[:, 0].mean())
                    cy = int(pts[:, 1].mean())
                    cy = max(0, min(cy, mask.shape[0] - 1))
                    cx = max(0, min(cx, mask.shape[1] - 1))
                    if mask[cy, cx] == 255:
                        self.filtered_results.append([box, (text, score)])
            else:
                self.filtered_results = conf_filtered

            # 4. Re-run GD&T / Diameter grouping
            all_raw_gdt = copy.deepcopy(getattr(self, '_raw_gdt_detections', []))
            diameter_dets = [d for d in all_raw_gdt if 'diameter' in d.get('class', '').lower()]
            gdt_only = [d for d in all_raw_gdt if 'diameter' not in d.get('class', '').lower()]

            diam_indices, diam_dims = self.ocr._group_diameter_symbols(self.filtered_results, diameter_dets)
            if diam_indices:
                self.filtered_results = [det for i, det in enumerate(self.filtered_results) if i not in diam_indices]

            self._gdt_detections = gdt_only
            fcf_indices = self.ocr._group_feature_control_frames(self.filtered_results, self._gdt_detections)
            if fcf_indices:
                self.filtered_results = [det for i, det in enumerate(self.filtered_results) if i not in fcf_indices]

            # 5. Re-parse remaining OCR dimensions
            self._parsed_dimensions = []
            for box, (text, score) in self.filtered_results:
                parsed = DimParser.parse(text)
                if parsed["is_dim"]:
                    pts = np.array(box).reshape(-1, 2)
                    x1, y1 = pts.min(axis=0)
                    x2, y2 = pts.max(axis=0)
                    self._parsed_dimensions.append({
                        'bbox': [float(x1), float(y1), float(x2), float(y2)],
                        'score': score, 'text': text.strip(), 'parsed': parsed, 'source': 'ocr'
                    })
            for dd in diam_dims:
                self._parsed_dimensions.append(dd)

            # Rebuild zone labels
            zone_info = getattr(self, '_zone_info', None)
            if zone_info:
                self._roi_zones = []
                for box, (text, score) in self.filtered_results:
                    pts = np.array(box).reshape(-1, 2)
                    cx, cy = int(pts[:, 0].mean()), int(pts[:, 1].mean())
                    self._roi_zones.append(zone_info.get_zone_label(cx, cy))
            else:
                self._roi_zones = [None] * len(self.filtered_results)

            self.show_text_results()
            print(f"Inflation factor updated to {factor:.2f}. All detections re-clustered.")

    # ==================================================================
    # ERROR / PAGE HANDLING
    # ==================================================================

    def on_ocr_error(self, err):
        self.progress_bar.setVisible(False)
        self.btn_open.setEnabled(True)
        self.page_spin.setEnabled(True)
        print(f"OCR Error: {err}")

    def on_page_changed(self, value):
        """Handle PDF page selection change."""
        self.current_page = value - 1
        self.page_label.setText(f"Page: {value}/{self.total_pages}")

        self.original_image = self.ocr.load_pdf_page(self.current_image_path, self.current_page)
        if self.original_image is not None:
            self.display_image = self.original_image
            rgb = cv2.cvtColor(self.original_image, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
            self.view_result.set_pixmap(QPixmap.fromImage(qimg))
            self.view_result.clear_all()
            self.table_results.setRowCount(0)
            self.btn_toggle_overlays.setEnabled(False)
            self.image_info_label.setText(f"Size: {w} x {h} px ({w*h:,} total)")

    # ==================================================================
    # RESULTS TABLE
    # ==================================================================

    def _zone_sort_key(self, zone_label):
        """Return a sort key for zone-wise ordering (top-down, left-to-right).

        Uses the zone_info label order (index in the list), NOT alphabetical/numerical
        order.  This ensures correct spatial sorting regardless of label direction
        (ascending or descending).
        """
        if not zone_label or not self._zone_info:
            return (999, 999)

        row_part = ""
        col_part = ""
        for ch in zone_label:
            if ch.isalpha():
                row_part += ch
            elif ch.isdigit():
                col_part += ch

        row_idx = 999
        col_idx = 999
        if row_part:
            try:
                row_idx = self._zone_info.row_labels.index(row_part)
            except ValueError:
                pass
        if col_part:
            try:
                col_idx = self._zone_info.col_labels.index(col_part)
            except ValueError:
                pass

        return (row_idx, col_idx)

    def show_text_results(self):
        self.table_results.setRowCount(0)
        self.table_results.itemSelectionChanged.disconnect(self.on_table_selection_changed)

        has_dims = bool(getattr(self, '_parsed_dimensions', []))
        has_gdt = bool(getattr(self, '_gdt_detections', []))
        if not has_dims and not has_gdt:
            self.table_results.itemSelectionChanged.connect(self.on_table_selection_changed)
            return

        filter_type = getattr(self, "combo_filter", None)
        filter_text = filter_type.currentText() if filter_type else "All"

        # ── 1. Collect all displayable items ──────────────────────────────
        all_items = []

        # Parsed Dimensions (OCR + Diameter, pre-parsed by engine)
        for i, dim in enumerate(getattr(self, '_parsed_dimensions', [])):
            parsed = dim['parsed']
            if not parsed.get("is_dim"):
                continue

            p_type = parsed["type"]
            if filter_text != "All" and filter_text != "Other":
                if p_type != filter_text:
                    continue
            elif filter_text == "Other":
                if p_type in ["GD&T", "Linear", "Angular", "Diameter", "Radius"]:
                    continue

            zone_label = ""
            if self._zone_info:
                bbox = dim['bbox']
                cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
                z = self._zone_info.get_zone_label(int(cx), int(cy))
                zone_label = z if z else ""

            all_items.append({
                'orig_index': i,
                'kind': 'dim',
                'source': dim.get('source', 'ocr'),
                'score': dim['score'],
                'zone': zone_label,
                'parsed': parsed,
                'bbox': [int(b) for b in dim['bbox']],
            })

        # GD&T Detections (non-diameter, display as GD&T symbols)
        for i, gdt in enumerate(getattr(self, '_gdt_detections', [])):
            if filter_text != "All" and filter_text != "GD&T":
                continue

            zone_label = ""
            if self._zone_info:
                bbox = gdt['bbox']
                cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
                z = self._zone_info.get_zone_label(int(cx), int(cy))
                zone_label = z if z else ""
            all_items.append({
                'orig_index': i,
                'kind': 'gdt',
                'score': gdt['score'],
                'zone': zone_label,
                'gdt_class': gdt['class'],
                'bbox': [int(b) for b in gdt['bbox']],
            })

        # ── 2. Sort by zone (top-down, left-to-right), then by bbox position ─
        def _sort_key(item):
            zone_key = self._zone_sort_key(item['zone'])
            b = item['bbox']
            cy = (b[1] + b[3]) / 2
            cx = (b[0] + b[2]) / 2
            return (*zone_key, cy, cx)
        all_items.sort(key=_sort_key)

        # ── 3. Populate table and overlays ────────────────────────────────
        displayed_overlays = []
        table_print_data = []
        self._current_table_items = []

        for item in all_items:
            self._current_table_items.append(item)
            row = self.table_results.rowCount()
            self.table_results.insertRow(row)

            id_val = len(displayed_overlays) + 1

            # ID
            id_item = QTableWidgetItem(str(id_val))
            id_item.setTextAlignment(Qt.AlignCenter)
            self.table_results.setItem(row, 0, id_item)

            # Conf
            conf_item = QTableWidgetItem(f"{item['score']:.2f}")
            conf_item.setTextAlignment(Qt.AlignCenter)
            self.table_results.setItem(row, 1, conf_item)

            # Zone
            zone_item = QTableWidgetItem(item['zone'])
            zone_item.setTextAlignment(Qt.AlignCenter)
            self.table_results.setItem(row, 2, zone_item)

            if item['kind'] == 'dim':
                parsed = item['parsed']
                self.table_results.setItem(row, 3, QTableWidgetItem(parsed["type"]))
                nom_item = QTableWidgetItem(parsed["nominal"])
                nom_item.setTextAlignment(Qt.AlignCenter)
                self.table_results.setItem(row, 4, nom_item)
                min_item = QTableWidgetItem(parsed["min_tol"])
                min_item.setTextAlignment(Qt.AlignCenter)
                self.table_results.setItem(row, 5, min_item)
                max_item = QTableWidgetItem(parsed["max_tol"])
                max_item.setTextAlignment(Qt.AlignCenter)
                self.table_results.setItem(row, 6, max_item)

                if item.get('source') == 'diameter':
                    overlay_color = (230, 126, 34)
                else:
                    overlay_color = (230, 57, 70)
                overlay_label = str(id_val)
                overlay_z = 10 + id_val
                table_print_data.append([id_val, f"{item['score']:.2f}", item['zone'],
                                         parsed["type"], parsed["nominal"],
                                         parsed["min_tol"], parsed["max_tol"]])
            else:  # gdt
                self.table_results.setItem(row, 3, QTableWidgetItem("GD&T"))
                nom_item = QTableWidgetItem(item['gdt_class'])
                self.table_results.setItem(row, 4, nom_item)
                self.table_results.setItem(row, 5, QTableWidgetItem(""))
                self.table_results.setItem(row, 6, QTableWidgetItem(""))

                overlay_color = (252, 191, 73)
                overlay_label = str(id_val)
                overlay_z = 50 + id_val
                table_print_data.append([id_val, f"{item['score']:.2f}", item['zone'],
                                         "GD&T", item['gdt_class'], "", ""])

            displayed_overlays.append({
                "bbox": item['bbox'],
                "label": overlay_label,
                "z": overlay_z,
                "color": overlay_color,
            })

        self._all_overlays = displayed_overlays
        self._visible_overlays = list(displayed_overlays)
        self.table_results.itemSelectionChanged.connect(self.on_table_selection_changed)

        headers = ["ID", "Conf", "Zone", "Type", "Nominal", "- Tol", "+ Tol"]
        if len(table_print_data) > 0:
            print("\n" + tabulate(table_print_data, headers=headers, tablefmt="grid"))
            total_items = len(table_print_data)
            print(f"Summary: Displaying {total_items} dimensions and GD&T symbols.\n")
            if hasattr(self, 'lbl_results'):
                self.lbl_results.setText(f"Results  ({total_items} items)")
        else:
            if hasattr(self, 'lbl_results'):
                self.lbl_results.setText(f"Results  (0 items)")

        self.update_result_image()

    # ==================================================================
    # ITEM DELETION
    # ==================================================================

    def delete_selected_items(self):
        selected_rows = [item.row() for item in self.table_results.selectedItems()]
        if not selected_rows:
            return

        selected_rows = list(set(selected_rows))
        selected_rows.sort(reverse=True)

        ocr_indices_to_delete = []
        gdt_indices_to_delete = []

        if not hasattr(self, '_current_table_items'):
            return

        for row in selected_rows:
            item_data = self._current_table_items[row]
            if item_data['kind'] == 'ocr':
                ocr_indices_to_delete.append(item_data['orig_index'])
            elif item_data['kind'] == 'gdt':
                gdt_indices_to_delete.append(item_data['orig_index'])

        ocr_indices_to_delete.sort(reverse=True)
        gdt_indices_to_delete.sort(reverse=True)

        for idx in ocr_indices_to_delete:
            if idx < len(self.filtered_results):
                del self.filtered_results[idx]
                if getattr(self, '_roi_zones', None) and idx < len(self._roi_zones):
                    del self._roi_zones[idx]

        for idx in gdt_indices_to_delete:
            if getattr(self, '_gdt_detections', None) and idx < len(self._gdt_detections):
                del self._gdt_detections[idx]

        self.show_text_results()

    # ==================================================================
    # VISUAL LAYER MANAGEMENT
    # ==================================================================

    def update_result_image(self):
        """Synchronize visual layers in the viewer."""
        # Layer 1: Zones & Boundary
        if self._zones_visible:
            if self._roi_boundary:
                self.view_result.set_boundary_overlay(self._roi_boundary.get('mask'))
            if self._zone_info:
                self.view_result.set_zone_grid(self._zone_info)
        else:
            self.view_result.clear_boundary()
            self.view_result.clear_zones()

        # Layer 2: OCR Balloons
        if self._overlays_visible:
            self.view_result.set_overlays(self._visible_overlays, self._mono_font_bold)
        else:
            self.view_result.clear_balloons()

    def on_table_selection_changed(self):
        if not self._overlays_visible:
            return

        selected_items = self.table_results.selectedItems()
        selected_rows = sorted(list(set(item.row() for item in selected_items)))

        if not selected_rows:
            self._visible_overlays = list(self._all_overlays)
            if self.view_result._scene.sceneRect().isValid():
                self.view_result.animate_to_rect(self.view_result._scene.sceneRect())
        else:
            selected_ids = []
            for row in selected_rows:
                id_item = self.table_results.item(row, 0)
                if id_item:
                    try:
                        detection_id = int(id_item.text())
                        selected_ids.append(detection_id)
                    except ValueError:
                        continue

            selected_indices = [id - 1 for id in selected_ids if 0 < id <= len(self._all_overlays)]
            self._visible_overlays = [self._all_overlays[i] for i in selected_indices]

            total_rect = None
            for i in selected_indices:
                bbox = self._all_overlays[i]["bbox"]
                rect = QRectF(bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1])
                if total_rect is None:
                    total_rect = rect
                else:
                    total_rect = total_rect.united(rect)

            if total_rect and total_rect.isValid():
                padx = max(total_rect.width() * 1.5, 150)
                pady = max(total_rect.height() * 1.5, 150)
                target_rect = total_rect.adjusted(-padx, -pady, padx, pady)
                scene_rect = self.view_result._scene.sceneRect()
                target_rect = target_rect.intersected(scene_rect)
                if target_rect.isValid():
                    self.view_result.animate_to_rect(target_rect)

        self.view_result.set_overlays(self._visible_overlays, self._mono_font_bold)

    # ==================================================================
    # SAVE / TOGGLE / TIMER
    # ==================================================================

    def save_processed_image(self):
        """Render the current scene high-res for saving."""
        if not self.current_image_path: return
        scene_rect = self.view_result._scene.sceneRect()
        if not scene_rect.isValid(): return

        path, _ = QFileDialog.getSaveFileName(self, "Save OCR Result", f"{os.path.splitext(self.current_image_path)[0]}_ocr.png", "PNG (*.png);;JPEG (*.jpg)")
        if not path: return

        image = QImage(scene_rect.size().toSize(), QImage.Format_ARGB32)
        image.fill(Qt.white)
        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.view_result._scene.render(painter)
        painter.end()
        image.save(path)
        print(f"Saved result to: {path}")

    def toggle_overlays(self):
        self._overlays_visible = not self._overlays_visible
        self.btn_toggle_overlays.setText("Show Overlays" if not self._overlays_visible else "Hide Overlays")
        self.update_result_image()

    def toggle_zones(self):
        """Toggle zone grid lines and boundary overlay on/off."""
        self._zones_visible = not self._zones_visible
        self.btn_toggle_zones.setText("Show Zones" if not self._zones_visible else "Hide Zones")
        self.update_result_image()

    def _tick_elapsed(self):
        """Called every second during processing to update the live timer display."""
        if hasattr(self, '_ocr_start_time'):
            elapsed = time.time() - self._ocr_start_time
            mins  = int(elapsed // 60)
            secs  = int(elapsed % 60)
            self.timing_label.setText(f"Time: {mins}:{secs:02d}")

    def _on_tiled_gdt_toggled(self, state):
        """Enable / disable tiled GD&T detection on the engine."""
        enabled = bool(state)
        self.ocr.use_tiled_gdt = enabled
        print(f"Tiled GD&T: {'ON' if enabled else 'OFF'}")
