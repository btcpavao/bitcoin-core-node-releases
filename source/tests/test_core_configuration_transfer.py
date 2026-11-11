"""Core-only configuration never contains operating system/network secrets."""
import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import settings_snapshot as s

def core_payload():
 return dict(format=s.CORE_FORMAT,version=1,created_utc='2026-11-06T12:00:00Z',core_version='32.1',
             network='main',core={'dbcache':'256','prune':'1024'},core_gui={'fCoinControlFeatures':'true'},
             not_included=['Wallets, network secrets and hardware paths'])
class CoreConfiguration(unittest.TestCase):
 def test_roundtrip_and_summary_scope(self):
  d=core_payload();self.assertEqual(s.validate_any(s.json_load(s.canonical(d))),d)
  self.assertEqual(s.summary_any(d)['scope'],'core')
  self.assertNotIn('wifi',s.summary_any(d))
 def test_privileged_or_private_extras_rejected(self):
  for field in ('wireguard','connections','files','wallets','wallet','script','login'):
   d=core_payload();d[field]='not permitted'
   with self.subTest(field=field),self.assertRaises(s.SettingsError):s.validate_any(d)
 def test_only_supported_preferences_are_permitted(self):
  for k in ('walletnotify','includeconf','datadir','wallet','rpcpassword','proxy'):
   d=core_payload();d['core'][k]='123'
   with self.subTest(option=k),self.assertRaises(s.SettingsError):s.validate_any(d)
 def test_collect_core_does_not_collect_node_credentials(self):
  user=type('User',(),{'pw_uid':100})()
  def read(path,*args,**kwargs):
   path=str(path)
   self.assertTrue(path.startswith('/var/lib/bitcoin-core-node/'),path)
   if path.endswith('settings.json'):return b'{"dbcache":"256","wallet":["not exported"]}'
   if path.endswith('bitcoin.conf'):return b'maxmempool=500\nwalletnotify=not-portable\n'
   return b'[General]\nfCoinControlFeatures=true\nstrDataDir=/old/device\n'
  with patch.object(s.pwd,'getpwnam',return_value=user),patch.object(s,'safe_read',side_effect=read),\
       patch.object(s,'load_setup',return_value={'network':'main'}),patch('upgrades.active_release',return_value={'version':'32.1'}):
   d=s.collect_core()
  self.assertNotIn('wallet',d['core']);self.assertNotIn('strDataDir',d['core_gui'])
  self.assertEqual(d['core']['maxmempool'],'500')
if __name__=='__main__':unittest.main()
