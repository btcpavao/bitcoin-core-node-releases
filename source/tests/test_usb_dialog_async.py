"""Asynchronous Qt USB/mount round-trip; fake selected devices, no real disk writes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtWidgets import QApplication,QDialog
import usb_dialog

APP=None
def app():
    global APP
    APP=QApplication.instance() or APP or QApplication([])
    return APP

class AsyncPicker(unittest.TestCase):
    def test_unmounted_usb_mounts_then_selects_same_partition(self):
        application=app()
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)
            original=dict(path='/dev/sdc1',label='Archive USB',fstype='exfat',
                          bytes=64*1024**3,read_only=False,mount=None,uuid='test-uuid')
            mounted=dict(original,mount=str(root))
            with patch.object(usb_dialog,'parse_lsblk',side_effect=[[original],[mounted]]),\
                 patch.object(usb_dialog,'UDISKS','/usr/bin/true'),\
                 patch.object(usb_dialog,'safe_mount',return_value=root):
                selector=usb_dialog.USBDriveDialog('backup')
                selector.show()
                end=time.monotonic()+4
                while selector.drive.count()==0 and time.monotonic()<end:
                    application.processEvents()
                    time.sleep(.01)
                self.assertEqual(selector.drive.count(),1)
                self.assertIsNone(selector.selected()['mount'])
                selector.choose_action('use')
                self.assertIsNotNone(selector.mounting)
                while selector.result()!=QDialog.Accepted and time.monotonic()<end:
                    application.processEvents()
                    time.sleep(.01)
                self.assertEqual(selector.result(),QDialog.Accepted)
                self.assertEqual(selector.selection,root)
                self.assertIsNone(selector.worker)
                selector.deleteLater()

    def test_read_only_usb_allowed_for_import_but_not_backup(self):
        application=app()
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            mount=Path(td)
            entry=dict(path='/dev/sdc1',label='Read Only USB',fstype='vfat',
                       bytes=10*1024**3,read_only=True,mount=str(mount),uuid='uuid')
            for mode,expected in (('import',True),('backup',False)):
                with patch.object(usb_dialog.USBDriveDialog,'scan',lambda self:None):
                    picker=usb_dialog.USBDriveDialog(mode)
                    picker.drives=[entry]
                    picker.drive.addItem('USB',entry['path'])
                    picker.selection_changed()
                    self.assertEqual(picker.folder.isEnabled(),expected)
                    picker.deleteLater()

    def test_import_accepts_drive_root_or_specific_completed_folder(self):
        application=app()
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)
            saved=root/'bitcoin-chain-main-100-abcdef123456'
            saved.mkdir()
            entry=dict(path='/dev/sdc1',label='Archive USB',fstype='ext4',
                       bytes=10*1024**3,read_only=False,mount=str(root),uuid='uuid')
            with patch.object(usb_dialog.USBDriveDialog,'scan',lambda self:None):
                picker=usb_dialog.USBDriveDialog('import')
                picker.drives=[entry]
                picker.drive.addItem('Archive USB',entry['path'])
                with patch.object(usb_dialog,'safe_mount',return_value=root),\
                     patch.object(usb_dialog,'folder_dialog',return_value=root):
                    picker.choose_action('folder')
                    self.assertEqual(picker.selection,root)
                    self.assertEqual(picker.result(),QDialog.Accepted)
                with patch.object(usb_dialog,'safe_mount',return_value=root),\
                     patch.object(usb_dialog,'folder_dialog',return_value=saved):
                    picker.choose_action('folder')
                    self.assertEqual(picker.selection,saved)
                    self.assertEqual(picker.result(),QDialog.Accepted)
                picker.deleteLater()

if __name__=='__main__':unittest.main(verbosity=2)
