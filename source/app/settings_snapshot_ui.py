"""One Settings entry for encrypted portable backup and reviewed boot-time import."""
import json
from pathlib import Path
from PySide6.QtCore import QProcess,Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,
                              QLineEdit,QCheckBox,QPlainTextEdit,QProgressBar)

class SettingsSnapshotDialog(QDialog):
    def __init__(self,parent=None,*,scope='settings',importing=False):
        super().__init__(parent)
        assert scope in ('settings','core')
        self.scope=scope
        from ui import STYLE
        self.setStyleSheet(STYLE);caption='Bitcoin Core Configuration' if scope=='core' else 'Node Configuration'
        self.setWindowTitle(caption);self.resize(720,620);self.setWindowFlag(Qt.WindowMinimizeButtonHint,True)
        self.process=None;self.busy=False;self.preview=None;self.action=None
        self.buffer=bytearray();self.error=bytearray();self.result=None;self.cancellable=True
        layout=QVBoxLayout(self);layout.setContentsMargins(22,18,22,16);layout.setSpacing(10)
        title=QLabel(caption);title.setObjectName('Title');layout.addWidget(title)
        description=QLabel('Transfer portable Bitcoin Core preferences without wallets or network credentials.' if scope=='core' else 'Move your Node configuration to another computer. The backup can include saved Wi-Fi passwords and managed WireGuard configuration.');description.setWordWrap(True);layout.addWidget(description)
        self.mode=QComboBox();self.mode.addItems(['Create settings backup','Import settings backup']);layout.addWidget(self.mode)
        row=QHBoxLayout();self.path=QLineEdit();self.path.setReadOnly(True);self.path.setAccessibleName('Settings backup path')
        self.choose_button=QPushButton('Choose folder…');self.choose_button.clicked.connect(self.choose)
        row.addWidget(self.path,1);row.addWidget(self.choose_button);layout.addLayout(row)
        self.encrypt=QCheckBox('Encrypt backup (optional)');self.encrypt.setChecked(False);layout.addWidget(self.encrypt)
        password_row=QHBoxLayout()
        self.password=QLineEdit();self.password.setEchoMode(QLineEdit.Password);self.password.setPlaceholderText('Backup passphrase');self.password.setAccessibleName('Settings backup passphrase')
        self.repeat=QLineEdit();self.repeat.setEchoMode(QLineEdit.Password);self.repeat.setPlaceholderText('Repeat passphrase');self.repeat.setAccessibleName('Confirm settings backup passphrase')
        password_row.addWidget(self.password);password_row.addWidget(self.repeat);layout.addLayout(password_row)
        self.notice=QLabel();self.notice.setWordWrap(True);self.notice.setObjectName('Muted');layout.addWidget(self.notice)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(110);self.details.setAccessibleName('Settings backup review');layout.addWidget(self.details)
        self.confirm=QCheckBox('I trust this backup and approve the settings shown above.');layout.addWidget(self.confirm)
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.hide();layout.addWidget(self.progress)
        self.feedback=QLabel();self.feedback.setWordWrap(True);self.feedback.setTextFormat(Qt.PlainText);layout.addWidget(self.feedback)
        layout.addStretch()
        status=QHBoxLayout();self.status_button=QPushButton('Check pending restore');self.cancel_pending=QPushButton('Cancel pending restore');self.cancel_pending.hide()
        self.status_button.clicked.connect(lambda:self.run('settings-status',{}));self.cancel_pending.clicked.connect(lambda:self.run('settings-cancel',{}))
        status.addWidget(self.status_button);status.addWidget(self.cancel_pending);status.addStretch();layout.addLayout(status)
        buttons=QHBoxLayout();self.back=QPushButton('Back to Backup and Restore');self.back.clicked.connect(self.go_back)
        self.cancel_job=QPushButton('Cancel operation');self.cancel_job.clicked.connect(self.request_cancel);self.cancel_job.hide()
        self.start=QPushButton('Save backup');self.start.clicked.connect(self.begin)
        buttons.addWidget(self.back);buttons.addWidget(self.cancel_job);buttons.addStretch();buttons.addWidget(self.start);layout.addLayout(buttons)
        self.encrypt.toggled.connect(self.encryption_changed)
        self.path.textChanged.connect(self.path_changed)
        self.mode.currentIndexChanged.connect(self.changed)
        self.password.textChanged.connect(self.invalidate);self.repeat.textChanged.connect(self.ready)
        self.confirm.toggled.connect(self.ready);self.changed();self.mode.setCurrentIndex(int(importing))

    def changed(self):
        self.path.clear();self.password.clear();self.repeat.clear();self.invalidate()
        importing=self.mode.currentIndex()==1
        self.repeat.setVisible(not importing);self.confirm.setVisible(importing)
        self.choose_button.setText('Choose backup…' if importing else 'Choose folder…')
        self.path.setPlaceholderText('Select a .json or .gpg backup…' if importing else 'Select a USB drive or destination folder…')
        self.notice.setText('Import is reviewed first, then applied on the next restart. Current connections stay unchanged until then. Static IPs or a shared WireGuard key may conflict if both computers remain online.' if importing else 'Use a separate strong passphrase, for example random words from KeePassXC. Keep it separately: without it, the settings backup cannot be opened.')
        self.details.setPlainText('Included: time zone and automatic time, keyboard, display scale, mouse preferences, saved Wi-Fi/Ethernet profiles, Node privacy and WireGuard, supported Bitcoin Core preferences.\n\nNot included: wallets, blockchain, login password, disk identity/encryption, Bluetooth pairing keys, arbitrary scripts or third-party certificate/VPN plug-ins.')
        if self.scope=='core':
            self.details.setPlainText('Includes supported Core numeric options and GUI preferences. Excludes wallet registrations, blockchain data, Wi-Fi/VPN secrets, datadir paths and executable configuration hooks.')
        self.update_encryption_controls()
        self.ready()

    def invalidate(self):
        self.preview=None;self.confirm.setChecked(False);self.ready()

    def encrypted(self):
        return self.path.text().lower().endswith('.gpg') if self.mode.currentIndex()==1 else self.encrypt.isChecked()

    def update_encryption_controls(self):
        importing=self.mode.currentIndex()==1;encrypted=self.encrypted()
        self.encrypt.setVisible(not importing)
        self.password.setVisible(encrypted);self.repeat.setVisible(encrypted and not importing)
        if importing:
            self.notice.setText('Encrypted backup: enter its passphrase.' if encrypted else 'Unencrypted backup: restore only a file you trust. A checksum detects damage, not a malicious change.')
        elif encrypted:
            self.notice.setText('Any non-empty passphrase is accepted, including one character. A longer random passphrase is safer. Keep it separately.')
        else:
            self.notice.setText('Not encrypted: anyone with this file can read its contents, including saved Wi-Fi passwords and VPN keys when present. Keep the backup private.')

    def encryption_changed(self,*_):
        self.invalidate();self.update_encryption_controls();self.ready()

    def path_changed(self,*_):
        self.invalidate();self.update_encryption_controls();self.ready()

    def validation_error(self):
        if not self.path.text():return 'Please choose the backup file or destination folder.'
        if self.encrypted():
            if not self.password.text():return 'Please enter a passphrase, or turn encryption off for an unencrypted backup.'
            if self.mode.currentIndex()==0 and self.password.text()!=self.repeat.text():return 'The two passphrases do not match.'
        if self.mode.currentIndex()==1 and self.preview and not self.confirm.isChecked():return 'Please review the contents and confirm restoration.'
        return ''

    def ready(self,*_):
        importing=self.mode.currentIndex()==1
        self.start.setText('Restore on next restart' if importing and self.preview else 'Review backup' if importing else 'Save encrypted backup' if self.encrypted() else 'Save backup')
        self.start.setEnabled(not self.busy)
        self.start.setToolTip(self.validation_error())

    def choose(self):
        if self.mode.currentIndex()==0:
            from usb_dialog import folder_dialog
            from usb_destinations import list_drives,DriveError
            try:drives=list_drives()
            except DriveError:drives=[]
            initial=next((Path(x['mount']) for x in drives if x.get('mount')),Path('/media'))
            chosen=folder_dialog(self,'Choose settings backup destination',initial,drives,writing=True)
        else:
            from media_file_dialog import choose_media_file
            current=Path(self.path.text()).parent if self.path.text() else Path('/media')
            chosen=choose_media_file(self,'Choose backup',str(current),
                                     name_filter='Node backups (*.json *.gpg)')
        if chosen:self.path.setText(str(chosen));self.invalidate();self.feedback.clear()

    def begin(self):
        if self.busy:return
        error=self.validation_error()
        if error:self.feedback.setText(error);return
        request=dict(path=self.path.text(),passphrase=self.password.text() if self.encrypted() else '')
        action='settings-backup' if self.mode.currentIndex()==0 else 'settings-preview'
        if action=='settings-preview' and self.preview:
            if not self.confirm.isChecked():return
            action='settings-import';request.update(confirmed=True,fingerprint=self.preview['fingerprint'])
        self.run(action,request)

    def run(self,action,request):
        if self.busy:return
        if self.scope=='core' and action.startswith('settings-'):action='core-'+action
        self.action=action;self.busy=True;self.result=None;self.buffer.clear();self.error.clear();self.cancellable=True
        self.request=(json.dumps(request)+'\n').encode()
        self.progress.show();self.feedback.setText('Waiting for local authorization…');self.cancel_job.show();self.cancel_job.setEnabled(True)
        for item in (self.mode,self.choose_button,self.encrypt,self.password,self.repeat,self.confirm,self.status_button,self.cancel_pending):item.setEnabled(False)
        self.ready();p=QProcess(self);self.process=p
        p.setProgram('/usr/bin/pkexec');p.setArguments(['/usr/libexec/core-node-admin',action])
        p.started.connect(self.send);p.readyReadStandardOutput.connect(self.read_output);p.readyReadStandardError.connect(self.read_error)
        p.finished.connect(self.completed);p.errorOccurred.connect(self.failed);p.start()

    def send(self):
        self.process.write(self.request);self.request=b''

    def read_error(self):
        self.error.extend(bytes(self.process.readAllStandardError())[:1600-len(self.error)])

    def read_output(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        if len(self.buffer)>32768:self.buffer.clear();self.process.write(b'cancel\n');return
        while b'\n' in self.buffer:
            raw,_,tail=self.buffer.partition(b'\n');self.buffer=bytearray(tail)
            try:row=json.loads(raw)
            except ValueError:continue
            if row.get('event')=='result':self.result=row
            elif row.get('event')=='progress':
                self.cancellable=row.get('cancellable') is True;self.cancel_job.setEnabled(self.cancellable)
                self.feedback.setText(str(row.get('phase','')))

    def failed(self,error):
        if error==QProcess.FailedToStart:
            self.error=bytearray(b'The settings helper could not start.');self.completed(1,None)

    def show_summary(self,value):
        if value.get('scope')=='core':
            self.details.setPlainText('Created: '+value['created_utc']+'\nNetwork: '+value['network']+'\nCore options: '+', '.join(value['options'])+'\nGUI options: '+', '.join(value['gui_options'])+'\n\nNot included:\n'+'\n'.join(value['not_included']))
            return
        lines=[f"Created: {value['created_utc']}",f"Time zone: {value['timezone']} · Automatic time: {'yes' if value['automatic_time'] else 'no'}",
               f"Saved Wi-Fi: {value['wifi']} · Ethernet: {value['ethernet']}",
               f"Node privacy: {value['privacy']} · WireGuard saved: {'yes' if value['wireguard'] else 'no'}",f"Keyboard: {value['keyboard']}",
               '', 'Not included:',*value['not_included']]
        self.details.setPlainText('\n'.join(lines))

    def completed(self,code,_):
        if not self.busy:return
        self.read_output();self.read_error();self.busy=False;self.request=b'';self.progress.hide()
        self.back.setText('Back to Backup and Restore');self.back.setEnabled(True);self.cancel_job.hide()
        for item in (self.mode,self.choose_button,self.encrypt,self.password,self.repeat,self.confirm,self.status_button,self.cancel_pending):item.setEnabled(True)
        result=self.result
        if code==0 and result and result.get('ok'):
            if self.action.removeprefix('core-')=='settings-preview':
                self.preview=result;self.show_summary(result['summary']);self.feedback.setText('Backup verified. Review the contents, then confirm restoration on the next restart.')
            elif self.action.removeprefix('core-')=='settings-backup':
                self.show_summary(result['summary']);self.feedback.setText(('Encrypted' if result.get('encrypted',result['file'].endswith('.gpg')) else 'Unencrypted')+' settings backup saved and verified.\n'+result['file']);self.password.clear();self.repeat.clear()
            elif self.action.removeprefix('core-')=='settings-import':
                self.feedback.setText('Settings are staged. Restart normally to apply them before networking starts. Login password, wallets and blockchain remain local.');self.password.clear();self.repeat.clear();self.cancel_pending.show()
            else:
                self.cancel_pending.setVisible(result.get('pending',False))
                last=result.get('last_result') or {}
                self.feedback.setText('Settings restore is pending. Restart to apply, or cancel it here.' if result.get('pending') else 'No settings restore is pending. '+last.get('message',''))
        else:
            self.feedback.setText(self.error.decode('utf-8','replace').strip() or 'Settings operation failed. No successful transfer was confirmed.')
        self.process.deleteLater();self.process=None;self.ready()

    def request_cancel(self):
        if self.busy and self.cancellable and self.process is not None:
            self.process.write(b'cancel\n');self.cancel_job.setEnabled(False);self.feedback.setText('Cancelling safely…')

    def go_back(self):
        from modeless import back_to_group
        back_to_group(self)

    def reject(self):
        if self.busy:self.showMinimized()
        else:self.password.clear();self.repeat.clear();super().reject()

    def closeEvent(self,event):
        if self.busy:self.showMinimized();event.ignore()
        else:super().closeEvent(event)
