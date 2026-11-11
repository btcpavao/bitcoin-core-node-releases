#!/usr/bin/python3
"""Nonsecret core-wallet fixture: direct GPG, multi-file TAR, legacy TAR recovery."""
import os
import sqlite3
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import sys
SRC=Path(__file__).resolve().parents[1]/'app'
sys.path.insert(0,str(SRC))
import layered_backend as layers
import gpg_backend

class DirectWallet(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(prefix='vault-direct-test-',dir='/dev/shm')
        self.root=Path(self.t.name)
        self.wallet=self.root/'wallet.dat'
        with sqlite3.connect(self.wallet) as con:
            con.execute('CREATE TABLE main (key BLOB PRIMARY KEY, value BLOB)')
            con.execute('INSERT INTO main (key,value) VALUES (?,?)',
                        (b'synthetic-not-a-secret',b'fake wallet data'))
        self.original=self.wallet.read_bytes()
        self.secrets=('synthetic-phrase-A','synthetic-phrase-B')
        self.workspace=self.root/'workspace';self.workspace.mkdir(mode=0o700)
    def tearDown(self):
        self.t.cleanup()

    def test_single_wallet_goes_directly_to_wallet_dat(self):
        crypt=self.root/'wallet.dat.gpg.gpg'
        layers.create_layers([self.wallet],crypt,self.secrets,ram_root=self.root)
        with layers.recover_payload(crypt,list(reversed(self.secrets)),ram_root=self.root) as payload:
            self.assertFalse(layers.is_tar_payload(payload))
            self.assertTrue(layers.is_direct_wallet(payload))
            self.assertEqual(payload.read_bytes(),self.original)
        recovered=layers.recover_files(crypt,self.workspace/'recovered',self.secrets,
                                       ram_root=self.root,workspace=self.workspace)
        self.assertEqual([p.name for p in recovered.iterdir()],['wallet.dat'])
        self.assertEqual((recovered/'wallet.dat').read_bytes(),self.original)

    def test_multifile_still_tar(self):
        note=self.root/'notes.txt';note.write_text('synthetic')
        crypt=self.root/'many.tar.gpg'
        layers.create_layers([self.wallet,note],crypt,[self.secrets[0]],ram_root=self.root)
        with layers.recover_payload(crypt,[self.secrets[0]],ram_root=self.root) as payload:
            self.assertTrue(layers.is_tar_payload(payload))
            self.assertFalse(layers.is_direct_wallet(payload))
        out=layers.recover_files(crypt,self.workspace/'multi',self.secrets[:1],
                                 ram_root=self.root,workspace=self.workspace)
        self.assertEqual(sorted(p.name for p in out.iterdir()),['notes.txt','wallet.dat'])

    def test_legacy_single_wallet_tar_still_restores(self):
        payload=self.root/'old-payload.tar'
        layers.package([self.wallet],payload,limit=layers.MAX_BYTES,budget=layers.Budget())
        crypt=self.root/'old-wallet.gpg'
        gpg_backend.encrypt_file(payload,crypt,self.secrets[0],ram_root=self.root,
                                 embedded_name='payload.tar')
        with layers.recover_payload(crypt,self.secrets[:1],ram_root=self.root) as recovered:
            self.assertTrue(layers.is_tar_payload(recovered))
        restored=layers.recover_files(crypt,self.workspace/'legacy',self.secrets[:1],
                                      ram_root=self.root,workspace=self.workspace)
        self.assertEqual((restored/'wallet.dat').read_bytes(),self.original)

    def test_invalid_wallet_does_not_silently_create_bogus_backup(self):
        self.wallet.write_bytes(b'not a supported wallet.dat')
        # Node's generic Encrypt Files accepts ordinary input; it must NOT
        # mistake a fake wallet.dat filename for a Core SQLite database.
        output=self.root/'invalid.tar.gpg'
        layers.create_layers([self.wallet],output,self.secrets[:1],ram_root=self.root)
        with layers.recover_payload(output,self.secrets[:1],ram_root=self.root) as recovered:
            self.assertTrue(layers.is_tar_payload(recovered))
            self.assertFalse(layers.is_direct_wallet(recovered))

if __name__ == '__main__':
    unittest.main(verbosity=2)
