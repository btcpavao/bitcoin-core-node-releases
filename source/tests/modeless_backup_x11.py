"""Actual X11 navigation while a real local copy emits ChainDialog progress.

The copy fixture substitutes only the privileged backend, never the UI, window
manager or taskbar. No host wallet, network settings or physical USB is used.
"""
import json,os,runpy,subprocess,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QProcess
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'app'))
import ui,connection_ui
app=QApplication([]);app.setQuitOnLastWindowClosed(False);ui.configure_ui(app)
wm=subprocess.Popen(['openbox'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def wait(fn,seconds=20):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  app.processEvents()
  try:
   result=fn()
   if result:return result
  except (OSError,ValueError):pass
  time.sleep(.035)
 raise AssertionError('X11 condition timed out')
try:
 time.sleep(.4)
 with tempfile.TemporaryDirectory(dir='/dev/shm') as td,patch.object(ui.Home,'poll_wallets',lambda _:None),patch.object(ui.Home,'poll_activity',lambda _:None),patch.object(connection_ui.ConnectionButton,'poll',lambda _:None):
  home=ui.Home();home.show();home.timer.stop();home.wallet_inventory_timer.stop();home.connection_button.timer.stop();home.clock.timer.stop()
  settings=home.settings();hub=home.backup_restore();progress=hub.open_transfer('chain',False)
  mod=runpy.run_path(str(R/'runtime/usr/local/bin/core-node-taskbar'),run_name='independent_ui_test');x=mod['Windows']()
  panel=subprocess.Popen([sys.executable,str(R/'runtime/usr/local/bin/core-node-taskbar'),'--preview','--assets',str(R/'runtime/usr/share/bitcoin-core-node')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  try:
   report=Path(os.environ['XDG_RUNTIME_DIR'])/'core-node-taskbar-geometry.json'
   ids=[int(w.winId()) for w in (settings,hub,progress)]
   wait(lambda:report.exists() and json.loads(report.read_text())['visible'])
   script=Path(td)/'copy.py'
   script.write_text('''import json,time,sys,os
from pathlib import Path
root=Path(sys.argv[1]);data=b'x'*65536
with (root/'copied.bin').open('wb') as out:
 for i in range(128):
  out.write(data);out.flush();print(json.dumps(dict(event='progress',phase='Copying fixture blockchain data',done=(i+1)*65536,total=128*65536,cancellable=True)),flush=True);time.sleep(.1)
 os.fsync(out.fileno())
print(json.dumps(dict(event='result',ok=True,height=None,directory=str(root),core_was_running=False,core_restarted=False)),flush=True)
''')
   p=QProcess(progress);progress.process=p;progress.busy=True;progress.progress.show();progress.start.setEnabled(False)
   p.readyReadStandardOutput.connect(progress.read_output);p.readyReadStandardError.connect(progress.read_error);p.finished.connect(progress.operation_finished)
   p.setProgram(sys.executable);p.setArguments([str(script),td]);p.start()
   wait(lambda:progress.progress.value()>0)
   for w in (progress,hub,settings):w.showMinimized()
   wait(lambda:all(x.minimized(i) for i in ids))
   assert json.loads(report.read_text())['visible']
   x.restore_task(ids[0]);wait(lambda:x.prop(x.root,'_NET_ACTIVE_WINDOW')==[ids[0]])
   assert progress.busy and x.minimized(ids[2]),'Progress must not steal focus from Settings'
   x.restore_task(ids[1]);wait(lambda:x.prop(x.root,'_NET_ACTIVE_WINDOW')==[ids[1]])
   hub.reject();app.processEvents();assert progress.busy
   hub=home.backup_restore();again=hub.open_transfer('chain',False);assert again is progress
   wait(lambda:not x.minimized(ids[2]));progress.go_back()
   assert progress.busy and progress.isMinimized()
   wait(lambda:not progress.busy,20)
   assert progress.result['ok'] and (Path(td)/'copied.bin').stat().st_size==128*65536
   assert progress.progress.value()==1000
   for d in list(home._modeless_windows.values()):d.reject()
   wait(lambda:not json.loads(report.read_text())['visible'])
   print(json.dumps(dict(status='passed',copy_bytes=128*65536,settings_and_hub_focus_independent=True,closing_menu_keeps_copy_alive=True,reopening_reuses_same_job=True,back_does_not_cancel=True,taskbar_retained=True,copy_completed=True)),flush=True)
  finally:panel.terminate();panel.wait(timeout=5);x.close();home.hide()
finally:wm.terminate();wm.wait(timeout=5)
