"""Removable USB destination, safety and full synthetic chain-copy regression tests."""
import contextlib
import json
import os
from pathlib import Path
import pwd
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
import subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import usb_destinations as usb
import chain_backup as chain

def sample_devices():
    return json.dumps({'blockdevices':[
        {'name':'nvme0n1','path':'/dev/nvme0n1','type':'disk','tran':'nvme','rm':False,
         'children':[{'name':'nvme0n1p1','path':'/dev/nvme0n1p1','type':'part','fstype':'vfat',
                      'mountpoints':['/boot/efi'],'size':1024**3}]},
        {'name':'sda','path':'/dev/sda','type':'disk','tran':'usb','rm':False,
         'children':[{'name':'sda1','path':'/dev/sda1','type':'part','fstype':'exfat',
                      'label':'Backup SSD','uuid':'USB-UUID-A','size':120*1024**3,
                      'ro':False,'mountpoints':['/media/node/Backup SSD']}]},
        {'name':'sdb','path':'/dev/sdb','type':'disk','tran':'usb','rm':True,
         'children':[{'name':'sdb1','path':'/dev/sdb1','type':'part','fstype':'vfat',
                      'label':'USB Stick','uuid':'USB-UUID-B','size':64*1024**3,
                      'ro':False,'mountpoints':[None]}]},
        {'name':'sr0','path':'/dev/sr0','type':'rom','tran':'sata','rm':True,
         'fstype':None,'mountpoints':[]}]})

class USBEnumeration(unittest.TestCase):
    def test_usb_ssd_and_stick_listed_but_not_internal_efi_or_cdrom(self):
        with patch.object(usb,'safe_mount',side_effect=lambda path,user=None:Path(path) if path.startswith('/media/node/') else None):
            drives=usb.parse_lsblk(sample_devices(),'node')
        self.assertEqual({x['path'] for x in drives},{'/dev/sda1','/dev/sdb1'})
        self.assertEqual(drives[0]['label'],'Backup SSD')
        self.assertEqual(drives[0]['mount'],'/media/node/Backup SSD')
        self.assertEqual(drives[1]['label'],'USB Stick')
        self.assertIsNone(drives[1]['mount'])
        self.assertTrue(usb.is_selected_drive(drives[0],drives[0]))
        self.assertFalse(usb.is_selected_drive(drives[0],drives[1]))

    def test_root_disk_is_never_exposed_as_removable_usb(self):
        with patch.object(usb,'safe_mount',return_value=None):
            drives=usb.parse_lsblk(sample_devices(),'node')
        self.assertFalse(any(d['path'].startswith('/dev/nvme') for d in drives))

    def test_symlinks_and_untrusted_mounts_not_accepted(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)
            root.joinpath('folder').mkdir()
            self.assertIsNone(usb.safe_mount(str(root/'folder'),'node'))
            self.assertIsNone(usb.safe_mount('/tmp','node'))
            self.assertIsNone(usb.safe_mount('/','node'))
        self.assertFalse(usb.BLOCK_PATH.fullmatch('/dev/../../etc/passwd'))

