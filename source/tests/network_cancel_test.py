"""Real hung subprocess and Qt modal lifecycle regression; no network mutations."""
import os,sys,time
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtWidgets import QApplication,QWidget,QPushButton
from PySide6.QtCore import QTimer
import network_access as net
import network_ui
from ui import configure_ui,STYLE
app=QApplication([]);configure_ui(app);app.setStyleSheet(STYLE)
parent=QWidget();parent.resize(800,600);button=QPushButton('Home is responsive',parent);parent.show()
clicks=[];button.clicked.connect(lambda:clicks.append(True))
children=[]
real=net.subprocess.Popen
def spawn(*args,**kwargs):
 p=real(*args,**kwargs);children.append(p);return p
def hung():
 return net.run_command(['/usr/bin/python3','-c','import time; time.sleep(120)'],timeout=125)
def drain():
 until=time.monotonic()+3
 while network_ui._live_jobs and time.monotonic()<until:app.processEvents();time.sleep(.01)
 assert not network_ui._live_jobs,'Worker leaked after close'
 assert all(p.poll() is not None for p in children),'Child process leaked'
for action in ('reject','close','accept'):
 with patch.object(net,'snapshot',side_effect=hung),patch.object(net.subprocess,'Popen',side_effect=spawn):
  d=network_ui.NetworkDialog(parent,for_core=True)
  before=len(children)
  def close():
   assert d.job is not None
   assert len(children)>before
   assert d.done_button.isEnabled(),'Offline/Done must stay usable during scan'
   start=time.monotonic();getattr(d,action)()
   assert time.monotonic()-start<.2
  QTimer.singleShot(200,close)
  start=time.monotonic();d.exec()
  assert time.monotonic()-start<1
  assert not d.timer.isActive()
  assert app.activeModalWidget() is None
  button.click();assert clicks
  drain();d.deleteLater();app.processEvents()
  print('PASS: hung scan ->',action,'immediate close, responsive Home, no child/thread leak')
# A new normal dialog still works after cancellations.
data=dict(connected=False,connections=[],wifi=True,radio=True,aps=[])
with patch.object(net,'snapshot',return_value=data):
 d=network_ui.NetworkDialog(parent)
 QTimer.singleShot(200,d.reject);d.exec();drain()
 assert not d.timer.isActive()
print('PASS: reopen after cancellation')
