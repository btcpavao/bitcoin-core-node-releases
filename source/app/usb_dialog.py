"""Qt USB drive picker for chainstate backups and imports.

The independent Files window can already see UDisks2 USB mounts. Qt's static
directory dialog did not: this picker discovers USB disks, offers Polkit/udisks
mounting and opens a directory chooser rooted in the selected USB filesystem.
"""
from pathlib import Path
import os
import shutil
from PySide6.QtCore import Qt,QProcess,QTimer,QUrl
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,
                               QPushButton,QFileDialog)
from usb_destinations import (LSBLK,LSBLK_ARGS,UDISKS,parse_lsblk,
                              safe_mount,recheck_drive,DriveError)


def folder_dialog(parent,title,initial,drives=(),*,writing=False):
    """Use the same live USB sidebar as file restores and Encrypt/Decrypt.

    ``drives`` is retained for existing callers, but is not an authority:
    the picker rescans identities and mount state while it is open.
    """
    from media_file_dialog import choose_media_folder
    return choose_media_folder(parent,title,str(initial),writable=writing)


class USBDriveDialog(QDialog):
    def __init__(self,mode,parent=None):
        super().__init__(parent)
        if mode not in ('backup','import'):raise ValueError('Unsupported USB selection mode')
        from ui import STYLE
        self.mode=mode;self.selection=None;self.drives=[];self.worker=None;self.mounting=None
        self.setStyleSheet(STYLE)
        self.setWindowTitle('USB / External Drive')
        self.resize(640,330)
        layout=QVBoxLayout(self);layout.setContentsMargins(22,18,22,18);layout.setSpacing(10)
        heading=QLabel('USB / External Drive');heading.setObjectName('Title')
        layout.addWidget(heading)
        detail=QLabel('Select a connected USB stick or external SSD. If it is not mounted, '
                      'the system can mount it without formatting or deleting files. '
                      'You can back up directly to its root folder or choose a subfolder.'
                      if mode=='backup' else
                      'Select the USB drive holding your previous blockchain backup, '
                      'then use the latest completed backup automatically, or choose an older backup folder.')
        detail.setWordWrap(True);layout.addWidget(detail)
        self.status=QLabel('Looking for connected USB drives…')
        self.status.setWordWrap(True);self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        row=QHBoxLayout()
        self.drive=QComboBox();self.drive.setAccessibleName('USB external drive')
        self.drive.currentIndexChanged.connect(self.selection_changed)
        row.addWidget(self.drive,1)
        self.refresh_button=QPushButton('Refresh USB')
        self.refresh_button.clicked.connect(self.scan)
        row.addWidget(self.refresh_button);layout.addLayout(row)
        note=QLabel('The system will verify free space and file integrity before finalizing a backup. '
                    'For large block files, use ext4, exFAT or NTFS instead of FAT32.')
        note.setObjectName('Muted');note.setWordWrap(True);layout.addWidget(note)
        layout.addStretch(1)
        buttons=QHBoxLayout()
        self.back=QPushButton('Back');self.back.clicked.connect(self.reject)
        self.use=QPushButton('Use USB drive' if mode=='backup' else 'Use latest backup')
        self.folder=QPushButton('Choose folder on USB…')
        if self.use is not None:
            self.use.clicked.connect(lambda:self.choose_action('use'))
        self.folder.clicked.connect(lambda:self.choose_action('folder'))
        buttons.addWidget(self.back);buttons.addStretch()
        if self.use is not None:buttons.addWidget(self.use)
        buttons.addWidget(self.folder);layout.addLayout(buttons)
        self.select_buttons(False)
        self.deadline=QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.operation_timed_out)
        QTimer.singleShot(0,self.scan)

    def select_buttons(self,enabled):
        if self.use is not None:self.use.setEnabled(enabled)
        self.folder.setEnabled(enabled)
        self.refresh_button.setEnabled(self.worker is None)
        self.drive.setEnabled(self.worker is None and bool(self.drives))

    def scan(self):
        if self.worker is not None:return
        self.status.setText('Checking connected USB devices…')
        self.run(LSBLK,list(LSBLK_ARGS),'scan')

    def run(self,program,args,operation):
        assert self.worker is None
        process=QProcess(self)
        process.setProgram(program);process.setArguments(args)
        self.worker=process
        self.select_buttons(False)
        process.finished.connect(lambda code,status:self.finished_operation(code,operation))
        process.errorOccurred.connect(lambda error:self.process_failed(error))
        process.start()
        self.deadline.start(50000 if operation=='mount' else 15000)

    def operation_timed_out(self):
        if self.worker is None:return
        self.cleanup_process()
        self.mounting=None
        self.status.setText('The USB scan/mount timed out. The system was not modified. '
                            'Check the disk in Files, then click Refresh USB.')

    def process_failed(self,error):
        if error==QProcess.FailedToStart:
            self.status.setText('The USB device utility could not start. Please check the system installation.')
            self.cleanup_process()

    def cleanup_process(self):
        if hasattr(self,'deadline'):self.deadline.stop()
        process=self.worker
        self.worker=None
        if process is not None:
            if process.state()!=QProcess.NotRunning:
                process.kill();process.waitForFinished(1500)
            process.deleteLater()
        self.select_buttons(bool(self.drives))
        self.selection_changed()

    def finished_operation(self,code,operation):
        if self.worker is None:return
        process=self.worker
        stdout=bytes(process.readAllStandardOutput()).decode('utf-8','replace')
        self.cleanup_process()
        if operation=='scan':
            if code!=0:
                self.status.setText('Could not read USB devices. Reconnect the drive, then select Refresh USB.')
                return
            try:drives=parse_lsblk(stdout)
            except DriveError as exc:
                self.status.setText(str(exc));return
            previous=self.drive.currentData()
            self.drives=drives
            self.drive.blockSignals(True)
            self.drive.clear()
            for entry in drives:
                size=entry['bytes']/1024**3
                state='Mounted' if entry['mount'] else 'Not mounted'
                if entry['read_only']:state+=' · read-only'
                self.drive.addItem(f"{entry['label']} · {size:.1f} GiB · {entry['fstype']} · {state}",entry['path'])
            index=self.drive.findData(previous)
            if index>=0:self.drive.setCurrentIndex(index)
            self.drive.blockSignals(False)
            self.select_buttons(bool(drives))
            if not drives:self.status.setText('No USB drive with a supported filesystem was detected. Plug in the USB stick, then choose Refresh USB.')
            self.selection_changed()
            # If the user just mounted a drive, verify the same partition by
            # immutable UUID/path before resuming the explicitly chosen action.
            if self.mounting:
                pending=self.mounting;self.mounting=None
                target=next((entry for entry in self.drives
                             if all(entry[field]==pending[field] for field in
                                    ('path','uuid','bytes','label','fstype'))),None)
                if target is None or not target['mount']:
                    self.status.setText('USB mount did not appear. Please reconnect the drive and click Refresh USB.')
                else:
                    self.drive.setCurrentIndex(self.drive.findData(target['path']))
                    QTimer.singleShot(0,lambda action=pending['intent']:self.choose_action(action))
            return
        if operation=='mount':
            if code!=0:
                self.mounting=None
                self.status.setText('Could not mount that USB filesystem. Unlock it in Files if encrypted, '
                                    'check disk permissions and retry. No data was erased.')
                return
            self.scan()
            return

    def selected(self):
        device=self.drive.currentData()
        return next((entry for entry in self.drives if entry['path']==device),None)

    def selection_changed(self,*_):
        if self.worker is not None:return
        entry=self.selected()
        # Import reads a trusted saved chain; a read-only USB is valid there.
        # Creating a backup must always require a writable filesystem.
        self.select_buttons(entry is not None and (self.mode=='import' or not entry['read_only']))
        if entry is None:return
        if entry['read_only'] and self.mode=='backup':
            self.status.setText('This USB filesystem is read-only. Use a writable drive for backups.')
        elif entry['mount']:
            try:
                used=shutil.disk_usage(entry['mount'])
                self.status.setText(f"Mounted at {entry['mount']} · {used.free/1024**3:.1f} GiB free")
            except OSError:
                self.status.setText('Drive mounted but the folder cannot be accessed. Reconnect and refresh.')
        else:self.status.setText('Drive detected but not mounted. Select the drive action or Choose folder to mount it.')

    def choose_action(self,intent):
        if self.worker is not None:return
        entry=self.selected()
        if entry is None or (entry['read_only'] and self.mode=='backup'):return
        if not entry['mount']:
            # The user explicitly selected this drive. Mount with UDisks2's
            # normal local-seat authorization; no root shell, formatting or
            # persistent mount configuration. Match its identity again after
            # mounting so /dev/sdX reordering cannot choose a different drive.
            self.mounting=dict(intent=intent,path=entry['path'],uuid=entry['uuid'],
                               bytes=entry['bytes'],label=entry['label'],fstype=entry['fstype'])
            self.status.setText('Mounting the selected USB drive…')
            self.run(UDISKS,['mount','-b',entry['path']],'mount')
            return
        mount=safe_mount(entry['mount'])
        if mount is None:
            self.status.setText('This USB mount is not in the local user’s external-drive folder.')
            return
        if intent=='use':
            if self.mode=='backup' and not os.access(mount,os.W_OK):
                self.status.setText('The mounted USB drive is not writable by the local Node account. '
                                    'Choose a writable drive or inspect it in Files.')
                return
            self.selection=mount
            self.accept()
            return
        chosen=folder_dialog(self,'Choose chain backup folder' if self.mode=='import'
                             else 'Choose destination folder on USB',mount,self.drives,writing=self.mode=='backup')
        if chosen is None:return
        if chosen!=mount and mount not in chosen.parents:
            self.status.setText('Please choose a folder on the selected USB drive, not another disk.')
            return
        if self.mode=='backup' and not os.access(chosen,os.W_OK):
            self.status.setText('This USB folder is not writable by your desktop account.')
            return
        self.selection=chosen
        self.accept()

    def reject(self):
        if self.worker is not None:
            # A user can cancel an unanswered UDisks2/Polkit prompt. Killing
            # only the mount utility never formats, unmounts or writes files.
            self.cleanup_process()
            self.mounting=None
        super().reject()
