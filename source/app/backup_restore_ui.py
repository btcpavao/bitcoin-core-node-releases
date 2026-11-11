"""One navigation home for the four distinct transfer workflows."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFrame

class BackupRestoreDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        from ui import STYLE,branding_file
        from PySide6.QtGui import QIcon
        from desktop_surface import optical_icon
        self.setWindowTitle('Backup and Restore');self.setStyleSheet(STYLE);self.resize(720,540)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint,True)
        layout=QVBoxLayout(self);layout.setContentsMargins(22,18,22,16);layout.setSpacing(12)
        title=QLabel('Backup and Restore');title.setObjectName('Title');layout.addWidget(title)
        hint=QLabel('Move your setup to another Node. Choose a category. Encryption is optional for wallets and configuration backups. Backup export has no read-back verification pass; restore checks remain enabled.')
        hint.setWordWrap(True);layout.addWidget(hint)
        self.actions={}
        rows=[('Blockchain','Downloaded blocks, block index and chainstate. No wallets.','chain'),
              ('Watch-only wallets','All supported watch-only wallets, labels and history. No signing wallets.','watch'),
              ('Bitcoin Core configuration','Portable Core preferences. No network passwords or wallet registrations.','core'),
              ('Node configuration','Wi-Fi passwords, Ethernet, WireGuard/privacy, time zone and desktop preferences; also includes portable Core preferences.','settings')]
        for title,description,kind in rows:
            frame=QFrame();row=QHBoxLayout(frame);row.setContentsMargins(0,7,0,7)
            images={'chain':'icons/settings-chain-backup.png','watch':'bitcoin-ui.png','core':'icons/settings-software-updates.png','settings':'icons/settings-network-connections.png'}
            icon=QLabel();icon.setFixedSize(48,48);icon.setAlignment(Qt.AlignCenter)
            icon.setPixmap(optical_icon(QIcon(str(branding_file(images[kind]))),44))
            row.addWidget(icon)
            text=QVBoxLayout();label=QLabel(title);label.setStyleSheet('font-weight:600;')
            sub=QLabel(description);sub.setObjectName('Muted');sub.setWordWrap(True)
            text.addWidget(label);text.addWidget(sub);row.addLayout(text,1)
            for importing in (False,True):
                action='Restore' if importing else 'Backup'
                button=QPushButton(action);button.setFixedWidth(106)
                button.setAccessibleName(action+' '+title)
                button.clicked.connect(lambda checked=False,k=kind,i=importing:self.open_transfer(k,i))
                row.addWidget(button);self.actions[(kind,importing)]=button
            layout.addWidget(frame)
        layout.addStretch();back=QPushButton('Back to Settings');back.clicked.connect(self.go_back);layout.addWidget(back,0,Qt.AlignLeft)

    def go_back(self):
        from modeless import root_of
        root=root_of(self);self.reject()
        if hasattr(root,'settings'):root.settings()

    def open_transfer(self,kind,importing):
        from modeless import open_window
        def create():
            if kind=='chain':
                from chain_ui import ChainDialog
                return ChainDialog('import' if importing else 'backup',self)
            if kind=='watch':
                from watch_backup_ui import WatchBackupDialog
                return WatchBackupDialog(self,importing=importing)
            from settings_snapshot_ui import SettingsSnapshotDialog
            return SettingsSnapshotDialog(self,scope='core' if kind=='core' else 'settings',importing=importing)
        return open_window(self,f'transfer-{kind}-{int(importing)}',create)
