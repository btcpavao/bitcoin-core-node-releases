"""Chain-specific capacity: exclude Debian, unrelated data and reserved blocks."""
import contextlib,json,os,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'app'))
import chain_storage as cs
G=1024**3

class Allocation(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
 def file(self,relative,data=b'a'*8192):
  p=self.root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
 def allocated(self,path):
  return sum(p.stat().st_blocks*512 for p in [path,*path.rglob('*')])
 def test_exact_backup_roots_only_wallets_and_logs_excluded(self):
  self.file('wallets/personal/wallet.dat',b'w'*16384);self.file('debug.log');self.file('bitcoin.conf')
  for name in cs.ROOTS:self.file(name+'/fixture',b'c'*8192)
  self.file('regtest/blocks/wrong-network',b'r'*20000)
  expected=sum(self.allocated(self.root/name) for name in cs.ROOTS)
  self.assertEqual(cs.allocated_chain_bytes(self.root,'main'),expected)
 def test_network_scope(self):
  self.file('blocks/main-only');self.file('signet/chainstate/selected')
  self.assertEqual(cs.allocated_chain_bytes(self.root,'signet'),self.allocated(self.root/'signet/chainstate'))
  self.assertEqual(cs.allocated_chain_bytes(self.root,'regtest'),0)
  with self.assertRaises(ValueError):cs.allocated_chain_bytes(self.root,'../wallets')
 def test_sparse_files_count_allocation_not_apparent_size(self):
  p=self.file('blocks/sparse',b'')
  with p.open('wb') as f:f.seek(200*1024*1024);f.write(b'end')
  value=cs.allocated_chain_bytes(self.root,'main')
  self.assertEqual(value,self.allocated(self.root/'blocks'));self.assertLess(value,1024*1024)
 def test_fresh_and_empty_chain(self):
  self.assertEqual(cs.allocated_chain_bytes(self.root,'main'),0)
  (self.root/'blocks').mkdir();self.assertEqual(cs.allocated_chain_bytes(self.root,'main'),(self.root/'blocks').stat().st_blocks*512)
 def test_never_opens_regular_file_contents(self):
  self.file('blocks/index/metadata');original=cs.os.open
  def only_dirs(path,flags,*args,**kw):
   self.assertTrue(flags & os.O_DIRECTORY);self.assertTrue(flags & os.O_NOFOLLOW)
   return original(path,flags,*args,**kw)
  with patch.object(cs.os,'open',side_effect=only_dirs):self.assertGreater(cs.allocated_chain_bytes(self.root,'main'),0)
 def test_symlink_root_and_nested_symlink_refused(self):
  outside=self.root/'outside';outside.mkdir();(self.root/'blocks').symlink_to(outside,target_is_directory=True)
  with self.assertRaises((OSError,ValueError)):cs.allocated_chain_bytes(self.root,'main')
  (self.root/'blocks').unlink();(self.root/'blocks').mkdir();(self.root/'blocks/link').symlink_to(outside)
  with self.assertRaises(ValueError):cs.allocated_chain_bytes(self.root,'main')
 def test_special_files_and_hardlinks_refused(self):
  p=self.file('blocks/file');os.link(p,self.root/'blocks/hardlink')
  with self.assertRaises(ValueError):cs.allocated_chain_bytes(self.root,'main')
  (self.root/'blocks/hardlink').unlink();os.mkfifo(self.root/'blocks/fifo')
  with self.assertRaises(ValueError):cs.allocated_chain_bytes(self.root,'main')
 def test_scan_budget_and_file_limit(self):
  self.file('blocks/a');self.file('blocks/b')
  with self.assertRaises(TimeoutError):cs.allocated_chain_bytes(self.root,'main',deadline=time.monotonic()-1)
  with self.assertRaises(ValueError):cs.allocated_chain_bytes(self.root,'main',max_entries=1)

class Capacity(unittest.TestCase):
 def test_excludes_system_and_all_other_data(self):
  row=cs.reading(30*G,60*G)
  self.assertEqual(row['total'],90*G);self.assertEqual(row['used_percent'],33.3)
  self.assertNotEqual(row['used_percent'],40) # 100 GiB disk includes 10 GiB elsewhere.
 def test_full_empty_and_fraction_rounding(self):
  self.assertEqual(cs.reading(1,0)['used_percent'],100)
  self.assertEqual(cs.reading(0,0)['used_percent'],100)
  self.assertEqual(cs.reading(0,100)['used_percent'],0)
  self.assertEqual(cs.reading(10000000,1)['used_percent'],99.9)
  for args in ((-1,1),(1,-1),(True,1),(1,1.5)):
   with self.assertRaises(ValueError):cs.reading(*args)
 def test_free_is_live_while_metadata_is_cached_and_reserved_space_excluded(self):
  cs._cache=None;key=['main',None,'fixture','/',1,2,3,4]
  fs=SimpleNamespace(f_bavail=60,f_bfree=65,f_frsize=G,f_blocks=100)
  proc=Mock(return_value=SimpleNamespace(stdout=json.dumps({'identity':key,'used':30*G})))
  with patch.object(cs,'context',return_value=('main',Path('/fixed'),key)),patch.object(cs.subprocess,'run',proc),patch.object(cs.os,'statvfs',return_value=fs):
   row=cs.storage_usage();self.assertEqual(row['total'],90*G);self.assertEqual(row['free'],60*G)
   fs.f_bavail=50;row=cs.storage_usage();self.assertEqual(row['total'],80*G);self.assertEqual(row['used_percent'],37.5)
   self.assertEqual(proc.call_count,1)
   args=proc.call_args.args[0];self.assertEqual(args[2:],["--measure"]);self.assertNotIn('pkexec',args)
   self.assertEqual(proc.call_args.kwargs['timeout'],cs.SCAN_PROCESS_TIMEOUT)
 def test_timeout_or_missing_view_or_changed_disk_never_reuses_old_usage(self):
  for error in (RuntimeError('disk missing'),OSError('view unmounted')):
   cs._cache=(['old'],time.monotonic(),100)
   with patch.object(cs,'context',side_effect=error),patch.object(cs.os,'statvfs') as fs:
    self.assertIsNone(cs.storage_usage());fs.assert_not_called();self.assertIsNone(cs._cache)
  key=['new'];cs._cache=None
  with patch.object(cs,'context',return_value=('main',Path('/fixed'),key)),patch.object(cs.subprocess,'run',side_effect=cs.subprocess.TimeoutExpired('metadata scan',5)):
   self.assertIsNone(cs.storage_usage())
  with patch.object(cs,'context',return_value=('main',Path('/fixed'),key)),patch.object(cs.subprocess,'run',return_value=SimpleNamespace(stdout=json.dumps({'identity':['old'],'used':5}))):
   self.assertIsNone(cs.storage_usage())
 def test_bad_counters_never_invent_capacity(self):
  key=['disk'];cs._cache=(key,time.monotonic(),10)
  with patch.object(cs,'context',return_value=('main',Path('/fixed'),key)),patch.object(cs.os,'statvfs',return_value=SimpleNamespace(f_bavail=-1,f_frsize=4096,f_blocks=100)):
   self.assertIsNone(cs.storage_usage())
 def test_view_checks_and_data_mount_run_before_any_scan(self):
  with patch.object(cs,'load_setup',return_value={'network':'main','data_uuid':'gone'}),patch.object(cs,'verify_data_mount',side_effect=RuntimeError('missing')),patch.object(cs,'check_core_view') as view:
   self.assertIsNone(cs.storage_usage());view.assert_not_called()

class Presentation(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from PySide6.QtWidgets import QApplication
  cls.app=QApplication.instance() or QApplication([])
 def test_full_percentage_and_current_chain_capacity_are_displayed(self):
  from activity_ui import StorageBar
  w=StorageBar();w.update_space(cs.reading(30*G,60*G))
  self.assertIn('33.3% full',w.caption.text());self.assertIn('60.0 GiB free of 90.0 GiB',w.caption.text())
  self.assertEqual(w.bar.value(),333);self.assertIn('Debian',w.caption.toolTip())
  w.update_space(cs.reading(90*G,1*G));self.assertIn('#FF5151',w.bar.styleSheet())
  w.update_space(None);self.assertTrue(w.isHidden());w.deleteLater()
 def test_backup_scope_and_beginner_guidance_agree(self):
  from chain_backup import ROOTS
  self.assertEqual(cs.ROOTS,ROOTS)
  from guide_content import SECTIONS
  s=SECTIONS['Storage & pruning'];self.assertIn('33.3% full',s);self.assertIn('not a separate reserved partition',s)
  self.assertIn('not all controlled by the block pruning target',s)

if __name__=='__main__':unittest.main()
