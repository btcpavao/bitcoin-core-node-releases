#!/usr/bin/python3
"""Shared Qt passphrase controls. Secrets never leave the current process."""
from pathlib import Path
import os
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)
from layered_backend import MAX_LAYERS

STYLE = """
QDialog, QScrollArea, QWidget#layers { background:#111111; color:#f2f2f2; }
QScrollArea { border:0; }
QLabel { color:#f2f2f2; background:transparent; }
QLabel#heading { font-size:22px; font-weight:600; }
QLabel#note, QLabel#status { color:#c5c5c5; }
QLineEdit { color:white; background:#202020; border:1px solid #626262;
 border-radius:5px; padding:9px; min-height:22px; selection-background-color:#2468a2; }
QLineEdit:focus { border:2px solid #589ddd; padding:8px; }
QCheckBox { color:#f2f2f2; spacing:8px; padding:5px 0; }
QCheckBox::indicator { width:18px; height:18px; }
QPushButton { color:#eee; background:#242424; border:1px solid #626262;
 border-radius:6px; padding:9px 14px; }
QPushButton:hover { border-color:#a0a0a0; }
QPushButton:focus { border:2px solid #8fbee8; padding:8px 13px; }
QPushButton#create { background:#2169a8; border-color:#438fcf; color:white; }
QPushButton:disabled, QPushButton#create:disabled { background:#262626; color:#888; border-color:#424242; }
"""

def label(text, name=None):
    result = QLabel(str(text))
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(True)
    if name:
        result.setObjectName(name)
    return result


class SecretEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_return = None
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self.setInputMethodHints(Qt.InputMethodHint.ImhSensitiveData | Qt.InputMethodHint.ImhNoPredictiveText)
        self.setDragEnabled(False)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            if self.on_return:
                self.on_return()
            return
        super().keyPressEvent(event)


class SecretRow(QWidget):
    def __init__(self, owner, confirm):
        super().__init__()
        self.owner = owner
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 14)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        self.title = label('')
        self.remove = QPushButton('Remove')
        self.remove.setAutoDefault(False)
        self.remove.clicked.connect(lambda: owner.remove_row(self))
        heading.addWidget(self.title, 1)
        heading.addWidget(self.remove)
        layout.addLayout(heading)
        self.password = SecretEdit()
        self.confirm = SecretEdit() if confirm else None
        self.title.setBuddy(self.password)
        layout.addWidget(self.password)
        self.password.textChanged.connect(owner.update_validation)
        if self.confirm is not None:
            confirmation_label = label('Confirm')
            confirmation_label.setBuddy(self.confirm)
            layout.addWidget(confirmation_label)
            layout.addWidget(self.confirm)
            self.confirm.textChanged.connect(owner.update_validation)
        self.show_secret = QCheckBox('Show')
        self.show_secret.toggled.connect(self.toggle_visibility)
        layout.addWidget(self.show_secret)
        if self.confirm:
            self.password.on_return = lambda: self.confirm.setFocus(Qt.FocusReason.TabFocusReason)
        self.password.setAccessibleName('Passphrase')

    def toggle_visibility(self, visible):
        for edit in (self.password, self.confirm):
            if edit is not None:
                pos = edit.cursorPosition()
                edit.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
                edit.setCursorPosition(pos)

    def clear(self):
        for edit in (self.password, self.confirm):
            if edit is not None:
                edit.blockSignals(True)
                edit.setEchoMode(QLineEdit.EchoMode.Password)
                edit.clear()
                edit.blockSignals(False)
        self.show_secret.setChecked(False)


