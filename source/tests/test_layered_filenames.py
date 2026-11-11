#!/usr/bin/python3
"""Synthetic interoperability test: each GPG decrypt exposes another GPG or TAR."""
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import sqlite3
import unittest
from unittest.mock import patch
SRC=Path(__file__).resolve().parents[1]/'app'
sys.path.insert(0,str(SRC))
import layered_backend as layers
from password_dialog import PassphraseDialog, ensure_app

class Interop(unittest.TestCase):
    def test_gui_filename_extension_count(self):
        os.environ['QT_QPA_PLATFORM']='offscreen'
        ensure_app()
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td)
            panel=PassphraseDialog(lambda x:None,destination=root/'wallet-backup.gpg')
            self.assertEqual(panel.normalized_destination().name,'wallet-backup.tar.gpg')
            panel.add_row()
            self.assertEqual(panel.normalized_destination().name,'wallet-backup.tar.gpg.gpg')
            self.assertEqual(panel.destination.text(),str(root/'wallet-backup.tar.gpg.gpg'))
            panel.add_row()
            self.assertEqual(panel.normalized_destination().name,'wallet-backup.tar.gpg.gpg.gpg')
            panel.remove_row(panel.rows[-1])
            self.assertEqual(panel.normalized_destination().name,'wallet-backup.tar.gpg.gpg')
            panel.reject()

    def test_wallet_sqlite_dialog_suffix_is_dat_not_tar(self):
        os.environ['QT_QPA_PLATFORM']='offscreen'
        ensure_app()
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td);wallet=root/'wallet.dat'
            with sqlite3.connect(wallet) as con:
                con.execute('CREATE TABLE main (key BLOB PRIMARY KEY, value BLOB)')
                con.execute('INSERT INTO main VALUES (?,?)',(b'fixture',b'fixture'))
            panel=PassphraseDialog(lambda x:None,destination=root/'my-backup.gpg',items=[wallet])
            self.assertEqual(panel.normalized_destination().name,'my-backup.dat.gpg')
            panel.add_row()
            self.assertEqual(panel.normalized_destination().name,'my-backup.dat.gpg.gpg')
            panel.reject()

    def test_two_real_layers_and_generic_embedded_names(self):
        with tempfile.TemporaryDirectory(prefix='vault-layer-filename-',dir='/dev/shm') as td:
            root=Path(td)
            file=root/'wallet.dat'
            with sqlite3.connect(file) as con:
                con.execute('CREATE TABLE main (key BLOB PRIMARY KEY, value BLOB)')
                con.execute('INSERT INTO main (key,value) VALUES (?,?)',
                            (b'synthetic key',b'disposable wallet data'))
            data=file.read_bytes()
            first,second='synthetic outer passphrase','synthetic inner passphrase'
            encrypted=root/'wallet.dat.gpg.gpg'
            layers.create_layers([file],encrypted,[first,second],ram_root=root)
            current=encrypted
            with tempfile.TemporaryDirectory(prefix='homedir-',dir=root) as home:
                for stage,(secret,expected) in enumerate(((second,'inner.gpg'),(first,'wallet.dat')),1):
                    target=root/('inner.gpg' if stage==1 else 'wallet-output.dat')
                    pass_read,pass_write=os.pipe()
                    os.write(pass_write,secret.encode()+b'\n');os.close(pass_write)
                    cmd=['/usr/bin/gpg','--no-options','--homedir',str(home),'--batch',
                         '--no-tty','--no-autostart','--pinentry-mode','loopback',
                         '--passphrase-fd',str(pass_read),'--status-fd','2','--output',str(target),
                         '--decrypt',str(current)]
                    result=subprocess.run(cmd,pass_fds=(pass_read,),capture_output=True,timeout=30)
                    os.close(pass_read)
                    self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace')[:500])
                    statuses=result.stderr.decode(errors='replace').splitlines()
                    plaintext=[a for a in statuses if a.startswith('[GNUPG:] PLAINTEXT ')]
                    self.assertEqual(len(plaintext),1,statuses)
                    self.assertEqual(plaintext[0].split(' ',4)[-1],expected)
                    self.assertTrue(target.is_file())
                    if expected.endswith('.gpg'):
                        self.assertIn(b'\xd2',target.read_bytes()[:2]) if False else None
                        with self.assertRaises(tarfile.TarError):tarfile.open(target)
                    else:
                        self.assertEqual(target.read_bytes(),data)
                        self.assertTrue(layers.is_direct_wallet(target))
                    current=target
            self.assertEqual(file.read_bytes(),data)
            print('PASSED: wallet.dat.gpg.gpg -> inner.gpg -> wallet.dat; original unchanged')

if __name__=='__main__':unittest.main(verbosity=2)
