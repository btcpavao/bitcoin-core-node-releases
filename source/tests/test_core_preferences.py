import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtCore import QSettings
from core_preferences import prepare_user_files, validate_user_config
from state import core_arguments, default_setup


class NativePreferences(unittest.TestCase):
    def test_defaults_enabled_once_and_user_choices_and_configuration_survive(self):
        with tempfile.TemporaryDirectory() as td:
            data=Path(td)/'data';data.mkdir();home=Path(td)/'home';home.mkdir()
            prepare_user_files(data,home)
            settings=QSettings(str(home/'.config/Bitcoin/Bitcoin-Qt.conf'),QSettings.IniFormat)
            for key in ('fCoinControlFeatures','enable_psbt_controls'):
                self.assertTrue(settings.value(key,type=bool))
                settings.setValue(key,False)
            settings.setValue('unrelated','keep');settings.sync()
            with (data/'bitcoin.conf').open('a') as stream:stream.write('dbcache=600\n')
            prepare_user_files(data,home)
            settings.sync()
            for key in ('fCoinControlFeatures','enable_psbt_controls'):
                self.assertFalse(settings.value(key,type=bool))
            self.assertEqual(settings.value('unrelated'),'keep')
            self.assertIn('dbcache=600',(data/'bitcoin.conf').read_text())
            self.assertEqual((data/'bitcoin.conf').stat().st_mode & 0o777,0o600)

    def test_config_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            data=Path(td);(data/'bitcoin.conf').symlink_to(data/'outside')
            with self.assertRaises(RuntimeError):prepare_user_files(data,data/'home')
            self.assertFalse((data/'outside').exists())

    def test_signet_and_regtest_use_native_network_specific_preferences(self):
        with tempfile.TemporaryDirectory() as td:
            data=Path(td)/'data';data.mkdir();home=Path(td)/'home';home.mkdir()
            for network in ('signet','regtest'):
                prepare_user_files(data,home,network=network)
                settings=QSettings(str(home/('.config/Bitcoin/Bitcoin-Qt-'+network+'.conf')),
                                   QSettings.IniFormat)
                self.assertTrue(settings.value('fCoinControlFeatures',type=bool))
                self.assertTrue(settings.value('enable_psbt_controls',type=bool))

    def test_opaque_upstream_qvariant_bytes_survive_default_migration(self):
        with tempfile.TemporaryDirectory() as td:
            data=Path(td)/'data';data.mkdir();home=Path(td)/'home';home.mkdir()
            prefs=home/'.config/Bitcoin';prefs.mkdir(parents=True)
            path=prefs/'Bitcoin-Qt.conf'
            opaque=r'nDisplayUnit=@Variant(\0\0\0\x7f\0\0\0\fBitcoinUnit\0\0\0\0\0)'
            path.write_text('[General]\nfCoinControlFeatures=false\n'+opaque+'\n[Other]\nx=y\n')
            prepare_user_files(data,home)
            self.assertIn(opaque+'\n',path.read_text())
            self.assertIn('fCoinControlFeatures=false\n',path.read_text())
            self.assertIn('enable_psbt_controls=true\n[Other]',path.read_text())
            first=path.read_bytes();prepare_user_files(data,home)
            self.assertEqual(path.read_bytes(),first)

    def test_list_options_negations_and_includes_cannot_override_managed_policy(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'bitcoin.conf'
            for text in ('onlynet=ipv4','[main]\nrpcbind=0.0.0.0','main.nolisten=0',
                         'includeconf=other.conf','noproxy=1','wallet=/outside',
                         'rpcallowip=0.0.0.0/0','regtest=1'):
                with self.subTest(text=text):
                    path.write_text(text)
                    with self.assertRaises(RuntimeError):validate_user_config(path)
            path.write_text('dbcache=600\n[main]\ntxindex=1\n')
            validate_user_config(path)

    def test_editable_conf_keeps_explicit_managed_privacy_rpc_and_storage_flags(self):
        args=core_arguments(default_setup())
        self.assertIn('-conf=/var/lib/bitcoin-core-node/data/bitcoin.conf',args)
        for value in ('-rpcbind=127.0.0.1','-rpcallowip=127.0.0.1','-rpcport=8332',
                      '-listen=0','-discover=0','-walletdir=/var/lib/bitcoin-core-node/data/wallets'):
            self.assertIn(value,args)


if __name__=='__main__':unittest.main()
