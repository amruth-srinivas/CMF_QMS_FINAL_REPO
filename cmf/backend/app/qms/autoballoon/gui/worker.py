"""
OCR Worker Thread
==================
Background QThread that runs the OCR pipeline without blocking the GUI.
"""

from PySide6.QtCore import QThread, Signal


class OCRWorker(QThread):
    """Runs OCR processing in a background thread."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, ocr_engine, image_path, page_index=0):
        super().__init__()
        self.ocr = ocr_engine
        self.image_path = image_path
        self.page_index = page_index

    def run(self):
        try:
            result = self.ocr.predict_with_regions(self.image_path, self.page_index)
            self.finished.emit(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))
