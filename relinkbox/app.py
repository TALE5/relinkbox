import logging
import sys
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from relinkbox import __version__
from relinkbox.brand import window_icon
from relinkbox.gui.fonts import ui_font
from relinkbox.gui.window import MainWindow
from relinkbox.logs import setup_logging


def _bundle_root():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[1]


def load_bundled_fonts():
    """Register Inter Display shipped with the app. OFL.txt is the license."""
    folder = _bundle_root() / "fonts"
    if not folder.is_dir():
        return
    for path in sorted(folder.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


def _windows_app_id():
    """Let the taskbar use this window's icon instead of python.exe."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TALE5.Relinkbox")
    except (AttributeError, OSError):
        pass


def main() -> int:
    _windows_app_id()
    setup_logging()
    logging.getLogger(__name__).info("Relinkbox %s starting", __version__)
    app = QApplication(sys.argv)
    icon = window_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    load_bundled_fonts()
    app.setFont(ui_font(10))
    window = MainWindow()
    window.show()
    return app.exec()
