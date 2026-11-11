"""Synthetic batch deletion and real Qt process completion; no actual Core wallets."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch,call
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtCore import QProcess,QTimer
from PySide6.QtWidgets import QApplication,QDialog
import wallet_delete as wd
import wallet_delete_ui as wui


APP=None
def application():
    global APP
    APP=QApplication.instance() or APP or QApplication([])
    APP.setQuitOnLastWindowClosed(False)
    return APP


def fixture_wallet(root,name):
    wallet=root/name;wallet.mkdir()
    db=sqlite3.connect(wallet/'wallet.dat')
    try:
        db.execute('CREATE TABLE synthetic (key TEXT, value TEXT)')
        db.execute('INSERT INTO synthetic VALUES (?,?)',('test','disposable'))
        db.commit()
    finally:
        db.close()
    return wallet


def contexts(root):
    import types
    user=types.SimpleNamespace(pw_uid=os.getuid())
    def lookup(name):
        assert name in ('node','bitcoinnode'),name
        return user
    return (patch.object(wd,'WALLET_ROOT',root),
            patch.object(wd.os,'geteuid',return_value=0),
            patch.dict(os.environ,{'PKEXEC_UID':str(os.getuid())}),
            patch.object(wd.pwd,'getpwnam',side_effect=lookup),
            patch.object(wd,'load_setup',return_value={'data_uuid':None}),
            patch.object(wd,'verify_data_mount',return_value=True))


class BackendMultipleWallets(unittest.TestCase):
    def test_two_unloaded_wallets_stop_core_only_once(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)/'wallets';root.mkdir()
            wallet1=fixture_wallet(root,'first')
            wallet2=fixture_wallet(root,'second')
            keep=fixture_wallet(root,'KEEP')
            previous=(keep/'wallet.dat').read_bytes()
            ctx=contexts(root)
            with ctx[0],ctx[1],ctx[2],ctx[3],ctx[4],ctx[5],\
                 patch.object(wd,'running',side_effect=[True,False]),\
                 patch.object(wd,'command') as service,\
                 patch('rpc.CoreRPC',return_value=lambda method:[]):
                result=wd.perform(dict(wallets=['first','second'],confirmed=True,
                                       profile='three-pass-best-effort'))
            self.assertEqual(result['removed_wallets'],['first','second'])
            self.assertEqual(service.call_args_list,[
                call('stop',wd.SERVICE),call('start',wd.SERVICE,timeout=120)])
            self.assertFalse(wallet1.exists())
            self.assertFalse(wallet2.exists())
            self.assertEqual((keep/'wallet.dat').read_bytes(),previous)

    def test_loaded_wallet_batch_is_closed_and_removed_together(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)/'wallets';root.mkdir()
            a=fixture_wallet(root,'first')
            b=fixture_wallet(root,'second')
            settings=root.parent/'settings.json'
            settings.write_text(json.dumps({'wallet':['first','second','keep']}))
            ctx=contexts(root)
            with ctx[0],ctx[1],ctx[2],ctx[3],ctx[4],ctx[5],\
                 patch.object(wd,'running',side_effect=[True,False]),\
                 patch.object(wd,'command') as service,\
                 patch('rpc.CoreRPC',return_value=lambda method:['second']):
                result=wd.perform(dict(wallets=['first','second'],confirmed=True,
                                      profile='three-pass-best-effort'))
                self.assertEqual(service.call_args_list,[call('stop',wd.SERVICE),
                                  call('start',wd.SERVICE,timeout=120)])
            self.assertTrue(result['ok'])
            self.assertFalse(a.exists());self.assertFalse(b.exists())
            self.assertEqual(json.loads(settings.read_text()),{'wallet':['keep']})

    def test_invalid_item_preflight_refuses_other_wallet_without_core_shutdown(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)/'wallets';root.mkdir()
            good=fixture_wallet(root,'good')
            bad=root/'invalid';bad.mkdir();(bad/'other.dat').write_bytes(b'no')
            ctx=contexts(root)
            with ctx[0],ctx[1],ctx[2],ctx[3],ctx[4],ctx[5],\
                 patch.object(wd,'running') as running,\
                 patch.object(wd,'command') as service:
                with self.assertRaisesRegex(wd.WalletDeleteError,'wallet.dat'):
                    wd.perform(dict(wallets=['good','invalid'],confirmed=True,
                                    profile='three-pass-best-effort'))
                running.assert_not_called();service.assert_not_called()
            self.assertTrue(good.exists())
            self.assertTrue((bad/'other.dat').exists())

    def test_batch_count_legacy_single_and_duplicate_names(self):
        self.assertEqual(wd.request_names(dict(wallet='single',confirmed=True,
                        profile='three-pass-best-effort')),['single'])
        self.assertEqual(wd.request_names(dict(wallets=['a','b'],confirmed=True,
                        profile='three-pass-best-effort')),['a','b'])
        for names in ([],['a']*33,['a','a'],['a','../blocks']):
            with self.subTest(names=names):
                with self.assertRaises(wd.WalletDeleteError):
                    wd.request_names(dict(wallets=names,confirmed=True,
                                          profile='three-pass-best-effort'))


class QtProcessCompletion(unittest.TestCase):
    def _simulate(self,dialog,script):
        # No pkexec, Bitcoin Core, or real wallet data. Exercise actual
        # QProcess.finished/errorOccurred paths using a harmless Python child.
        process=QProcess(dialog)
        dialog.worker=process
        process.setProgram('/usr/bin/python3')
        process.setArguments(['-c',script])
        process.finished.connect(dialog.operation_finished)
        process.errorOccurred.connect(dialog.process_error)
        process.start()

    def test_after_success_progress_closes_automatically_and_never_locks_close(self):
        application()
        dialog=wui.WalletDeletionProgress(['alpha','beta'])
        payload=json.dumps(dict(ok=True,removed_wallets=['alpha','beta'],files=2))
        QTimer.singleShot(0,lambda:self._simulate(
            dialog,'import time;time.sleep(0.09);print('+repr(payload)+')'))
        QTimer.singleShot(5000,dialog.reject)
        result=dialog.exec()
        self.assertEqual(result,QDialog.Accepted)
        self.assertTrue(dialog.completed)
        self.assertIsNone(dialog.worker)
        self.assertFalse(dialog.isVisible())

    def test_helper_failure_unlocks_close_and_never_claims_success(self):
        application()
        dialog=wui.WalletDeletionProgress(['alpha'])
        QTimer.singleShot(0,lambda:self._simulate(
            dialog,'import sys;sys.exit(1)'))
        def close_on_failure():
            if dialog.worker is not None:
                QTimer.singleShot(15,close_on_failure)
                return
            self.assertTrue(dialog.close_button.isEnabled())
            self.assertEqual(dialog.close_button.text(),'Close')
            self.assertFalse(dialog.completed)
            dialog.close_button.click()
        QTimer.singleShot(20,close_on_failure)
        QTimer.singleShot(5000,dialog.reject)
        result=dialog.exec()
        self.assertEqual(result,QDialog.Rejected)
        self.assertIsNone(dialog.worker)
        self.assertFalse(dialog.completed)

    def test_failed_to_start_allows_close_instead_of_stuck_modal(self):
        application()
        dialog=wui.WalletDeletionProgress(['alpha'])
        def fail_launch():
            worker=QProcess(dialog);dialog.worker=worker
            worker.setProgram('/invalid/path/never/exists')
            worker.errorOccurred.connect(dialog.process_error)
            worker.finished.connect(dialog.operation_finished)
            worker.start()
        QTimer.singleShot(0,fail_launch)
        def close_on_failure():
            if dialog.worker is not None:
                QTimer.singleShot(15,close_on_failure)
                return
            self.assertTrue(dialog.close_button.isEnabled())
            dialog.close_button.click()
        QTimer.singleShot(20,close_on_failure)
        QTimer.singleShot(5000,dialog.reject)
        self.assertEqual(dialog.exec(),QDialog.Rejected)
        self.assertIsNone(dialog.worker)


if __name__=='__main__':unittest.main()
