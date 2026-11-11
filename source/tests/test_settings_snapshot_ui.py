"""UI defaults, reviewed imports, grouped 3x3 menu, no privileged commands."""
import os,sys,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtWidgets import QApplication,QDialog
import settings_snapshot_ui as su
import ui,connection_ui
from launcher_ui import NodeSettingsDialog,ToolCard
APP=QApplication.instance() or QApplication([])
class PortableSettingsUI(unittest.TestCase):
    def test_password_confirmation_is_required_for_export(self):
        d=su.SettingsSnapshotDialog();d.encrypt.setChecked(True);d.path.setText('/media/node/Test');d.password.setText('long test passphrase')
        self.assertTrue(d.validation_error());d.repeat.setText('long test passphrase');self.assertTrue(d.start.isEnabled())
        d.reject();self.assertEqual(d.password.text(),'')
    def test_import_first_previews_then_requires_explicit_confirmation(self):
        d=su.SettingsSnapshotDialog();d.mode.setCurrentIndex(1);d.path.setText('/media/node/Test/settings.gpg');d.password.setText('test')
        with patch.object(d,'run') as run:
            d.begin();self.assertEqual(run.call_args.args[0],'settings-preview')
            d.preview={'fingerprint':'a'*64};d.ready();self.assertTrue(d.validation_error())
            d.confirm.setChecked(True);d.begin();self.assertEqual(run.call_args.args[0],'settings-import')
            self.assertTrue(run.call_args.args[1]['confirmed'])
            d.password.setText('changed');self.assertIsNone(d.preview)
        d.reject()
    def test_grouped_settings_entry_has_nine_cards(self):
        with patch.object(ui.Home,'poll_wallets',lambda self:None),patch.object(ui.Home,'poll_activity',lambda self:None),patch.object(connection_ui.ConnectionButton,'poll',lambda self:None):
            home=ui.Home();home.timer.stop();home.clock.timer.stop();home.wallet_inventory_timer.stop();home.connection_button.timer.stop()
            menu=NodeSettingsDialog(home);menu.resize(650,510);menu.show();APP.processEvents()
            self.assertEqual(len(menu.findChildren(ToolCard)),9)
            self.assertNotIn('Backup Chain State',menu.cards)
            self.assertNotIn('Import Chain State',menu.cards)
            with patch('backup_restore_ui.BackupRestoreDialog') as dialog:
                menu.cards['Backup and Restore'].click();dialog.assert_called_once_with(home);dialog.return_value.show.assert_called_once();dialog.return_value.exec.assert_not_called()
            self.assertTrue(menu.isVisible());menu.reject();home.close()

    def test_four_categories_route_both_directions_and_preserve_group(self):
        from backup_restore_ui import BackupRestoreDialog
        d=BackupRestoreDialog();d.show();APP.processEvents()
        self.assertEqual(len(d.actions),8)
        for importing in (False,True):
            with patch('chain_ui.ChainDialog') as child:
                d.actions[('chain',importing)].click()
                child.assert_called_once_with('import' if importing else 'backup',d)
            with patch('watch_backup_ui.WatchBackupDialog') as child:
                d.actions[('watch',importing)].click();child.assert_called_once_with(d,importing=importing)
            for kind,scope in (('core','core'),('settings','settings')):
                with patch('settings_snapshot_ui.SettingsSnapshotDialog') as child:
                    d.actions[(kind,importing)].click();child.assert_called_once_with(d,scope=scope,importing=importing)
            self.assertTrue(d.isVisible())
        d.reject()

    def test_watch_only_requires_password_repeat_and_confirm(self):
        from watch_backup_ui import WatchBackupDialog
        d=WatchBackupDialog();d.encrypt.setChecked(True);d.path.setText('/media/node/Test');d.password.setText('random test passphrase')
        self.assertTrue(d.validation_error());d.repeat.setText('random test passphrase');self.assertTrue(d.start.isEnabled())
        self.assertFalse(d.status_button.isVisible());d.reject()
        d=WatchBackupDialog(importing=True);d.path.setText('/media/node/Test/watch.gpg');d.password.setText('secret')
        with patch.object(d,'run') as run:
            d.begin();self.assertEqual(run.call_args.args[0],'settings-preview')
            d.preview={'fingerprint':'a'*64};d.ready();self.assertTrue(d.validation_error())
            d.confirm.setChecked(True);d.begin();self.assertTrue(run.call_args.args[1]['confirmed'])
        d.reject()

if __name__=='__main__':unittest.main()
