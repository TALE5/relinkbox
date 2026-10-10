"""Load the logo files in relinkbox_brand_assets."""

import sys
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication


def assets_dir():
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    else:
        root = Path(__file__).resolve().parents[1]
    folder = root / "relinkbox_brand_assets"
    return folder if folder.is_dir() else None


def window_icon():
    folder = assets_dir()
    if folder is None:
        return QIcon()
    ico = folder / "app_icon" / "relinkbox.ico"
    if ico.is_file():
        icon = QIcon(str(ico))
        if not icon.isNull():
            return icon
    png = folder / "app_icon" / "relinkbox-app-icon-512.png"
    if png.is_file():
        return QIcon(str(png))
    return QIcon()


def apply_window_icon(widget=None):
    icon = window_icon()
    if icon.isNull():
        return
    app = QApplication.instance()
    if app is not None:
        app.setWindowIcon(icon)
    if widget is not None:
        widget.setWindowIcon(icon)


def trimmed_pixmap(path, height):
    """Crop away empty margins and scale to a logical pixel height."""
    image = QImage(str(path))
    if image.isNull():
        return QPixmap()
    cropped = QPixmap.fromImage(image).copy(_opaque_bounds(image))
    if cropped.isNull() or height <= 0:
        return cropped
    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    ratio = screen.devicePixelRatio() if screen is not None else 1.0
    scaled = cropped.scaledToHeight(max(1, round(height * ratio)), Qt.SmoothTransformation)
    scaled.setDevicePixelRatio(ratio)
    return scaled


def _opaque_bounds(image):
    width = image.width()
    height = image.height()
    min_x, min_y, max_x, max_y = width, height, -1, -1
    step = 2
    for y in range(0, height, step):
        for x in range(0, width, step):
            if image.pixelColor(x, y).alpha() <= 16:
                continue
            if x < min_x:
                min_x = x
            if y < min_y:
                min_y = y
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y
    if max_x < 0:
        return image.rect()
    left = max(0, min_x - step)
    top = max(0, min_y - step)
    right = min(width, max_x + step + 1)
    bottom = min(height, max_y + step + 1)
    return QRect(left, top, right - left, bottom - top)
