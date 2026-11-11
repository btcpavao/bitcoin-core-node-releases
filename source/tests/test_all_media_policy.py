"""Shared GTK/Qt policy and device-verified Core USB read/write bridge."""
import json,os,runpy,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'app'))
from PySide6.QtCore import QSettings
import file_dialog_policy as policy
import removable_media as media
from usb_destinations import parse_lsblk

class Preferences(unittest.TestCase):
 def test_shortcuts_width_other_preferences_and_idempotence(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);config=root/'config';config.mkdir(mode=0o700);path=config/'QtProject.conf'
   s=QSettings(str(path),QSettings.IniFormat);s.setValue('Unrelated/keep','original');s.setValue('FileDialog/sidebarWidth',70);s.setValue('FileDialog/shortcuts',['file:///media/node/OLD','file:///chosen']);s.sync();path.chmod(0o600)
   places=[Path('/home/node/Private Workspace'),Path('/media/node/USB')]
   policy.qt_preferences(config,places);s.sync()
   self.assertEqual(s.value('Unrelated/keep'),'original');self.assertEqual(s.value('FileDialog/sidebarWidth',type=int),320)
   urls=s.value('FileDialog/shortcuts');self.assertIn('file:///media/node/USB',urls);self.assertNotIn('file:///media/node/OLD',urls);self.assertIn('file:///chosen',urls)
   old=path.read_bytes();policy.qt_preferences(config,places);self.assertEqual(old,path.read_bytes())
   s.setValue('FileDialog/sidebarWidth',420);s.sync();policy.qt_preferences(config,places);s.sync();self.assertEqual(s.value('FileDialog/sidebarWidth',type=int),420)
 def test_symlink_preferences_refused(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);target=p/'keep';target.write_text('unchanged');(p/'QtProject.conf').symlink_to(target)
   with self.assertRaises(RuntimeError):policy.qt_preferences(p,[])
   self.assertEqual(target.read_text(),'unchanged')
 def test_gtk_css_preserves_existing_user_style_and_has_no_remote_import(self):
  with tempfile.TemporaryDirectory() as d:
   config=Path(d);p=config/'gtk-3.0';p.mkdir(mode=0o700);(p/'gtk.css').write_text('label {color:red;}\n');(p/'gtk.css').chmod(0o600)
   policy.gtk_preferences(config,[]);before=(p/'gtk.css').read_bytes();policy.gtk_preferences(config,[])
   self.assertEqual(before,(p/'gtk.css').read_bytes());self.assertIn('label {color:red;}',before.decode());self.assertIn('min-width: 300px',(p/'core-node-chooser.css').read_text())
 def test_shortcut_never_replaces_user_files(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'USB Media').write_text('keep')
   with self.assertRaises(RuntimeError):policy.shortcut(p,'USB Media',Path('/media/node'))
   self.assertEqual((p/'USB Media').read_text(),'keep')
 def test_fixed_account_mismatch_refused(self):
  with patch.object(policy.pwd,'getpwuid',return_value=Mock(pw_name='wrong')):
   with self.assertRaises(RuntimeError):policy.apply(True)
   with self.assertRaises(RuntimeError):policy.apply(False)

