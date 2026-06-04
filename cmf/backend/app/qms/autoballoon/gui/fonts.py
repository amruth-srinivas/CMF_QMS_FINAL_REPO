"""
Font Loader
============
Loads and configures application fonts (Roboto / Roboto Mono) for use
in the Qt GUI and PIL-based overlay rendering.
"""

import sys
import os

from PySide6.QtGui import QFont, QFontDatabase


def resource_path(*relative_parts: str) -> str:
    """Resolve a path relative to the application root (or PyInstaller bundle)."""
    base_path = getattr(sys, "_MEIPASS", None)
    if not base_path:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, *relative_parts)


def _configure_qt_font(font: QFont) -> QFont:
    """Apply anti-aliasing preferences to a QFont."""
    font.setHintingPreference(QFont.PreferNoHinting)
    font.setStyleStrategy(QFont.PreferAntialias)
    return font


_APP_FONTS = None


def load_app_fonts():
    """Load Roboto and Roboto Mono font families and return a dict of QFont objects.

    Returns a dict with keys: 'main', 'main_bold', 'mono', 'mono_bold', 'pil_label'.
    Caches on first call.
    """
    global _APP_FONTS
    if _APP_FONTS is not None:
        return _APP_FONTS

    roboto_regular_path = resource_path("fonts", "Roboto-Regular.ttf")
    roboto_bold_path = resource_path("fonts", "Roboto-Bold.ttf")
    roboto_mono_regular_path = resource_path("fonts", "RobotoMono-Regular.ttf")
    roboto_mono_bold_path = resource_path("fonts", "RobotoMono-Bold.ttf")

    def _add_font(ttf_path: str):
        if not os.path.exists(ttf_path):
            return None
        font_id = QFontDatabase.addApplicationFont(ttf_path)
        if font_id == -1:
            return None
        families = QFontDatabase.applicationFontFamilies(font_id)
        return families[0] if families else None

    roboto_family = _add_font(roboto_regular_path)
    _add_font(roboto_bold_path)
    roboto_mono_family = _add_font(roboto_mono_regular_path)
    _add_font(roboto_mono_bold_path)

    if not roboto_family: roboto_family = "Roboto"
    if not roboto_mono_family: roboto_mono_family = "RobotoMono"

    main_font = _configure_qt_font(QFont(roboto_family, 10))
    main_font_bold = _configure_qt_font(QFont(roboto_family, 10))
    main_font_bold.setBold(True)
    mono_font = _configure_qt_font(QFont(roboto_mono_family, 10))
    mono_font_bold = _configure_qt_font(QFont(roboto_mono_family, 10))
    mono_font_bold.setBold(True)

    pil_label_font = None
    try:
        from PIL import ImageFont
        if os.path.exists(roboto_mono_regular_path):
            pil_label_font = ImageFont.truetype(roboto_mono_regular_path, size=8)
    except Exception:
        pil_label_font = None

    _APP_FONTS = {
        "main": main_font,
        "main_bold": main_font_bold,
        "mono": mono_font,
        "mono_bold": mono_font_bold,
        "pil_label": pil_label_font,
    }
    return _APP_FONTS