class USBBackend(unittest.TestCase):
    def test_run_media_allowed_only_for_real_usb_block_mount_of_same_desktop_user(self):
        user=pwd.getpwuid(os.getuid()).pw_name
        path=Path('/run/media')/user/'Backup SSD'/'backups'
        valid={'target':str(Path('/run/media')/user/'Backup SSD'),
               'source':'/dev/sda1','fstype':'exfat','options':'rw'}
        self.assertTrue(chain.approved_user_media_mount(path,valid,os.getuid()))
        local=Path('/media')/user/'Backup SSD'/'backups'
        self.assertTrue(chain.approved_user_media_mount(
            local,dict(valid,target=str(Path('/media')/user/'Backup SSD')),os.getuid()))
        self.assertFalse(chain.approved_user_media_mount(path,{**valid,'source':'tmpfs'},os.getuid()))
        self.assertFalse(chain.approved_user_media_mount(path,{**valid,'fstype':'tmpfs'},os.getuid()))
        self.assertFalse(chain.approved_user_media_mount(Path('/run/core-node-files'),valid,os.getuid()))
        self.assertFalse(chain.approved_user_media_mount(path,{**valid,'target':'/run/media/other/Backup SSD'},os.getuid()))

    def test_unplugged_media_folder_must_not_fall_back_to_internal_root(self):
        user=pwd.getpwuid(os.getuid()).pw_name
        fake=Path('/media')/user/'UNPLUGGED'
        mount_root={'filesystems':[{'target':'/','source':'/dev/nvme0n1p2',
                                    'fstype':'ext4','options':'rw'}]}
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            fd=os.open(td,chain.DIR_FLAGS)
            with patch.object(chain.os,'open',return_value=fd),\
                 patch.object(chain.os,'readlink',return_value=str(fake)),\
                 patch.object(chain.subprocess,'check_output',return_value=json.dumps(mount_root)):
                with self.assertRaisesRegex(chain.ChainError,'not mounted'):
                    chain.external(str(fake),os.getuid(),writing=True)
            # external() owns and closes its descriptor on failure.
            with self.assertRaises(OSError):os.fstat(fd)

    def test_verified_media_block_mount_can_be_used_by_desktop_user(self):
        user=pwd.getpwuid(os.getuid()).pw_name
        fake=Path('/run/media')/user/'USBSSD'
        mounted={'filesystems':[{'target':str(fake),'source':'/dev/sdc1',
                                 'fstype':'exfat','options':'rw'}]}
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            fd=os.open(td,chain.DIR_FLAGS)
            with patch.object(chain.os,'open',return_value=fd),\
                 patch.object(chain.os,'readlink',return_value=str(fake)),\
                 patch.object(chain.subprocess,'check_output',return_value=json.dumps(mounted)):
                handle,resolved,fstype=chain.external(str(fake),os.getuid(),writing=True)
                self.assertEqual(handle,fd)
                self.assertEqual(resolved,fake)
                self.assertEqual(fstype,'exfat')
            os.close(handle)

    def test_external_failure_preflight_keeps_core_running(self):
        data=dict(directory='/media/node/Missing',confirmed=True)
        caller=os.getuid()
        events=chain.Events(emit=lambda row:None)
        with patch.object(chain.pwd,'getpwnam',return_value=type('User',(),{'pw_uid':caller})()),\
             patch.object(chain,'load_setup',return_value={'network':'main'}),\
             patch.object(chain,'verify_data_mount'),\
             patch('upgrades.active_release',return_value={'version':'32.1'}),\
             patch.object(chain,'external',side_effect=chain.ChainError('USB is not mounted')) as external,\
             patch.object(chain,'stop_core') as stop,\
             patch.object(chain,'service_running') as service:
            with self.assertRaises(chain.ChainError):
                chain.perform('chain-backup',data,caller,events)
            external.assert_called_once()
            stop.assert_not_called()
            service.assert_not_called()

    def test_full_chain_copy_and_manifest_verified_to_synthetic_external_mount(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)
            data=root/'chain'
            usb_dir=root/'synthetic-external-usb'
            usb_dir.mkdir();data.mkdir()
            files={'blocks/index/CURRENT':b'MANIFEST-000001\n',
                   'blocks/index/MANIFEST-000001':b'index',
                   'blocks/blk00000.dat':b'validating blocks'*2048,
                   'blocks/rev00000.dat':b'undo'*200,
                   'chainstate/CURRENT':b'MANIFEST-000002\n',
                   'chainstate/MANIFEST-000002':b'UTXO'*220}
            for name,contents in files.items():
                p=data/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(contents)
            events=chain.Events(emit=lambda row:None)
            uid=os.getuid()
            def external(_path,_uid,writing=False):
                self.assertTrue(writing)
                return os.open(usb_dir,chain.DIR_FLAGS),usb_dir,'exfat'
            with patch.object(chain,'external',side_effect=external),\
                 patch.object(chain,'chain_root',return_value=data),\
                 patch.object(chain,'probe',return_value={'blocks':100,
                                   'bestblockhash':'a'*64,'pruneheight':0}),\
                 patch.object(chain.os,'fstatvfs',return_value=type('Space',(),{'f_bavail':1024**3,'f_frsize':4096})()),\
                 patch.object(chain,'core_lock',return_value=contextlib.nullcontext()),\
                 patch.object(chain,'settings_read',return_value=(b'{}',{'prune':'1024'})):
                record=chain.backup(str(usb_dir),uid,{'network':'main','prune_mib':1024},
                                   {'version':'32.1'},events,tip_hint={'blocks':100,'bestblockhash':'a'*64,'pruneheight':0})
            backup=Path(record['directory'])
            self.assertTrue(backup.is_dir())
            for name,contents in files.items():
                self.assertEqual((backup/name).read_bytes(),contents,name)
            saved=json.loads((backup/chain.MANIFEST).read_text())
            self.assertEqual(saved['network'],'main')
            self.assertEqual(saved['core_version'],'32.1')
            self.assertEqual(saved['total_bytes'],sum(map(len,files.values())))
            self.assertEqual(len(saved['files']),len(files))
            self.assertFalse(any(p.name.startswith('.chain-backup-partial') for p in usb_dir.iterdir()))
            fd=os.open(backup,chain.DIR_FLAGS)
            try:
                self.assertEqual(chain.load_manifest(fd,uid,'main','32.1')['height'],100)
            finally:os.close(fd)

