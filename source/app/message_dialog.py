#!/usr/bin/python3
"""Dark result/error dialog. Only explicit non-secret status text is presented."""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QFont, QIcon, QPainter, QColor, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout)

STYLE = '''
QDialog { background: #111111; color: #f2f2f2; }
QLabel { background: transparent; color: #eeeeee; }
QLabel#resultTitle { font-size: 22px; font-weight: 600; }
QLabel#resultText { color: #c7c7c7; }
QPushButton { color: white; background: #2169a8; border: 1px solid #438fcf;
              border-radius: 6px; padding: 9px 24px; min-width: 80px; }
QPushButton:hover { background: #287cbe; }
QPushButton:focus { border: 2px solid #afd2f2; padding: 8px 23px; }
'''


def status_icon(error=False, recovery=False):
    image = QPixmap(128, 128)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(128/48, 128/48)
    colour = QColor('#e3ac55' if error else '#83bfff')
    painter.setPen(QPen(colour, 3.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    if error:
        painter.drawEllipse(QRectF(6, 6, 36, 36))
        painter.drawLine(QPointF(24, 14), QPointF(24, 27))
        painter.drawPoint(QPointF(24, 34))
    elif recovery:
        painter.drawRoundedRect(QRectF(10, 5, 28, 38), 3, 3)
        painter.drawLine(QPointF(17, 14), QPointF(30, 14))
        painter.drawLine(QPointF(17, 21), QPointF(27, 21))
        painter.drawLine(QPointF(24, 27), QPointF(24, 36))
        painter.drawLine(QPointF(18, 31), QPointF(24, 37))
        painter.drawLine(QPointF(30, 31), QPointF(24, 37))
    else:
        painter.drawArc(QRectF(14, 4, 20, 26), 0, 180*16)
        painter.drawLine(QPointF(14, 17), QPointF(14, 22))
        painter.drawLine(QPointF(34, 17), QPointF(34, 22))
        painter.setBrush(QColor('#1b3550'))
        painter.drawRoundedRect(QRectF(7, 20, 34, 24), 5, 5)
        painter.setPen(QPen(colour, 3.0, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(24, 29), QPointF(24, 35))
    painter.end()
    return image


class ResultDialog(QDialog):
    def __init__(self, text, error=False, parent=None, *, operation=None):
        super().__init__(parent)
        self.setObjectName('NodeFilesResultDialog')
        recovery = operation == 'recovery'
        self.setWindowTitle('Bitcoin Core Node — GPG Recovery' if recovery else
                            'Bitcoin Core Node — File Encryption')
        self.setWindowIcon(QIcon(status_icon(error, recovery)))
        self.setStyleSheet(STYLE)
        self.setModal(True)
        self.resize(620, 290)
        self.setMinimumWidth(450)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 24, 26, 22)
        outer.setSpacing(18)
        row = QHBoxLayout()
        row.setSpacing(18)
        self.icon_label = QLabel(self)
        self.icon_label.setObjectName('warningIcon' if error else ('recoveryIcon' if recovery else 'lockIcon'))
        self.icon_label.setAccessibleName('Warning' if error else ('Recovered file' if recovery else 'Encrypted backup lock'))
        self.icon_label.setPixmap(status_icon(error, recovery).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.icon_label.setFixedSize(52, 52)
        row.addWidget(self.icon_label, 0, Qt.AlignTop)
        text_box = QVBoxLayout()
        self.heading = QLabel(('GPG recovery could not be completed' if error else 'File recovered to RAM')
            if recovery else ('Encryption could not be completed' if error else 'Encrypted files ready'))
        self.heading.setObjectName('resultTitle')
        self.heading.setWordWrap(True)
        text_box.addWidget(self.heading)
        self.body = QLabel(text)
        self.body.setObjectName('resultText')
        self.body.setTextFormat(Qt.PlainText)
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_box.addWidget(self.body)
        row.addLayout(text_box, 1)
        outer.addLayout(row)
        outer.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.ok_button = QPushButton('OK')
        self.ok_button.clicked.connect(self.accept)
        self.ok_button.setDefault(True)
        buttons.addWidget(self.ok_button)
        outer.addLayout(buttons)


def show_message(text, error=False, *, operation=None):
    from password_dialog import ensure_app
    app = ensure_app()
    window = ResultDialog(text, error, operation=operation)
    window.exec()
