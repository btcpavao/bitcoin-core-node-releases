import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import file_browser as f

class CoreFilesView(unittest.TestCase):
 def test_only_the_real_read_only_core_view_opens(self):
  row={'target':str(f.CORE_VIEW),'source':str(f.CORE_DATA),'fstype':'fuse.bindfs','options':'ro,nosuid,nodev,noexec,allow_other'}
  with patch.object(f.subprocess,'check_output',side_effect=lambda *a,**kw:json.dumps({'filesystems':[row]})),patch.object(f.subprocess,'Popen') as opened:
   f.open_core_files();opened.assert_called_once_with(['/usr/bin/thunar',str(f.CORE_VIEW)])
   for key,bad in [('source','/wrong-data'),('target','/wrong-view'),('fstype','ext4'),('options','rw,nosuid,nodev,noexec')]:
    old=row[key];row[key]=bad
    with self.assertRaises(f.BrowserError):f.open_core_files()
    row[key]=old
   self.assertEqual(opened.call_count,1)

if __name__=='__main__':unittest.main()
