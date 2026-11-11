"""Optional native desktop login; secrets are passed only through helper stdin."""
import json
from pathlib import Path
import subprocess

from PySide6.QtWidgets import QCheckBox, QFormLayout, QLabel, QLineEdit, QMessageBox
from wallet_ui import WorkDialog
from wallets import WalletError
from login import passwordless, validate_request


class LoginDialog(WorkDialog):
    def __init__(self, parent):
        super().__init__(parent, 'Login Password')
        self.installed = Path('/etc/bitcoin-core-node/installed').is_file()
        self.password_required = not passwordless()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.layout.addWidget(self.summary)
        note = QLabel('Set a password to sign in after starting or restarting this computer. '
                      'Remove it to open the Node desktop automatically. Changes apply at the next login; '
                      'your current session stays open. Once signed in, Node actions do not ask for this password again.')
        note.setWordWrap(True)
        self.layout.addWidget(note)
        form = QFormLayout()
        self.password = QLineEdit()
        self.confirm = QLineEdit()
        for label, field in (('New password', self.password), ('Repeat password', self.confirm)):
            field.setEchoMode(QLineEdit.Password)
            # Keep the full text for validation; do not silently truncate at
            # either the former Node limit or the system's byte boundary.
            field.setAccessibleName(label)
            form.addRow(label, field)
        self.layout.addLayout(form)
        self.show_password = QCheckBox('Show password')
        self.show_password.toggled.connect(self.show_secret)
        self.layout.addWidget(self.show_password)
        hint = QLabel('No minimum length or required mix of letters, numbers and symbols. '
                      'A login password controls access to the desktop; it does not encrypt the disk '
                      'or replace a Bitcoin Core wallet passphrase.')
        hint.setWordWrap(True)
        self.layout.addWidget(hint)
        self.save_button = self.button('Set password', self.save)
        self.remove_button = self.button('Remove password', self.remove)
        self.button('Back to Settings', self.reject)
        for button in self.actions:
            button.setAutoDefault(False)
        self.password.returnPressed.connect(self.confirm.setFocus)
        self.confirm.returnPressed.connect(self.save)
        self.refresh_actions()

    def show_secret(self, visible):
        for field in (self.password, self.confirm):
            field.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)

    def refresh_actions(self):
        busy = self.job is not None and self.job.isRunning()
        enabled = self.installed and not busy
        for control in (self.password, self.confirm, self.show_password, self.save_button):
            control.setEnabled(enabled)
        self.remove_button.setVisible(self.installed and self.password_required)
        self.remove_button.setEnabled(enabled)
        self.save_button.setText('Change password' if self.password_required else 'Set password')
        self.summary.setText('Password required at login.' if self.password_required
                             else 'Automatic login is enabled. No login password is required.')
        if not self.installed:
            self.summary.setText('Login settings are available after installing Bitcoin Core Node.')

    def save(self):
        if not self.installed or (self.job is not None and self.job.isRunning()):
            return
        if self.password.text() != self.confirm.text():
            self.status.setText('Please enter the same password in both fields.')
            self.confirm.setFocus()
            return
        request = {'required': True, 'password': self.password.text()}
        try:
            validate_request(request)
        except WalletError as exc:
            self.status.setText(str(exc))
            request.pop('password', None)
            return
        self.apply(request)

    def remove(self):
        if not self.installed or not self.password_required or (self.job is not None and self.job.isRunning()):
            return
        prompt = QMessageBox(self)
        prompt.setWindowTitle('Remove login password?')
        prompt.setText('This computer will open the Node desktop automatically at the next login.')
        remove = prompt.addButton('Remove password', QMessageBox.AcceptRole)
        cancel = prompt.addButton('Cancel', QMessageBox.RejectRole)
        prompt.setDefaultButton(cancel)
        prompt.setEscapeButton(cancel)
        prompt.exec()
        confirmed = prompt.clickedButton() is remove
        prompt.deleteLater()
        if confirmed:
            self.apply({'required': False})

    def apply(self, request):
        self.password.clear()
        self.confirm.clear()
        self.show_password.setChecked(False)
        def perform():
            try:
                result = subprocess.run(
                    ['/usr/bin/pkexec', '/usr/libexec/core-node-login', 'configure'],
                    input=json.dumps(request), capture_output=True, text=True, timeout=180)
            except (OSError, subprocess.TimeoutExpired):
                raise WalletError('The login settings service did not respond. Please keep this session open and try again.') from None
            finally:
                request.pop('password', None)
            if result.returncode:
                raise WalletError('Login settings were not saved. Please use the active local Node desktop and check the local service status.')
            return json.loads(result.stdout)
        def done(result):
            self.password_required = result['password_required']
            self.status.setText('Saved. A password will be required at the next login.'
                                if self.password_required else
                                'Saved. The Node desktop will open automatically at the next login.')
        self.run(perform, done, 'Saving login settings…')
        self.refresh_actions()

    def reject(self):
        if self.job is not None and self.job.isRunning():
            self.status.setText('Saving login settings. Please wait before closing this window.')
            return
        self.password.clear()
        self.confirm.clear()
        super().reject()
