"""Vault-style permanent deletion of selected Node wallets only."""
import json
from pathlib import Path
import sys

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QVBoxLayout)
from wallet_delete import MAX_WALLETS, validate_name
from file_browser import CORE_VIEW, check_core_view


# The red Permanently Delete button and other widgets use Vault's actual
# permanent-deletion visual design, rather than the old Node warning dialog.
VAULT_DELETE_STYLE = """
QDialog { background: #111111; color: #f2f2f2; }
QLabel { color: #eeeeee; background: transparent; }
QLabel#heading { font-size: 22px; font-weight: 600; }
QLabel#note { color: #bdbdbd; }
QPlainTextEdit { background: #1d1d1d; color: #dedede; border: 1px solid #484848;
                 border-radius: 5px; padding: 7px; }
QPushButton { color: #eeeeee; background: #242424; border: 1px solid #626262;
              border-radius: 6px; padding: 9px 16px; min-width: 90px; }
QPushButton:hover { border-color: #a0a0a0; }
QPushButton:focus { border: 2px solid #8fbee8; padding: 8px 15px; }
QPushButton#delete { background: #9a302c; border-color: #c45b55; color: white; }
QPushButton#delete:hover { background: #b13a34; }
QPushButton:disabled { color: #888888; background: #262626; border-color: #424242; }
QProgressBar { background: #242424; color: #eeeeee; border: 1px solid #555555;
               border-radius: 4px; min-height: 10px; }
QProgressBar::chunk { background: #438fcf; }
"""


def selected_wallets(paths):
    """Map ONLY direct, ordinary folder children of the read-only Core view."""
    if not isinstance(paths,(list,tuple)) or not 1<=len(paths)<=MAX_WALLETS:
        raise ValueError('Please select between one and 32 Bitcoin Core wallet folders.')
    root=CORE_VIEW/'wallets'
    names=[]
    for value in paths:
        file=Path(value)
        if not file.is_absolute() or '..' in file.parts or file.parent!=root:
            raise ValueError('Please select only wallet folders directly inside Core → wallets.')
        name=validate_name(file.name)
        if file.is_symlink() or not file.is_dir() or file.is_mount():
            raise ValueError('Only ordinary Bitcoin Core wallet folders can be deleted.')
        marker=file/'wallet.dat'
        if marker.is_symlink() or not marker.is_file():
            raise ValueError('Every selected folder must contain a Bitcoin Core wallet.dat.')
        if name in names:
            raise ValueError('A wallet folder was selected more than once.')
        names.append(name)
    return tuple(names)


def selected_wallet(path):
    """Backwards compatible exact-one path helper."""
    return selected_wallets([path])[0]


def _label(message,object_name=None):
    item=QLabel(message)
    item.setTextFormat(Qt.PlainText)
    item.setWordWrap(True)
    if object_name:item.setObjectName(object_name)
    return item


def _layout(dialog,heading):
    dialog.setWindowTitle('Bitcoin Core Node — Permanent deletion')
    dialog.setStyleSheet(VAULT_DELETE_STYLE)
    dialog.setMinimumWidth(450)
    dialog.resize(620,400)
    layout=QVBoxLayout(dialog)
    layout.setContentsMargins(24,22,24,20)
    layout.setSpacing(14)
    layout.addWidget(_label(heading,'heading'))
    return layout


class WalletDeletionDialog(QDialog):
    """A single Vault-style red confirmation, never a typed wallet name."""

    def __init__(self,names,parent=None):
        super().__init__(parent)
        self.names=(names,) if isinstance(names,str) else tuple(names)
        if not self.names or len(self.names)>MAX_WALLETS:
            raise ValueError('Invalid wallet selection.')
        layout=_layout(self,'Permanent deletion')
        count=len(self.names)
        layout.addWidget(_label(
            f'{count} Bitcoin Core wallet folder'+('' if count==1 else 's')+' selected'
        ))
        layout.addWidget(_label(
            'The selected wallet files will be overwritten and removed without using Trash. '
            'This is permanent deletion: there is no Undo. Bitcoin Core will close '
            'open wallets safely before deletion.'
        ))
        self.paths=QPlainTextEdit(self)
        self.paths.setReadOnly(True)
        self.paths.setAccessibleName('Selected Bitcoin Core wallets to permanently delete')
        self.paths.setPlainText('\n'.join(self.names))
        self.paths.setMinimumHeight(70)
        self.paths.setMaximumHeight(110)
        layout.addWidget(self.paths)
        layout.addWidget(_label(
            'Bitcoin Core will stop cleanly and restart after successful deletion. '
            'Blocks and chainstate are not affected. On SSDs and USB flash drives, '
            'earlier copies may remain; backups and snapshots are not removed.',
            'note'
        ))
        layout.addStretch(1)
        buttons=QHBoxLayout()
        buttons.addStretch(1)
        self.cancel=QPushButton('Cancel',self)
        self.delete=QPushButton('Permanently Delete',self)
        self.delete.setObjectName('delete')
        self.cancel.setAutoDefault(False)
        self.cancel.setDefault(True)
        self.delete.setAutoDefault(False)
        self.delete.setDefault(False)
        self.cancel.clicked.connect(self.reject)
        self.delete.clicked.connect(self.accept)
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.delete)
        layout.addLayout(buttons)
        self.cancel.setFocus(Qt.OtherFocusReason)


