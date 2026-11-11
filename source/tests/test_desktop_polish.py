import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'app'))
import desktop_input as inp
import pointer_control as ptr

class InputPolicy(unittest.TestCase):
 def test_supported_keyboard_and_variant(self):
  for layout in ('us','hr','de','fr'):
   self.assertEqual(inp.validate_layout(dict(model='pc105',layout=layout,variant='',options=''))['layout'],layout)
 def test_unknown_or_injected_layout_rejected(self):
  for layout in ('../hr','$(id)','hr\nXkbOptions bad','madeup','us;exit'):
   with self.assertRaises(inp.InputError):inp.validate_layout(dict(model='pc105',layout=layout,variant='',options=''))
  with self.assertRaises(inp.InputError):inp.validate_layout(dict(model='pc105',layout='hr',variant='madeup',options=''))
 def test_xorg_is_fixed_data_not_commands(self):
  text=inp.xorg_text(dict(model='pc105',layout='hr',variant='',options=''))
  self.assertIn('MatchIsKeyboard "on"',text);self.assertIn('Option "XkbLayout" "hr"',text);self.assertNotIn('exec',text)
 def test_only_root_can_change_system_layout(self):
  with patch.object(inp.os,'geteuid',return_value=1000),self.assertRaises(inp.InputError):inp.apply_system_layout({})
 def test_unprivileged_save_roundtrip_and_no_symlink_overwrite(self):
  with tempfile.TemporaryDirectory() as t,patch('home_backup.remember_local_use'):
   p=Path(t)/'prefs.json';value=copy.deepcopy(inp.DEFAULTS);value['keyboard']['numlock']=False;value['devices']={'Test Mouse':{'natural_scroll':True}}
   inp.save(value,p);self.assertEqual(inp.load(p),value);self.assertEqual(p.stat().st_mode & 0o777,0o600)
   target=Path(t)/'keep';target.write_text('keep');p.unlink();p.symlink_to(target)
   with self.assertRaises(inp.InputError):inp.save(value,p)
   self.assertEqual(target.read_text(),'keep')
 def test_validation_limits_and_unknown_properties(self):
  for field,value in [('rate_hz',0),('delay_ms',3000),('repeat',1),('numlock','yes')]:
   data=copy.deepcopy(inp.DEFAULTS);data['keyboard'][field]=value
   with self.assertRaises(inp.InputError):inp.validate(data)
  for value in ({'shell':'whoami'},{'left_handed':'yes'},{'acceleration':'custom-script'}):
   data=copy.deepcopy(inp.DEFAULTS);data['devices']={'Mouse':value}
   with self.assertRaises(inp.InputError):inp.validate(data)
 def test_empty_preferences_do_not_share_mutable_defaults(self):
  with tempfile.TemporaryDirectory() as t:
   a=inp.load(Path(t)/'none');a['keyboard']['numlock']=False;self.assertTrue(inp.DEFAULTS['keyboard']['numlock'])
 def test_keyboard_commands_are_fixed_and_numlock_explicit(self):
  with patch.object(inp,'run',return_value='') as run:
   inp.apply_keyboard(dict(repeat=True,delay_ms=400,rate_hz=33,numlock=False),layout=dict(model='pc105',layout='hr',variant='',options=''))
   self.assertIn(['/usr/bin/xset','r','rate','400','33'],[x.args[0] for x in run.call_args_list])
   self.assertIn(['/usr/local/bin/core-node-numlock','off'],[x.args[0] for x in run.call_args_list])
 def test_device_capabilities_and_three_entry_accel_vector(self):
  props={'libinput Left Handed Enabled':(0,), 'libinput Accel Profiles Available':(1,1,1),'libinput Accel Profile Enabled':(1,0,0)}
  choices=inp.device_choices(props);self.assertFalse(choices['left_handed']);self.assertNotIn('tap_to_click',choices)
  with patch.object(inp,'properties',return_value=props),patch.object(ptr,'xinput') as call:
   inp.apply_device(9,{'left_handed':True,'acceleration':'flat','tap_to_click':True})
   self.assertEqual(call.call_count,2)
   self.assertIn(('--set-prop',9,'libinput Accel Profile Enabled',0,1,0),[c.args for c in call.call_args_list])
 def test_keyboard_configuration_lock_serializes_exports(self):
  from operation_locks import resources
  import fcntl
  self.assertIn(('core-node-configuration.lock',fcntl.LOCK_EX),resources('keyboard-settings'))
 def test_session_uses_input_watcher_no_unrestricted_auth(self):
  s=(R/'runtime/usr/local/bin/core-node-session').read_text();self.assertIn('desktop_input.py --watch',s)
  rules=(R/'runtime/etc/polkit-1/rules.d/49-core-node.rules').read_text();self.assertNotIn('localed',rules)
 def test_v1_and_v2_settings_backup_validation(self):
  from test_settings_snapshot import payload
  import settings_snapshot as ss
  old=payload();self.assertEqual(ss.validate(copy.deepcopy(old)),old)
  new=copy.deepcopy(old);new.update(version=2,input=copy.deepcopy(inp.DEFAULTS))
  new['input']['keyboard']['delay_ms']=350;new['input']['devices']={'My USB Mouse':{'natural_scroll':True,'left_handed':False}}
  self.assertEqual(ss.validate(copy.deepcopy(new)),new)
  self.assertEqual(ss.summary(new)['desktop_input'],new['input'])
  bad=copy.deepcopy(new);bad['input']['devices']['My USB Mouse']['run']='bad'
  with self.assertRaises(ss.SettingsError):ss.validate(bad)
 def test_restore_targets_allow_only_fixed_input_files(self):
  import settings_restore as r
  self.assertTrue(r.allowed('home/node/.config/bitcoin-core-node/input.json'))
  self.assertTrue(r.allowed('etc/X11/xorg.conf.d/90-core-node-keyboard.conf'))
  self.assertFalse(r.allowed('etc/X11/xorg.conf.d/arbitrary.conf'))

