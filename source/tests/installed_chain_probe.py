#!/usr/bin/python3
"""Real polkit + native GUI round trips in an owned installed networkless VM."""
from pathlib import Path
import hashlib,json,os,pwd,shutil,subprocess,sys,time,traceback
from unittest.mock import patch
media=Path(sys.argv[1]);phase=sys.argv[2]
assert os.environ.get('NODE_VM_ACCEPTANCE')=='1'
assert os.getuid()==pwd.getpwnam('node').pw_uid
assert 'Q35' in Path('/sys/devices/virtual/dmi/id/product_name').read_text()
assert sorted(p.name for p in Path('/sys/class/net').iterdir())==['lo']
assert 'boot=live' not in Path('/proc/cmdline').read_text()
assert subprocess.check_output(['findmnt','-n','-o','SOURCE','/'],text=True).strip() in ('/dev/vda1','/dev/vda2')
assert (media/'NODE-TEST-ONLY').read_text().strip()=='disposable QEMU fixture'
sys.path.insert(0,'/usr/lib/bitcoin-core-node')
from PySide6.QtCore import QPoint,QTimer
from PySide6.QtWidgets import QApplication,QLabel,QPushButton,QFileDialog
from rpc import CoreRPC
import ui,chain_ui,chain_backup as backend
from launcher_ui import NodeSettingsDialog,ToolCard
app=QApplication([]);ui.configure_ui(app);app.setQuitOnLastWindowClosed(False)
report=dict(status='running',phase=phase,checks=[]);rpc=CoreRPC(timeout=30)
def passed(s):report['checks'].append(s);print('PASS '+s,flush=True)
def wait(predicate,seconds=90):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  app.processEvents()
  try:
   result=predicate()
   if result:return result
  except Exception:pass
  time.sleep(.025)
 raise AssertionError('Native chain acceptance deadline')
def admin(action):
 return ui.admin(action)
def ready_core():
 wait(lambda:rpc('getnetworkinfo')['version']==320100,180)
 assert rpc('getblockchaininfo')['chain']=='regtest'
 rpc('setnetworkactive',False)
def run_dialog(mode,directory,*,cancel=False,expect_failure=False):
 d=chain_ui.ChainDialog(mode);d.show();d.directory.setText(str(directory));d.confirm.setChecked(True)
 d.grab().save(str(media/('chain-'+phase+'-'+mode+'-form.png')))
 ticks=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(time.monotonic()));timer.start(20)
 d.start.click();wait(lambda:d.busy or d.process is None)
 if cancel:
  wait(lambda:'Checking blockchain' in d.feedback.text(),120)
  d.reject();assert d.isVisible() and d.busy
 wait(lambda:not d.busy,300);timer.stop()
 assert len(ticks)>5,'GUI failed to keep processing events during privileged operation'
 d.grab().save(str(media/('chain-'+phase+'-'+mode+('-cancel' if cancel else '-failed' if expect_failure else '-result')+'.png')))
 text=d.feedback.text();result=d.result;d.reject()
 if cancel or expect_failure:
  assert result is None or not result.get('ok'),(result,text)
  return text
 assert result and result['ok'] is True,(result,text)
 return result
def all_wallet_bytes():
 root=Path('/run/core-node-files/Core/wallets')
 return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
