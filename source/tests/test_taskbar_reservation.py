"""A map-time/stale X11 reservation must not permanently shrink the desktop."""
import os,runpy,sys,unittest
from pathlib import Path
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
app=QApplication.instance() or QApplication([])
root=Path(__file__).resolve().parents[1]
Taskbar=runpy.run_path(str(root/'runtime/usr/local/bin/core-node-taskbar'),run_name='reservation_test')['Taskbar']

class X:
 def __init__(self):self.bottom=400;self.values={};self.writes=[]
 def native_strut(self,wid):return self.bottom,0,1279
 def prop(self,wid,name):return self.values.get(name,[])
 def set_cardinals(self,wid,name,value):self.values[name]=list(value);self.writes.append(name)
 def clear_property(self,wid,name):self.values.pop(name,None)

class TaskbarReservation(unittest.TestCase):
 def test_settled_geometry_replaces_stale_strut_without_notification_churn(self):
  x=X();panel=SimpleNamespace(x=x,panel_active=True,winId=lambda:1)
  Taskbar.sync_reservation(panel)
  self.assertEqual(x.values['_NET_WM_STRUT'][3],400)
  x.bottom=40;Taskbar.sync_reservation(panel)
  self.assertEqual(x.values['_NET_WM_STRUT'],[0,0,0,40])
  self.assertEqual(x.values['_NET_WM_STRUT_PARTIAL'],[0,0,0,40,0,0,0,0,0,0,0,1279])
  count=len(x.writes);Taskbar.sync_reservation(panel);self.assertEqual(len(x.writes),count)
 def test_hidden_panel_releases_both_reservations(self):
  x=X();panel=SimpleNamespace(x=x,panel_active=True,winId=lambda:1)
  Taskbar.sync_reservation(panel);panel.panel_active=False;Taskbar.sync_reservation(panel)
  self.assertEqual(x.values,{})

if __name__=='__main__':unittest.main()
