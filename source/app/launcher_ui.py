"""Native launcher cards and the grouped Settings menu."""
from PySide6.QtCore import Qt, QSize
from pathlib import Path
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (QApplication, QDialog, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QStyle, QVBoxLayout)
from desktop_surface import optical_icon


def themed_icon(names, fallback):
    for name in names:
        if str(name).startswith('/') and Path(name).is_file():
            icon=QIcon(str(name))
            if not icon.isNull():
                return icon
        for candidate in (name,name+'-symbolic'):
            icon=QIcon.fromTheme(candidate)
            if icon.isNull():continue
            if candidate.endswith('-symbolic'):
                pixmap=icon.pixmap(QSize(64,64))
                if pixmap.isNull():continue
                painter=QPainter(pixmap);painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
                painter.fillRect(pixmap.rect(),QColor('#f2f2f2'));painter.end()
                icon=QIcon(pixmap)
            return icon
    return QApplication.style().standardIcon(fallback)


class StatusLabel(QLabel):
    def __init__(self,text=''):
        super().__init__(text)
        self.setVisible(bool(text))
    def setText(self,text):
        super().setText(text)
        self.setVisible(bool(text))


class ToolCard(QPushButton):
    def __init__(self,title,description,icon,action):
        super().__init__()
        self.setObjectName('ToolCard');self.setAccessibleName(title)
        self.setAccessibleDescription(description);self.setToolTip(description)
        self.setCursor(Qt.PointingHandCursor);self.setMinimumWidth(0)
        self.setFixedHeight(148)
        layout=QVBoxLayout(self);layout.setContentsMargins(7,9,7,9);layout.setSpacing(3)
        mark=QLabel();mark.setAlignment(Qt.AlignCenter);mark.setFixedHeight(42)
        mark.setPixmap(optical_icon(icon,42))
        label=QLabel(title);label.setObjectName('CardTitle');label.setWordWrap(True)
        label.setMinimumHeight(45);label.setMaximumHeight(55)
        detail=QLabel(description);detail.setObjectName('CardDescription');detail.setWordWrap(True)
        detail.setMinimumHeight(28)
        for item in [mark,label,detail]:
            item.setAlignment(Qt.AlignCenter);item.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(item)
        self.clicked.connect(action)


class NodeSettingsDialog(QDialog):
    """One Settings screen, Home-style centered cards, and a grouped backup menu."""
    def __init__(self,parent):
        super().__init__(parent)
        from ui import STYLE, branding_file
        self.selected_action=None
        self.setWindowTitle('Settings')
        self.setStyleSheet(STYLE + """
            QPushButton#SettingsExit {
                padding:4px 12px; font-size:12px; border-radius:6px; min-width:0px;
            }
        """)
        screen=QApplication.primaryScreen()
        available=screen.availableGeometry() if screen else None
        width=min(960,max(600,available.width()-40)) if available else 960
        height=min(555,max(480,available.height()-40)) if available else 555
        self.resize(width,height)
        # Match Home's vertically centered title, subtitle and card cluster.
        # Keep the Exit control anchored to the bottom-right independently.
        layout=QVBoxLayout(self);layout.setContentsMargins(18,15,18,13);layout.setSpacing(0)
        layout.addStretch(1)
        heading=QLabel('Settings');heading.setObjectName('Title')
        heading.setAlignment(Qt.AlignCenter);layout.addWidget(heading)
        layout.addSpacing(8)
        subtitle=QLabel('Configure Bitcoin Core, network connections, devices, backups and system updates.')
        subtitle.setObjectName('Muted');subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignCenter);layout.addWidget(subtitle)
        layout.addSpacing(24)
        bitcoin_icon=str(branding_file('bitcoin-ui.png'))
        def bundled(name):
            return (str(branding_file('icons/'+name)),)
        # Read left-to-right, first row followed by second row.
        actions=[
            ('Network Connections','Wi-Fi, Ethernet and IP',bundled('settings-network-connections.png'),QStyle.SP_ComputerIcon,lambda:parent.network_status(from_settings=True)),
            ('Bitcoin Core Network & Privacy','Tor, WireGuard and privacy',(bitcoin_icon,),QStyle.SP_ComputerIcon,parent.privacy),
            ('Bitcoin Core Status','Blocks, peers and validation',(bitcoin_icon,),QStyle.SP_ComputerIcon,lambda:parent.refresh(from_settings=True)),
            ('Date & Time','System clock and time zone',bundled('settings-date-time.png'),QStyle.SP_FileDialogDetailedView,parent.date_time),
            ('Backup and Restore','Blockchain, wallets and configuration',bundled('settings-chain-backup.png'),QStyle.SP_DialogSaveButton,parent.backup_restore),
            ('Bluetooth Devices','Pair mice and keyboards',bundled('settings-bluetooth.png'),QStyle.SP_ComputerIcon,lambda:parent.bluetooth_devices(from_settings=True)),
            ('Mouse Speed','Bluetooth and USB pointer speed',bundled('settings-mouse.png'),QStyle.SP_ComputerIcon,parent.mouse_settings),
            ('Login Password','Choose password or automatic login',bundled('settings-login.png'),QStyle.SP_DialogApplyButton,parent.login_settings),
            ('Software Updates','Debian, apps and KeePassXC',bundled('settings-software-updates.png'),QStyle.SP_BrowserReload,parent.updates)
        ]
        self.card_order=tuple(title for title,_,_,_,_ in actions)
        grid=QGridLayout();grid.setSpacing(14);self.grid=grid
        self.cards={}
        for i,(title,description,names,fallback,action) in enumerate(actions):
            card=ToolCard(title,description,themed_icon(names,fallback),
                          lambda checked=False,a=action:self.choose(a))
            self.cards[title]=card
            card.setFixedHeight(148)
        self.reflow_cards(width)
        layout.addLayout(grid)
        layout.addStretch(1)
        bottom=QHBoxLayout();bottom.addStretch(1)
        self.exit_button=QPushButton('Exit')
        self.exit_button.setObjectName('SettingsExit')
        self.exit_button.setAccessibleName('Exit Settings')
        self.exit_button.setToolTip('Close Settings and return to Home.')
        self.exit_button.setFixedSize(78,32)
        self.exit_button.clicked.connect(self.reject)
        bottom.addWidget(self.exit_button,0,Qt.AlignRight)
        layout.addLayout(bottom)

    def reflow_cards(self,width):
        columns=5 if width>=740 else 3
        while self.grid.count():self.grid.takeAt(0)
        for col in range(10):self.grid.setColumnStretch(col,1 if col<columns*2 else 0)
        cards=list(self.cards.values())
        for i,card in enumerate(cards):
            row=i//columns;count=min(columns,len(cards)-row*columns)
            self.grid.addWidget(card,row,(columns-count)+(i%columns)*2,1,2)

    def resizeEvent(self,event):
        if hasattr(self,'grid'):self.reflow_cards(event.size().width())
        super().resizeEvent(event)

    def choose(self,action):
        # Settings is the parent menu, not a one-shot launcher. Keep this modal
        # menu alive while a child dialog runs. Closing the child (Back, Cancel,
        # Apply then Back, Escape or window close) returns here automatically.
        # Only the explicit Exit button closes Settings and returns Home.
        self.selected_action=action
        action()
