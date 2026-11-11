import runpy,tempfile,unittest
from pathlib import Path

p=runpy.run_path(str(Path(__file__).resolve().parents[1]/'runtime/usr/local/bin/core-node-file-places'))

class Places(unittest.TestCase):
 def test_core_then_workspace_preserves_other_bookmarks_and_is_idempotent(self):
  home=Path('/home/node');private=p['PRIVATE'];core=p['CORE']
  previous='file:///media/node/USB My USB\n'+private.as_uri()+' Old label\n'
  expected=core.as_uri()+' Core\n'+private.as_uri()+' Private Workspace\nfile:///run/core-node-private/psbt PSBT Transfer Folder\nfile:///media/node/USB My USB\n'
  merged=p['merge_bookmarks'](previous,home,private)
  self.assertEqual(merged,expected)
  self.assertEqual(p['merge_bookmarks'](merged,home,private),expected)
 def test_core_and_workspace_devices_are_hidden_but_usb_stays_visible(self):
  private=p['PRIVATE'];core=p['CORE']
  mounts=[{'root':str(private.parent),'fstype':'tmpfs','source':'tmpfs'}, {'root':str(core),'fstype':'fuse.bindfs','source':'/var/lib/bitcoin-core-node/data'}]
  records=[{'root':str(private.parent),'id':'ram'}, {'root':str(core),'id':'core'}, {'root':'/media/node/USB','unix':'/dev/sda1','name':'CORE_NODE_DEV','id':'usb'}]
  self.assertEqual(p['selected_device_ids'](records,mounts,private),['ram','core'])
 def test_bookmarks_and_visibility_roll_back_if_xfconf_fails(self):
  with tempfile.TemporaryDirectory() as tmp:
   home=Path(tmp);config=home/'.config';runtime=home/'run';runtime.mkdir()
   book=config/'gtk-3.0/bookmarks';book.parent.mkdir(parents=True);book.write_text('file:///keep Keep\n')
   calls=[]
   def query(args):
    calls.append(args)
    if args==['-l']:return ''
    if '--create' in args:raise RuntimeError('fixture xfconf failure')
    return ''
   with self.assertRaises(RuntimeError):p['configure'](home,runtime,config,run=query,devices=lambda _:[])
   self.assertEqual(book.read_text(),'file:///keep Keep\n')

if __name__=='__main__':unittest.main()
