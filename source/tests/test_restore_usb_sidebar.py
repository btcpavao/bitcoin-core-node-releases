"""Shared live-media selection in all four backup/restore categories."""
import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'app'))
from PySide6.QtWidgets import QApplication,QDialog,QFileDialog
from PySide6.QtCore import Qt
import media_file_dialog as media
from settings_snapshot_ui import SettingsSnapshotDialog
from watch_backup_ui import WatchBackupDialog
from chain_ui import ChainDialog
from usb_dialog import folder_dialog
APP=QApplication.instance() or QApplication([])

class RestoreEntryPoints(unittest.TestCase):
    def test_node_core_and_watch_choose_use_live_media_and_both_formats(self):
        factories=[lambda:SettingsSnapshotDialog(importing=True),
                   lambda:SettingsSnapshotDialog(scope='core',importing=True),
                   lambda:WatchBackupDialog(importing=True)]
        for factory in factories:
            for suffix in ('.json','.gpg'):
                d=factory();chosen='/media/node/TEST/backup'+suffix
                d.preview={'fingerprint':'a'*64};d.confirm.setChecked(True)
                with patch.object(media,'choose_media_file',return_value=chosen) as picker:
                    d.choose()
                self.assertEqual(d.path.text(),chosen)
                self.assertEqual(picker.call_args.kwargs['name_filter'],'Node backups (*.json *.gpg)')
                self.assertEqual(picker.call_args.args[0],d)
                self.assertEqual(d.encrypted(),suffix=='.gpg')
                self.assertIsNone(d.preview);self.assertFalse(d.confirm.isChecked());d.reject()
    def test_cancel_preserves_existing_selection_and_review(self):
        d=SettingsSnapshotDialog(importing=True);d.path.setText('/media/node/TEST/original.json')
        d.preview={'fingerprint':'b'*64};d.confirm.setChecked(True)
        with patch.object(media,'choose_media_file',return_value=None):d.choose()
        self.assertEqual(d.path.text(),'/media/node/TEST/original.json')
        self.assertEqual(d.preview,{'fingerprint':'b'*64});self.assertTrue(d.confirm.isChecked());d.reject()
    def test_chain_import_and_backup_choose_directory_with_correct_write_policy(self):
        with tempfile.TemporaryDirectory() as td:
            for mode in ('import','backup'):
                d=ChainDialog(mode)
                with patch('usb_destinations.list_drives',return_value=[]),patch.object(media,'choose_media_folder',return_value=Path(td)) as picker:
                    d.choose()
                self.assertEqual(d.directory.text(),td)
                self.assertEqual(picker.call_args.kwargs['writable'],mode=='backup');d.reject()
    def test_configuration_backup_also_uses_writable_live_directory_picker(self):
        d=SettingsSnapshotDialog()
        with patch('usb_destinations.list_drives',return_value=[]),patch.object(media,'choose_media_folder',return_value=Path('/media/node/TEST')) as picker:
            d.choose()
        self.assertTrue(picker.call_args.kwargs['writable']);self.assertEqual(d.path.text(),'/media/node/TEST');d.reject()
    def test_folder_wrapper_retains_path_contract_and_current_rescan(self):
        with patch.object(media,'choose_media_folder',return_value=Path('/media/node/TEST')) as picker:
            result=folder_dialog(None,'Restore chain','/media',[{'mount':'/obsolete'}])
        self.assertEqual(result,Path('/media/node/TEST'))
        picker.assert_called_once_with(None,'Restore chain','/media',writable=False)

class DirectoryMode(unittest.TestCase):
    def drive(self,**kw):
        d=dict(path='/dev/sdb1',label='RESTORE USB',bytes=1024**3,fstype='exfat',uuid='test',read_only=False,mount=None)
        d.update(kw);return d
    def item(self,d):
        return next(d.places.item(i) for i in range(d.places.count()) if d.places.item(i).data(Qt.UserRole)==('drive','/dev/sdb1'))
    def test_directory_mode_is_not_save_mode_and_shows_media(self):
        d=media.MediaFileDialog(directory=True,autostart=False);d.render_places([self.drive()])
        self.assertEqual(d.fileMode(),QFileDialog.Directory);self.assertEqual(d.acceptMode(),QFileDialog.AcceptOpen)
        self.assertTrue(d.testOption(QFileDialog.ShowDirsOnly));self.assertFalse(d.requires_writable)
        self.assertIn('RESTORE USB',self.item(d).text());d.reject()
    def test_file_modes_remain_unchanged(self):
        for saving,mode in ((False,QFileDialog.ExistingFile),(True,QFileDialog.AnyFile)):
            d=media.MediaFileDialog(saving=saving,autostart=False)
            self.assertEqual(d.fileMode(),mode);self.assertEqual(d.requires_writable,saving);d.reject()
    def test_readonly_folder_allowed_for_restore_not_backup(self):
        for writable in (False,True):
            d=media.MediaFileDialog(directory=True,writable=writable,autostart=False)
            d.render_places([self.drive(read_only=True)])
            with patch.object(d,'scan') as scan:d.visit(self.item(d));self.assertEqual(scan.call_count,0 if writable else 1)
            if writable:self.assertIn('read-only',d.media_status.text())
            d.reject()
    def test_no_automount_and_hotplug_refresh_in_folder_mode(self):
        d=media.MediaFileDialog(directory=True,autostart=False)
        with patch.object(d,'run_utility') as run:
            d.render_places([]);d.render_places([self.drive()]);run.assert_not_called()
            self.assertIn('RESTORE USB',self.item(d).text())
            d.render_places([]);run.assert_not_called()
        self.assertIsNone(d.pending);d.reject()
    def test_removed_folder_media_is_not_selected(self):
        d=media.MediaFileDialog(directory=True,autostart=False);d.pending=self.drive();p=Mock();d.worker=p
        with patch.object(d,'read_output'),patch.object(d,'stop_worker',side_effect=lambda:setattr(d,'worker',None)),patch.object(media,'parse_lsblk',return_value=[]),patch.object(d,'setDirectory') as change:
            d.completed(p,'scan',0);change.assert_not_called()
        self.assertIsNone(d.pending);self.assertIn('removed',d.media_status.text());d.reject()
    def test_select_root_or_subfolder_and_cancel(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);sub=root/'bitcoin-chain-main-test';sub.mkdir()
            for path in (root,sub):
                with patch.object(media,'_choose_media',return_value=str(path)) as choose:
                    self.assertEqual(media.choose_media_folder(None,'Restore','/media'),path)
                    self.assertTrue(choose.call_args.kwargs['directory'])
            with patch.object(media,'_choose_media',return_value=None):self.assertIsNone(media.choose_media_folder(None,'Restore','/media'))
            with patch.object(media,'_choose_media',return_value=str(root/'gone')):self.assertIsNone(media.choose_media_folder(None,'Restore','/media'))
            file=root/'backup.json';file.write_text('{}')
            with patch.object(media,'_choose_media',return_value=str(file)):self.assertIsNone(media.choose_media_folder(None,'Restore','/media'))
    def test_compact_size_and_cleanup(self):
        d=media.MediaFileDialog(directory=True,autostart=False);d.resize(800,600);d.show();APP.processEvents()
        self.assertLessEqual(d.width(),800);self.assertLessEqual(d.height(),600)
        d.timer.start();d.reject();self.assertFalse(d.timer.isActive());self.assertIsNone(d.worker)

if __name__=='__main__':unittest.main()
