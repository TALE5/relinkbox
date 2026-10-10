import logging
import sys

from PySide6.QtWidgets import QApplication

from relinkbox import __version__
from relinkbox.gui.window import MainWindow
from relinkbox.logs import setup_logging


def main() -> int:
    setup_logging()
    logging.getLogger(__name__).info("Relinkbox %s starting", __version__)
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
