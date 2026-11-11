"""A responsive review/install surface for the persistent maintenance service."""
from PySide6.QtCore import QTimer, Qt, Slot
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout
from system_updates import read_status


class SoftwareUpdatesDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        from ui import STYLE
        self.setWindowTitle('Software Updates')
        self.setStyleSheet(STYLE)
        self.resize(780, 560)
        self.job = None
        self.launching = False
        self.last_record = None
        self.launch_error = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        title = QLabel('Software Updates'); title.setObjectName('Title'); layout.addWidget(title)
        note = QLabel('Update Debian 13, installed Debian applications and signature-verified KeePassXC. Bitcoin Core uses its separate verified update process. Downloads use the system connection; Tor P2P mode does not route OS downloads through Tor.')
        note.setWordWrap(True); note.setObjectName('Muted'); layout.addWidget(note)
        self.status = QLabel('Checking update status…')
        self.status.setWordWrap(True); self.status.setTextFormat(Qt.PlainText); layout.addWidget(self.status)
        self.progress = QProgressBar(self)
        self.progress.setRange(0,100)
        self.progress.setValue(0)
        self.progress.setFormat('Update progress: %p% (package steps)')
        self.progress.setAccessibleName('Software update progress')
        self.progress.hide()
        layout.addWidget(self.progress)
        self.details = QPlainTextEdit(); self.details.setReadOnly(True)
        self.details.setAccessibleName('Available software updates'); layout.addWidget(self.details, 1)
        self.restart_note = QLabel(''); self.restart_note.setWordWrap(True); layout.addWidget(self.restart_note)
        row = QHBoxLayout(); layout.addLayout(row)
        self.check = QPushButton('Check for Updates'); self.check.clicked.connect(lambda: self.begin('check'))
        self.install = QPushButton('Install Updates'); self.install.clicked.connect(lambda: self.begin('install'))
        self.install.setEnabled(False)
        self.close_button = QPushButton('Back to Settings'); self.close_button.clicked.connect(self.reject)
        for button in (self.check, self.install, self.close_button):
            button.setAutoDefault(False); row.addWidget(button)
        advanced = QHBoxLayout(); layout.addLayout(advanced)
        core = QPushButton('Bitcoin Core updates…'); core.clicked.connect(self.core_updates); advanced.addWidget(core)
        self.core_button = core
        self.reboot_button = QPushButton('Restart computer…'); self.reboot_button.clicked.connect(self.reboot)
        advanced.addWidget(self.reboot_button)
        self.timer = QTimer(self); self.timer.setInterval(1500); self.timer.timeout.connect(self.refresh)
        self.timer.start(); self.refresh()
        if not read_status().get('busy'):
            QTimer.singleShot(0, lambda: self.begin('check'))

    def refresh(self):
        record = read_status()
        if record == self.last_record:
            return
        self.last_record = record
        busy = self.launching or record.get('busy', False)
        self.status.setText(self.launch_error or record.get('message', 'Software status is unavailable.'))
        packages = record.get('packages', [])
        lines = ['Debian 13: official stable, security and point updates',
                 'Bitcoin Core: managed separately; no automatic version change', '']
        if record.get('keepass_current'):
            latest = record.get('keepass_latest')
            lines += ['KeePassXC: ' + record['keepass_current'] + ' installed · ' + (str(latest) + ' latest' if latest else 'latest version not verified'), '']
        if record.get('keepass_source'):
            lines += ['Release source: ' + record['keepass_source']]
        if record.get('keepass_note'):
            lines += [record['keepass_note'], '']
        if record.get('debian_checked') and record.get('check_complete') is False:
            lines += ['Debian check completed; KeePassXC/full update verification is incomplete. Installation is disabled until a fresh complete check succeeds.', '']
        lines += [row['name'] + ': ' + row['previous'] + ' → ' + row['version'] for row in packages]
        if not packages and record.get('stage') in ('checked', 'complete'):
            lines.append('No Debian package updates are pending.')
        if record.get('keepass_available'):
            lines.append('KeePassXC ' + record['keepass_latest'] + ' is available (official signed release).')
        self.details.setPlainText('\n'.join(lines))
        stage=record.get('stage','idle')
        self.progress.setVisible(busy or stage=='complete')
        if busy and record.get('progress') is None:
            self.progress.setRange(0,0)
        else:
            self.progress.setRange(0,100)
            self.progress.setValue(int(max(0,min(100,record.get('progress',0) or 0))))
        self.check.setEnabled(not busy)
        self.install.setEnabled(not busy and record.get('stage') in ('checked','complete') and record.get('check_complete') is not False and bool(record.get('updates_available')))
        self.core_button.setEnabled(not busy)
        self.reboot_button.setEnabled(not busy)
        self.restart_note.setText(
            'Restart needed to use the updated system or kernel. Bitcoin Core is not restarted automatically.' if record.get('reboot_required') else
            'Some pending kernel/system updates may require a restart after installation.' if record.get('reboot_likely') else
            'Installation continues if you close this window. Core is not deliberately stopped.' if busy else
            'Bitcoin Core updates are handled separately. Some Debian updates may briefly affect OS services.'
        )

    def begin(self, action):
        if self.job is not None:
            return
        from ui import Job, admin
        if action=='install':
            record=read_status()
            if record.get('busy') or record.get('stage') not in ('checked','complete') or record.get('check_complete') is False or not record.get('updates_available'):
                return
            lines=[p['name'] + ': ' + p['previous'] + ' → ' + p['version']
                   for p in record.get('packages',[])]
            if record.get('keepass_available'):
                lines.append('KeePassXC → '+record.get('keepass_latest','latest signed release'))
            sample='\n'.join(lines[:15])
            if len(lines)>15:sample+=f'\n… and {len(lines)-15} more packages'
            note='\n\nRestart may be required.' if record.get('reboot_likely') else ''
            if QMessageBox.question(
                self, 'Confirm software updates',
                f'Install {len(lines)} listed update(s)?\n\n{sample}{note}\n\n'
                'Bitcoin Core will not be deliberately stopped. Debian maintenance may restart other services.',
                QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel
            )!=QMessageBox.Yes:
                return
        self.launching = True
        self.launch_error = None
        self.check.setEnabled(False); self.install.setEnabled(False)
        self.status.setText('Starting software ' + ('check…' if action == 'check' else 'installation…'))
        self.job = Job(lambda: admin('software-' + action), self)
        self.job.failure.connect(self.failed)
        self.job.finished.connect(self.started)
        self.job.start()

    @Slot(str)
    def failed(self, message):
        self.launch_error = message
        self.status.setText(message)

    @Slot()
    def started(self):
        job = self.sender()
        if self.job is job:
            self.job = None
        job.deleteLater()
        self.launching = False; self.last_record = None; self.refresh()

    def core_updates(self):
        from update_ui import UpdatesDialog
        UpdatesDialog(self.parentWidget()).exec()

    def reboot(self):
        self.accept()
        # Reuse the workspace warning and timer, including hidden files.
        QTimer.singleShot(0, lambda: self.parentWidget().power('reboot'))

    def reject(self):
        if self.job is None:
            self.timer.stop(); super().reject()

    def closeEvent(self, event):
        if self.job is not None:
            event.ignore()
        else:
            self.timer.stop(); event.accept()