class USBPickerQt(unittest.TestCase):
    def test_usb_button_visible_and_dialog_selects_drive_root(self):
        os.environ['QT_QPA_PLATFORM']='offscreen'
        from PySide6.QtWidgets import QApplication,QDialog
        import chain_ui,usb_dialog
        app=QApplication.instance() or QApplication([])
        with patch.object(usb_dialog.USBDriveDialog,'scan',lambda self:None):
            dialog=usb_dialog.USBDriveDialog('backup')
            self.assertIn('USB',dialog.windowTitle())
            with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
                mounted=Path(tmp)
                entry=dict(path='/dev/sdc1',label='USB backup',fstype='exfat',
                           bytes=64*1024**3,read_only=False,mount=str(mounted),uuid='test')
                dialog.drives=[entry]
                dialog.drive.addItem('USB backup',entry['path'])
                with patch.object(usb_dialog,'safe_mount',return_value=mounted):
                    dialog.choose_action('use')
                    self.assertEqual(dialog.result(),QDialog.Accepted)
                    self.assertEqual(dialog.selection,mounted)
            dialog.deleteLater()
        with patch.object(usb_dialog.USBDriveDialog,'scan',lambda self:None):
            dialog=usb_dialog.USBDriveDialog('import')
            self.assertEqual(dialog.use.text(),'Use latest backup')
            with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
                mounted=Path(tmp)
                entry=dict(path='/dev/sdc1',label='USB backup',fstype='exfat',bytes=1024**3,
                           read_only=True,mount=str(mounted),uuid='test')
                dialog.drives=[entry];dialog.drive.addItem('USB backup',entry['path'])
                with patch.object(usb_dialog,'safe_mount',return_value=mounted):
                    dialog.choose_action('use')
                    self.assertEqual(dialog.result(),QDialog.Accepted)
                    self.assertEqual(dialog.selection,mounted)
            dialog.deleteLater()
        chain_dialog=chain_ui.ChainDialog('backup')
        self.assertEqual(chain_dialog.usb.text(),'USB / External Drive…')
        self.assertEqual(chain_dialog.usb.accessibleName(),'Choose USB stick or external drive')
        chain_dialog.close()

if __name__=='__main__':
    unittest.main(verbosity=2)
