"""Backup exports do one write pass; restore safeguards remain independent."""
import contextlib,errno,hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'app'),str(Path(__file__).parent)]
import chain_backup as cb
import encrypted_transfer as transfer
import gpg_backend as gpg
import settings_snapshot as settings
import watch_backup as watch
from test_chain_snapshot_v2 import SnapshotV2
from test_watch_transfer import payload

class ChainWriteOnly(SnapshotV2):
 def test_backup_never_reads_destination_again(self):
  emitted=[];events=cb.Events(emit=emitted.append)
  real_open=cb.regular_at;opened=[]
  def record(fd,name,uid=None):
   opened.append((os.readlink('/proc/self/fd/'+str(fd)),name))
   return real_open(fd,name,uid)
  with patch.object(cb,'verify_files',side_effect=AssertionError('Export must not read back')),patch.object(cb,'regular_at',side_effect=record):
   result=self.backup(events=events)
  self.assertFalse(result['readback_verified'])
  self.assertTrue(opened)
  self.assertTrue(all(str(self.data) in folder for folder,name in opened),opened)
  self.assertFalse(any('verif' in str(row.get('phase','')).lower() for row in emitted),emitted)
  saved=Path(result['directory']);manifest=json.loads((saved/cb.MANIFEST).read_text())
  for row in manifest['files']:
   self.assertEqual((saved/row['path']).read_bytes(),self.files[row['path']])
   self.assertEqual(row['sha256'],hashlib.sha256(self.files[row['path']]).hexdigest())
 def test_default_copy_used_by_restore_still_checks_destination(self):
  target=self.base/'restored';target.mkdir();src=os.open(self.data,cb.DIR_FLAGS);dst=os.open(target,cb.DIR_FLAGS)
  try:
   dirs,files,_=cb.inventory(src);cb.make_dirs(dst,dirs)
   with patch.object(cb,'verify_files',wraps=cb.verify_files) as verify:
    cb.copy_files(src,dst,files,self.events)
    verify.assert_called_once()
  finally:os.close(src);os.close(dst)
 def test_export_flush_failure_does_not_publish_snapshot_or_latest(self):
  real_fsync=os.fsync
  def fail(fd):
   if os.readlink('/proc/self/fd/'+str(fd)).endswith('blk00000.dat'):raise OSError(errno.EIO,'synthetic output failure')
   return real_fsync(fd)
  with patch.object(cb.os,'fsync',side_effect=fail),self.assertRaises(OSError):self.backup()
  self.assertFalse(list(self.usb.iterdir()))