class PassphraseDialog(QDialog):
    def __init__(self, validator, parent=None, *, destination=None, items=(),
                 recovery=False, workspace=None, previous=(), error='', secrets_only=False):
        super().__init__(parent)
        self.validator, self.recovery = validator, recovery
        self.workspace = Path(workspace) if workspace is not None else None
        from layered_backend import is_direct_wallet
        self.payload_suffix = ('.dat' if len(items) == 1 and
            Path(items[0]).name == 'wallet.dat' and Path(items[0]).is_file()
            and is_direct_wallet(Path(items[0])) else '.tar')
        self.secrets_only = secrets_only
        self.value = self.destination_value = None
        self.rows = []
        self.setWindowTitle('Decrypt Files' if recovery else 'Encrypt Files')
        self.setStyleSheet(STYLE)
        self.resize(680, 690)
        screen = QApplication.primaryScreen()
        if screen:
            size = screen.availableGeometry().size()
            self.resize(min(680, size.width() - 32), min(690, size.height() - 48))
        self.setMinimumSize(440, 400)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        outer.addWidget(label(self.windowTitle(), 'heading'))
        if items:
            selected = label('Selected: ' + ', '.join(Path(p).name for p in items[:4]) +
                             (' …' if len(items) > 4 else ''), 'note')
            selected.setToolTip('\n'.join(map(str, items)))
            outer.addWidget(selected)
        outer.addWidget(label(('Enter the available backup passphrases in any order. Files stay in Private Workspace.'
            if recovery else 'Use a separate strong random passphrase for each layer. Keep each secret separately from the encrypted files.'), 'note'))
        if error:
            outer.addWidget(label(error, 'status'))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.panel = QWidget()
        self.panel.setObjectName('layers')
        self.rows_layout = QVBoxLayout(self.panel)
        self.rows_layout.setContentsMargins(0, 0, 12, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(self.panel)
        outer.addWidget(self.scroll, 1)
        self.add_button = QPushButton('+ Add Passphrase' if recovery else '+ Add Encryption Layer')
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(lambda: self.add_row(focus=True))
        outer.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.ordinary = None
        if recovery and not secrets_only:
            self.ordinary = QCheckBox('Recover one ordinary GPG layer only')
            self.ordinary.setToolTip('For files made outside Vault. Saves one authenticated payload as recovered-file without guessing nested layers or extracting archives.')
            outer.addWidget(self.ordinary)
        self.destination = None
        if not secrets_only:
            self.destination = QLineEdit(str(destination or 'recovered-backup'))
            self.destination.setAccessibleName('Recovery folder name' if recovery else 'Save backup as')
            caption = label('Recovery folder in Private Workspace' if recovery else 'Save backup as')
            caption.setBuddy(self.destination)
            outer.addWidget(caption)
            row = QHBoxLayout()
            row.addWidget(self.destination, 1)
            if not recovery:
                self.choose_destination = QPushButton('Choose…')
                self.choose_destination.setAutoDefault(False)
                self.choose_destination.clicked.connect(self.choose_location)
                row.addWidget(self.choose_destination)
            outer.addLayout(row)
            self.destination.textChanged.connect(self.update_validation)
        self.status = label('', 'status')
        outer.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton('Cancel')
        self.create_button = QPushButton('Verify Backup' if secrets_only else
                                        'Decrypt Files' if recovery else 'Encrypt Files')
        self.create_button.setObjectName('create')
        for button in (self.cancel_button, self.create_button):
            button.setAutoDefault(False)
            button.setDefault(False)
            buttons.addWidget(button)
        outer.addLayout(buttons)
        self.cancel_button.clicked.connect(self.reject)
        self.create_button.clicked.connect(self.accept)
        for value in previous or ('',):
            row = self.add_row()
            row.password.setText(value)
        self.rows[0].password.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update_validation()

    def add_row(self, focus=False):
        if len(self.rows) >= MAX_LAYERS:
            return None
        row = SecretRow(self, not self.recovery)
        self.rows.append(row)
        self.rows_layout.insertWidget(len(self.rows) - 1, row)
        self.renumber()
        self.update_validation()
        if focus:
            row.password.setFocus(Qt.FocusReason.TabFocusReason)
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(row))
        return row

    def remove_row(self, row):
        if len(self.rows) == 1:
            return
        index = self.rows.index(row)
        self.rows.remove(row)
        row.clear()
        self.rows_layout.removeWidget(row)
        row.deleteLater()
        self.renumber()
        self.rows[min(index, len(self.rows) - 1)].password.setFocus()
        self.update_validation()

    def renumber(self):
        for i, row in enumerate(self.rows, 1):
            title = 'Passphrase' if len(self.rows) == 1 else 'Passphrase ' + str(i)
            row.title.setText(title)
            row.password.setAccessibleName(title)
            row.show_secret.setAccessibleName('Show ' + title.lower())
            if row.confirm:
                row.confirm.setAccessibleName('Confirm ' + title.lower())
            row.remove.setAccessibleName('Remove ' + title.lower())
            row.remove.setVisible(len(self.rows) > 1)
        self.add_button.setEnabled(len(self.rows) < MAX_LAYERS)
        if not self.recovery and self.destination is not None:
            self.destination.setText(str(self.backup_name(self.destination.text())))

    def backup_name(self, text):
        # Preserve existing directory; one .gpg suffix per independent layer.
        # Generic multi-file and single non-wallet sources use TAR.
        base = text
        while base.lower().endswith('.gpg'):
            base = base[:-4]
        for suffix in ('.tar', '.dat'):
            if base.lower().endswith(suffix):
                base = base[:-len(suffix)]
                break
        base += self.payload_suffix
        return Path(base + '.gpg' * len(self.rows))

    def normalized_destination(self):
        if self.secrets_only:
            return None
        text = self.destination.text()
        if not text or any(ord(c) < 32 or ord(c) == 127 for c in text):
            raise ValueError('Please choose a valid destination name.')
        if self.recovery:
            if text in ('.', '..') or '/' in text or '\\' in text:
                raise ValueError('Please choose a folder name without path separators.')
            path = self.workspace / text
        else:
            from private_workspace import canonical_path
            path = canonical_path(text)
            if not path.is_absolute():
                raise ValueError('Please choose an absolute backup location.')
            path = self.backup_name(text)
        if not path.parent.is_dir() or any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('Please choose an existing destination without symbolic links.')
        if os.path.lexists(path):
            raise ValueError('That destination exists. Please choose a new name.')
        return path

    def choose_location(self):
        from media_file_dialog import choose_media_file
        selected = choose_media_file(self, 'Save encrypted backup', self.destination.text(),
            saving=True, name_filter='GPG backup (*.gpg)')
        if selected:
            self.destination.setText(selected)

    def update_validation(self, *_):
        if not hasattr(self, 'status'):
            return
        error, values = '', [row.password.text() for row in self.rows]
        try:
            self.normalized_destination()
            for row in self.rows:
                self.validator(row.password.text())
                if row.confirm and row.password.text() != row.confirm.text():
                    raise ValueError('Please enter matching passphrases in each layer.')
            if len(set(values)) != len(values):
                raise ValueError('Please use a different passphrase for each layer.')
        except ValueError as exc:
            error = str(exc)
        valid = bool(values) and not error
        self.create_button.setEnabled(valid)
        self.status.setText(error or ('Ready. All required backup passphrases must remain available for recovery.'
                                    if self.recovery else 'Ready to create and verify every encryption layer.'))

    def accept(self):
        self.update_validation()
        if not self.create_button.isEnabled():
            return
        self.value = [row.password.text() for row in self.rows]
        self.destination_value = self.normalized_destination()
        self.clear_fields()
        super().accept()

    def clear_fields(self):
        # UI cleanup only. Python/Qt memory erasure is not guaranteed.
        for row in self.rows:
            row.clear()

    def reject(self):
        self.value = self.destination_value = None
        self.clear_fields()
        super().reject()


_APPLICATION = None

def ensure_app():
    global _APPLICATION
    _APPLICATION = QApplication.instance() or _APPLICATION or QApplication(['core-node-files-crypto'])
    from ui import configure_ui
    configure_ui(_APPLICATION)
    _APPLICATION.setFont(QFont('DejaVu Sans', 10))
    return _APPLICATION


def get_backup_request(validator, destination, *, items=()):
    ensure_app()
    window = PassphraseDialog(validator, destination=Path(destination), items=items)
    result = window.exec()
    value = (window.destination_value, window.value) if result == QDialog.DialogCode.Accepted else None
    window.value = None
    window.clear_fields()
    window.deleteLater()
    return value


def get_verification_secrets(validator, archive):
    ensure_app()
    window = PassphraseDialog(validator, items=[archive], recovery=True, secrets_only=True)
    result = window.exec()
    value = window.value if result == QDialog.DialogCode.Accepted else None
    window.value = None
    window.clear_fields()
    window.deleteLater()
    return value
