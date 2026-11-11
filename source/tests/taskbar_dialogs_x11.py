"""Real X11/Openbox regression: minimized Node modals stay recoverable."""
import json,os,runpy,subprocess,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication,QWidget,QDialog,QLabel,QVBoxLayout
from PySide6.QtCore import Qt
R=Path(__file__).resolve().parents[1]
app=QApplication([]);app.setQuitOnLastWindowClosed(False)
wm=subprocess.Popen(['openbox'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def wait(predicate,seconds=8):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  app.processEvents()
  try:
   value=predicate()
   if value:return value
  except (OSError,ValueError):pass
  time.sleep(.04)
 raise AssertionError('X11 taskbar condition timed out')
try:
 time.sleep(.4)
 mod=runpy.run_path(str(R/'runtime/usr/local/bin/core-node-taskbar'),run_name='x11_dialog_test')
 x=mod['Windows']()
 home=QWidget();home.setWindowTitle('Bitcoin Core Node');home.setAttribute(Qt.WA_X11NetWmWindowTypeDesktop,True);home.resize(1024,700);home.show()
 settings=QDialog(home);settings.setWindowTitle('Settings');settings.setModal(True);settings.resize(600,400)
 settings.setWindowFlag(Qt.WindowMinimizeButtonHint,True);settings.show()
 hub=QDialog(settings);hub.setWindowTitle('Backup and Restore');hub.setModal(True);hub.resize(550,360);hub.show()
 progress=QDialog(hub);progress.setWindowTitle('Backup Chain State');progress.setModal(True);progress.resize(500,300)
 progress.setWindowFlag(Qt.WindowMinimizeButtonHint,True)
 label=QLabel('Copying fixture blockchain data',progress);label.move(25,40);progress.show()
 wid=int(progress.winId());sid=int(settings.winId());hid=int(hub.winId())
 wait(lambda:wid in x.managed())
 panel=subprocess.Popen([sys.executable,str(R/'runtime/usr/local/bin/core-node-taskbar'),'--preview','--assets',str(R/'runtime/usr/share/bitcoin-core-node')],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 try:
  report=Path(os.environ['XDG_RUNTIME_DIR'])/'core-node-taskbar-geometry.json'
  def get():return json.loads(report.read_text())
  wait(lambda:get()['visible'] and hex(wid) in get()['tasks'])
  # Reproduce all three nested dialogs being iconified while no Core task exists.
  progress.showMinimized();hub.showMinimized();settings.showMinimized()
  wait(lambda:x.minimized(wid) and x.minimized(sid))
  wait(lambda:get()['visible'] and all(hex(w) in get()['tasks'] for w in (wid,sid,hid)))
  record=get()
  assert record['strut'][3]>0
  x.restore_task(sid)
  wait(lambda:not x.minimized(wid) and not x.minimized(sid))
  wait(lambda:x.prop(x.root,'_NET_ACTIVE_WINDOW')==[wid])
  assert progress.isVisible() and label.text()=='Copying fixture blockchain data'
  progress.done(0);hub.done(0);settings.done(0)
  wait(lambda:not get()['visible'])
  result=dict(status='passed',minimized_modals_listed=True,panel_kept_visible=True,
              parent_click_restores_deepest_modal=True,copy_dialog_kept_alive=True,
              panel_hides_only_after_all_dialogs_closed=True)
  print(json.dumps(result),flush=True)
 finally:
  panel.terminate();panel.wait(timeout=5)
 home.close();x.close()
finally:
 wm.terminate();wm.wait(timeout=5)