class PortableWriteOnly(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='node-export-qa-',dir='/dev/shm');self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.dest=self.root/'usb';self.dest.mkdir();self.rows=[]
  self.events=cb.Events(emit=self.rows.append);self.raw=settings.canonical({'fixture':'public synthetic settings','number':1})
  self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
  self.stack.enter_context(patch.object(transfer,'external',side_effect=lambda p,*a,**k:(os.open(p,cb.DIR_FLAGS),Path(p),'exfat')))
  @contextlib.contextmanager
  def ram():
   with tempfile.TemporaryDirectory(dir=self.root) as td:yield Path(td)
  self.stack.enter_context(patch.object(settings,'ram_work',side_effect=ram))
 def publish(self,secret='',prefix='bitcoin-node-settings'):
  return Path(transfer.publish(self.raw,str(self.dest),secret,os.getuid(),self.events,prefix=prefix,limit=1024**2))
 def test_all_unencrypted_categories_write_once_no_readback(self):
  for prefix in ('watch-only-wallets','bitcoin-core-config','bitcoin-node-settings'):
   with self.subTest(prefix=prefix),patch.object(transfer,'regular_at',side_effect=AssertionError('No destination read')),patch.object(transfer,'unpack_plain',side_effect=AssertionError('No export reparse')):
    output=self.publish(prefix=prefix)
   self.assertEqual(transfer.unpack_plain(output.read_bytes(),1024**2),self.raw)
  self.assertFalse(any('verif' in str(row.get('phase','')).lower() for row in self.rows))
 def test_optional_encryption_uses_one_gpg_pass_and_no_destination_read(self):
  modes=[];run=gpg._run
  def record(mode,*a,**kw):modes.append(mode);return run(mode,*a,**kw)
  with patch.object(transfer,'regular_at',side_effect=AssertionError('No destination re-read')),patch.object(gpg,'_run',side_effect=record),patch.object(gpg,'_hash',side_effect=AssertionError('No roundtrip hash pass')):
   output=self.publish(secret='synthetic test phrase only')
  self.assertEqual(modes,['encrypt'])
  recovered,_=transfer.read(str(output),'synthetic test phrase only',os.getuid(),self.events,limit=1024**2)
  self.assertEqual(recovered,self.raw)
 def test_plain_restore_rejects_modified_payload(self):
  output=self.publish();doc=json.loads(output.read_text());doc['payload']['number']=2;output.write_text(json.dumps(doc))
  with self.assertRaisesRegex(settings.SettingsError,'checksum'):transfer.read(str(output),'',os.getuid(),self.events,limit=1024**2)
 def test_encrypted_restore_rejects_wrong_secret_and_damage(self):
  output=self.publish(secret='synthetic test phrase only')
  with self.assertRaises(gpg.GPGError):transfer.read(str(output),'wrong test secret',os.getuid(),self.events,limit=1024**2)
  raw=bytearray(output.read_bytes());raw[-1]^=1;output.write_bytes(raw)
  with self.assertRaises(gpg.GPGError):transfer.read(str(output),'synthetic test phrase only',os.getuid(),self.events,limit=1024**2)
 def test_export_flush_failure_cleans_partial_no_success(self):
  real_fsync=os.fsync
  def fail(fd):
   if '.portable-partial-' in os.readlink('/proc/self/fd/'+str(fd)):raise OSError(errno.ENOSPC,'synthetic USB full')
   return real_fsync(fd)
  with patch.object(transfer.os,'fsync',side_effect=fail),self.assertRaises(OSError):self.publish()
  self.assertFalse(list(self.dest.iterdir()))
 def test_encryption_error_does_not_fall_back_to_plaintext(self):
  with patch.object(transfer,'encrypt_file',side_effect=gpg.GPGError('synthetic encryption failure')),self.assertRaises(gpg.GPGError):self.publish('test')
  self.assertFalse(list(self.dest.iterdir()))
 def test_cancel_before_write_leaves_no_output(self):
  self.events.check=Mock(side_effect=cb.Cancelled('cancelled test'))
  with self.assertRaises(cb.Cancelled):self.publish()
  self.assertFalse(list(self.dest.iterdir()))
 def test_general_encryption_still_roundtrips_by_default(self):
  src=self.root/'input';src.write_bytes(self.raw);out=self.root/'default.gpg';modes=[];run=gpg._run
  def record(mode,*a,**kw):modes.append(mode);return run(mode,*a,**kw)
  with patch.object(gpg,'_run',side_effect=record):gpg.encrypt_file(src,out,'synthetic secret',ram_root=self.root)
  self.assertEqual(modes,['encrypt','decrypt'])

class WatchExportScope(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);(self.root/'installed').touch()
  self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close);s=self.stack
  s.enter_context(patch.object(watch.os,'geteuid',return_value=0))
  s.enter_context(patch.object(watch.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=os.getuid())))
  s.enter_context(patch.object(watch,'CONFIG',self.root));s.enter_context(patch.object(watch,'load_setup',return_value={'network':'main'}))
  s.enter_context(patch.object(watch,'CoreRPC',return_value=Mock(return_value={'chain':'main'})))
  s.enter_context(patch.object(watch,'active_release',return_value={'version':'32.1'}))
 def test_export_does_not_launch_isolated_wallet_verification(self):
  with patch.object(settings,'external',side_effect=lambda *a,**k:(os.open(self.root,cb.DIR_FLAGS),self.root,'ext4')),patch.object(watch,'collect',return_value=payload()),patch.object(watch,'check_copies',side_effect=AssertionError('No output probe')),patch.object(transfer,'publish',return_value=str(self.root/'watch.json')):
   result=watch._perform('watch-backup',{'path':str(self.root),'passphrase':''},os.getuid(),cb.Events(emit=lambda _:None))
  self.assertTrue(result['ok']);self.assertFalse(result['readback_verified'])
 def test_restore_preview_still_requires_isolated_core_validation(self):
  with patch.object(transfer,'read',return_value=(settings.canonical(payload()),'a'*64)),patch.object(watch,'check_copies') as probe:
   result=watch._perform('watch-preview',{'path':str(self.root/'watch.json'),'passphrase':''},os.getuid(),cb.Events(emit=lambda _:None))
   probe.assert_called_once();self.assertEqual(result['fingerprint'],'a'*64)

if __name__=='__main__':unittest.main()