class WalletDeletionProgress(QDialog):
    """Asynchronous privileged operation; close itself after confirmed success."""

    def __init__(self,names,parent=None):
        super().__init__(parent)
        self.names=tuple(names)
        self.worker=None
        self.completed=False
        self._request_bytes=b''
        layout=_layout(self,'Permanently deleting')
        self.status=_label('Checking the selected wallets…')
        layout.addWidget(self.status)
        self.bar=QProgressBar(self)
        self.bar.setRange(0,0)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)
        self.paths=QPlainTextEdit(self)
        self.paths.setReadOnly(True)
        self.paths.setAccessibleName('Wallets being permanently deleted')
        self.paths.setPlainText('\n'.join(self.names))
        self.paths.setMinimumHeight(70)
        self.paths.setMaximumHeight(96)
        layout.addWidget(self.paths)
        layout.addWidget(_label(
            'Deleting a persistent wallet cannot be undone. The process must '
            'complete safely before this window can close. It will close '
            'automatically on success.',
            'note'
        ))
        layout.addStretch(1)
        row=QHBoxLayout()
        row.addStretch(1)
        self.close_button=QPushButton('Deleting…',self)
        self.close_button.setEnabled(False)
        self.close_button.clicked.connect(self.reject)
        row.addWidget(self.close_button)
        layout.addLayout(row)
        self.resize(620,340)

    def launch(self):
        if self.worker is not None or self.completed:return
        request={'wallets':list(self.names),
                 'confirmed':True,'profile':'three-pass-best-effort'}
        self._request_bytes=(json.dumps(request)+'\n').encode('utf-8')
        self.worker=QProcess(self)
        self.worker.setProgram('/usr/bin/pkexec')
        self.worker.setArguments(['/usr/libexec/core-node-admin','wallet-delete'])
        self.worker.started.connect(self.started)
        self.worker.finished.connect(self.operation_finished)
        self.worker.errorOccurred.connect(self.process_error)
        self.status.setText('Checking the wallets, stopping Bitcoin Core cleanly, '
                            'then overwriting the selected wallet files…')
        self.worker.start()

    def started(self):
        worker=self.worker
        if worker is None:return
        worker.write(self._request_bytes)
        worker.closeWriteChannel()
        self._request_bytes=b''

    def process_error(self,error):
        if self.worker is None:return
        if error==QProcess.FailedToStart:
            self._finish_error('The wallet deletion helper could not start. No deletion was confirmed.')

    def _detach_worker(self):
        # QProcess.finished means the child is finished even if the state
        # property has not propagated to our old cleanup() path. Never retain
        # the process pointer as an artificial reason to block Close.
        process=self.worker
        self.worker=None
        self._request_bytes=b''
        if process is not None:
            process.deleteLater()

    def _finish_error(self,text):
        self._detach_worker()
        self.bar.setRange(0,100)
        self.bar.setValue(0)
        self.status.setText(text)
        self.close_button.setEnabled(True)
        self.close_button.setText('Close')

    def operation_finished(self,exit_code,exit_status):
        if self.worker is None:return
        raw=bytes(self.worker.readAllStandardOutput())
        self._detach_worker()
        if exit_code==0 and exit_status==QProcess.NormalExit:
            try:record=json.loads(raw)
            except (ValueError,TypeError):record=None
            if isinstance(record,dict) and record.get('ok') is True \
               and record.get('removed_wallets')==list(self.names):
                self.completed=True
                self.bar.setRange(0,100)
                self.bar.setValue(100)
                self.status.setText('Selected wallets were permanently deleted.')
                # The progress dialog disappears just like on Vault; no
                # second inert, impossible-to-close confirmation window.
                super().accept()
                return
        self.bar.setRange(0,100)
        self.bar.setValue(0)
        self.status.setText(
            'Deletion was refused or did not complete. If deletion already started, '
            'Bitcoin Core may remain stopped to avoid opening incomplete data. '
            'Review the remaining wallets and Node log before trying again.'
        )
        self.close_button.setEnabled(True)
        self.close_button.setText('Close')

    def reject(self):
        if self.worker is not None:
            self.status.setText(
                'Deletion is still running. Complete the operation before closing '
                'this window to avoid incomplete wallet data.'
            )
            return
        super().reject()

    def closeEvent(self,event):
        if self.worker is not None:
            event.ignore()
        else:
            super().closeEvent(event)


def main(argv=None):
    argv=sys.argv[1:] if argv is None else argv
    app=QApplication.instance() or QApplication(['bitcoin-core-wallet-delete'])
    from ui import configure_ui
    configure_ui(app)
    try:
        check_core_view()
        names=selected_wallets(argv)
    except (ValueError,OSError,RuntimeError) as exc:
        QMessageBox.warning(None,'Bitcoin Core wallets only',
            str(exc) if isinstance(exc,ValueError)
            else 'Core wallet storage is not available. Open Files and try again.')
        return 2

    confirmation=WalletDeletionDialog(names)
    if confirmation.exec()!=QDialog.Accepted:
        return 0
    progress=WalletDeletionProgress(names)
    QTimer.singleShot(0,progress.launch)
    progress.exec()
    return 0 if progress.completed else 1


if __name__=='__main__':
    raise SystemExit(main())
