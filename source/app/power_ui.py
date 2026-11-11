"""Vault's two confirmations and five-minute countdown, scoped to Node RAM files."""
import math
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout
from private_workspace import has_contents

COUNTDOWN_SECONDS = 300
STYLE = '''
QWidget { background:#191919; color:#f0f0f0; }
QLabel { background:transparent; }
QPushButton { background:#272727; border:1px solid #626262;
 border-radius:5px; padding:9px 16px; min-height:24px; }
QPushButton:hover { border-color:#aaa; }
QPushButton:focus { border:2px solid #8fbee8; padding:8px 15px; }
QLabel#countdown { font-size:48px; font-weight:600; }
'''


def fit_buttons(dialog):
    # QMessageBox and the system's dialog style may reserve extra room for
    # icons/standard-button indicators. The old text width + 40 left the
    # rightmost character of Cancel clipped on the real ThinkPad T550.
    # Include Qt's full size hint, icon, padding, focus border, and a
    # generous fixed safety margin for varying DPI/font metrics.
    for button in dialog.buttons():
        button.ensurePolished()
        text_width = button.fontMetrics().horizontalAdvance(button.text().replace('&', ''))
        icon_space = button.iconSize().width() + 10 if not button.icon().isNull() else 0
        required = max(button.sizeHint().width() + 20,
                       text_width + icon_space + 68,
                       124)
        button.setMinimumWidth(required)


def confirmation(restart, stage, parent=None):
    action = 'Restart' if restart else 'Shut down'
    if stage == 1:
        title = 'Save before you ' + action.lower()
        message = (
            'Files and folders kept only in Private Workspace or PSBT Transfer Folder will be lost when you '
            + action.lower() + '. This includes decrypted files.\n\n'
            'Please save everything you need to USB or disk, and keep all required '
            'passphrases separately recoverable. Copies already saved outside '
            'the RAM folders will remain.\n\n'
            'Bitcoin Core\u2019s saved blockchain and loaded wallets remain on disk. '
            'Node will not ask you to re-enter passphrases or check backups during shutdown.'
        )
        proceed_text = "I've saved what I need"
    else:
        title = action + ' this private session?'
        message = (
            'Anything still stored only in Private Workspace or PSBT Transfer Folder will be unavailable after '
            + ('restarting' if restart else 'shutting down') + '.\n\n'
            'Your confirmation does not verify your backups. Please continue only if '
            'you are sure you have saved everything you need.\n\n'
            'A five-minute countdown starts next. You can cancel and keep working, '
            'or choose to ' + action.lower() + ' immediately.'
        )
        proceed_text = 'Start 5-minute ' + ('restart' if restart else 'shutdown') + ' countdown'
    dialog = QMessageBox(QMessageBox.Icon.Warning, title, message, parent=parent)
    dialog.setStyleSheet(STYLE)
    dialog.setFont(QFont('DejaVu Sans', 12))
    cancel = dialog.addButton('Keep session open', QMessageBox.ButtonRole.RejectRole)
    proceed = dialog.addButton(proceed_text, QMessageBox.ButtonRole.AcceptRole)
    dialog.setDefaultButton(cancel)
    dialog.setEscapeButton(cancel)
    proceed.setAutoDefault(False)
    fit_buttons(dialog)
    dialog.exec()
    return dialog.clickedButton() == proceed


class CountdownDialog(QDialog):
    """No Core stop, file cleanup or power request occurs in this dialog."""
    def __init__(self, restart=False, parent=None, *, clock=None):
        super().__init__(parent)
        self.clock = clock or time.monotonic
        self.deadline = self.clock() + COUNTDOWN_SECONDS
        self.finished_once = False
        self.setWindowTitle('Restart countdown' if restart else 'Shutdown countdown')
        self.setStyleSheet(STYLE)
        self.setFont(QFont('DejaVu Sans', 12))
        self.resize(580, 350)
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(18)
        heading = QLabel('Restarting in' if restart else 'Shutting down in')
        heading.setFont(QFont('DejaVu Sans', 16))
        layout.addWidget(heading)
        self.remaining = QLabel()
        self.remaining.setObjectName('countdown')
        self.remaining.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.remaining.setAccessibleName('Time remaining')
        layout.addWidget(self.remaining)
        note = QLabel('Private Workspace is still available. Please cancel this countdown '
                      'if you need more time to save files or encrypted copies.\n\n'
                      'At zero, Bitcoin Core closes cleanly and the computer '
                      + ('restarts' if restart else 'shuts down') + '. '
                      'Files kept only in Private Workspace or PSBT Transfer Folder will be lost. '
                      'Core\u2019s saved blockchain and loaded wallets remain on disk.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QHBoxLayout()
        self.cancel_button = QPushButton('Cancel countdown')
        self.now_button = QPushButton('Restart now' if restart else 'Shut down now')
        for button in (self.cancel_button, self.now_button):
            button.setAutoDefault(False)
            button.setDefault(False)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.cancel_button.clicked.connect(self.reject)
        self.now_button.clicked.connect(self.accept)
        self.cancel_button.setFocus()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.tick()
        self.timer.start()

    def tick(self):
        if self.finished_once:
            return
        seconds = max(0, math.ceil(self.deadline - self.clock()))
        self.remaining.setText(f'{seconds // 60:02d}:{seconds % 60:02d}')
        if seconds == 0:
            self.accept()

    def done(self, result):
        if self.finished_once:
            return
        self.finished_once = True
        self.timer.stop()
        super().done(result)

    def closeEvent(self, event):
        self.reject()
        event.accept()


def ordinary_confirmation(restart, parent=None):
    action = 'Restart' if restart else 'Shut down'
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(action)
    dialog.setText('Restart this computer?' if restart else 'Shut down this computer?')
    dialog.setInformativeText('Bitcoin Core will stop cleanly. Its saved blockchain and wallets remain on disk.')
    # Apply one consistent Node dialog style rather than inheriting the
    # Home button stylesheet, which can shrink system-standard buttons.
    dialog.setStyleSheet(STYLE)
    proceed = dialog.addButton(action, QMessageBox.ButtonRole.AcceptRole)
    # Explicit RejectRole keeps Cancel's full label and its Escape/default
    # semantics, avoiding truncated platform-specific standard-button art.
    cancel = dialog.addButton('Cancel', QMessageBox.ButtonRole.RejectRole)
    proceed.setAutoDefault(False)
    cancel.setAutoDefault(False)
    dialog.setDefaultButton(cancel)
    dialog.setEscapeButton(cancel)
    fit_buttons(dialog)
    dialog.exec()
    return dialog.clickedButton() == proceed


def confirm_power_action(restart, parent=None, *, occupied=None):
    occupied = occupied or has_contents
    if not occupied():
        if not ordinary_confirmation(restart, parent):
            return False
        # Files can arrive from Core, an editor or Files while the question is open.
        if not occupied():
            return True
    if not confirmation(restart, 1, parent):
        return False
    if not confirmation(restart, 2, parent):
        return False
    countdown = CountdownDialog(restart, parent)
    return countdown.exec() == QDialog.DialogCode.Accepted
