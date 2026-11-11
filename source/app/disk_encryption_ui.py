"""Explain the actual disk status without offering unsafe live root conversion."""
from PySide6.QtWidgets import QDialog,QLabel,QPushButton,QVBoxLayout
from disk_encryption import status


class DiskEncryptionDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Disk Encryption');self.resize(600,310)
        layout=QVBoxLayout(self);layout.setContentsMargins(24,24,24,24);layout.setSpacing(18)
        title=QLabel('Disk Encryption');title.setObjectName('Title');layout.addWidget(title)
        try:state=status()
        except (OSError,ValueError,KeyError,RuntimeError):state='unknown'
        except Exception:state='unknown'
        texts={
            'encrypted':('System disk encryption is enabled.',
                         'Enter the disk password when you turn on or restart this computer. '
                         'If a login password is set, enter it on the next screen.'),
            'plain':('This system disk is not encrypted.',
                     'For an optional password at login, open Settings → Login Password. '
                     'A login password does not encrypt the system disk.'),
            'live':('Running from the installation USB.',
                    'The installer does not ask for a password. After installation, you can set '
                    'an optional login password in Settings → Login Password.'),
            'unknown':('Disk encryption status could not be checked.',
                       'Please check the installed system disk before relying on disk encryption.')}
        summary,detail=texts[state]
        for text in (summary,detail):
            label=QLabel(text);label.setWordWrap(True);layout.addWidget(label)
        layout.addStretch(1)
        back=QPushButton('Back to Settings');back.clicked.connect(self.reject);layout.addWidget(back)
