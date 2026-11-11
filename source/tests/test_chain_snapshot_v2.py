"""Cold-copy invariants and automatic selection of completed snapshots only."""
import contextlib,copy,hashlib,json,os
from pathlib import Path
import tempfile,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import chain_backup as cb

class SnapshotV2(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.data=self.base/'data';self.data.mkdir();self.usb=self.base/'usb';self.usb.mkdir()
        self.files={'blocks/index/CURRENT':b'MANIFEST-000001\n','blocks/index/MANIFEST-000001':b'index',
                    'blocks/blk00000.dat':b'blocks'*128,'blocks/xor.dat':b'12345678',
                    'chainstate/CURRENT':b'MANIFEST-000002\n','chainstate/MANIFEST-000002':b'chain'}
        for name,content in self.files.items():
            p=self.data/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
        (self.data/'wallets').mkdir();(self.data/'wallets/wallet.dat').write_bytes(b'private wallet sentinel')
        self.uid=os.getuid();self.events=cb.Events(emit=lambda row:None)
        self.setup={'network':'main','prune_mib':0};self.release={'version':'32.1'}
        self.stack=contextlib.ExitStack()
        def external(path,uid,writing=False):
            p=Path(path);return os.open(p,cb.DIR_FLAGS),p,'exfat'
        self.stack.enter_context(patch.object(cb,'external',side_effect=external))
        self.stack.enter_context(patch.object(cb,'chain_root',return_value=self.data))
        self.stack.enter_context(patch.object(cb,'core_lock',return_value=contextlib.nullcontext()))
        self.stack.enter_context(patch.object(cb,'settings_read',return_value=(None,{})))
        self.probe=self.stack.enter_context(patch.object(cb,'probe',side_effect=AssertionError('A backup must NOT launch another Core')))

    def tearDown(self):self.stack.close();self.tmp.cleanup()
    def backup(self,hint=None,events=None):
        return cb.backup(str(self.usb),self.uid,self.setup,self.release,events or self.events,tip_hint=hint)
    def select(self,path=None):
        fd,resolved,fs,m=cb.open_backup(str(path or self.usb),self.uid,'main','32.1')
        os.close(fd);return resolved,m

    def test_stopped_backup_needs_no_core_process_or_rpc(self):
        before={p: (self.data/p).read_bytes() for p in self.files}
        result=self.backup();path=Path(result['directory']);m=json.loads((path/cb.MANIFEST).read_text())
        self.assertEqual(m['version'],2);self.assertIsNone(m['height']);self.assertIsNone(m['bestblockhash'])
        self.probe.assert_not_called()
        self.assertEqual(before,{p:(self.data/p).read_bytes() for p in self.files})
        self.assertFalse((path/'wallets').exists())
        self.assertEqual(self.select()[0],path)

    def test_hint_is_explicit_and_streamed_checksums_match_saved_files(self):
        r=self.backup({'blocks':100,'bestblockhash':'a'*64,'pruned':False})
        p,m=self.select();self.assertEqual(m['height'],100);self.assertTrue(r['tip_is_hint'])
        for entry in m['files']:
            self.assertEqual(hashlib.sha256((p/entry['path']).read_bytes()).hexdigest(),entry['sha256'])
        self.probe.assert_not_called()

    def test_successful_second_copy_updates_shortcut_but_preserves_old_snapshot(self):
        first=self.backup();(self.data/'blocks/blk00000.dat').write_bytes(b'new blocks')
        second=self.backup();chosen,m=self.select()
        self.assertEqual(str(chosen),second['directory']);self.assertNotEqual(first['directory'],second['directory'])
        self.assertEqual((Path(first['directory'])/'blocks/blk00000.dat').read_bytes(),self.files['blocks/blk00000.dat'])
        self.assertEqual((chosen/'blocks/blk00000.dat').read_bytes(),b'new blocks')

    def test_cancelled_second_copy_keeps_previous_latest(self):
        first=self.backup();pointer=self.usb/cb.latest_name('main');old=pointer.read_bytes()
        class Cancelling(cb.Events):
            def update(self,phase,*a,**kw):
                if phase=='Copying blockchain data':raise cb.Cancelled('cancelled')
        with self.assertRaises(cb.Cancelled):self.backup(events=Cancelling(emit=lambda r:None))
        self.assertEqual(pointer.read_bytes(),old);self.assertEqual(str(self.select()[0]),first['directory'])
        self.assertFalse(list(self.usb.glob('.chain-backup-partial-*')))

    def test_corrupt_newest_copy_does_not_silently_fall_back(self):
        self.backup();last=self.backup()
        (Path(last['directory'])/'blocks/xor.dat').unlink()
        with self.assertRaises(cb.ChainError):self.select()

    def test_pointer_cannot_escape_directory_or_use_symlink(self):
        self.backup();pointer=self.usb/cb.latest_name('main');original=pointer.read_text()
        for name in ('../data','/etc','bitcoin-chain-main-link'):
            if name.endswith('-link'):(self.usb/name).symlink_to(self.data)
            p=json.loads(original);p['directory']=name;pointer.write_text(json.dumps(p))
            with self.subTest(name=name),self.assertRaises((cb.ChainError,OSError)):self.select()

    def test_legacy_folder_is_discovered_without_shortcut(self):
        r=self.backup({'blocks':10,'bestblockhash':'a'*64})
        p=Path(r['directory']);m=json.loads((p/cb.MANIFEST).read_text());m['version']=1
        (p/cb.MANIFEST).write_text(json.dumps(m));(self.usb/cb.latest_name('main')).unlink()
        self.assertEqual(self.select()[0],p);self.assertEqual(self.select(p)[1]['version'],1)

    def test_invalid_v2_hint_pairs_and_versions_rejected(self):
        self.backup();_,m=self.select()
        for extra in ({'height':3},{'bestblockhash':'a'*64},{'version':3},{'height':True,'bestblockhash':'a'*64}, {'created_utc':[] }):
            with self.subTest(extra=extra),self.assertRaises(cb.ChainError):cb.parse_manifest(json.dumps(m|extra),'main','32.1')

    def test_manifest_v1_still_requires_exact_tip(self):
        self.backup();_,m=self.select();m['version']=1
        with self.assertRaises(cb.ChainError):cb.parse_manifest(json.dumps(m),'main','32.1')

    def test_insufficient_capacity_does_not_publish_new_copy(self):
        with patch.object(cb.os,'fstatvfs',return_value=type('FS',(),{'f_bavail':0,'f_frsize':4096})()):
            with self.assertRaisesRegex(cb.ChainError,'free space'):self.backup()
        self.assertEqual(list(self.usb.iterdir()),[])

class MaintenanceRestarts(unittest.TestCase):
    def exercise(self, running, error=None):
        from types import SimpleNamespace
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as td, contextlib.ExitStack() as stack:
            data=Path(td);calls=[]
            stack.enter_context(patch.object(cb,'DATA',data))
            stack.enter_context(patch.object(cb.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=os.getuid())))
            stack.enter_context(patch.object(cb,'load_setup',return_value={'network':'main'}))
            stack.enter_context(patch.object(cb,'verify_data_mount'))
            stack.enter_context(patch('upgrades.active_release',return_value={'version':'32.1'}))
            stack.enter_context(patch.object(cb,'external',side_effect=lambda *a,**kw:(os.open(data,cb.DIR_FLAGS),data,'ext4')))
            stack.enter_context(patch.object(cb,'service_running',return_value=running))
            stack.enter_context(patch.object(cb,'read_tip_hint',return_value=None))
            stop=stack.enter_context(patch.object(cb,'stop_core'))
            stack.enter_context(patch.object(cb,'recover'))
            stack.enter_context(patch.object(cb,'backup',side_effect=error,return_value={'ok':True,'height':None}))
            stack.enter_context(patch.object(cb,'command',side_effect=lambda a,*more:calls.append(a)))
            inhibitor=Mock();inhibitor.poll.return_value=None
            stack.enter_context(patch.object(cb.subprocess,'Popen',return_value=inhibitor))
            try:result=cb.perform('chain-backup',{'directory':td,'confirmed':True},os.getuid(),cb.Events(emit=lambda r:None))
            except cb.ChainError as exc:result=exc
            stop.assert_called_once()
            return result,calls

    def test_backup_leaves_previously_running_core_stopped(self):
        result,calls=self.exercise(True)
        self.assertFalse(result['core_restarted']);self.assertTrue(result['core_was_running'])
        self.assertEqual(calls,[])

    def test_stopped_core_is_not_started_by_backup(self):
        result,calls=self.exercise(False)
        self.assertFalse(result['core_restarted']);self.assertEqual(calls,[])

    def test_failed_copy_preserves_error_and_never_restarts(self):
        result,calls=self.exercise(True,cb.ChainError('test drive write failure'))
        self.assertIsInstance(result,cb.ChainError)
        self.assertIn('test drive write failure',str(result));self.assertNotIn('restarted',str(result))
        self.assertEqual(calls,[])


if __name__=='__main__':unittest.main()
