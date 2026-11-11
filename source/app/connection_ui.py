"""An always-visible, clickable peer indicator beside the system clock."""
from PySide6.QtCore import QTimer, Qt, QSize, Slot
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout
from desktop_surface import HintButton
from connection_state import snapshot


class ConnectionButton(HintButton):
    def __init__(self, home):
        super().__init__('Checking', 'Bitcoin peer connection status. Click for connection details.',
                         home.show_card_help, home.hide_card_help)
        self.home = home
        self.job = None
        self.dialog = None
        self.record = dict(state='unknown', label='Checking', explanation='Checking Bitcoin peer connectivity…')
        self.setObjectName('PeerConnection')
        self.setAccessibleName('Bitcoin peer connection status')
        self.setCursor(Qt.PointingHandCursor)
        self.compact=False
        self.setFixedSize(208, 26); self.setIconSize(QSize(16, 16))
        self.setStyleSheet('''QPushButton#PeerConnection { background:transparent; color:#ddd;
            border:1px solid transparent; border-radius:7px; padding:3px; font-size:11px; font-weight:600; }
            QPushButton#PeerConnection:hover { background:#202020; border-color:#555; }
            QPushButton#PeerConnection:focus { border-color:#f7931a; }''')
        self.clicked.connect(self.show_details)
        self.timer = QTimer(self); self.timer.setInterval(5000); self.timer.timeout.connect(self.poll)
        self.timer.start(); QTimer.singleShot(0, self.poll)
        self.update_record(self.record)

    def poll(self):
        if self.job is not None:
            return
        from ui import Job
        self.job = Job(snapshot, self)
        self.job.success.connect(self.update_record)
        self.job.failure.connect(self.failed)
        self.job.finished.connect(self.finished)
        self.job.start()

    @Slot(str)
    def failed(self, _message):
        self.update_record(dict(state='unknown', label='Unknown', explanation='Connection status is unavailable. Open Network Settings to inspect the connection.'))

    @Slot()
    def finished(self):
        job = self.sender()
        if self.job is job:
            self.job = None
        job.deleteLater()

    def set_compact(self,compact):
        compact=bool(compact)
        if compact==self.compact:return
        self.compact=compact
        # Full wording remains readable at lower screen resolutions.
        # Full status label must stay on ONE line above the clock, at all sizes.
        self.setFixedSize(208,26)
        self.render_label()

    def render_label(self):
        state=self.record['state']
        if state=='online':
            text='Bitcoin Core is online'
        elif state in ('stopped','offline'):
            text='Bitcoin Core is offline'
        elif state=='starting':
            text='Bitcoin Core is starting'
        elif state=='error':
            text='Bitcoin Core error'
        else:
            text='Checking Bitcoin Core'
        self.setText(text)
        self.setAccessibleName(text.replace('\n',' '))

    @Slot(object)
    def update_record(self, record):
        self.record = record
        self.render_label()
        # High-contrast, solid dots. Green is intentionally vivid against black,
        # red is equally saturated; unknown/starting never claim to be online.
        color = {'online': '#1CF46B', 'offline': '#FF5151', 'stopped':'#FF5151', 'error': '#FF5151',
                 'starting': '#FFB545'}.get(record['state'], '#9A9A9A')
        mark = QPixmap(18, 18); mark.fill(Qt.transparent)
        painter = QPainter(mark); painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen); painter.setBrush(QColor(color))
        painter.drawEllipse(2, 2, 14, 14); painter.end()
        self.setIcon(QIcon(mark))
        explanation = self.text().replace('\n',' ') + '. ' + record['explanation'] + ' Click for connection details.'
        self.setToolTip(explanation); self.setAccessibleDescription(explanation)
        if self.dialog is not None:
            self.fill_details()

    def fill_details(self):
        r = self.record
        self.detail_status.setText(r['explanation'])
        if hasattr(self,'start_button'):
            service=r.get('service')
            networkactive=r.get('networkactive')
            is_active=service=='active'
            self.start_button.setEnabled(service in ('inactive','failed'))
            self.pause_button.setText('Resume sync' if networkactive is False and is_active
                                      else 'Pause sync')
            self.pause_button.setEnabled(is_active and networkactive is not None)
            self.stop_button.setEnabled(is_active)
            self.restart_button.setEnabled(service in ('active','inactive','failed'))
        rows = [('Bitcoin Core', r.get('version') or r.get('service', 'unknown')),
                ('Peer status', r['label']), ('Connected peers', r.get('peers')),
                ('Outgoing / incoming', str(r.get('outgoing')) + ' / ' + str(r.get('incoming'))),
                ('Bitcoin network activity', r.get('networkactive')),
                ('Wi-Fi / Ethernet', r.get('connections', 'Checking…'))]
        self.details.setPlainText('\n\n'.join(str(k) + ': ' + ('Unavailable' if v is None else str(v)) for k, v in rows)
                                  + ('\n\n' + r['detail'] if r.get('detail') else ''))

    def show_details(self):
        if self.dialog is not None:
            self.dialog.showNormal(); self.dialog.raise_(); self.dialog.activateWindow(); return
        dialog = QDialog(self.home); self.dialog = dialog
        from ui import STYLE
        dialog.setStyleSheet(STYLE); dialog.setWindowTitle('Bitcoin Core'); dialog.resize(720, 560)
        layout = QVBoxLayout(dialog)
        title = QLabel('Bitcoin Core'); title.setObjectName('Title'); layout.addWidget(title)
        self.detail_status = QLabel(); self.detail_status.setWordWrap(True); self.detail_status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.detail_status)
        self.details = QPlainTextEdit(); self.details.setReadOnly(True)
        self.details.setAccessibleName('Bitcoin and operating-system connection details'); layout.addWidget(self.details, 1)
        hint=QLabel('Pause sync disconnects Bitcoin peers without stopping Bitcoin Core. '
                    'Stop shuts down Bitcoin Core cleanly. Restart affects Bitcoin Core only, '
                    'not the Debian computer.')
        hint.setWordWrap(True);hint.setObjectName('Muted')
        layout.addWidget(hint)
        controls=QHBoxLayout();layout.addLayout(controls)
        self.start_button=QPushButton('Start Bitcoin Core')
        self.pause_button=QPushButton('Pause sync')
        self.stop_button=QPushButton('Stop Bitcoin Core')
        self.restart_button=QPushButton('Restart Bitcoin Core')
        self.start_button.setToolTip('Start Bitcoin Core when it is not running.')
        self.pause_button.setToolTip('Pause or resume peer connections; Core continues local operations.')
        self.stop_button.setToolTip('Gracefully stop only Bitcoin Core, preserving disk data.')
        self.restart_button.setToolTip('Gracefully restart only Bitcoin Core.')
        for action,button in [('start',self.start_button),('pause',self.pause_button),
                              ('stop',self.stop_button),('restart',self.restart_button)]:
            button.clicked.connect(lambda _=False,a=action:self.perform_action(a))
            controls.addWidget(button)
        row = QHBoxLayout(); layout.addLayout(row)
        network = QPushButton('Network settings'); network.clicked.connect(self.open_network); row.addWidget(network)
        refresh = QPushButton('Refresh'); refresh.clicked.connect(self.poll); row.addWidget(refresh)
        close = QPushButton('Close'); close.clicked.connect(dialog.accept); row.addWidget(close)
        dialog.finished.connect(self.details_closed)
        self.fill_details(); self.poll(); dialog.show()

    def perform_action(self,action):
        # An external Core shutdown or RPC call must never block the Qt GUI
        # thread, nor overlap existing privileged operations. The user presses
        # each named control deliberately.
        if self.dialog is None:return
        if self.home.job is not None and self.home.job.isRunning():
            self.detail_status.setText('Another Bitcoin Core operation is in progress. Please wait.')
            return
        record=self.record
        service=record.get('service')
        if action in ('pause','resume'):
            if service!='active' or record.get('networkactive') is None:return
            enabled=record.get('networkactive') is False
            label='Resuming Bitcoin peer connections…' if enabled else 'Pausing Bitcoin peer connections…'
            self.detail_status.setText(label)
            def task():
                # RPC changes runtime network activity, not the stored privacy
                # profile; it never starts new OS connections or services.
                from rpc import CoreRPC
                CoreRPC(timeout=7)('setnetworkactive',enabled)
                return enabled
            def done(_result):
                self.detail_status.setText('Peer connections resumed.' if enabled else
                                           'Peer connections paused. Core remains running.')
                self.poll()
                self.home.poll_activity()
            self.home.start(task,done)
            return
        if action not in ('start','stop','restart'):return
        if action=='start' and service not in ('inactive','failed'):return
        if action=='stop' and service!='active':return
        if action=='restart' and service not in ('active','inactive','failed'):return
        if action in ('stop','restart'):
            explanation=('Stop Bitcoin Core cleanly? Blockchain and wallet data stay on disk; '
                         'synchronization stops until you start it again.'
                         if action=='stop' else
                         'Restart Bitcoin Core cleanly? Blockchain and wallet data stay on disk; '
                         'peer connections will reconnect automatically.')
            if QMessageBox.question(
                self.dialog,'Confirm '+action+' Bitcoin Core',explanation,
                QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel
            )!=QMessageBox.Yes:
                return
        self.detail_status.setText(action.title()+' Bitcoin Core requested. Please wait…')
        self.home.control(action)
        QTimer.singleShot(1500,self.poll)

    def open_network(self):
        if self.dialog is not None:
            self.dialog.accept()
        self.home.network_status()

    @Slot(int)
    def details_closed(self, _result):
        dialog = self.dialog; self.dialog = None
        if dialog is not None:
            dialog.deleteLater()
