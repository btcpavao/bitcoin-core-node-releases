"""Root-owned keyboard transaction checks; only temporary files are touched."""
import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import desktop_input as d

@unittest.skipUnless(os.geteuid()==0,'requires isolated root fixture')
class KeyboardFiles(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.keyboard=self.root/'etc/default/keyboard';self.xorg=self.root/'etc/X11/xorg.conf.d/90-core-node-keyboard.conf'
  self.keyboard.parent.mkdir(parents=True);self.keyboard.write_text('XKBLAYOUT="us"\n');self.keyboard.chmod(0o644)
  self.data=dict(model='pc105',layout='hr',variant='',options='')
  self.a=patch.object(d,'KEYBOARD',self.keyboard);self.b=patch.object(d,'XORG',self.xorg);self.a.start();self.b.start();self.addCleanup(self.a.stop);self.addCleanup(self.b.stop)
 def test_success_is_fixed_files_and_readable_after_strict_umask(self):
  old=os.umask(0o077)
  try:r=d.apply_system_layout(self.data)
  finally:os.umask(old)
  self.assertTrue(r['ok']);self.assertIn('XKBLAYOUT="hr"',self.keyboard.read_text());self.assertIn('XkbLayout" "hr',self.xorg.read_text());self.assertEqual(self.xorg.stat().st_mode & 0o777,0o644);self.assertEqual(self.xorg.parent.stat().st_mode & 0o777,0o755)
 def test_second_write_failure_rolls_back_first_file(self):
  old=self.keyboard.read_bytes();real=d.atomic;count=0
  def fail(path,*args):
   nonlocal count
   count+=1
   if count==2:raise OSError('fixture failure')
   return real(path,*args)
  with patch.object(d,'atomic',side_effect=fail),self.assertRaises(OSError):d.apply_system_layout(self.data)
  self.assertEqual(self.keyboard.read_bytes(),old);self.assertFalse(self.xorg.exists())
 def test_unknown_layout_rejected_before_any_write(self):
  old=self.keyboard.read_bytes()
  with self.assertRaises(d.InputError):d.apply_system_layout(dict(self.data,layout='not-a-layout'))
  self.assertEqual(self.keyboard.read_bytes(),old);self.assertFalse(self.xorg.exists())
 def test_symlink_refused(self):
  keep=self.root/'keep';keep.write_text('keep');self.keyboard.unlink();self.keyboard.symlink_to(keep)
  with self.assertRaises(d.InputError):d.apply_system_layout(self.data)
  self.assertEqual(keep.read_text(),'keep')

if __name__=='__main__':unittest.main()
