"""EWMH filtering retains Home-owned modals even with SKIP_TASKBAR."""
import os,runpy,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
R=Path(__file__).resolve().parents[1]
Windows=runpy.run_path(str(R/'runtime/usr/local/bin/core-node-taskbar'),run_name='taskbar_filter_test')['Windows']
class Fake:
 ancestors=Windows.ancestors;node_dialog=Windows.node_dialog;task_windows=Windows.task_windows
 def __init__(self):
  self.root=1;self.records={};self.titles={100:'Bitcoin Core Node'}
  self.records[(1,'_NET_CURRENT_DESKTOP')]=[0]
  for w,kind,parent,state in ((100,'DESKTOP',None,1),(101,'DIALOG',100,3),(102,'DIALOG',101,3),(103,'DOCK',None,1),(104,'TOOLTIP',102,1),(105,'NORMAL',None,3)):
   self.records[(w,'_NET_WM_WINDOW_TYPE')]=[self.atom('_NET_WM_WINDOW_TYPE_'+kind)]
   self.records[(w,'_NET_WM_DESKTOP')]=[0]
   self.records[(w,'WM_STATE')]=[state]
   if parent:self.records[(w,'WM_TRANSIENT_FOR')]=[parent]
  self.records[(101,'_NET_WM_STATE')]=[self.atom('_NET_WM_STATE_SKIP_TASKBAR')]
  self.records[(102,'_NET_WM_STATE')]=[self.atom('_NET_WM_STATE_SKIP_TASKBAR'),self.atom('_NET_WM_STATE_MODAL')]
 def atom(self,name):return name
 def prop(self,window,name):return self.records.get((window,name),[])
 def managed(self):return list(range(100,106))
 def title(self,w):return self.titles.get(w,'Dialog')
class TaskbarDialogs(unittest.TestCase):
 def test_iconified_nested_modals_remain_tasks(self):
  self.assertEqual(Fake().task_windows(),[101,102,105])
 def test_inherits_desktop_from_home_and_rejects_other_workspace(self):
  f=Fake();del f.records[(102,'_NET_WM_DESKTOP')]
  self.assertIn(102,f.task_windows());f.records[(101,'_NET_WM_DESKTOP')]=[1]
  self.assertNotIn(102,f.task_windows())
 def test_cycles_are_bounded(self):
  f=Fake();f.records[(100,'WM_TRANSIENT_FOR')]=[102]
  self.assertEqual(f.ancestors(102),[101,100])
if __name__=='__main__':unittest.main()
