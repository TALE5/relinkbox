import sys

from PySide6.QtWidgets import QApplication

from cue_relinker.gui.window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
