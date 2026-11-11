"""User-requested behavior: optional crypto, independent windows, RAM PSBTs."""
import contextlib,copy,json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'app'))
from PySide6.QtWidgets import QApplication,QLabel,QDialog
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt
APP=QApplication.instance() or QApplication([])
import settings_snapshot as ss,encrypted_transfer as transfer
from settings_snapshot_ui import SettingsSnapshotDialog
from watch_backup_ui import WatchBackupDialog
from desktop_surface import optical_icon
from chain_backup import Events
from operation_locks import guard,OperationBusy
from core_status_ui import CoreStatusDialog

class OptionalCryptoUI(unittest.TestCase):
    def test_all_categories_default_plain_and_accept_one_character_when_selected(self):
        for ctor in (lambda:SettingsSnapshotDialog(scope='settings'),lambda:SettingsSnapshotDialog(scope='core'),WatchBackupDialog):
            d=ctor();d.path.setText('/media/node/fixture')
            self.assertFalse(d.encrypt.isChecked());self.assertEqual(d.validation_error(),'')
            with patch.object(d,'run') as run:
                d.begin();self.assertEqual(run.call_args.args[1]['passphrase'],'')
                d.encrypt.setChecked(True);d.password.setText('1');d.repeat.setText('1');d.begin()
                self.assertEqual(run.call_args.args[1]['passphrase'],'1')
            d.reject()
    def test_incomplete_action_explains_error_without_launching_helper(self):
        d=SettingsSnapshotDialog()
        with patch.object(d,'run') as run:d.start.click();run.assert_not_called()
        self.assertIn('choose',d.feedback.text().lower())
        d.path.setText('/media/node/fixture');d.encrypt.setChecked(True);d.password.setText('1');d.repeat.setText('2')
        with patch.object(d,'run') as run:d.start.click();run.assert_not_called()
        self.assertIn('match',d.feedback.text());d.reject()
    def test_plain_restore_needs_no_password_but_requires_review_and_confirmation(self):
        d=SettingsSnapshotDialog(importing=True);d.path.setText('/media/node/fixture/backup.json')
        with patch.object(d,'run') as run:
            d.begin();self.assertEqual(run.call_args.args[0],'settings-preview')
            d.preview={'fingerprint':'a'*64};run.reset_mock();d.begin();run.assert_not_called()
            d.confirm.setChecked(True);d.begin();self.assertEqual(run.call_args.args[0],'settings-import')
        d.reject()
    def test_active_window_back_never_cancels_the_job(self):
        d=SettingsSnapshotDialog();d.busy=True;d.process=Mock();d.navigation_owner=Mock()
        d.go_back();d.process.write.assert_not_called();self.assertTrue(d.isMinimized())
        d.request_cancel();d.process.write.assert_called_once_with(b'cancel\n')
        d.busy=False;d.reject()

