"""Only native public-only RPC exports are permitted; ciphertext is bounded."""
import base64,copy,hashlib,os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import watch_backup as w
import settings_snapshot as s

def payload():
 raw=b'SQLite format 3\0'+b'public test fixture'
 return dict(format=w.FORMAT,version=1,network='main',core_version='32.1',created_utc='2026-11-06T12:00:00Z',skipped=1,
             wallets=[dict(name='Public savings',sha256=hashlib.sha256(raw).hexdigest(),public_export=base64.b64encode(raw).decode())])
class WatchTransfer(unittest.TestCase):
 def test_public_schema_roundtrip(self):
  d=payload();self.assertEqual(w.parse(s.canonical(d)),d);self.assertEqual(w.summary(d)['wallets'],['Public savings'])
 def test_type_guard_refuses_signing_legacy_external_signer(self):
  self.assertTrue(w.is_watch(dict(private_keys_enabled=False,descriptors=True)))
  for x in (dict(private_keys_enabled=True,descriptors=True),dict(private_keys_enabled=False,descriptors=False),dict(private_keys_enabled=False,descriptors=True,external_signer=True),{}):
   self.assertFalse(w.is_watch(x))
 def test_names_do_not_become_paths(self):
  for name in ('../bad','/tmp/evil','.hidden','hello\\wallet','a\nb',''):
   self.assertFalse(w.wallet_name(name))
 def test_checksum_duplicate_extra_and_size_guard(self):
  for mutation in ('checksum','duplicate','key','version','network','type'):
   d=payload()
   if mutation=='checksum':d['wallets'][0]['sha256']='0'*64
   if mutation=='duplicate':d['wallets']*=2
   if mutation=='key':d['private_key']='forbidden'
   if mutation=='version':d['version']=True
   if mutation=='network':d['network']='unknown'
   if mutation=='type':d['wallets'][0]['public_export']='eA=='
   with self.subTest(mutation=mutation),self.assertRaises(s.SettingsError):w.validate(d)
 def test_backend_uses_only_native_public_export_not_source_database_copy(self):
  source=Path(w.__file__).read_text()
  self.assertIn("rpc('exportwatchonlywallet'",source)
  self.assertNotIn("rpc('backupwallet'",source)
  self.assertNotIn('sqlite3',source)
  self.assertNotIn("DATA/'wallets'",source)
if __name__=='__main__':unittest.main()
