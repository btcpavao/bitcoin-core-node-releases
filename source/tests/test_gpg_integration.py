"""Real GnuPG file publication and RAM-only recovery integration."""
import hashlib,os,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import file_crypto as crypto
import layered_backend as layers
from gpg_backend import GPGError

class FileEncryption(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir='/dev/shm');self.root=Path(self.tmp.name)
  self.export=self.root/'export';self.export.mkdir(mode=0o700)
  self.workspace=self.root/'workspace';self.workspace.mkdir(mode=0o700)
  self.source=self.workspace/'wallet.dat';self.source.write_bytes(b'synthetic file only\0'+os.urandom(8192))
  self.dest=self.root/'saved.gpg';self.passwords=['synthetic amber cedar','synthetic blue birch']
  self.policy=types.SimpleNamespace(EXPORT=self.export,PRIVATE=self.workspace,check_storage=Mock(),canonical_path=Path,
   file_digest=lambda p:hashlib.sha256(Path(p).read_bytes()).digest(),share_recovered=Mock())
 def tearDown(self):self.tmp.cleanup()
 def create(self):return crypto.create_backup([self.source],self.dest,self.passwords,policy=self.policy)
 def test_verified_roundtrip_retains_source_and_no_plaintext_outside_workspace(self):
  original=self.source.read_bytes();self.create()
  self.assertEqual(self.source.read_bytes(),original)
  self.assertNotIn(original,self.dest.read_bytes())
  result=crypto.decrypt_files(self.dest,self.workspace/'restored',list(reversed(self.passwords)),policy=self.policy)
  self.assertEqual((result/'wallet.dat').read_bytes(),original)
  self.assertEqual(list(self.export.iterdir()),[])
  self.policy.share_recovered.assert_called_once()
 def test_missing_wrong_passphrase_and_tampering_publish_nothing(self):
  self.create();original=self.dest.read_bytes()
  for secrets,cipher in [(['wrong'],original),(self.passwords[:-1],original),
    (self.passwords,original[:-20]),(self.passwords,original[:20]+bytes([original[20]^1])+original[21:])]:
   self.dest.write_bytes(cipher)
   with self.assertRaises((layers.LayerError,GPGError)):
    crypto.decrypt_files(self.dest,self.workspace/'failed',secrets,policy=self.policy)
   self.assertFalse((self.workspace/'failed').exists());self.assertEqual(list(self.export.iterdir()),[])
 def test_recovery_cannot_target_disk_or_replace_existing(self):
  self.create()
  for target in [self.root/'outside',self.source]:
   with self.assertRaises(crypto.BackupError):crypto.decrypt_files(self.dest,target,self.passwords,policy=self.policy)
 def test_existing_ciphertext_and_publication_race_never_overwrite(self):
  self.dest.write_bytes(b'existing')
  with self.assertRaises(crypto.BackupError):self.create()
  candidate=self.root/'candidate';candidate.write_bytes(b'new')
  with self.assertRaises(FileExistsError):crypto.publish_new(candidate,self.dest)
  self.assertEqual(self.dest.read_bytes(),b'existing')
 def test_corrupt_copy_never_published(self):
  with patch.object(crypto,'copy_ciphertext',side_effect=lambda src,out,progress:out.write(b'corrupt')):
   with self.assertRaises(crypto.BackupError):self.create()
  self.assertFalse(self.dest.exists());self.assertEqual(list(self.export.iterdir()),[])
 def test_cancel_cleans_staging_and_does_not_publish(self):
  class Cancel:
   def check(self):raise crypto.Cancelled()
  with self.assertRaises(crypto.Cancelled):
   crypto.create_backup([self.source],self.dest,self.passwords,policy=self.policy,progress=Cancel())
  self.assertFalse(self.dest.exists());self.assertEqual(list(self.export.iterdir()),[])
 def test_passphrases_never_enter_arguments_or_environment(self):
  import gpg_backend
  original=gpg_backend.subprocess.Popen
  def inspect(args,**kw):
   for secret in self.passwords:
    self.assertNotIn(secret,str(args));self.assertNotIn(secret,str(kw.get('env',{})))
   self.assertIn('--passphrase-fd',args)
   return original(args,**kw)
  with patch.object(gpg_backend.subprocess,'Popen',inspect):self.create()

if __name__=='__main__':unittest.main()
