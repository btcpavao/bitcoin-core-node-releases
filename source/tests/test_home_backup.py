"""Factory-hidden shortcut, meaningful changes, durable discovery, no secret reads."""
import contextlib,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'app'))
import home_backup as hb

class Detection(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.home=self.root/'home/node';self.home.mkdir(parents=True)
  installed=self.root/str(hb.INSTALLED).lstrip('/');installed.parent.mkdir(parents=True);installed.write_text('installed')
  self.core=self.root/'core';(self.core/'wallets').mkdir(parents=True)
  self.baseline=self.root/str(hb.BASELINE).lstrip('/')
  self.baseline.write_text(json.dumps({'version':2,'preferences':hb.preferences(self.root,self.home)}))
  self.detector=hb.BackupPresence(root=self.root,home=self.home,core_view=self.core)
  self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
  self.net=self.stack.enter_context(patch.object(hb,'network_customized',return_value=False))
  self.bt=self.stack.enter_context(patch.object(hb,'bluetooth_customized',return_value=False))
 def test_pristine_hidden_even_after_repeated_checks(self):
  self.assertFalse(self.detector.check());self.assertFalse(self.detector.check())
  self.assertFalse(self.detector.marker.exists())
 def test_root_private_os_preferences_do_not_block_timezone_detection(self):
  p=self.root/'etc/lightdm/lightdm.conf.d/99-node-login.conf';p.parent.mkdir(parents=True);p.write_text('private mode');p.chmod(0o600)
  self.baseline.write_text(json.dumps({'version':2,'preferences':hb.preferences(self.root,self.home)}))
  self.assertFalse(self.detector.check())
  before=p.stat().st_mode
  real=hb.regular_bytes
  def guarded(path,*args):
   if Path(path)==p:raise PermissionError('Private OS contents must never be read')
   return real(path,*args)
  zone=self.root/'etc/timezone';zone.write_text('Europe/Zagreb')
  with patch.object(hb,'regular_bytes',side_effect=guarded):self.assertTrue(self.detector.check())
  self.assertEqual(p.stat().st_mode,before)
 def test_normal_own_group_writable_local_directory_keeps_flag_after_restart(self):
  local=self.home/'.local';local.mkdir();local.chmod(0o775)
  self.detector.remember();self.assertTrue(self.detector.marker.is_file())
  self.assertEqual(local.stat().st_mode & 0o777,0o775)
  self.assertTrue(hb.BackupPresence(root=self.root,home=self.home,core_view=self.core).remembered())
 def test_world_writable_state_parent_is_refused_without_modifying_it(self):
  local=self.home/'.local';local.mkdir();local.chmod(0o777)
  self.detector.remember();self.assertFalse(self.detector.marker.exists())
  self.assertEqual(local.stat().st_mode & 0o777,0o777)
 def test_each_saved_preference_reveals_without_network_or_core(self):
  for relative in hb.PREFERENCES:
   with self.subTest(preference=relative):
    p=self.root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('changed')
    d=hb.BackupPresence(root=self.root,home=self.home,core_view=self.core)
    self.assertTrue(d.check());p.unlink();d.marker.unlink()
 def test_mouse_preference_reveals_empty_auto_file_does_not(self):
  p=self.home/'.config/bitcoin-core-node/pointer.json';p.parent.mkdir(parents=True)
  p.write_text('{"devices":{}}');self.assertFalse(self.detector.check())
  p.write_text('{"devices":{"test mouse":0.4}}');self.assertTrue(self.detector.check())
 def test_wifi_or_bluetooth_reveals_and_persists_after_disconnect(self):
  for probe in (self.net,self.bt):
   d=hb.BackupPresence(root=self.root,home=self.home,core_view=self.core)
   probe.return_value=True;self.assertTrue(d.check());probe.return_value=False
   rebooted=hb.BackupPresence(root=self.root,home=self.home,core_view=self.core)
   self.assertTrue(rebooted.remembered());self.assertTrue(rebooted.check())
   payload=d.marker.read_text();self.assertNotIn('password',payload);self.assertNotIn('SSID',payload)
   self.assertEqual(json.loads(payload),{'version':1,'visible':True});d.marker.unlink()
 def test_chain_or_wallet_presence_never_reads_databases(self):
  for path in ('blocks','wallets/test-wallet'):
   p=self.core/path;p.mkdir()
   with patch.object(hb,'regular_bytes',wraps=hb.regular_bytes) as read:
    self.assertTrue(self.detector.check())
    self.assertFalse(any(str(self.core) in str(c.args[0]) for c in read.call_args_list))
   p.rmdir();self.detector.marker.unlink();self.detector.visible=False
 def test_stopping_core_and_reverting_settings_never_hides_shortcut(self):
  self.detector.remember();self.assertTrue(self.detector.check())
  new=hb.BackupPresence(root=self.root,home=self.home,core_view=self.core);self.assertTrue(new.check())
 def test_unavailable_probes_do_not_imply_configuration(self):
  self.net.side_effect=hb.subprocess.TimeoutExpired('nmcli',2);self.bt.side_effect=OSError()
  self.assertFalse(self.detector.check())
 def test_no_baseline_on_upgrade_reveals_never_rebaselines_old_settings(self):
  self.baseline.unlink();self.assertTrue(self.detector.check());self.assertFalse(self.baseline.exists())
 def test_marker_symlink_cannot_overwrite_another_file(self):
  self.detector.marker.parent.mkdir(parents=True);target=self.root/'keep';target.write_text('keep')
  self.detector.marker.symlink_to(target);self.detector.remember();self.assertEqual(target.read_text(),'keep')
 def test_noninstalled_session_never_creates_user_state(self):
  (self.root/str(hb.INSTALLED).lstrip('/')).unlink()
  self.assertFalse(self.detector.check());self.detector.remember();self.assertFalse(self.detector.marker.exists())
 def test_baseline_cannot_contain_secret_hash_sources(self):
  names=' '.join(hb.PREFERENCES)
  for forbidden in ('shadow','wireguard','system-connections','wallet.dat'):
   self.assertNotIn(forbidden,names)

class NetworkMetadata(unittest.TestCase):
 def test_only_types_and_timestamps_requested_never_secret_names(self):
  for output,expected in [('loopback:0\n802-3-ethernet:0\n',False),('802-11-wireless:0\n',True),('802-3-ethernet:1790000000\n',True),('vpn:0\n',True),('wireguard:0\n',True)]:
   run=Mock(return_value=Mock(returncode=0,stdout=output))
   self.assertEqual(hb.network_customized(run),expected)
   args=run.call_args.args[0];self.assertIn('TYPE,TIMESTAMP',args);self.assertNotIn('--show-secrets',args)

class HomeCards(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from PySide6.QtWidgets import QApplication
  cls.app=QApplication.instance() or QApplication([])
 def test_position_persistence_and_single_existing_backup_window(self):
  import ui,connection_ui
  from PySide6.QtCore import Qt
  with patch.object(ui.Home,'poll_activity',lambda _:None),patch.object(ui.Home,'poll_wallets',lambda _:None),patch.object(connection_ui.ConnectionButton,'poll',lambda _:None),patch.object(hb.BackupPresence,'remembered',return_value=False),patch.object(hb.BackupPresence,'remember'):
   home=ui.Home()
   self.assertNotIn('Backup and Restore',[c.tool['title'] for c in home.cards])
   home.set_backup_available(True);names=[c.tool['title'] for c in home.cards]
   i=names.index('Private Workspace');self.assertEqual(names[i+1:i+3],['Backup and Restore','Encrypt Files'])
   home.set_watch_only_available(True);self.assertEqual(len(home.cards),13)
   home.set_watch_only_available(False);home.set_backup_available(False)
   self.assertIn(home.backup_card,home.cards);self.assertEqual(len(home.cards),11)
   home.backup_card.click();one=home._modeless_windows['backup_restore']
   home.backup_restore();self.assertIs(home._modeless_windows['backup_restore'],one);self.assertFalse(one.isModal())
   one.reject()
   for timer in (home.timer,home.wallet_inventory_timer,home.connection_button.timer,home.clock.timer):timer.stop()
   home.hide();home.deleteLater();self.app.processEvents()
 def test_customized_home_keeps_progress_and_cards_visible_at_800x600(self):
  import ui,connection_ui
  from PySide6.QtCore import QPoint
  with patch.object(ui.Home,'poll_activity',lambda _:None),patch.object(ui.Home,'poll_wallets',lambda _:None),patch.object(connection_ui.ConnectionButton,'poll',lambda _:None),patch.object(hb.BackupPresence,'remembered',return_value=False),patch.object(hb.BackupPresence,'remember'):
   ui.configure_ui(self.app);home=ui.Home();home._test_size=(800,600);home.fit_screen();home.show()
   home.set_watch_only_available(True)
   home.show_activity(('syncing','Blockchain download and validation in progress · 73.25%',False,.7325,dict(total=850*1024**3,free=255*1024**3,used_percent=70,free_percent=30)))
   for _ in range(25):self.app.processEvents();home.layout_cards()
   self.assertEqual(home.scroll.verticalScrollBar().maximum(),0)
   for card in home.cards:
    for label in (card.icon_label,card.title_label,card.description_label):
     point=label.mapTo(card,QPoint(0,0));self.assertGreaterEqual(point.y(),0);self.assertLessEqual(point.y()+label.height(),card.height())
   self.assertTrue(home.activity.isVisible());self.assertTrue(home.blockchain_storage.isVisible())
   for t in (home.timer,home.wallet_inventory_timer,home.connection_button.timer,home.clock.timer):t.stop()
   home.hide();home.deleteLater();self.app.processEvents()
 def test_installer_only_records_factory_baseline_after_defaults(self):
  source=(R/'runtime/usr/libexec/core-node-install-target').read_text()
  self.assertLess(source.index("call('/usr/libexec/core-node-defaults')"),source.index('from home_backup import capture_defaults'))
  self.assertNotIn('capture_defaults', (R/'runtime/usr/local/bin/core-node-session').read_text())

if __name__=='__main__':unittest.main()
