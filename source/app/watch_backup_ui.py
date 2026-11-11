"""Responsive native public-wallet collection; no secret keys in this workflow."""
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QLabel
from settings_snapshot_ui import SettingsSnapshotDialog

class WatchBackupDialog(SettingsSnapshotDialog):
    def __init__(self,parent=None,*,importing=False):
        super().__init__(parent,importing=importing)
        self.setWindowTitle('Watch-only Wallets')
        title=self.findChild(QLabel,'Title')
        if title is not None:title.setText('Watch-only Wallets')
        # Replace the first explanatory label, retaining native layout/styles.
        for label in self.findChildren(QLabel):
            if label.text().startswith('Move your Node configuration'):
                label.setText('Back up supported watch-only wallets using Bitcoin Core’s public-only export, or restore a saved collection. Bitcoin Core must be running.')
        self.status_button.hide();self.cancel_pending.hide()
        self.mode.setItemText(0,'Create watch-only backup')
        self.mode.setItemText(1,'Restore watch-only wallets')
        self.changed();self.mode.setCurrentIndex(int(importing))

    def changed(self):
        super().changed()
        importing=self.mode.currentIndex()==1
        self.details.setPlainText('Includes watch-only descriptors, labels, address book and transaction records from Core’s native export. Signing wallets are never exported.\n\nExisting wallets are not replaced. Name conflicts receive a new name. Restored wallets may need additional block history for rescanning; import the blockchain first where possible.')
        self.notice.setText('Review the wallet names before restoring. Completed wallets are kept if a later wallet fails; the same backup can resume.' if importing else 'Keep this backup private: public descriptors can reveal your addresses and balances. Use a separate strong backup passphrase.')
        self.update_encryption_controls()
        self.path.setPlaceholderText('Choose a .json or .gpg watch-only backup…' if importing else 'Choose a USB drive or destination folder…')

    def ready(self,*_):
        super().ready(*_)
        self.start.setText('Restore wallets' if self.mode.currentIndex()==1 and self.preview else 'Review backup' if self.mode.currentIndex()==1 else 'Create wallet backup')

    def run(self,action,request):
        mapped={'settings-backup':'watch-backup','settings-preview':'watch-preview','settings-import':'watch-import'}
        if action not in mapped:return
        super().run(mapped[action],request)

    def show_summary(self,value):
        self.details.setPlainText('Created: '+value['created_utc']+'\nNetwork: '+value['network']+'\n\nWatch-only wallets:\n'+'\n'.join(value['wallets'])+'\n\nOther/unsupported wallets not exported: '+str(value['skipped']))

    def completed(self,code,_):
        if not self.busy:return
        self.read_output();self.read_error();self.busy=False;self.request=b'';self.progress.hide()
        self.back.setText('Back to Backup and Restore');self.back.setEnabled(True);self.cancel_job.hide()
        for item in (self.mode,self.choose_button,self.encrypt,self.password,self.repeat,self.confirm):item.setEnabled(True)
        result=self.result
        if code==0 and result and result.get('ok'):
            self.show_summary(result['summary'])
            if self.action=='watch-preview':
                self.preview=result
                self.feedback.setText('Public-only wallets verified by Bitcoin Core. Review the names, then approve restoration.')
            elif self.action=='watch-backup':
                self.feedback.setText(('Encrypted' if result.get('encrypted',result['file'].endswith('.gpg')) else 'Unencrypted')+' watch-only collection saved.\n'+result['file'])
                self.password.clear();self.repeat.clear()
            else:
                self.feedback.setText('Watch-only wallets restored:\n'+', '.join(result['names'])+'\nExisting wallets were not replaced. Check Bitcoin Core for scanning progress.')
                self.password.clear();self.repeat.clear()
        else:
            self.feedback.setText(self.error.decode('utf-8','replace').strip() or 'Watch-only transfer failed. No successful transfer was confirmed.')
        self.process.deleteLater();self.process=None;self.update_encryption_controls();self.ready()
