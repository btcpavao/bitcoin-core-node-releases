#!/usr/bin/python3
"""Recovery reuses the same dynamic passphrase controls as backup creation."""
from PySide6.QtWidgets import QDialog
from password_dialog import PassphraseDialog, ensure_app

class RecoveryDialog(PassphraseDialog):
    def __init__(self, validator, workspace, suggested_name='recovered-backup',
                 *, source=None, previous=(), error=''):
        super().__init__(validator, recovery=True, workspace=workspace,
            destination=suggested_name, items=[source] if source else (),
            previous=previous, error=error)

def get_recovery_request(validator, workspace, suggested_name='recovered-backup',
                         *, source=None, previous=(), error=''):
    ensure_app()
    window = RecoveryDialog(validator, workspace, suggested_name,
                            source=source, previous=previous, error=error)
    result = window.exec()
    value = ((window.destination_value, window.value, window.ordinary.isChecked())
             if result == QDialog.DialogCode.Accepted else None)
    window.value = None
    window.clear_fields()
    window.deleteLater()
    return value
