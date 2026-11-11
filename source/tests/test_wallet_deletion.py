"""Disposable-wallet-only deletion and scoped privilege tests. NO real Core data."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
from pathlib import Path
import pwd
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock,call

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import wallet_delete as wd
import wallet_delete_ui as wui
from PySide6.QtWidgets import QApplication,QMessageBox,QInputDialog
from PySide6.QtCore import QProcess

APP=None
def application():
    global APP
    APP=QApplication.instance() or APP or QApplication(['test-wallet-deletion'])
    return APP

def fixture_wallet(base,name,*,db=True):
    wallet=base/name
    wallet.mkdir()
    if db:
        con=sqlite3.connect(wallet/'wallet.dat')
        try:
            con.execute('CREATE TABLE main (key BLOB, value BLOB)')
            con.execute('INSERT INTO main VALUES (?,?)',(b'fixture-only',b'not-real-keys'))
            con.commit()
        finally:con.close()
    return wallet

class FolderGuard(unittest.TestCase):
    def test_exact_direct_wallet_folder_only(self):
        for name in ('../blocks','wallets/btc','..','', '.', '\\n','bad\\0name','-flags','.hidden','a'*200):
            with self.subTest(name=repr(name)):
                with self.assertRaises((wd.WalletDeleteError,UnicodeError)):
                    wd.validate_name(name)
        self.assertEqual(wd.validate_name('My Test Wallet'),'My Test Wallet')
        self.assertEqual(wd.validate_name('wallet_000001'),'wallet_000001')

    def test_refuses_symlink_hardlink_special_files_and_neighbor_folders(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)/'wallets'
            root.mkdir()
            real=fixture_wallet(root,'fixture')
            other=fixture_wallet(root,'other')
            wd.validate_inventory('fixture',root,os.getuid())
            # A symlink inside wallet could otherwise redirect to chainstate.
            (real/'external').symlink_to(other/'wallet.dat')
            with self.assertRaisesRegex(wd.WalletDeleteError,'symbolic links'):
                wd.wipe_directory('fixture',root,os.getuid())
            (real/'external').unlink()
            os.link(real/'wallet.dat',real/'another-link')
            with self.assertRaisesRegex(wd.WalletDeleteError,'(hard link|normal Bitcoin Core wallet.dat)'):
                wd.wipe_directory('fixture',root,os.getuid())
            (real/'another-link').unlink()
            (root/'alias').symlink_to(real,target_is_directory=True)
            with self.assertRaises(wd.WalletDeleteError):
                wd.wipe_directory('alias',root,os.getuid())
            self.assertTrue((other/'wallet.dat').exists())

    def test_three_pass_best_effort_wipes_exact_selected_wallet_and_retains_other(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)/'wallets';root.mkdir()
            wallet=fixture_wallet(root,'remove')
            other=fixture_wallet(root,'KEEP')
            contents=(other/'wallet.dat').read_bytes()
            extra=wallet/'database'
            extra.mkdir()
            (extra/'cache.log').write_bytes(b'synthetic journal for unit test'*24)
            count=wd.wipe_directory('remove',root,os.getuid())
            self.assertGreaterEqual(count,2)
            self.assertFalse(wallet.exists())
            self.assertTrue(other.exists())
            self.assertEqual((other/'wallet.dat').read_bytes(),contents)
            self.assertTrue(root.exists())

    def test_nonwallet_folder_and_missing_marker_rejected(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)/'wallets';root.mkdir()
            (root/'blocks').mkdir()
            (root/'blocks'/'blk00000.dat').write_bytes(b'block data')
            with self.assertRaisesRegex(wd.WalletDeleteError,'wallet.dat'):
                wd.wipe_directory('blocks',root,os.getuid())
            self.assertTrue((root/'blocks'/'blk00000.dat').exists())

class PrivilegedOrchestration(unittest.TestCase):
    def test_forced_or_failed_service_stop_is_not_treated_as_clean_shutdown(self):
        for status in (b'timeout\n',b'signal\n',b'exit-code\n',b''):
            with self.subTest(status=status),patch.object(wd.subprocess,'run',side_effect=[
                    Mock(returncode=0),Mock(returncode=0,stdout=status)]):
                with self.assertRaisesRegex(wd.WalletDeleteError,'did not exit cleanly'):
                    wd.command('stop',wd.SERVICE)

    def prepare(self,root):
        wallet=fixture_wallet(root,'testwallet')
        return wallet

    def environment(self,root):
        import types
        user=types.SimpleNamespace(pw_uid=os.getuid())
        def fake_user(name):
            assert name in ('node','bitcoinnode'),name
            return user
        return (patch.object(wd,'WALLET_ROOT',root),
                patch.object(wd.os,'geteuid',return_value=0),
                patch.dict(os.environ,{'PKEXEC_UID':str(os.getuid())}),
                patch.object(wd.pwd,'getpwnam',side_effect=fake_user),
                patch.object(wd,'load_setup',return_value={'data_uuid':None}),
                patch.object(wd,'verify_data_mount',return_value=True))

    def test_loaded_wallet_stops_core_cleans_startup_and_preserves_watch_only(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)/'wallets';root.mkdir()
            wallet=self.prepare(root)
            keep=fixture_wallet(root,'watch-only')
            before=(keep/'wallet.dat').read_bytes()
            settings=root.parent/'settings.json'
            settings.write_text(json.dumps({'wallet':['testwallet','watch-only'],'prune':'1000'}))
            contexts=self.environment(root)
            with contexts[0],contexts[1],contexts[2],contexts[3],contexts[4],contexts[5],\
                 patch.object(wd,'running',side_effect=[True,False]),\
                 patch.object(wd,'command') as ctl,\
                 patch('rpc.CoreRPC',return_value=lambda method:['testwallet']):
                wd.perform(dict(wallet='testwallet',confirmed=True,
                                profile='three-pass-best-effort'))
                self.assertEqual(ctl.call_args_list,[call('stop',wd.SERVICE),
                                  call('start',wd.SERVICE,timeout=120)])
                self.assertFalse(wallet.exists())
                self.assertEqual((keep/'wallet.dat').read_bytes(),before)
                self.assertEqual(json.loads(settings.read_text()),
                                 {'wallet':['watch-only'],'prune':'1000'})

    def test_malformed_settings_refuse_deletion_before_core_shutdown(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)/'wallets';root.mkdir();wallet=self.prepare(root)
            (root.parent/'settings.json').write_text('{broken')
            ctx=self.environment(root)
            with ctx[0],ctx[1],ctx[2],ctx[3],ctx[4],ctx[5],patch.object(wd,'command') as ctl:
                with self.assertRaisesRegex(wd.WalletDeleteError,'settings are invalid'):
                    wd.perform(dict(wallet='testwallet',confirmed=True,
                                    profile='three-pass-best-effort'))
                ctl.assert_not_called()
            self.assertTrue((wallet/'wallet.dat').exists())

    def test_failed_shutdown_never_updates_settings_or_overwrites_wallet(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)/'wallets';root.mkdir();wallet=self.prepare(root)
            settings=root.parent/'settings.json'
            settings.write_text('{"wallet":["testwallet"]}')
            before=settings.read_bytes();ctx=self.environment(root)
            with ctx[0],ctx[1],ctx[2],ctx[3],ctx[4],ctx[5],\
                 patch.object(wd,'running',return_value=True),patch.object(wd,'command') as ctl:
                with self.assertRaisesRegex(wd.WalletDeleteError,'finish shutting down'):
                    wd.perform(dict(wallet='testwallet',confirmed=True,
                                    profile='three-pass-best-effort'))
                self.assertEqual(ctl.call_args_list,[call('stop',wd.SERVICE)])
            self.assertTrue((wallet/'wallet.dat').exists())
            self.assertEqual(settings.read_bytes(),before)

    def test_unloaded_wallet_stops_core_deletes_and_restarts_on_success(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)/'wallets';root.mkdir();wallet=self.prepare(root)
            contexts=self.environment(root)
            with contexts[0],contexts[1],contexts[2],contexts[3],contexts[4],contexts[5],\
                 patch.object(wd,'running',side_effect=[True,False]),\
                 patch.object(wd,'command') as command,\
                 patch('rpc.CoreRPC',return_value=lambda method:[]):
                result=wd.perform(dict(wallet='testwallet',confirmed=True,
                                       profile='three-pass-best-effort'))
                self.assertEqual(command.call_args_list,[
                    call('stop',wd.SERVICE),call('start',wd.SERVICE,timeout=120)])
                self.assertTrue(result['ok'])
                self.assertFalse(wallet.exists())

    def test_wrong_explicit_request_cannot_delete_wallet(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)/'wallets';root.mkdir()
            wallet=self.prepare(root)
            contexts=self.environment(root)
            with contexts[0],contexts[1],contexts[2],contexts[3],contexts[4],contexts[5],\
                 patch.object(wd,'command') as command:
                for request in [
                    dict(wallet='testwallet',confirmed=False,profile='three-pass-best-effort'),
                    dict(wallet='testwallet',confirmed=True,profile='force'),
                    dict(wallet='/etc/shadow',confirmed=True,profile='three-pass-best-effort')
                ]:
                    with self.assertRaises(wd.WalletDeleteError):
                        wd.perform(request)
                command.assert_not_called()
                self.assertTrue(wallet.exists())

class ContextMenuAndDialog(unittest.TestCase):
    def test_only_read_only_core_view_direct_child_wallet_is_accepted(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)/'Core';wallets=root/'wallets';wallets.mkdir(parents=True)
            wallet=fixture_wallet(wallets,'User Wallet')
            with patch.object(wui,'CORE_VIEW',root):
                self.assertEqual(wui.selected_wallet(str(wallet)),'User Wallet')
                for candidate in (root/'blocks',root/'chainstate',
                                  root/'wallets',root/'wallets/User Wallet/wallet.dat'):
                    with self.assertRaises((ValueError,OSError)):
                        wui.selected_wallet(str(candidate))
                (wallets/'fake').symlink_to(wallet,target_is_directory=True)
                with self.assertRaises(ValueError):
                    wui.selected_wallet(str(wallets/'fake'))

    def test_vault_style_red_confirmation_without_typed_name_or_second_prompt(self):
        application()
        dialog=wui.WalletDeletionDialog(['My Test Wallet','secondwallet'])
        dialog.show();application().processEvents()
        self.assertEqual(dialog.delete.text(),'Permanently Delete')
        self.assertEqual(dialog.delete.objectName(),'delete')
        self.assertTrue(dialog.cancel.isDefault())
        self.assertFalse(dialog.delete.isDefault())
        self.assertTrue(dialog.delete.isVisible())
        self.assertEqual(dialog.paths.toPlainText(),'My Test Wallet\nsecondwallet')
        self.assertIn('#9a302c',dialog.styleSheet())
        self.assertFalse(hasattr(dialog,'confirm'))
        with patch.object(wui.QMessageBox,'question') as question,\
             patch.object(QInputDialog,'getText') as typed:
            dialog.delete.click()
            question.assert_not_called();typed.assert_not_called()
        self.assertEqual(dialog.result(),wui.QDialog.Accepted)

    def test_multiwallet_selection_requires_only_core_wallet_folders(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)/'Core';wallets=root/'wallets';wallets.mkdir(parents=True)
            one=fixture_wallet(wallets,'Test One')
            two=fixture_wallet(wallets,'Test Two')
            with patch.object(wui,'CORE_VIEW',root):
                self.assertEqual(wui.selected_wallets([str(one),str(two)]),
                                 ('Test One','Test Two'))
                with self.assertRaisesRegex(ValueError,'more than once'):
                    wui.selected_wallets([str(one),str(one)])
                with self.assertRaises(ValueError):
                    wui.selected_wallets([str(one),str(root/'blocks')])
                with self.assertRaises(ValueError):
                    wui.selected_wallets([str(one/'wallet.dat')])
                with self.assertRaises(ValueError):
                    wui.selected_wallets([])
                with self.assertRaises(ValueError):
                    wui.selected_wallets([str(one)]*33)

    def test_thunar_action_is_folder_only_and_no_generic_delete_is_enabled(self):
        from xml.etree import ElementTree as ET
        r=Path(__file__).resolve().parents[1]
        actions=ET.parse(r/'runtime/etc/skel/.config/Thunar/uca.xml').getroot()
        target=next(x for x in actions if x.findtext('unique-id')=='node-wallet-shred-delete')
        self.assertIsNotNone(target.find('directories'))
        self.assertIsNone(target.find('other-files'))
        self.assertEqual(target.findtext('command'),'/usr/local/bin/core-node-wallet-delete %F')
        code=(r/'app/file_browser.py').read_text()
        self.assertIn("'ro', 'nodev', 'nosuid', 'noexec'",code)
        admin=(r/'runtime/usr/libexec/core-node-admin').read_text()
        self.assertIn("action=='wallet-delete'",admin)

if __name__=='__main__': unittest.main(verbosity=2)