try:
 home=ui.Home();home.timer.stop();home.wallet_inventory_timer.stop();home.show()
 for width,height in [(800,600),(1024,768),(1366,768),(1920,1080)]:
  home._test_size=(width,height);home.fit_screen()
  for _ in range(15):app.processEvents();home.layout_cards()
  assert home.width()==width and home.height()==height,(home.size(),width,height)
  assert home.scroll.verticalScrollBar().maximum()==0
  positions=[]
  for w in (home.clock,home.network_button,home.restart_button,home.shutdown_button):
   p=w.mapTo(home,QPoint(0,0));positions.append(p.x())
   assert p.x()>=0 and p.x()+w.width()<=width and p.y()>=home.footer.y() and p.y()+w.height()<=height
   assert not w.icon().isNull(),w.accessibleName()
  assert positions==sorted(positions)
  home.grab().save(str(media/f'chain-home-{width}.png'))
 settings=NodeSettingsDialog(home);settings.show();app.processEvents()
 assert settings.height()<=560
 cards={c.accessibleName():c for c in settings.findChildren(ToolCard)}
 assert {'Backup Chain State','Import Chain State','Date & Time'}<=set(cards)
 settings.grab().save(str(media/'chain-settings.png'))
 with patch.object(chain_ui,'ChainDialog') as menu_dialog:
  cards['Backup Chain State'].click()
  menu_dialog.assert_called_once_with('backup',home)
  menu_dialog.return_value.exec.assert_called_once()
 assert settings.selected_action==home.chain_backup and settings.isVisible()
 settings.reject()
 home.hide()
 passed('exact installed native clock icons, ordering, footer fit at 800x600–1920x1080 and settings actions')
 if phase=='source':
  ready_core();wallet='Vault Public';address=rpc('getnewaddress',wallet=wallet)
  rpc('generatetoaddress',35,address)
  before=rpc('getblockchaininfo');height=before['blocks'];tip=before['bestblockhash']
  result=run_dialog('backup',media)
  backup=Path(result['directory']);m=json.loads((backup/backend.MANIFEST).read_text())
  assert m['height']==height and m['bestblockhash']==tip
  assert (m['prune_mib']>0)==before['pruned']
  for f in m['files']:
   assert hashlib.sha256((backup/f['path']).read_bytes()).hexdigest()==f['sha256']
   assert f['path'].split('/')[0] in backend.ROOTS
  assert (backup/'blocks/xor.dat').is_file() and (backup/'blocks/index/CURRENT').is_file()
  assert not (backup/'wallets').exists() and not (backup/'settings.json').exists() and not (backup/'.cookie').exists()
  (media/'chain-expected.json').write_text(json.dumps(dict(backup=backup.name,height=height,tip=tip,prune_mib=m['prune_mib'])))
  ready_core();assert rpc('getbestblockhash')==tip
  passed('real GUI backup stops Core, uses isolated upstream validation, copies/verifies complete block+chainstate set, excludes wallets and restarts')
  text=run_dialog('backup',media,cancel=True)
  assert 'cancel' in text.lower(),text
  ready_core();assert rpc('getbestblockhash')==tip
  assert not list(media.glob('.chain-backup-partial-*'))
  passed('Cancel/close during real validation keeps GUI responsive, publishes no partial backup and restarts original Core')
  rpc('generatetoaddress',5,address);new_tip=rpc('getbestblockhash')
  bad=media/'bad-chain-copy';shutil.copytree(backup,bad)
  p=bad/'blocks/xor.dat';content=p.read_bytes();p.write_bytes(bytes([content[0]^1])+content[1:])
  text=run_dialog('import',bad,expect_failure=True)
  assert 'checksum' in text.lower(),text
  ready_core();assert rpc('getbestblockhash')==new_tip
  passed('same-size tampered source is rejected without replacing the active blockchain')
  shutil.rmtree(bad)
  admin('stop');before_wallets=all_wallet_bytes();assert before_wallets
  result=run_dialog('import',backup)
  assert result['height']==height and result['core_was_running'] is False
  assert before_wallets==all_wallet_bytes()
  assert int(json.loads(Path('/run/core-node-files/Core/settings.json').read_text())['prune'])==m['prune_mib']
  assert not Path('/run/bitcoin-core-node/auth.cookie').exists()
  passed('verified import from older tip atomically replaces only chain data, preserves wallet bytes and leaves stopped Core stopped')
  admin('start');ready_core();assert rpc('getbestblockhash')==tip
  assert set(rpc('listwallets'))=={'Vault Public','Recovered Public'}
  assert rpc('getwalletinfo',wallet=wallet)['private_keys_enabled'] is False
  rpc('generatetoaddress',1,address);assert rpc('getblockcount')==height+1
  passed('real native Core loads restored tip and original public wallets, then extends the imported chain')
 elif phase=='target':
  expected=json.loads((media/'chain-expected.json').read_text());backup=media/expected['backup']
  assert subprocess.run(['systemctl','is-active','--quiet','bitcoin-core-node.service']).returncode!=0
  before=all_wallet_bytes()
  result=run_dialog('import',backup)
  assert result['height']==expected['height']
  assert before==all_wallet_bytes()
  settings=json.loads(Path('/run/core-node-files/Core/settings.json').read_text())
  assert int(settings['prune'])==expected['prune_mib']
  admin('start');ready_core()
  pid=subprocess.check_output(['systemctl','show','bitcoin-core-node.service','--property=MainPID','--value'],text=True).strip()
  assert b'-datadir=/var/lib/bitcoin-core-node/data' in Path('/proc',pid,'cmdline').read_bytes()
  assert rpc('getbestblockhash')==expected['tip'] and rpc('getblockcount')==expected['height']
  assert rpc('getblockchaininfo')['pruned']==(expected['prune_mib']>0)
  assert rpc('getnetworkinfo')['connections']==0
  passed('fresh computer imports before first Core launch, skips Intro, loads the saved tip without peers/download and adopts pruning')
 elif phase=='reboot':
  expected=json.loads((media/'chain-expected.json').read_text())
  assert not list(Path('/run/core-node-private/workspace').iterdir())
  admin('start');ready_core()
  assert rpc('getbestblockhash')==expected['tip']
  passed('imported chain, prune preference and normal RAM clearing survive a real reboot')
 else:raise AssertionError('Unknown phase')
 report['status']='passed';print('CHAIN_NATIVE_PASSED '+phase,flush=True)
except Exception:
 report.update(status='failed',error=traceback.format_exc());raise
finally:
 (media/('chain-'+phase+'-result.json')).write_text(json.dumps(report,indent=2)+'\n');os.sync()
