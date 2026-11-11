"""Synthetic settings only: no production wallets or private key material."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from wallet_startup import clean_startup, read_settings, WalletStartupError


class StartupCleanup(unittest.TestCase):
    def test_missing_local_aliases_removed_and_watch_only_and_unknown_keys_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            data=Path(td);root=data/'wallets';root.mkdir()
            (root/'watch-only').mkdir()
            (root/'damaged-but-existing').mkdir()
            external=str(data/'external'/'absent')
            kept=['watch-only','damaged-but-existing',external,'nested/absent','../outside','']
            deleted=['gone','./gone',str(root/'gone')]
            settings=data/'settings.json'
            record={'wallet':deleted+kept,'prune':'550','future-option':{'x':[True,4]}}
            settings.write_text(json.dumps(record));settings.chmod(0o600)
            removed=clean_startup(settings,root,os.getuid(),missing=True)
            self.assertEqual(removed,deleted)
            self.assertEqual(json.loads(settings.read_text()),dict(record,wallet=kept))
            self.assertEqual(settings.stat().st_uid,os.getuid())
            self.assertEqual(settings.stat().st_mode & 0o777,0o600)
            unchanged=settings.stat().st_mtime_ns
            self.assertEqual(clean_startup(settings,root,os.getuid(),missing=True),[])
            self.assertEqual(settings.stat().st_mtime_ns,unchanged)

    def test_selected_wallet_is_forgotten_while_its_directory_still_exists(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'wallets';root.mkdir();(root/'selected').mkdir()
            path=Path(td)/'settings.json'
            path.write_text(json.dumps({'wallet':['selected',str(root/'selected'),'keep']}))
            self.assertEqual(len(clean_startup(path,root,os.getuid(),selected=['selected'])),2)
            self.assertEqual(json.loads(path.read_text())['wallet'],['keep'])

    def test_unsafe_or_malformed_settings_fail_without_changes(self):
        for text in ('{bad','[]','{"wallet":"gone"}','{"wallet":[3]}',
                     '{"wallet":[],"wallet":["gone"]}'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as td:
                root=Path(td)/'wallets';root.mkdir();path=Path(td)/'settings.json'
                path.write_text(text)
                with self.assertRaises(WalletStartupError):
                    clean_startup(path,root,os.getuid(),missing=True)
                self.assertEqual(path.read_text(),text)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'settings.json';other=Path(td)/'other'
            other.write_text('{"wallet":["gone"]}');path.symlink_to(other)
            with self.assertRaises(WalletStartupError):read_settings(path,os.getuid())
            path.unlink();os.link(other,path)
            with self.assertRaises(WalletStartupError):read_settings(path,os.getuid())

    def test_missing_wallet_root_refuses_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'settings.json';path.write_text('{"wallet":["gone"]}')
            with self.assertRaises(WalletStartupError):
                clean_startup(path,Path(td)/'not-mounted',os.getuid(),missing=True)
            self.assertEqual(json.loads(path.read_text())['wallet'],['gone'])


if __name__=='__main__':unittest.main()