class Boundaries(unittest.TestCase):
 def test_core_write_policy_expands_only_verified_media_root(self):
  text=(R/'runtime/etc/systemd/system/bitcoin-core-node.service').read_text()
  line=next(s for s in text.splitlines() if s.startswith('ReadWritePaths='))
  paths=line.split('=',1)[1].split()
  self.assertIn('/run/core-node-media',paths)
  self.assertNotIn('/media',paths);self.assertNotIn('/run',paths);self.assertNotIn('/',paths)
  self.assertEqual(set(paths)-{'/run/core-node-media'}, {'/run/core-node-private/workspace','/run/core-node-private/psbt','/var/lib/bitcoin-core-node/data','/var/lib/bitcoin-core-node/gui','/run/bitcoin-core-node'})
  self.assertIn('ProtectSystem=strict',text);self.assertIn('ProtectHome=true',text)
 def test_bridge_no_shell_or_mutation_of_source_permissions(self):
  text=(R/'app/removable_media.py').read_text()
  self.assertIn("'--chmod-ignore'",text);self.assertIn("'--chown-deny'",text)
  self.assertIn("'--create-for-user=node'",text);self.assertIn("'--create-for-group=node'",text)
  self.assertIn('mnt_id:',text);self.assertIn('identity[-2]',text)
  self.assertIn('os.O_NOFOLLOW',text);self.assertIn('backing.st_rdev != device.st_rdev',text)
  self.assertNotIn('shell=True',text);self.assertNotIn('shutil.rmtree',text)
  self.assertNotIn('os.chmod',text);self.assertNotIn('os.chown',text)
 def test_mirror_names_are_single_components_and_bounded(self):
  for name in ('../../escape','x/../a', '\n#script', 'A'*500, 'USB disk'):
   n=media.view_name({'label':name},('/media/node/USB',1,2,3,'uuid',100,77,False))
   self.assertNotIn('/',n);self.assertNotIn('\n',n);self.assertLessEqual(len(n),55)
 def test_all_active_node_choosers_use_shared_media_dialog(self):
  for name in ('ui.py','settings_snapshot_ui.py','file_crypto.py','password_dialog.py','usb_dialog.py'):
   text=(R/'app'/name).read_text()
   for legacy in ('QFileDialog.getOpenFileName','QFileDialog.getSaveFileName','QFileDialog.getExistingDirectory'):
    self.assertNotIn(legacy,text,name)
 def test_removable_encrypted_child_detected_only_with_external_ancestry(self):
  child={'name':'unlocked','path':'/dev/mapper/unlocked','type':'crypt','fstype':'ext4','uuid':'test','size':123,'mountpoints':[]}
  raw={'blockdevices':[{'name':'sda','path':'/dev/sda','tran':'usb','type':'disk','children':[child]}]}
  self.assertEqual(parse_lsblk(json.dumps(raw))[0]['path'],'/dev/mapper/unlocked')
  raw['blockdevices'][0]['tran']='nvme';self.assertEqual(parse_lsblk(json.dumps(raw)),[])

class WritablePolicy(unittest.TestCase):
 def test_ram_watcher_cannot_order_before_paths_target_and_after_basic(self):
  text=(R/'runtime/etc/systemd/system/bitcoin-core-node-transfer.path').read_text()
  self.assertIn('DefaultDependencies=no',text)
  self.assertIn('Requires=core-node-private.service',text)
  self.assertIn('After=basic.target systemd-tmpfiles-setup.service core-node-private.service',text)
  self.assertIn('Conflicts=shutdown.target',text)
  self.assertIn('Before=shutdown.target',text)
  self.assertIn('WantedBy=multi-user.target',text)

 def test_media_views_are_released_when_core_stops(self):
  for state,expected in [('active',True),('activating',True),('deactivating',True),('inactive',False),('failed',False)]:
   with patch.object(media.subprocess,'run',return_value=Mock(stdout=state)):
    self.assertEqual(media.core_in_use(),expected)

 def test_readonly_cannot_be_promoted_to_writable(self):
  for readonly in (False,True):
   identity=('/media/node/USB',1,2,3,'uuid',100,77,readonly)
   args=media.mount_arguments(5,Path('/run/core-node-media/test'),identity)
   self.assertEqual('-r' in args,readonly)
   self.assertIn('--perms=0000:u=rD:g=rD' if readonly else '--perms=0000:u=rwD:g=rwD',args)
   self.assertIn('--create-for-user=node',args)
   self.assertNotIn('--resolve-symlinks',args);self.assertNotIn('--enable-ioctl',args)
   self.assertIn('nodev,nosuid,noexec,default_permissions',args[args.index('-o')+1])
 def test_same_device_remount_has_new_path(self):
  entry={'label':'Test disk'}
  old=('/media/node/Test',1,2,3,'uuid',100,77,False)
  new=(*old[:-2],78,False)
  self.assertNotEqual(media.view_name(entry,old),media.view_name(entry,new))
  self.assertIn('read-only',media.view_name(entry,(*old[:-1],True)))
 def test_disconnected_root_is_not_app_writable(self):
  text=(R/'app/removable_media.py').read_text()
  self.assertIn('mkdir(mode=0o555)',text)
  self.assertIn('info.st_mode & 0o022',text)
  tmp=(R/'runtime/etc/tmpfiles.d/bitcoin-core-node.conf').read_text()
  self.assertIn('d /run/core-node-media 0755 root root -',tmp)

if __name__=='__main__':unittest.main()
