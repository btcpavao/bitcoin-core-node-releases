"""Controlled system maintenance with review before authenticated mutation."""
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QLabel, QLineEdit, QMessageBox
from wallet_ui import WorkDialog
from wallets import WalletError
import upgrades

class UpdatesDialog(WorkDialog):
    def __init__(self,parent):
        super().__init__(parent,'System Updates')
        self.download=None;self.candidate=None
        current=upgrades.active_release()
        self.current=current
        self.status.setText('Verified Core '+current['version']+'. No update runs automatically.')
        note=QLabel('Version checks and downloads use the operating-system network. In Tor P2P mode this is clearnet; the WireGuard policy remains enforced.');note.setWordWrap(True);self.layout.addWidget(note)
        self.button('Check official Core version',self.check)
        self.number=QLineEdit(current['version']);self.number.setAccessibleName('Core maintenance version');self.layout.addWidget(self.number)
        self.button('Download and verify Core release',self.download_core)
        self.review=self.text('Verified release details')
        self.activate=self.button('Review and install verified Core',self.install)
        # Operating-system and KeePassXC maintenance lives in Software Updates.
        self.button('Restart computer',self.reboot)
        self.button('Close',self.reject)
        self.refresh_actions()

    def refresh_actions(self):self.activate.setEnabled(self.candidate is not None)

    def check(self):
        def done(record):
            self.number.setText(record['version'])
            message='Current: '+record['current']+'. Latest official stable release: '+record['version']+'. '
            if not record['supported']:message+='This major version requires a reviewed Node system update.'
            elif upgrades.version(record['version'])>upgrades.version(record['current']):message+='A maintenance release is available for verification.'
            else:message+='No newer supported release was reported.'
            self.status.setText(message)
        self.run(upgrades.latest_release,done,'Checking the official Bitcoin Core release record…')

    def download_core(self):
        number=self.number.text().strip()
        try:
            if upgrades.version(number)[0]!=32 or upgrades.version(number)<upgrades.version(self.current['version']):
                raise WalletError('Please choose the current version or a later Core 32 maintenance release. Downgrades and new major versions are refused.')
        except WalletError as exc:self.status.setText(str(exc));return
        if self.download:self.download.cleanup()
        self.download=tempfile.TemporaryDirectory(prefix='node-core-download-')
        directory=Path(self.download.name);directory.chmod(0o700);self.candidate=None
        def done(record):
            record.pop('files',None);self.candidate=record
            self.review.setPlainText('Official Core '+record['version']+'\n\nArchive SHA256\n'+record['archive_sha256']+'\n\nBitcoin Core GUI SHA256\n'+record['gui_sha256']+'\n\nDaemon SHA256\n'+record['binary_sha256']+'\n\nVerified primary release signers\n'+'\n'.join(record['signers'])+'\n\nThe service will stop gracefully. Wallet databases and settings are copied to a protected local snapshot before the verified release is activated. Existing binaries are retained. There is no automatic database rollback.')
            self.status.setText('Release signatures and archive verified. Please review before installation.')
        self.run(lambda:upgrades.download_release(number,directory),done,'Downloading the official archive and verifying at least two release signers…')

    def install(self):
        if self.candidate is None:return
        number=self.candidate['version']
        if QMessageBox.question(self,'Install verified Core '+number+'?',
            'Please confirm the version and hashes above. Core will stop while a consistent wallet snapshot is made. The new version may update database formats. Keep your independent public recovery backup; automatic downgrade is not provided.',
            QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)!=QMessageBox.Yes:return
        from ui import admin
        request={'directory':self.download.name,'version':number,'archive_sha256':self.candidate['archive_sha256'],'current_sha256':self.current['binary_sha256']}
        def done(result):
            self.current=upgrades.active_release();self.candidate=None
            self.status.setText('Verified Core '+result['version']+(' is running.' if result.get('running',True) else ' is installed. Open Bitcoin Core when ready.')+' Protected wallet snapshot: '+result['backup'])
        self.run(lambda:admin('core-update',request),done,'Authenticating, preserving wallet databases and activating verified Core…')

    def debian(self):
        from software_ui import SoftwareUpdatesDialog
        SoftwareUpdatesDialog(self.parentWidget()).exec()

    def reboot(self):
        self.accept()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.parentWidget().power('reboot'))

    def reject(self):
        if self.job and self.job.isRunning():super().reject();return
        if self.download:self.download.cleanup();self.download=None
        super().reject()

    def closeEvent(self,event):
        if not self.job or not self.job.isRunning():
            if self.download:self.download.cleanup();self.download=None
        super().closeEvent(event)
