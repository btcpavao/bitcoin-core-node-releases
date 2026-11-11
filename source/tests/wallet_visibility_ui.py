#!/usr/bin/python3
"""Exercise real Home layouts and asynchronous read-only inventory with fake RPC."""
import argparse,os,sys,tempfile,time,threading
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'app'))
from PySide6.QtCore import QEventLoop,QTimer
from PySide6.QtWidgets import QApplication
from rpc import CoreError
from wallet_presence import watch_only_wallets_present
import ui
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);out=p.parse_args().output;out.mkdir(parents=True,exist_ok=True)
app=QApplication([]);ui.configure_ui(app)
state={'wallets':{},'offline':False,'block':False}
started=threading.Event();release=threading.Event()
def rpc(method,*args,**kwargs):
 if state['offline']:raise CoreError('offline')
 if method=='listwallets':
  result=list(state['wallets'])
  if state['block']:
   state['block']=False;started.set();assert release.wait(5)
  return result
 if method=='getwalletinfo':return state['wallets'][kwargs['wallet']]
 if method=='listwalletdir':return {'wallets':[]}
 raise AssertionError(method)
def spin(predicate):
 deadline=time.monotonic()+6
 while not predicate():
  assert time.monotonic()<deadline,'inventory did not finish'
  loop=QEventLoop();QTimer.singleShot(10,loop.quit);loop.exec()
 for _ in range(4):app.processEvents()
def check(home,visible):
 assert home.watch_only_available is visible
 assert home.wallet_manager_card.isHidden() is (not visible)
 assert len(home.cards)==(10 if visible else 9)
 titles=[c.tool['title'] for c in home.cards]
 assert titles.count('Import Watch-Only Wallet')==0
 assert titles[-1]=='Node Guide'
 assert titles.count('Watch-Only Wallets')==int(visible)
 assert all(c.parentWidget() is home.grid_wrap for c in home.cards)
 for size in [(800,600),(1366,768)]:
  home._test_size=size;home.fit_screen()
  for _ in range(5):app.processEvents();home.layout_cards()
  assert home.scroll.horizontalScrollBar().maximum()==0
  assert home.grid.count()==len(home.cards)
  positions=[home.grid.getItemPosition(home.grid.indexOf(c)) for c in home.cards]
  assert len(set(positions))==len(positions)
  home.grab().save(str(out/f'home-{size[0]}-wallet-{visible}.png'))
with tempfile.TemporaryDirectory() as tmp,patch('ui.CoreRPC',return_value=rpc),patch('ui.watch_only_wallets_present',side_effect=lambda r:watch_only_wallets_present(r,tmp)):
 home=ui.Home();home.timer.stop();home.wallet_inventory_timer.stop();home.show()
 check(home,False)
 def probe():
  home.poll_wallets();spin(lambda:home.wallet_inventory_job is None and not home.wallet_inventory_pending)
 probe();check(home,False)
 state['wallets']={'private':{'private_keys_enabled':True,'descriptors':True}}
 probe();check(home,False)
 state['wallets']['watch-one']={'private_keys_enabled':False,'descriptors':True}
 probe();check(home,True)
 state['wallets']['watch-two']={'private_keys_enabled':False,'descriptors':True}
 probe();check(home,True)
 state['offline']=True;probe();check(home,True)
 state['offline']=False;state['wallets']={};probe();check(home,False)
 # An old empty response must not hide the card after a confirmed import.
 state['block']=True;home.poll_wallets();spin(started.is_set)
 state['wallets']={'new-import':{'private_keys_enabled':False,'descriptors':True}}
 home.poll_wallets();release.set()
 spin(lambda:home.wallet_inventory_job is None and not home.wallet_inventory_pending)
 check(home,True)
 home.hide()
print('PASS: empty/private-only => no custom import card; one/multiple watch-only wallets => manager visible; no grid gaps; outage retains known state; queued inventory detects a native Core restore.')
