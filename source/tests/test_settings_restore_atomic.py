"""Run as root only inside a disposable Node VM; all writes in a temporary tree."""
import copy,json,os,pwd,shutil,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import settings_restore as r
import settings_snapshot as s
from test_settings_snapshot import payload,WIFI

class PowerLoss(BaseException):pass

@unittest.skipUnless(os.geteuid()==0,'requires root-owned isolated fixture')
class AtomicSettings(unittest.TestCase):
    def setUp(self):
        try:self.node=pwd.getpwnam('node');self.core=pwd.getpwnam('bitcoinnode')
        except KeyError:self.skipTest('Node fixture accounts required')
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.state=self.root/'state';self.state.mkdir(mode=0o700)
        self.put('etc/bitcoin-core-node/setup.json',s.canonical(dict(version=1,confirmed=True,profile='clearnet',network='main',prune_mib=0,private_broadcast=False,data_uuid='abcd1234-5678')))
        self.put('etc/default/keyboard',b'XKBLAYOUT="us"\n')
        self.put('etc/core-display-scale.conf',b'1\n')
        self.put('etc/timezone',b'Etc/UTC\n')
        for name in ('Etc/UTC','Europe/Zagreb'):
            self.put('usr/share/zoneinfo/'+name,Path('/usr/share/zoneinfo',name).read_bytes())
        (self.root/'etc/localtime').symlink_to('../usr/share/zoneinfo/Etc/UTC')
        self.put('var/lib/bitcoin-core-node/data/settings.json',b'{"wallet":["target-only"],"dbcache":"450"}',self.core)
        self.put('var/lib/bitcoin-core-node/data/bitcoin.conf',b'# target\nmaxmempool=300\n[signet]\ndbcache=777\n',self.core)
        self.put('var/lib/bitcoin-core-node/data/wallets/target-only/wallet.dat',b'never touch wallet',self.core)
        self.put('var/lib/bitcoin-core-node/data/chainstate/fixture',b'never touch chain',self.core)
        self.put('etc/shadow',b'never touch login')
        self.put('etc/machine-id',b'local-machine-only')
        self.put('etc/NetworkManager/system-connections/source name.nmconnection',s.nm_profile(WIFI)['keyfile'].encode())
        self.data=payload();self.data['core']['maxmempool']='512'
        s.atomic_private(self.state/'pending.json',self.data)

    def put(self,name,body,owner=None):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body);p.chmod(0o600)
        if owner:os.chown(p,owner.pw_uid,owner.pw_gid)

    def tearDown(self):self.temp.cleanup()

    def apply(self):
        with patch('upgrades.active_release',return_value={'version':'32.1'}):r.apply_pending(self.state,self.root)

    def preserved(self):
        self.assertEqual((self.root/'etc/shadow').read_bytes(),b'never touch login')
        self.assertEqual((self.root/'etc/machine-id').read_bytes(),b'local-machine-only')
        self.assertEqual((self.root/'var/lib/bitcoin-core-node/data/wallets/target-only/wallet.dat').read_bytes(),b'never touch wallet')
        self.assertEqual((self.root/'var/lib/bitcoin-core-node/data/chainstate/fixture').read_bytes(),b'never touch chain')

    def test_success_merges_network_and_core_without_machine_identity(self):
        self.apply();self.preserved()
        self.assertEqual(json.loads((self.root/'etc/bitcoin-core-node/setup.json').read_bytes())['data_uuid'],'abcd1234-5678')
        settings=json.loads((self.root/'var/lib/bitcoin-core-node/data/settings.json').read_bytes())
        self.assertEqual(settings['wallet'],['target-only']);self.assertEqual(settings['dbcache'],'256')
        conf=(self.root/'var/lib/bitcoin-core-node/data/bitcoin.conf').read_text();self.assertIn('[signet]\ndbcache=777',conf)
        files=list((self.root/'etc/NetworkManager/system-connections').iterdir());self.assertEqual(len(files),1)
        self.assertEqual(files[0].stat().st_mode&0o777,0o600)
        self.assertEqual(os.readlink(self.root/'etc/localtime'),'../usr/share/zoneinfo/Europe/Zagreb')
        self.assertFalse((self.state/'rollback.json').exists());self.assertFalse((self.state/'pending.json').exists())

    def test_runtime_failure_rolls_back_every_prior_file(self):
        original=r.write_record;calls=0
        def fail_once(*args):
            nonlocal calls
            calls+=1
            if calls==7:raise OSError('synthetic failure')
            return original(*args)
        with patch.object(r,'write_record',side_effect=fail_once),self.assertRaises(s.SettingsError):self.apply()
        self.preserved();self.assertEqual((self.root/'etc/default/keyboard').read_bytes(),b'XKBLAYOUT="us"\n')
        self.assertEqual(os.readlink(self.root/'etc/localtime'),'../usr/share/zoneinfo/Etc/UTC')
        self.assertFalse(json.loads((self.state/'result.json').read_bytes())['ok'])

    def test_crash_journal_recovers_before_next_apply(self):
        original=r.write_record;calls=0;recover=r.recover
        def loss(*args):
            nonlocal calls
            calls+=1
            if calls==8:raise PowerLoss()
            return original(*args)
        def defer(*args):
            if (self.state/'rollback.json').exists():raise PowerLoss()
            return recover(*args)
        with patch.object(r,'write_record',side_effect=loss),patch.object(r,'recover',side_effect=defer),self.assertRaises(PowerLoss):self.apply()
        self.assertTrue((self.state/'rollback.json').exists())
        r.recover(self.state,self.root);r.recover(self.state,self.root)
        self.preserved();self.assertEqual((self.root/'etc/default/keyboard').read_bytes(),b'XKBLAYOUT="us"\n')
        self.apply();self.assertEqual((self.root/'etc/timezone').read_text(),'Europe/Zagreb\n')

    def test_malformed_pending_and_symlink_target_have_no_privileged_side_effect(self):
        (self.root/'etc/default/keyboard').unlink();(self.root/'etc/default/keyboard').symlink_to('/etc/shadow')
        with self.assertRaises(s.SettingsError):self.apply()
        self.preserved();self.assertTrue((self.root/'etc/default/keyboard').is_symlink())

    def test_different_network_refused_before_writes(self):
        self.data['node']['network']='regtest';s.atomic_private(self.state/'pending.json',self.data)
        with self.assertRaises(s.SettingsError):self.apply()
        self.preserved();self.assertEqual((self.root/'etc/timezone').read_text(),'Etc/UTC\n')

if __name__=='__main__':unittest.main()