class PortableFormats(unittest.TestCase):
    @contextlib.contextmanager
    def ram(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:yield Path(td)
    def test_real_plain_and_one_character_gpg_roundtrips(self):
        raw=ss.canonical({'format':'fixture','value':'synthetic data'})
        with tempfile.TemporaryDirectory() as td,patch.object(ss,'ram_work',self.ram),\
          patch.object(transfer,'identity',lambda uid:contextlib.nullcontext()),\
          patch.object(transfer,'external',side_effect=lambda p,*a,**k:(os.open(p,ss.DIR_FLAGS),Path(p),'ext4')):
            for secret in ('','1'):
                E=Events(emit=lambda _:None)
                name=transfer.publish(raw,td,secret,os.getuid(),E,prefix='bitcoin-core-config',limit=4*1024**2)
                self.assertEqual(Path(name).suffix,'.gpg' if secret else '.json')
                actual,_=transfer.read(name,secret,os.getuid(),Events(emit=lambda _:None),limit=4*1024**2)
                self.assertEqual(actual,raw)
                if secret:
                    with self.assertRaises(Exception):transfer.read(name,'2',os.getuid(),E,limit=4*1024**2)
    def test_plain_tampering_and_duplicate_fields_are_refused(self):
        raw=ss.canonical({'x':1});packed=transfer.pack_plain(raw);data=json.loads(packed);data['payload']['x']=2
        with self.assertRaises(ss.SettingsError):transfer.unpack_plain(ss.canonical(data),1000)
        with self.assertRaises(ss.SettingsError):transfer.unpack_plain(b'{"format":1,"format":2}',1000)
        self.assertEqual(transfer.unpack_plain(packed,1000),raw)

class ParallelOperations(unittest.TestCase):
    def test_config_exports_can_overlap_chain_but_start_and_wallet_changes_cannot(self):
        with tempfile.TemporaryDirectory() as td:
            with guard('chain-backup',Path(td)):
                with guard('settings-backup',Path(td)),guard('core-settings-backup',Path(td)):pass
                for action in ('start','restart','watch-backup','watch-import','chain-import','settings-import'):
                    with self.subTest(action=action),self.assertRaises(OperationBusy):
                        with guard(action,Path(td)):pass
    def test_config_changes_and_chain_import_cannot_race_export(self):
        with tempfile.TemporaryDirectory() as td:
            with guard('settings-backup',Path(td)):
                for action in ('configure','time-settings','chain-import'):
                    with self.subTest(action=action),self.assertRaises(OperationBusy):
                        with guard(action,Path(td)):pass
    def test_symlink_lock_cannot_redirect_a_write(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);target=p/'target';target.write_text('keep')
            (p/'bitcoin-core-node-admin.lock').symlink_to(target)
            with self.assertRaises(OSError):
                with guard('start',p):pass
            self.assertEqual(target.read_text(),'keep')

class VisualAndNavigation(unittest.TestCase):
    def test_icons_have_transparent_border_at_every_requested_size(self):
        paths=[R/'runtime/usr/share/bitcoin-core-node/bitcoin-ui.png',R/'runtime/usr/share/bitcoin-core-node/icons/settings-network-connections.png']
        for path in paths:
            for size in (16,28,42,64):
                image=optical_icon(QIcon(str(path)),size).toImage();w=image.width();h=image.height()
                border=[image.pixelColor(x,y).alpha() for x in range(w) for y in (0,h-1)]+[image.pixelColor(x,y).alpha() for y in range(h) for x in (0,w-1)]
                self.assertFalse(any(border),(path,size))
    def test_independent_job_survives_closing_menu_and_reopens_without_duplicate(self):
        from modeless import open_window
        owner=QDialog();menu=open_window(owner,'menu',QDialog);job=open_window(owner,'job',QDialog)
        self.assertFalse(menu.isModal());self.assertFalse(job.isModal());self.assertIsNone(job.parent())
        menu.reject();APP.processEvents();self.assertTrue(job.isVisible())
        self.assertIs(open_window(owner,'job',QDialog),job)
        job.reject();APP.processEvents();self.assertNotIn('job',owner._modeless_windows)
    def test_psbt_launcher_follows_watch_wallet_before_private_workspace(self):
        import ui,connection_ui
        with patch.object(ui.Home,'poll_wallets',lambda _:None),patch.object(ui.Home,'poll_activity',lambda _:None),patch.object(connection_ui.ConnectionButton,'poll',lambda _:None):
            home=ui.Home();self.assertNotIn('PSBT Transfer Folder',[c.tool['title'] for c in home.cards])
            home.set_watch_only_available(True);names=[c.tool['title'] for c in home.cards]
            self.assertEqual(names[:4],['Bitcoin Core','Watch-Only Wallets','PSBT Transfer Folder','Private Workspace'])
            home.set_watch_only_available(None);self.assertEqual(names,[c.tool['title'] for c in home.cards])
            for t in (home.timer,home.wallet_inventory_timer,home.connection_button.timer,home.clock.timer):t.stop()
            home.hide();home.deleteLater()
    def test_ram_psbt_uses_same_protected_mount_and_triggers_power_warning(self):
        import private_workspace as w
        self.assertEqual(w.PSBT,w.ROOT/'psbt')
        service=(R/'runtime/etc/systemd/system/bitcoin-core-node.service').read_text()
        self.assertIn('/run/core-node-private/psbt',service);self.assertNotIn('/var/lib/bitcoin-core-node/transfer',service)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);a=p/'a';b=p/'b';a.mkdir();b.mkdir()
            with patch.object(w,'check_storage',return_value=a),patch.object(w,'check_psbt_storage',return_value=b):
                self.assertFalse(w.has_contents());(b/'pending.psbt').write_text('fixture');self.assertTrue(w.has_contents())

class VisualStatus(unittest.TestCase):
    def test_live_values_version_and_progress_are_not_hardcoded(self):
        d=CoreStatusDialog(autostart=False)
        d.apply(dict(available=True,chain={'blocks':123,'headers':200,'verificationprogress':.615,'initialblockdownload':True,'chain':'main','pruned':True},net={'subversion':'/Satoshi:32.1.0/','connections':8,'networkactive':True},mempool={'size':17},privacy='tor',free=15*1024**3,transports={'onion':8}))
        self.assertIn('32.1.0',d.version.text());self.assertEqual(d.values['blocks'].text(),'123');self.assertEqual(d.progress.value(),615)
        self.assertTrue(d.validating);self.assertIn('77',d.sync_note.text())
        d.apply(dict(available=False,service='inactive'));self.assertFalse(d.validating);self.assertEqual(d.values['blocks'].text(),'—');self.assertEqual(d.phase.text(),'Core stopped');d.reject()

if __name__=='__main__':unittest.main()
