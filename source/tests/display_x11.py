#!/usr/bin/python3
import argparse,json,os,runpy,sys,time,subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
p=argparse.ArgumentParser();p.add_argument('product');p.add_argument('scale',type=float);p.add_argument('out',type=Path);a=p.parse_args()
root=Path(__file__).resolve().parents[1 if a.product=='node' else 2]
runtime=root/('runtime' if a.product=='node' else 'tools/core-vault/runtime-template')
assets=runtime/'usr/share'/('bitcoin-core-node' if a.product=='node' else 'core-vault')
wm=subprocess.Popen(['/usr/bin/openbox','--config-file',str(assets/'openbox.xml')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
time.sleep(.3)
from PySide6.QtWidgets import QApplication,QDialog
from PySide6.QtGui import QFont
app=QApplication([]);app.setStyle('Fusion');app.setFont(QFont('DejaVu Sans',10))
screen=app.primaryScreen()
assert abs(screen.devicePixelRatio()-a.scale)<.02,(screen.devicePixelRatio(),a.scale)
patches=[]
if a.product=='node':
 sys.path.insert(0,str(root/'app'))
 import ui
 ui.configure_ui(app)
 patcher=patch('ui.CoreRPC');patcher.start();patches.append(patcher)
 home=ui.Home();home.timer.stop();home.wallet_inventory_timer.stop();home.set_watch_only_available(True)
else:
 with patch.object(sys,'argv',['core-vault-home','--self-test','--assets',str(assets)]):
  mod=runpy.run_path(str(runtime/'usr/local/bin/core-vault-home'),run_name='scaling_home')
 home=mod['VaultHome']();home.set_watch_only_available(True)
home.show()
for _ in range(10):app.processEvents();home.layout_cards()
assert home.geometry()==screen.geometry(),(home.geometry(),screen.geometry())
assert home.scroll.horizontalScrollBar().maximum()==0
assert home.scroll.verticalScrollBar().maximum()==0
a.out.mkdir(parents=True,exist_ok=True)
home.grab().save(str(a.out/'home.png'))
card=home.cards[0];pix=card.grab()
assert abs(pix.height()-card.height()*a.scale)<=1,(pix.height(),a.scale)
mod=runpy.run_path(str(runtime/f'usr/local/bin/core-{a.product}-taskbar'),run_name='scaling_panel')
panel=mod['Taskbar'](SimpleNamespace(preview=True,assets=assets))
panel.timer.stop();panel.panel_active=True;panel.show()
for _ in range(10):app.processEvents();time.sleep(.02)
panel.place()
strut=panel.x.prop(int(panel.winId()),'_NET_WM_STRUT_PARTIAL')
expected=round(40*a.scale)
assert abs(strut[3]-expected)<=1,(strut,expected)
# Fractional Qt/X11 window sizing can round the native right edge by one pixel.
assert strut[10]==0 and abs(strut[11]-(round(screen.geometry().width()*a.scale)-1))<=1,strut
for _ in range(10):app.processEvents();time.sleep(.02)
work=panel.x.prop(panel.x.root,'_NET_WORKAREA')
assert work[3]==round(screen.geometry().height()*a.scale)-expected,(work,expected)
panel.grab().save(str(a.out/'taskbar.png'))
if a.product=='node':
 from wallet_ui import WalletDialog
 from wallets import WalletService
 def rpc(method,*args,**kwargs):
  if method=='listwallets':return ['Wallet One','Wallet Two']
  raise AssertionError(method)
 def snapshot(name):
  return {'incomplete':False,'balances':{'mine':{}},'info':{'scanning':False},'utxos':[],'transactions':[]}
 home.rpc=rpc
 with patch.object(WalletService,'watch',return_value={}),patch.object(WalletService,'snapshot',side_effect=snapshot):
  dialog=WalletDialog(home);dialog.show()
  until=time.monotonic()+3
  while time.monotonic()<until:
   app.processEvents()
   if dialog.wallet.count()==2 and (not dialog.job or not dialog.job.isRunning()):break
   time.sleep(.01)
  assert dialog.wallet.count()==2
  assert dialog.width()<=screen.geometry().width() and dialog.height()<=screen.geometry().height(),(dialog.size(),screen.geometry())
  dialog.grab().save(str(a.out/'wallet.png'))
  dialog.wallet.showPopup()
  for _ in range(4):app.processEvents()
  dialog.wallet.view().window().grab().save(str(a.out/'dropdown.png'))
  dialog.wallet.hidePopup();dialog.hide()
panel.hide();home.hide();panel.x.close()
for x in patches:x.stop()
result=dict(product=a.product,scale=screen.devicePixelRatio(),logical_size=[screen.geometry().width(),screen.geometry().height()],card_pixels=[pix.width(),pix.height()],taskbar_strut=strut)
(a.out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
wm.terminate();wm.wait(timeout=5)
print('PASS',json.dumps(result))
