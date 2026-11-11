"""Responsive blockchain backup/import progress over the narrow polkit broker."""
import json
from pathlib import Path
import subprocess
from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                              QLineEdit, QProgressBar, QPushButton, QVBoxLayout)


def size_text(value):
    return f'{value / 1024**3:.2f} GiB'


class ChainDialog(QDialog):
    def __init__(self, mode, parent=None):
        super().__init__(parent)
        if mode not in ('backup', 'import'): raise ValueError('Unsupported blockchain operation')
        from ui import STYLE
        self.mode=mode;self.busy=False;self.cancellable=True;self.result=None;self.process=None
        self.buffer=bytearray();self.error=bytearray()
        self.setStyleSheet(STYLE+'''
            QProgressBar { border:1px solid #555; border-radius:6px; background:#151515;
                           text-align:center; color:#f2f2f2; min-height:24px; }
            QProgressBar::chunk { background:#3a774e; border-radius:5px; }
        ''')
        title='Backup Chain State' if mode=='backup' else 'Import Chain State'
        self.setWindowTitle(title);self.resize(640,480);self.setWindowFlag(Qt.WindowMinimizeButtonHint,True)
        layout=QVBoxLayout(self);layout.setContentsMargins(24,20,24,20);layout.setSpacing(12)
        heading=QLabel(title);heading.setObjectName('Title');layout.addWidget(heading)
        text=('Save the downloaded blocks, block index and chainstate to a folder on USB or disk. '
              'Core stops while files are copied and verified. Start it manually after the backup. Each completed snapshot is kept separately.'
              if mode=='backup' else
              'Select the USB drive or a completed backup folder from a Node with the same Bitcoin Core version. The latest completed copy is detected automatically. '
              'The copy is verified before replacing this computer’s blockchain data. Core stops during import.')
        detail=QLabel(text);detail.setWordWrap(True);layout.addWidget(detail)
        note=QLabel('Wallets, passwords and network settings are kept separately. This is a blockchain copy, not a wallet backup.')
        note.setWordWrap(True);note.setObjectName('Muted');layout.addWidget(note)
        row=QHBoxLayout();self.directory=QLineEdit();self.directory.setReadOnly(True)
        self.directory.setAccessibleName('Backup destination' if mode=='backup' else 'Chain backup folder')
        self.directory.setPlaceholderText('Select destination folder…' if mode=='backup' else 'Select USB drive or backup folder…')
        self.browse=QPushButton('Choose folder…');self.browse.clicked.connect(self.choose)
        self.usb=QPushButton('USB / External Drive…')
        self.usb.setAccessibleName('Choose USB stick or external drive')
        self.usb.setToolTip('See connected USB drives, mount a drive if needed, and select its destination folder.')
        self.usb.clicked.connect(self.choose_usb)
        row.addWidget(self.directory,1);row.addWidget(self.browse)
        layout.addLayout(row)
        layout.addWidget(self.usb)
        confirm=('I understand that Core will stop while the backup is created.' if mode=='backup' else
                 'This is my trusted blockchain backup. Replace this Node’s current blockchain data and use the saved pruning setting.')
        self.confirm=QCheckBox(confirm);self.confirm.setAccessibleName('Confirm blockchain operation')
        # A wrapped label makes the long import confirmation fit small displays.
        self.confirm.setText('')
        confirm_row=QHBoxLayout();confirm_row.setSpacing(8)
        confirm_label=QLabel(confirm);confirm_label.setWordWrap(True);confirm_label.setBuddy(self.confirm)
        confirm_row.addWidget(self.confirm,0,Qt.AlignTop);confirm_row.addWidget(confirm_label,1)
        layout.addLayout(confirm_row)
        self.progress=QProgressBar();self.progress.setRange(0,1000);self.progress.setValue(0)
        self.progress.hide();layout.addWidget(self.progress)
        self.feedback=QLabel('');self.feedback.setWordWrap(True);self.feedback.setTextFormat(Qt.PlainText)
        self.feedback.setAccessibleName('Blockchain copy status');layout.addWidget(self.feedback)
        layout.addStretch()
        buttons=QHBoxLayout();self.back=QPushButton('Back to Backup and Restore');self.back.clicked.connect(self.go_back)
        self.cancel_job=QPushButton('Cancel backup' if mode=='backup' else 'Cancel import');self.cancel_job.clicked.connect(self.request_cancel);self.cancel_job.hide()
        self.open_folder=QPushButton('Open backup folder');self.open_folder.hide()
        self.open_folder.clicked.connect(self.open_result)
        self.start=QPushButton('Create backup' if mode=='backup' else 'Verify and import')
        self.start.setEnabled(False);self.start.clicked.connect(self.begin)
        buttons.addWidget(self.back);buttons.addWidget(self.cancel_job);buttons.addWidget(self.open_folder);buttons.addStretch();buttons.addWidget(self.start)
        layout.addLayout(buttons)
        self.confirm.toggled.connect(self.ready)

    def choose(self):
        from usb_dialog import folder_dialog
        from usb_destinations import list_drives,DriveError
        try:drives=list_drives()
        except DriveError:drives=[]
        initial=next((Path(d['mount']) for d in drives if d['mount']),None)
        current=Path(self.directory.text()) if self.directory.text() else None
        if current is not None and current.is_dir():initial=current
        if initial is None:initial=Path('/media') if Path('/media').is_dir() else Path.home()
        directory=folder_dialog(self,'Choose backup destination' if self.mode=='backup'
                                else 'Choose chain backup folder',initial,drives,writing=self.mode=='backup')
        if directory is not None:
            self.directory.setText(str(directory))
            self.feedback.setText('')
        self.ready()

    def choose_usb(self):
        from usb_dialog import USBDriveDialog
        dialog=USBDriveDialog(self.mode,self)
        if dialog.exec()==QDialog.Accepted and dialog.selection is not None:
            self.directory.setText(str(dialog.selection))
            self.feedback.setText('USB destination selected. Verify the selected folder and available disk space before starting.' if self.mode=='backup' else 'USB selected. The latest completed blockchain backup will be detected and verified before import.')
        dialog.deleteLater()
        self.ready()

    def ready(self):
        self.start.setEnabled(not self.busy and bool(self.directory.text()) and self.confirm.isChecked())

    def begin(self):
        if self.busy or not self.confirm.isChecked() or not self.directory.text():return
        self.busy=True;self.cancellable=True;self.result=None
        self.buffer.clear();self.error.clear()
        self.start.setEnabled(False);self.browse.setEnabled(False);self.usb.setEnabled(False);self.confirm.setEnabled(False)
        self.cancel_job.show();self.cancel_job.setEnabled(True);self.open_folder.hide();self.progress.show();self.progress.setRange(0,0)
        self.feedback.setText('Waiting for local authorization…')
        p=QProcess(self);self.process=p
        p.setProgram('/usr/bin/pkexec');p.setArguments(['/usr/libexec/core-node-admin','chain-'+self.mode])
        p.started.connect(self.send_request)
        p.readyReadStandardOutput.connect(self.read_output)
        p.readyReadStandardError.connect(self.read_error)
        p.finished.connect(self.operation_finished)
        p.errorOccurred.connect(self.process_error)
        p.start()

    def send_request(self):
        self.process.write((json.dumps(dict(directory=self.directory.text(),confirmed=True))+'\n').encode())

    def read_error(self):
        self.error.extend(bytes(self.process.readAllStandardError())[:2048-len(self.error)])

    def read_output(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        if len(self.buffer)>65536:
            self.request_cancel();return
        while b'\n' in self.buffer:
            line,_,rest=self.buffer.partition(b'\n');self.buffer=bytearray(rest)
            try:row=json.loads(line)
            except ValueError:continue
            if row.get('event')=='result':self.result=row
            elif row.get('event')=='progress':
                self.cancellable=row.get('cancellable') is True
                self.cancel_job.setEnabled(self.cancellable)
                done,total=row.get('done',0),row.get('total',0)
                if type(done) is not int or type(total) is not int or not 0<=done<=total:continue
                if total:
                    self.progress.setRange(0,1000);self.progress.setValue(round(done*1000/total))
                else:self.progress.setRange(0,0)
                self.feedback.setText(str(row.get('phase',''))+(f'\n{size_text(done)} / {size_text(total)}' if total else ''))

    def process_error(self,error):
        if error==QProcess.FailedToStart:
            self.error=bytearray(b'The local administration helper could not start.')
            self.operation_finished(1,QProcess.NormalExit)

    def operation_finished(self,code,_status):
        if not self.busy:return
        self.read_output();self.read_error();self.busy=False
        self.progress.setRange(0,1000);self.back.setEnabled(True);self.back.setText('Back to Backup and Restore');self.cancel_job.hide()
        self.browse.setEnabled(True);self.usb.setEnabled(True);self.confirm.setEnabled(True)
        if code==0 and self.result and self.result.get('ok') is True:
            self.progress.setValue(1000);height=self.result['height']
            if self.mode=='backup':
                message='Blockchain files copied and verified.\n'+self.result['directory']
                if height is not None:
                    label='Last reported block before shutdown' if self.result.get('tip_is_hint') else 'Verified block'
                    message+=f'\n{label}: {height:,}.'
                message+='\nOn the other Node, choose Import Chain State and select this USB drive.'
                self.open_folder.show()
            else:message=f'Blockchain data imported and checked at block {height:,}. Core will continue from this saved state, without downloading the copied history again.'
            if self.mode=='backup':message+='\nBitcoin Core remains stopped. Start it manually when you are ready.'
            elif self.result.get('core_restarted'):message+='\nBitcoin Core is starting again.'
            elif self.result.get('core_was_running'):message+='\nAutomatic Core restart did not complete. Use the Bitcoin Core button and check Node status.'
            else:message+='\nOpen Bitcoin Core when you are ready.'
            self.feedback.setText(message);self.confirm.setChecked(False)
        else:
            self.progress.setValue(0)
            message=self.error.decode('utf-8','replace').strip()[:800]
            self.feedback.setText(message or 'The copy did not complete. Please check the selected folder and Node status.')
        self.ready()
        self.process.deleteLater();self.process=None

    def open_result(self):
        if self.result and self.mode=='backup':subprocess.Popen(['/usr/bin/thunar',self.result['directory']])

    def request_cancel(self):
        if self.busy and self.cancellable and self.process is not None:
            self.process.write(b'cancel\n');self.cancel_job.setEnabled(False)
            self.feedback.setText('Cancelling safely. Please wait for Bitcoin Core and the copy operation to stop.')

    def go_back(self):
        from modeless import back_to_group
        back_to_group(self)

    def reject(self):
        if self.busy:self.showMinimized()
        else:super().reject()

    def closeEvent(self,event):
        if self.busy:self.showMinimized();event.ignore()
        else:super().closeEvent(event)
