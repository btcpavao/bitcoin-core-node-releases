"""Real QProcess completion/cancellation/error regression; no privileged writes."""
from pathlib import Path
import json,os,sys,tempfile,time
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QProcess
import chain_ui,ui
app=QApplication([]);ui.configure_ui(app);app.setQuitOnLastWindowClosed(False)
def wait(predicate):
 end=time.monotonic()+10
 while time.monotonic()<end:
  app.processEvents()
  if predicate():return
  time.sleep(.01)
 raise AssertionError('Process/UI lifecycle deadline')
checks=[]
with tempfile.TemporaryDirectory() as temp:
 helper=Path(temp)/'helper.py'
 helper.write_text('''import json,sys,time
request=json.loads(sys.stdin.readline());assert request['confirmed'] is True
mode=sys.argv[1]
print(json.dumps(dict(event='progress',phase='Checking blockchain',done=0,total=0,cancellable=mode!='commit')),flush=True)
if mode=='cancel':
 assert sys.stdin.readline().strip()=='cancel'
 print('Cancelled. Existing blockchain data was kept.',file=sys.stderr);sys.exit(1)
time.sleep(.3)
print(json.dumps(dict(event='result',ok=True,height=None if mode=='unknown' else 250,tip_is_hint=mode in ('hint','unknown'),bytes=1024,directory='/tmp/test-chain-copy',core_restarted=False,core_was_running=False)),flush=True)
''')
 for mode in ('success','cancel','commit','missing','hint','unknown'):
  class FixtureProcess(QProcess):
   def setProgram(self,program):
    assert program=='/usr/bin/pkexec'
    super().setProgram('/missing/fixture-helper' if mode=='missing' else sys.executable)
   def setArguments(self,arguments):
    assert arguments==['/usr/libexec/core-node-admin','chain-backup']
    super().setArguments([str(helper),mode])
  with patch.object(chain_ui,'QProcess',FixtureProcess):
   d=chain_ui.ChainDialog('backup');d.show();d.directory.setText(temp);d.confirm.setChecked(True)
   assert callable(d.operation_finished),'QDialog finished(int) signal must not hide completion handler'
   d.start.click()
   if mode in ('cancel','commit'):
    wait(lambda:d.feedback.text().startswith('Checking blockchain'))
    d.reject();assert d.isVisible() and d.busy
   wait(lambda:not d.busy and d.process is None)
   assert d.back.isEnabled() and d.browse.isEnabled() and d.usb.isEnabled()
   if mode in ('success','commit','hint','unknown'):
    assert d.result['ok'] is True and 'Blockchain files copied and verified.' in d.feedback.text()
    if mode=='unknown':assert 'reported block' not in d.feedback.text()
    elif mode=='hint':assert 'Last reported block before shutdown: 250' in d.feedback.text()
    else:assert 'Verified block: 250' in d.feedback.text()
    assert d.open_folder.isVisible() and not d.confirm.isChecked()
   elif mode=='cancel':assert 'Cancelled' in d.feedback.text() and d.result is None
   else:assert 'could not start' in d.feedback.text() and d.result is None
   d.reject();checks.append(mode)
print('CHAIN_PROCESS_UI_PASSED '+json.dumps(checks),flush=True)