class LayoutAndContent(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from PySide6.QtWidgets import QApplication
  cls.app=QApplication.instance() or QApplication([])
 def test_exact_centered_row_and_equal_meter_spacing(self):
  import ui,home_backup,connection_ui
  from PySide6.QtCore import QPoint
  with patch.object(ui.Home,'poll_activity',lambda _:None),patch.object(ui.Home,'poll_wallets',lambda _:None),patch.object(connection_ui.ConnectionButton,'poll',lambda _:None),patch.object(home_backup.BackupPresence,'remembered',return_value=False),patch.object(home_backup.BackupPresence,'remember'):
   h=ui.Home();h.show();h.set_watch_only_available(True)
   h.show_activity(('syncing','Blockchain download and validation in progress · 73.25%',False,.7325,dict(total=850*1024**3,free=255*1024**3,used_percent=70,free_percent=30)))
   for w,ht in ((800,600),(1024,768),(1280,800),(1366,768),(1920,1080)):
    h._test_size=(w,ht);h.fit_screen()
    for _ in range(30):self.app.processEvents();h.layout_cards();h.position_activity()
    cards={c.tool['title']:c for c in h.cards}
    def xy(c):return c.mapTo(h,QPoint(0,0))
    for bottom,above in [('Editor','Decrypt Files'),('Terminal','KeePassXC'),('Node Guide','Settings')]:
     self.assertEqual(xy(cards[bottom]).x(),xy(cards[above]).x(),(w,bottom))
    top=xy(h.grid_wrap).y()+h.grid_wrap.height();logo=xy(h.debian_logo).y();row=xy(h.activity_row).y();height=h.activity_row.height()
    self.assertLessEqual(abs((row-top)-(logo-row-height)),2,(w,row,top,logo,height))
    self.assertGreaterEqual(row-top,8)
    self.assertLessEqual(row+height,xy(h.footer).y()+2,(w,'meters overlap footer controls'))
    self.assertEqual(h.scroll.verticalScrollBar().maximum(),0,(w,ht))
    for card in h.cards:
     for label in (card.icon_label,card.title_label,card.description_label):
      p=label.mapTo(card,QPoint(0,0));self.assertGreaterEqual(p.y(),0);self.assertLessEqual(p.y()+label.height(),card.height())
   for timer in (h.timer,h.wallet_inventory_timer,h.clock.timer,h.connection_button.timer):timer.stop()
   h.hide();h.deleteLater();self.app.processEvents()
 def test_keyboard_tab_works_without_mouse(self):
  from input_ui import KeyboardMouseDialog
  with patch.object(ptr,'get_devices',return_value=[]):
   d=KeyboardMouseDialog();self.assertEqual(d.windowTitle(),'Keyboard and Mouse');self.assertTrue(d.save.isEnabled());self.assertEqual(d.tabs.count(),2);self.assertFalse(d.slider.isEnabled());d.accept()
 def test_keyboard_save_worker_finishes_without_clashing_with_dialog_signal(self):
  import time
  from input_ui import KeyboardMouseDialog
  from wallets import WalletError
  for failure in (False,True):
   with self.subTest(failure=failure),patch.object(ptr,'get_devices',return_value=[]),patch('ui.admin',side_effect=WalletError('Test save failure') if failure else None,return_value={'ok':True}),patch.object(inp,'apply_keyboard'),patch.object(inp,'save'):
    d=KeyboardMouseDialog();d.layout_box.setCurrentIndex(d.layout_box.findData('hr'));d.apply()
    deadline=time.monotonic()+5
    while d.job is not None and time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
    self.assertIsNone(d.job);self.assertTrue(d.save.isEnabled());self.assertTrue(d.close_button.isEnabled())
    self.assertIn('Test save failure' if failure else 'applied and saved',d.status.text())
    d.accept();d.deleteLater();self.app.processEvents()
 def test_guide_retains_all_topics_and_explains_first_use_terms(self):
  from guide_content import SECTIONS
  self.assertEqual(len(SECTIONS),19)
  self.assertEqual(next(iter(SECTIONS)), 'Start here: Node & Vault')
  intro=SECTIONS['Start here: Node & Vault'].lower()
  for word in ('private keys','blockchain','ram','psbt','backup','restore'):self.assertIn(word,intro)
  for term in ('headers','rescan','pruned','Coin Control','checksum','mount','full-tunnel','hardened','TLS','Num Lock'):
   self.assertIn(term,' '.join(SECTIONS.values()))
  self.assertIn('Keyboard and Mouse',SECTIONS['Networking']);self.assertNotIn('Settings → Mouse Speed',' '.join(SECTIONS.values()))
 def test_no_network_access_in_guide_module(self):
  import ast
  tree=ast.parse((R/'app/guide_content.py').read_text())
  self.assertFalse(any(isinstance(n,(ast.Import,ast.ImportFrom,ast.Call)) for n in ast.walk(tree)))
  values=[n.value for n in tree.body if isinstance(n,ast.Assign)]
  self.assertEqual(len(values),1)
  self.assertTrue(all(isinstance(k,str) and isinstance(v,str) for k,v in ast.literal_eval(values[0]).items()))

if __name__=='__main__':unittest.main()
