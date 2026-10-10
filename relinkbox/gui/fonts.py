"""Shared UI font. Cue Manager and the main window both use this."""

from PySide6.QtGui import QFont


def ui_font(point_size=10, bold=False):
    font = QFont()
    font.setFamilies(["Inter Display", "Inter", "Helvetica Neue", "Helvetica", "Arial"])
    font.setPointSize(point_size)
    if bold:
        font.setStyleName("Bold")
        font.setWeight(QFont.Weight.Bold)
    else:
        font.setStyleName("Regular")
        font.setWeight(QFont.Weight.Normal)
    return font
