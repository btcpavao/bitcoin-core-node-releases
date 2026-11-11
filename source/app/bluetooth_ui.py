"""Back-to-Settings navigation around the native Blueman pairing manager."""
import subprocess
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QHBoxLayout, QVBoxLayout


class BluetoothDevicesDialog(QDialog):
    """Keep Settings navigation available while the external manager runs."""

    def __init__(self,parent=None):
        super().__init__(parent)
        from ui import STYLE
        self.setWindowTitle('Bluetooth Devices')
        self.setStyleSheet(STYLE)
        self.resize(610,260)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(22,22,22,22)
        layout.setSpacing(12)
        title=QLabel('Bluetooth Devices')
        title.setObjectName('Title')
        layout.addWidget(title)
        explanation=QLabel(
            'Pair Bluetooth mice and keyboards using the system Bluetooth Manager. '
            'You can leave the manager open while you return to Settings.'
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.status=QLabel('')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setObjectName('Muted')
        layout.addWidget(self.status)
        layout.addStretch(1)
        controls=QHBoxLayout()
        self.open_button=QPushButton('Open Bluetooth Manager')
        self.open_button.clicked.connect(self.open_manager)
        self.back_button=QPushButton('Back to Settings')
        self.back_button.setAccessibleName('Back to Settings')
        self.back_button.clicked.connect(self.reject)
        controls.addWidget(self.open_button)
        controls.addStretch(1)
        controls.addWidget(self.back_button)
        layout.addLayout(controls)
        # Preserve one-click entry from Settings; do not wait for the manager,
        # which is another process with its own window and lifecycle.
        QTimer.singleShot(0,self.open_manager)

    def open_manager(self):
        if not self.isVisible():return
        try:
            subprocess.Popen(['/usr/bin/blueman-manager'],
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             close_fds=True)
            self.status.setText('Bluetooth Manager opened. Pair your device there, then select Back to Settings.')
        except OSError:
            self.status.setText('Bluetooth Manager could not open. Check the installed Bluetooth packages, then try again.')
