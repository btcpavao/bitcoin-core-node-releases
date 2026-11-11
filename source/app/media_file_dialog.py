"""Local file picker with Places and hot-plug USB filesystem discovery.

Only a clicked, revalidated filesystem is mounted through desktop UDisks
permissions. No formatting or raw writes. Callers retain their path and RAM
recovery checks; browsing media never changes the decryption destination.
"""
from pathlib import Path
from PySide6.QtCore import Qt, QProcess, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QFileDialog, QDialog, QWidget, QVBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QPushButton, QSplitter, QListView, QStyle)
from usb_destinations import (LSBLK, LSBLK_ARGS, UDISKS, parse_lsblk,
    safe_mount, is_selected_drive, DriveError)


class MediaFileDialog(QFileDialog):
    def __init__(self, parent=None, title='Choose file', initial='', *, saving=False,
                 name_filter='All files (*)', autostart=True, directory=False, writable=False):
        super().__init__(parent, title)
        self.setOption(QFileDialog.DontUseNativeDialog, True)
        self.setAcceptMode(QFileDialog.AcceptSave if saving else QFileDialog.AcceptOpen)
        if directory and saving:
            raise ValueError('Folder selection and file saving are separate modes.')
        self.directory_mode = directory
        self.requires_writable = bool(saving or writable)
        self.setFileMode(QFileDialog.Directory if directory else
                         QFileDialog.AnyFile if saving else QFileDialog.ExistingFile)
        if directory:
            self.setOption(QFileDialog.ShowDirsOnly, True)
            self.setLabelText(QFileDialog.Accept, 'Choose folder')
        else:
            self.setNameFilter(name_filter)
        self.setOption(QFileDialog.DontConfirmOverwrite, True)  # Backend refuses overwrites.
        self.saving = saving
        self.worker = None
        self.pending = None
        self.drives = []
        self.closed = False
        self.output = bytearray()
        self.autostart = autostart
        path = Path(initial or Path.home())
        if saving and not path.is_dir():
            self.setDirectory(str(path.parent))
            self.selectFile(path.name)
        else:
            self.setDirectory(str(path))
        self.resize(960, 640)
        self.panel = QWidget(self)
        side = QVBoxLayout(self.panel)
        side.setContentsMargins(0, 0, 8, 0)
        side.setSpacing(8)
        self.places = QListWidget()
        self.places.setAccessibleName('Places and external media')
        self.places.setMinimumWidth(320)
        self.places.setWordWrap(True)
        self.places.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side.addWidget(self.places, 1)
        self.media_status = QLabel('Checking USB devices…')
        self.media_status.setWordWrap(True)
        self.media_status.setTextFormat(Qt.PlainText)
        side.addWidget(self.media_status)
        self.refresh_media = QPushButton('Refresh USB')
        self.refresh_media.clicked.connect(self.scan)
        side.addWidget(self.refresh_media)
        splitter = self.findChild(QSplitter, 'splitter')
        native = self.findChild(QListView, 'sidebar')
        if splitter is None or native is None:
            raise RuntimeError('The local file picker layout is unavailable.')
        native.hide()
        splitter.insertWidget(0, self.panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([330, 0, 590])
        self.places.itemClicked.connect(self.visit)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.scan)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.timed_out)
        self.render_places([])
        if autostart:
            QTimer.singleShot(0, self.scan)

    def showEvent(self, event):
        self.closed = False
        if self.autostart:
            self.timer.start()
        super().showEvent(event)

    def section(self, text):
        item = QListWidgetItem(text, self.places)
        item.setFlags(Qt.NoItemFlags)
        font = item.font()
        font.setBold(True)
        item.setFont(font)

    def render_places(self, drives):
        previous = self.places.currentItem()
        key = previous.data(Qt.UserRole) if previous else None
        self.places.clear()
        self.section('Places')
        for label, path, icon in [
            ('Core', Path('/run/core-node-files/Core'), 'bitcoin'),
            ('Private Workspace', Path('/run/core-node-private/workspace'), 'folder'),
            ('PSBT Transfer Folder', Path('/run/core-node-private/psbt'), 'folder-publicshare'),
            ('Node', Path.home(), 'user-home'), ('Computer', Path('/'), 'computer')]:
            if path.is_dir():
                item = QListWidgetItem(QIcon.fromTheme(icon, self.style().standardIcon(QStyle.SP_DirIcon)), label, self.places)
                item.setData(Qt.UserRole, ('place', str(path)))
                item.setToolTip(str(path))
        self.section('USB / External media')
        for entry in drives:
            label = entry['label'] + (' · read-only' if entry['read_only'] else '')
            if not entry['mount']:
                label += ' · click to mount'
            item = QListWidgetItem(QIcon.fromTheme('drive-removable-media-usb', self.style().standardIcon(QStyle.SP_DriveHDIcon)), label, self.places)
            item.setData(Qt.UserRole, ('drive', entry['path']))
            item.setToolTip(f"{entry['label']}\n{entry['bytes']/1024**3:.1f} GiB · {entry['fstype']}\n" + (entry['mount'] or 'Click to mount; existing files are kept.'))
        if not drives:
            self.section('No USB filesystem detected')
        for i in range(self.places.count()):
            item = self.places.item(i)
            if item.data(Qt.UserRole) == key:
                self.places.setCurrentItem(item)
                break
        self.drives = drives

    def visit(self, item):
        value = item.data(Qt.UserRole)
        if not value or self.worker is not None:
            return
        kind, path = value
        if kind == 'place':
            if Path(path).is_dir():
                self.setDirectory(path)
            return
        entry = next((d for d in self.drives if d['path'] == path), None)
        if entry is None:
            return
        if self.requires_writable and entry['read_only']:
            self.media_status.setText('This drive is read-only. Please choose a writable destination.')
            return
        self.pending = dict(entry)
        self.scan()

    def scan(self):
        if self.closed or self.worker is not None:
            return
        self.run_utility(LSBLK, list(LSBLK_ARGS), 'scan')

    def run_utility(self, program, args, operation):
        process = QProcess(self)
        self.worker = process
        self.output.clear()
        self.refresh_media.setEnabled(False)
        process.setProgram(program)
        process.setArguments(args)
        process.readyReadStandardOutput.connect(lambda: self.read_output(process))
        process.finished.connect(lambda code, status: self.completed(process, operation, code))
        process.errorOccurred.connect(lambda error: self.failed(process, error))
        process.start()
        self.deadline.start(45000 if operation == 'mount' else 12000)

    def read_output(self, process):
        if self.worker is not process:
            return
        self.output.extend(bytes(process.readAllStandardOutput()))
        if len(self.output) > 1024 * 1024:
            self.stop_worker()
            self.pending = None
            self.media_status.setText('USB information exceeded the supported limit.')

    def stop_worker(self):
        self.deadline.stop()
        process = self.worker
        self.worker = None
        if process is not None:
            if process.state() != QProcess.NotRunning:
                process.kill()
                process.waitForFinished(1000)
            process.deleteLater()
        self.refresh_media.setEnabled(True)

    def failed(self, process, error):
        if process is self.worker and error == QProcess.FailedToStart:
            self.stop_worker()
            self.pending = None
            self.media_status.setText('USB utility could not start. Please use Files to inspect the drive.')

    def timed_out(self):
        self.stop_worker()
        self.pending = None
        self.media_status.setText('USB scan or mount timed out. Please reconnect the drive and refresh.')

    def completed(self, process, operation, code):
        if self.worker is not process:
            return
        self.read_output(process)
        if self.worker is not process:
            return
        raw = bytes(self.output)
        self.stop_worker()
        if self.closed:
            return
        if code != 0:
            self.pending = None
            self.media_status.setText('Could not mount the selected drive. Please unlock encrypted media in Files, then refresh.' if operation == 'mount' else 'USB scan failed. Please reconnect the drive and refresh.')
            return
        if operation == 'mount':
            self.scan()
            return
        try:
            drives = parse_lsblk(raw.decode('utf-8', 'replace'))
        except DriveError as exc:
            self.pending = None
            self.media_status.setText(str(exc))
            return
        if drives != self.drives:
            self.render_places(drives)
        if self.pending is None:
            self.media_status.setText('Select a USB drive on the left. New devices appear automatically.' if drives else 'Plug in a USB drive; its filesystem will appear here.')
            return
        expected = self.pending
        entry = next((d for d in drives if is_selected_drive(expected, d)), None)
        if entry is None:
            self.pending = None
            self.media_status.setText('The selected drive changed or was removed. Please select it again.')
            return
        if self.requires_writable and entry['read_only']:
            self.pending = None
            self.media_status.setText('This drive is read-only. Please choose a writable destination.')
            return
        if entry['mount']:
            location = safe_mount(entry['mount'])
            self.pending = None
            if location is None:
                self.media_status.setText('The USB is no longer mounted. Please reconnect it and refresh.')
                return
            name = Path(self.selectedFiles()[0]).name if self.saving and self.selectedFiles() else None
            self.setDirectory(str(location))
            if name:
                self.selectFile(name)
            self.media_status.setText('Selected ' + entry['label'])
            return
        if expected.get('_mount_attempted'):
            self.pending = None
            self.media_status.setText('The mount did not appear. Please open the drive in Files and retry.')
            return
        self.pending = dict(entry, _mount_attempted=True)
        self.media_status.setText('Mounting ' + entry['label'] + '…')
        self.run_utility(UDISKS, ['mount', '-b', entry['path']], 'mount')

    def done(self, result):
        self.closed = True
        self.timer.stop()
        self.stop_worker()
        super().done(result)

    def closeEvent(self, event):
        self.closed = True
        self.timer.stop()
        self.stop_worker()
        super().closeEvent(event)


def choose_media_file(parent, title, initial, *, saving=False, name_filter='All files (*)'):
    return _choose_media(parent, title, initial, saving=saving, name_filter=name_filter)


def choose_media_folder(parent, title, initial, *, writable=False):
    selected = _choose_media(parent, title, initial, directory=True, writable=writable)
    if selected is None:
        return None
    try:
        path = Path(selected).resolve(strict=True)
        return path if path.is_dir() else None
    except OSError:
        return None  # Removed media cannot become a successful selection.


def _choose_media(parent, title, initial, **options):
    dialog = MediaFileDialog(parent, title, initial, **options)
    try:
        if dialog.exec() != QDialog.Accepted:
            return None
        selected = dialog.selectedFiles()
        return selected[0] if selected else None
    finally:
        dialog.closed = True
        dialog.timer.stop()
        dialog.stop_worker()
        dialog.deleteLater()
