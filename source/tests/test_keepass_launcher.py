"""Volatile generator defaults preserve choices within one session."""
import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import keepass_launcher as k
from private_workspace import WorkspaceError
class KeePassProfile(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.user=self.root/'user';self.user.mkdir(mode=0o700)
  for name in ('config','data','state','cache','tmp'):(self.user/name).mkdir(mode=0o700)
  self.patches=[patch.object(k,'USER',self.user),patch.object(k,'private_environment',return_value={'TMPDIR':str(self.user/'tmp')})]
  for item in self.patches:item.start()
 def tearDown(self):
  for item in self.patches:item.stop()
  self.temp.cleanup()
 def test_defaults_and_same_session_preferences(self):
  env=k.environment();p=self.user/'config/keepassxc/keepassxc.ini'
  self.assertEqual(p.read_text(),k.DEFAULTS);self.assertEqual(p.stat().st_mode&0o777,0o600)
  self.assertEqual(env['QT_LINUX_ACCESSIBILITY_ALWAYS_ON'],'1')
  changed=p.read_text().replace('WordCount=6','WordCount=8').replace('ClearClipboard=false','ClearClipboard=true');p.write_text(changed)
  k.environment();self.assertEqual(p.read_text(),changed)
 def test_profile_symlink_is_not_followed(self):
  target=self.root/'persistent';target.mkdir();(self.user/'config/keepassxc').symlink_to(target)
  with self.assertRaises(WorkspaceError):k.environment()
  self.assertEqual(list(target.iterdir()),[])
 def test_unsafe_private_directories_are_rejected(self):
  (self.user/'data').rmdir();(self.user/'data').symlink_to(self.root)
  with self.assertRaises(WorkspaceError):k.environment()
  (self.user/'data').unlink();(self.user/'data').mkdir(mode=0o755)
  (self.user/'data').chmod(0o755)  # Ensure an unsafe fixture even with umask 077.
  with self.assertRaises(WorkspaceError):k.environment()
 def test_config_symlink_is_not_read_or_modified(self):
  target=self.root/'persistent.ini';target.write_text('unchanged');directory=self.user/'config/keepassxc';directory.mkdir(mode=0o700)
  (directory/'keepassxc.ini').symlink_to(target)
  with self.assertRaises(WorkspaceError):k.environment()
  self.assertEqual(target.read_text(),'unchanged')
if __name__=='__main__':unittest.main()
