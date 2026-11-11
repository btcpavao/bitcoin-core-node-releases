"""A small Wi-Fi chooser with a separate advanced configuration path."""
import subprocess
import threading
from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QListWidget,
    QListWidgetItem,QPushButton,QLineEdit,QCheckBox,QApplication)
import network_access as network

_live_jobs = set()

class NetworkJob(QThread):
    result = Signal(object)
    error = Signal(str)
    def __init__(self,fn,parent):
        super().__init__(QApplication.instance()); self.fn=fn; self.cancelled=threading.Event()
        _live_jobs.add(self)
    @Slot()
    def dispose(self):
        _live_jobs.discard(self)
        self.deleteLater()
    def run(self):
        try:
            with network.cancellation_scope(self.cancelled): value=self.fn()
            if not self.cancelled.is_set(): self.result.emit(value)
        except network.NetworkCancelled: pass
        except network.NetworkError as exc:
            if not self.cancelled.is_set(): self.error.emit(str(exc))
        except Exception:
            if not self.cancelled.is_set(): self.error.emit('Network information is unavailable. Please try again or use Advanced settings.')
        finally: self.fn=None

class NetworkDialog(QDialog):
    def __init__(self,parent=None,for_core=False,for_settings=False):
        super().__init__(parent)
        self.setWindowTitle('Connect to a network')
        self.resize(660,560); self.job=None; self.for_core=for_core; self.for_settings=for_settings; self.connected=False; self.selected_key=None; self._closed=False
        layout=QVBoxLayout(self); layout.setContentsMargins(24,20,24,20); layout.setSpacing(12)
        title=QLabel('Connect to a network'); title.setObjectName('Title'); layout.addWidget(title)
        self.intro=QLabel('Connect to Wi-Fi or plug in an Ethernet cable to download and validate Bitcoin blocks.' if for_core else 'Choose a Wi-Fi network and connect. Ethernet connects automatically when a cable is plugged in.')
        self.intro.setWordWrap(True); layout.addWidget(self.intro)
        self.status=QLabel('Looking for available networks…'); self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText); layout.addWidget(self.status)
        self.hotspot_hint=QLabel(
            'iPhone hotspot tip: On iPhone open Settings → Personal Hotspot, '
            'turn on Allow Others to Join and Maximize Compatibility, then leave '
            'that screen open while connecting.')
        self.hotspot_hint.setWordWrap(True)
        self.hotspot_hint.setObjectName('Muted')
        self.hotspot_hint.hide()
        layout.addWidget(self.hotspot_hint)
        self.list=QListWidget(); self.list.setAccessibleName('Available Wi-Fi networks')
        self.list.setStyleSheet('QListWidget { background:#151515; border:1px solid #555; border-radius:8px; } QListWidget::item { padding:10px; } QListWidget::item:selected { background:#343434; color:#fff; }')
        self.list.currentItemChanged.connect(self.selection); layout.addWidget(self.list,1)
        self.password=QLineEdit(); self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText('Wi-Fi password (leave blank for a saved network)')
        self.password.setAccessibleName('Wi-Fi password'); layout.addWidget(self.password)
        self.show_password=QCheckBox('Show password')
        self.show_password.toggled.connect(lambda checked:self.password.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password))
        layout.addWidget(self.show_password)
        row=QHBoxLayout(); self.refresh=QPushButton('Refresh'); self.enable=QPushButton('Enable Wi-Fi'); self.connect_button=QPushButton('Connect')
        for button in (self.refresh,self.enable,self.connect_button): row.addWidget(button)
        layout.addLayout(row)
        self.refresh.clicked.connect(self.scan)
        self.enable.clicked.connect(lambda:self.run(network.enable_wifi,lambda _:self.after_scan()))
        self.connect_button.clicked.connect(self.connect_selected)
        footer=QHBoxLayout(); self.advanced=QPushButton('Advanced settings'); self.done_button=QPushButton('Use Core offline' if for_core else 'Back to Settings' if for_settings else 'Done')
        footer.addWidget(self.advanced); footer.addStretch(); footer.addWidget(self.done_button); layout.addLayout(footer)
        self.advanced.clicked.connect(self.open_advanced); self.done_button.clicked.connect(self.accept)
        for b in self.findChildren(QPushButton): b.setAutoDefault(False)
        self.password.returnPressed.connect(self.connect_selected)
        self.selection()
        self.timer=QTimer(self); self.timer.setInterval(10000); self.timer.timeout.connect(self.idle_scan); self.timer.start()
        QTimer.singleShot(0,self.scan)

    def busy(self,value):
        for w in (self.list,self.refresh,self.enable,self.password,self.show_password,self.connect_button):
            w.setEnabled(not value)
        if not value: self.selection()

    def run(self,fn,done,*,quiet=False):
        if self._closed or self.job is not None: return
        # When connected, a status-only probe must neither hide the active
        # connection nor disable the network chooser.
        if not quiet: self.busy(True)
        self.job_quiet=quiet
        self.job=NetworkJob(fn,self); self.completion=done
        self.job.result.connect(self.received)
        self.job.error.connect(self.failed)
        self.job.finished.connect(self.finished_job)
        # Clear dialog state on the GUI thread before deleting the worker.
        # The application owns unfinished jobs even if this dialog is destroyed.
        self.job.finished.connect(self.job.dispose)
        self.job.start()

    @Slot(object)
    def received(self,value):
        if not self._closed: self.completion(value)

    @Slot(str)
    def failed(self,text):
        if not self._closed: self.status.setText(text)

    @Slot()
    def finished_job(self):
        if self.job is not self.sender(): return
        quiet=self.job_quiet
        self.job=None; self.completion=None; self.job_quiet=False
        if not self._closed:
            if not quiet: self.busy(False)
            else: self.selection()

    def after_scan(self):
        QTimer.singleShot(50,self.scan)

    def idle_scan(self):
        if self._closed or self.job is not None:return
        if self.connected:
            # Poll the live connection without forcing repeated Wi-Fi scans.
            # Keep the displayed networks and success message stable.
            self.run(lambda:network.snapshot(scan=False),self.status_only,quiet=True)
        elif self.list.currentItem() is None and not self.password.hasFocus():
            # Background discovery should not overwrite the visible guidance.
            self.run(network.snapshot,self.display)

    def scan(self):
        if self._closed or self.job is not None: return
        # Only the user's Refresh action explicitly searches for new networks.
        if not self.connected:
            self.status.setText('Looking for available networks… You can close this window at any time.')
        self.run(network.snapshot,self.display)

    @staticmethod
    def ap_label(ap):
        text=ap['ssid']+'  ·  '+str(ap['signal'])+'%  ·  '+(
            ap['security'] if ap['security'] not in ('','--') else 'Open')
        return text+('  ·  Connected' if ap['active'] else '')

    def status_only(self,data):
        """Status-only check: never clear the AP list or initiate a scan."""
        previous=self.connected
        self.connected=bool(data['connected'])
        self.done_button.setText(('Continue to Bitcoin Core' if self.connected else 'Use Core offline')
                                 if self.for_core else 'Back to Settings' if self.for_settings else 'Done')
        if self.connected:
            names=[str(x) for x in data['connections'] if x]
            label='Connected to '+', '.join(names)+'.' if names else 'Connected to a network.'
            if self.status.text()!=label:self.status.setText(label)
        elif previous:
            self.status.setText('Connection lost. Press Refresh to search for available networks.')
            self.list.blockSignals(True)
            for index in range(self.list.count()):
                item=self.list.item(index)
                access=item.data(Qt.UserRole)
                if access['active']:
                    access=dict(access,active=False)
                    item.setData(Qt.UserRole,access)
                    item.setText(self.ap_label(access))
            self.list.blockSignals(False)

    def connected_result(self,data,selected):
        """Activation succeeded: keep cached APs and mark the selected one."""
        self.status_only(data)
        if not self.connected:return
        self.list.blockSignals(True)
        for index in range(self.list.count()):
            item=self.list.item(index)
            access=item.data(Qt.UserRole)
            same=(access['ssid']==selected['ssid'] and access['device']==selected['device'])
            updated=dict(access,active=same)
            item.setData(Qt.UserRole,updated)
            item.setText(self.ap_label(updated))
        self.list.blockSignals(False)
        self.selection()

    def display(self,data):
        key=self.selected_key
        self.connected=data['connected']
        self.done_button.setText(('Continue to Bitcoin Core' if self.connected else 'Use Core offline') if self.for_core else 'Back to Settings' if self.for_settings else 'Done')
        if self.connected: text='Connected to '+', '.join(data['connections'])+'.'
        elif not data['wifi']: text='No Wi-Fi adapter detected. Plug in Ethernet, or check the adapter in Advanced settings.'
        elif not data['radio']: text='Wi-Fi is off. Enable Wi-Fi to find networks; also check the laptop’s wireless switch.'
        elif data.get('unavailable'): text='Wi-Fi adapter is unavailable. Check the laptop wireless switch; the driver, firmware and Wi-Fi service must be available.'
        elif not data['aps']: text='No Wi-Fi networks found. Move closer to your router and refresh, or use Advanced settings for a hidden network.'
        else: text='Select your network below.'
        self.status.setText(text); self.enable.setVisible(data['wifi'] and not data['radio'])
        self.list.blockSignals(True)
        self.list.clear()
        for ap in data['aps']:
            item=QListWidgetItem(self.ap_label(ap)); item.setData(Qt.UserRole,ap); self.list.addItem(item)
            if key==(ap['ssid'],ap['security'],ap['device']): self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.selection()

    def selection(self,*_):
        item=self.list.currentItem(); ap=item.data(Qt.UserRole) if item else None
        key=(ap['ssid'],ap['security'],ap['device']) if ap else None
        if key != self.selected_key:
            self.password.clear(); self.show_password.setChecked(False)
        self.selected_key=key
        self.hotspot_hint.setVisible(bool(ap and 'iphone' in ap['ssid'].casefold()))
        secure=bool(ap and ap['security'] not in ('','--'))
        enterprise=bool(ap and ('802.1X' in ap['security'] or 'WEP' in ap['security']))
        self.password.setVisible(secure and not enterprise); self.show_password.setVisible(secure and not enterprise)
        self.connect_button.setEnabled(bool(ap and not ap['active']) and self.job is None)
        self.connect_button.setText('Configure network' if enterprise else 'Connect')
        if not secure: self.password.clear()
        if ap and ap['active']: self.password.clear()

    def connect_selected(self):
        if self.job is not None: return
        item=self.list.currentItem()
        if not item: return
        ap=item.data(Qt.UserRole)
        if ap['active']: return
        if '802.1X' in ap['security'] or 'WEP' in ap['security']:
            self.open_advanced(); return
        password=self.password.text(); self.password.clear(); self.show_password.setChecked(False)
        self.status.setText('Connecting to '+ap['ssid']+'…')
        def work():
            network.connect(ap,password)
            # Activation is already complete. A driver refusing an immediate
            # rescan must not turn a successful connection into an error.
            return network.snapshot(scan=False)
        # A no-rescan snapshot has no AP list; display() used to clear the
        # list after connecting and make the next polling scan visible.
        self.run(work,lambda data:self.connected_result(data,ap))

    def open_advanced(self):
        try: subprocess.Popen(['/usr/bin/nm-connection-editor'])
        except OSError:
            self.status.setText('Advanced settings could not open.'); return
        # Hand control to the native editor without leaving a hidden modal
        # chooser blocking Home when the editor is closed or minimized.
        self.reject()

    def done(self,result):
        # Never keep a hidden modal window blocking Home while a worker waits.
        self._closed=True
        self.timer.stop()
        if self.job is not None: self.job.cancelled.set()
        self.password.clear()
        super().done(result)

    def closeEvent(self,event):
        self.reject()
        event.accept()
