import copy
import hashlib
import json
import os
from pathlib import Path
import pwd
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import chain_backup as cb


class PowerLoss(BaseException):pass


class ChainCopies(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.src=self.root/'source';self.src.mkdir()
        for name,content in {'blocks/index/CURRENT':b'MANIFEST-000001\n','blocks/index/MANIFEST-000001':b'index',
                             'blocks/blk00000.dat':b'public blocks'*100000,'blocks/rev00000.dat':b'undo',
                             'blocks/xor.dat':b'12345678','chainstate/CURRENT':b'MANIFEST-000002\n',
                             'chainstate/MANIFEST-000002':b'coins','indexes/txindex/CURRENT':b'old index'}.items():
            p=self.src/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
        self.events=cb.Events(emit=lambda row:None)
        self.fd=os.open(self.src,cb.DIR_FLAGS)
        dirs,files,total=cb.inventory(self.fd)
        for f in files:f['sha256']=hashlib.sha256((self.src/f['path']).read_bytes()).hexdigest()
        self.manifest=dict(format='bitcoin-core-node-chain',version=1,core_version='32.1',network='main',height=250,
                           bestblockhash='a'*64,prune_mib=1024,created_utc='2026-10-30T00:00:00Z',directories=dirs,files=files,total_bytes=total)
        (self.src/cb.MANIFEST).write_text(json.dumps(self.manifest))

    def tearDown(self):os.close(self.fd);self.tmp.cleanup()

    def test_complete_copy_checks_every_byte_and_includes_xor_and_block_index(self):
        target=self.root/'copy';target.mkdir();fd=os.open(target,cb.DIR_FLAGS)
        try:
            cb.make_dirs(fd,self.manifest['directories'])
            cb.copy_files(self.fd,fd,copy.deepcopy(self.manifest['files']),self.events)
            cb.verify_files(fd,self.manifest['files'],self.events)
        finally:os.close(fd)
        self.assertEqual((target/'blocks/xor.dat').read_bytes(),b'12345678')
        self.assertTrue((target/'blocks/index/CURRENT').is_file())

    def test_import_manifest_refuses_missing_modified_and_additional_chain_files(self):
        self.assertEqual(cb.load_manifest(self.fd,os.geteuid(),'main','32.1')['height'],250)
        p=self.src/'blocks/rev00000.dat';saved=p.read_bytes();p.unlink()
        with self.assertRaises(cb.ChainError):cb.load_manifest(self.fd,os.geteuid(),'main','32.1')
        p.write_bytes(saved+b'!')
        with self.assertRaises(cb.ChainError):cb.load_manifest(self.fd,os.geteuid(),'main','32.1')
        p.write_bytes(saved);(self.src/'chainstate/EXTRA').write_bytes(b'extra')
        with self.assertRaises(cb.ChainError):cb.load_manifest(self.fd,os.geteuid(),'main','32.1')

    def test_wrong_network_and_core_version_are_refused(self):
        for network,version in [('signet','32.1'),('main','32.2')]:
            with self.subTest(network=network,version=version),self.assertRaises(cb.ChainError):
                cb.parse_manifest(json.dumps(self.manifest),network,version)

    def test_manifest_rejects_traversal_duplicates_links_and_broken_totals(self):
        for mutation in ['absolute','parent','duplicate','prefix','boolean_size','digest','total','prune','orphan_directory']:
            m=copy.deepcopy(self.manifest)
            if mutation=='absolute':m['files'][0]['path']='/etc/shadow'
            elif mutation=='parent':m['files'][0]['path']='blocks/../../wallets/wallet.dat'
            elif mutation=='duplicate':m['files'].append(m['files'][0])
            elif mutation=='prefix':m['files'][0]['path']='wallets/wallet.dat'
            elif mutation=='boolean_size':m['files'][0]['size']=True
            elif mutation=='digest':m['files'][0]['sha256']='not a digest'
            elif mutation=='total':m['total_bytes']+=1
            elif mutation=='prune':m['prune_mib']=1
            else:m['directories'].append('chainstate/absent/child')
            with self.subTest(mutation=mutation),self.assertRaises(cb.ChainError):cb.parse_manifest(json.dumps(m),'main','32.1')

    def test_special_and_symbolic_or_hard_link_inputs_are_rejected(self):
        p=self.src/'chainstate/unsafe'
        p.symlink_to('/etc/passwd')
        with self.assertRaises(cb.ChainError):cb.inventory(self.fd)
        p.unlink();os.mkfifo(p)
        with self.assertRaises(cb.ChainError):cb.inventory(self.fd)
        p.unlink();os.link(self.src/'blocks/xor.dat',p)
        with self.assertRaises(cb.ChainError):cb.inventory(self.fd)

    def test_no_follow_walk_cannot_escape_via_parent_symlink(self):
        (self.src/'blocks/outside').symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(OSError):
            with cb.directory_at(self.fd,('blocks','outside')):pass

    def test_same_size_tampering_is_detected_before_activation(self):
        p=self.src/'blocks/xor.dat';p.write_bytes(b'87654321')
        target=self.root/'copy';target.mkdir();fd=os.open(target,cb.DIR_FLAGS)
        try:
            cb.make_dirs(fd,self.manifest['directories'])
            with self.assertRaises(cb.ChainError):cb.copy_files(self.fd,fd,copy.deepcopy(self.manifest['files']),self.events)
        finally:os.close(fd)

    def test_cancellation_is_observed_during_streaming(self):
        read,write=os.pipe()
        try:
            stream=os.fdopen(read,'rb',buffering=0);read=None
            os.write(write,b'c') # incomplete line must not block the broker
            with self.assertRaises(cb.Cancelled):cb.Events(stream=stream).check()
            stream.close()
        finally:
            if read is not None:os.close(read)
            os.close(write)

    @unittest.skipUnless(os.geteuid()==0,'requires identity boundary')
    def test_external_file_is_opened_with_callers_permissions(self):
        self.root.chmod(0o755);self.src.chmod(0o755)
        p=self.src/'private';p.write_bytes(b'root only');p.chmod(0o600)
        with self.assertRaises(PermissionError):cb.regular_at(self.fd,'private',pwd.getpwnam('nobody').pw_uid)


class AtomicImports(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name)
        self.owner=(os.getuid(),os.getgid())
        for name in cb.ROOTS:
            (self.data/name).mkdir();(self.data/name/'old').write_text(name)
        (self.data/'wallets').mkdir();(self.data/'wallets/wallet.dat').write_bytes(b'wallet must remain byte identical')
        (self.data/'settings.json').write_text('{"wallet":["watch"],"prune":"0","dbcache":"450"}')
        self.previous_settings=(self.data/'settings.json').read_bytes()
        self.stage=self.data/('.core-node-chain-'+'a'*32);self.stage.mkdir()
        (self.stage/'candidate').mkdir()
        for name in ('blocks','chainstate'):
            (self.stage/'candidate'/name).mkdir();(self.stage/'candidate'/name/'new').write_text(name)
        self.manifest=dict(network='main',prune_mib=1024,core_version='32.1',height=250,bestblockhash='a'*64)
        self.events=cb.Events(emit=lambda row:None)
        self.account=type('Account',(),dict(pw_uid=self.owner[0],pw_gid=self.owner[1]))()

    def tearDown(self):self.tmp.cleanup()

    def assert_old_and_wallet(self):
        for name in cb.ROOTS:self.assertEqual((self.data/name/'old').read_text(),name)
        self.assertEqual((self.data/'settings.json').read_bytes(),self.previous_settings)
        self.assertEqual((self.data/'wallets/wallet.dat').read_bytes(),b'wallet must remain byte identical')

    @unittest.skipUnless(os.geteuid()==0,'root-owned journal recovery')
    def test_every_rename_interruption_recovers_consistently_and_is_idempotent(self):
        original=os.rename
        for boundary in range(1,7):
            with self.subTest(boundary=boundary):
                if boundary>1:self.tearDown();self.setUp()
                count=0
                def interrupted(*a,**kw):
                    nonlocal count
                    count+=1
                    if count==boundary:raise PowerLoss()
                    return original(*a,**kw)
                with patch.object(cb.os,'rename',side_effect=interrupted),patch.object(cb,'recover',side_effect=PowerLoss):
                    with self.assertRaises(PowerLoss):cb.activate(self.data,self.stage,self.manifest,self.owner,self.events)
                with patch.object(cb.pwd,'getpwnam',return_value=self.account):
                    cb.recover(self.data);cb.recover(self.data)
                self.assert_old_and_wallet()

    @unittest.skipUnless(os.geteuid()==0,'root-owned journal recovery')
    def test_success_keeps_wallets_preferences_and_removes_stale_snapshot_and_indexes(self):
        cb.activate(self.data,self.stage,self.manifest,self.owner,self.events)
        self.assertEqual((self.data/'blocks/new').read_text(),'blocks')
        self.assertEqual((self.data/'chainstate/new').read_text(),'chainstate')
        self.assertFalse((self.data/'indexes').exists());self.assertFalse((self.data/'chainstate_snapshot').exists())
        settings=json.loads((self.data/'settings.json').read_text())
        self.assertEqual(settings,dict(wallet=['watch'],prune='1024',dbcache='450'))
        self.assertEqual((self.data/'wallets/wallet.dat').read_bytes(),b'wallet must remain byte identical')
        self.assertFalse((self.data/cb.JOURNAL).exists());self.assertFalse(self.stage.exists())
        receipt=json.loads((self.data/cb.CHAIN_IMPORT_RECEIPT).read_text())
        self.assertEqual(receipt['bestblockhash'],'a'*64)

    @unittest.skipUnless(os.geteuid()==0,'root-owned journal recovery')
    def test_committed_power_loss_keeps_new_chain_on_next_start(self):
        with patch.object(cb,'recover',side_effect=PowerLoss):
            with self.assertRaises(PowerLoss):cb.activate(self.data,self.stage,self.manifest,self.owner,self.events)
        self.assertEqual(json.loads((self.data/cb.JOURNAL).read_text())['phase'],'committed')
        cb.recover(self.data);cb.recover(self.data)
        self.assertTrue((self.data/'blocks/new').is_file())
        self.assertEqual(json.loads((self.data/'settings.json').read_text())['prune'],'1024')
        self.assertTrue((self.data/cb.CHAIN_IMPORT_RECEIPT).is_file())

    @unittest.skipUnless(os.geteuid()==0,'root-owned journal recovery')
    def test_settings_failure_rolls_back_chain_and_preserves_wallet_bytes(self):
        original=cb.restore_settings;count=0
        def fail_once(*a,**kw):
            nonlocal count
            count+=1
            if count==1:raise OSError('synthetic disk error')
            return original(*a,**kw)
        with patch.object(cb,'restore_settings',side_effect=fail_once),patch.object(cb.pwd,'getpwnam',return_value=self.account):
            with self.assertRaises(OSError):cb.activate(self.data,self.stage,self.manifest,self.owner,self.events)
        self.assert_old_and_wallet()

    @unittest.skipUnless(os.geteuid()==0,'root-owned journal recovery')
    def test_non_mainnet_uses_shared_managed_gui_settings(self):
        regtest=self.data/'regtest';regtest.mkdir()
        for name in cb.ROOTS:os.rename(self.data/name,regtest/name)
        nested=self.stage/'candidate/regtest';nested.mkdir()
        for name in ('blocks','chainstate'):os.rename(self.stage/'candidate'/name,nested/name)
        self.manifest['network']='regtest'
        cb.activate(self.data,self.stage,self.manifest,self.owner,self.events)
        self.assertEqual(json.loads((self.data/'settings.json').read_text())['prune'],'1024')
        self.assertFalse((regtest/'settings.json').exists())
        self.assertTrue((regtest/'blocks/new').is_file())


if __name__=='__main__':unittest.main()
