"""All Home status states stay between the last launcher and Debian mark."""
import contextlib,json,os,sys,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint,QRect
import ui,connection_ui,home_backup
SPACE=dict(scope='blockchain',used=30*1024**3,free=60*1024**3,total=90*1024**3,used_percent=33.3)
STATES=[
 ('syncing','Blockchain download and validation in progress · 73.25%',False,.7325,SPACE),
 ('stopped','Bitcoin Core is stopped. Open Bitcoin Core to resume validation.',False),
 ('starting','Bitcoin Core is starting…',False),
 ('starting','Bitcoin Core is loading and verifying local data…',False),
 ('syncing','Waiting for Bitcoin peers. Check your connection in Network Status.',False,.2,SPACE),
 ('synchronized','Blockchain synchronized. Wallet rescans are shown separately.',False,1.0,SPACE),
 ('error','Bitcoin Core encountered an error. Please check local service diagnostics.',False),
 ('error','Bitcoin Core is running; local RPC status is unavailable. Please check Bitcoin Core. '
          'The selected external data disk may be missing; check that it is connected before continuing.',False),
]
class StatusCentering(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.app=QApplication.instance() or QApplication([]);ui.configure_ui(cls.app)
 def setUp(self):
  self.scope=contextlib.ExitStack();self.addCleanup(self.scope.close)
  for obj,name,result in ((ui.Home,'poll_activity',lambda _:None),(ui.Home,'poll_wallets',lambda _:None),(connection_ui.ConnectionButton,'poll',lambda _:None)):
   self.scope.enter_context(patch.object(obj,name,result))
  self.scope.enter_context(patch.object(home_backup.BackupPresence,'remembered',return_value=False))
  self.scope.enter_context(patch.object(home_backup.BackupPresence,'remember'))
  self.h=ui.Home();self.h.screen_ref=Mock()
  self.h.screen_ref.geometry.return_value=QRect(0,0,1280,800)
  self.h.screen_ref.availableGeometry.return_value=QRect(0,0,1280,800)
  for timer in (self.h.timer,self.h.wallet_inventory_timer,self.h.clock.timer,self.h.connection_button.timer,self.h.reaper):timer.stop()
  self.addCleanup(self.cleanup)
 def cleanup(self):
  self.h.hide();self.h.activity_position_timer.stop();self.h.layout_timer.stop();self.h.geometry_timer.stop();self.h.deleteLater();self.app.processEvents()
 def settle(self):
  for _ in range(20):self.app.processEvents()
 def geometry(self,width=1280,height=800,panel=0):
  self.h.screen_ref.geometry.return_value=QRect(0,0,width,height)
  self.h.screen_ref.availableGeometry.return_value=QRect(0,0,width,height-panel)
  self.h.fit_screen();self.h.show();self.settle()
 def assert_centered(self):
  h=self.h
  top=max(card.mapTo(h,QPoint(0,card.height())).y() for card in h.cards if not card.isHidden())
  bottom=h.debian_logo.mapTo(h,QPoint()).y()
  visible=[w for w in (h.activity_text,h.activity,h.blockchain_storage) if not w.isHidden()]
  first=min(w.mapTo(h,QPoint()).y() for w in visible)
  last=max(w.mapTo(h,QPoint(0,w.height())).y() for w in visible)
  self.assertLessEqual(abs((first-top)-(bottom-last)),2,(h.size(),h.activity_text.text(),top,bottom,first,last))
  self.assertGreaterEqual(first,top+8)
  self.assertLessEqual(last,bottom-8)
  self.assertEqual(h.scroll.verticalScrollBar().maximum(),0)
  self.assertEqual(h.activity_row.height(),last-first)
 def test_all_states_sizes_card_counts_and_taskbar_changes(self):
  count=0
  for cards in (10,11,13):
   if cards==11:self.h.set_backup_available(True)
   if cards==13:self.h.set_watch_only_available(True)
   self.assertEqual(len(self.h.cards),cards)
   for w,ht in ((800,600),(1024,768),(1280,800),(1366,768),(1920,1080)):
    for panel in (40,0):
     self.geometry(w,ht,panel)
     for value in STATES:
      self.h.show_activity(value);self.settle();self.assert_centered();count+=1
  self.assertEqual(count,240)
 def test_same_text_reflows_when_meter_visibility_changes(self):
  self.h.set_watch_only_available(True);self.geometry()
  for value in [('syncing','Checking Bitcoin Core…',False,.4,SPACE),('starting','Checking Bitcoin Core…',False),('syncing','Checking Bitcoin Core…',False,.4,SPACE)]:
   self.h.show_activity(value);self.settle();self.assert_centered()
 def test_late_credit_layout_change_without_a_new_status_message(self):
  self.h.set_watch_only_available(True);self.geometry();self.h.show_activity(STATES[1]);self.h.activity_seen=True;self.h.activity_row.show();self.settle();self.assert_centered()
  for margin in (27,7):
   self.h.credit_box.layout().setContentsMargins(0,0,0,margin)
   self.settle();self.assert_centered()
 def test_geometry_timer_settles_instead_of_zero_delay_polling(self):
  self.h.set_watch_only_available(True);self.geometry();self.h.show_activity(STATES[0]);self.settle()
  for _ in range(30):self.app.processEvents()
  self.assertFalse(self.h.activity_position_timer.isActive())
  self.assertFalse(self.h.layout_timer.isActive())
  self.assertFalse(self.h.geometry_timer.isActive())
if __name__=='__main__':unittest.main(verbosity=2)
