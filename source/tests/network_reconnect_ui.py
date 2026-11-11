"""Real Qt events and children: reconnect, close, minimize and repeat safely."""
import json,os,sys,time,threading
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtCore import Qt,QThread,QPointF,QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication,QPushButton
import ui,connection_ui,network_ui as nw,network_access as net
from launcher_ui import NodeSettingsDialog,ToolCard

app=QApplication([]);ui.configure_ui(app);app.setQuitOnLastWindowClosed(False)
checks=[]
def wait(fn,seconds=4):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        app.processEvents()
        if fn():return
        time.sleep(.005)
    raise AssertionError('UI deadline')
with patch('ui.CoreRPC'),patch.object(connection_ui.ConnectionButton,'poll',lambda self:None):
    # Stop background peer-status Popen calls before mocking the network editor.
    home=ui.Home();home.timer.stop();home.wallet_inventory_timer.stop();home.show()
home.connection_button.timer.stop()
ap=dict(ssid='Pavao’s iPhone',signal=82,security='WPA2',device='wlan0',bssid='02:00:00:00:00:01',active=False)
data=dict(connected=False,connections=[],wifi=True,radio=True,aps=[ap])
clicks=[];button=QPushButton('Independent Home action',home);button.setGeometry(20,20,240,60)
button.clicked.connect(lambda:clicks.append(True));button.show();button.raise_()

# Native network editor from Settings closes only the child chooser, leaving
# the Settings parent available. The Home shortcut remains independently
# nonmodal and minimizable (tested below).
with patch.object(net,'snapshot',return_value=data),patch.object(nw.subprocess,'Popen') as editor:
    settings=NodeSettingsDialog(home);settings.show()
    def launch_advanced():
        d=next(x for x in home.findChildren(nw.NetworkDialog) if x.isVisible())
        assert d.done_button.text()=='Back to Settings'
        d.open_advanced()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(100,launch_advanced)
    next(b for b in settings.findChildren(ToolCard) if b.accessibleName()=='Network Connections').click()
    assert settings.isVisible()
    assert app.activeModalWidget() is None
    settings.reject()
    editor.assert_called_once_with(['/usr/bin/nm-connection-editor'])
checks.append('Settings network chooser returns to its same menu after external editor, with no orphan modal')

# Repeat disconnected/deleted profile -> successful reconnect, error -> retry.
with patch.object(net,'snapshot',return_value=data) as scan,patch.object(net,'connect') as connect:
    for i in range(15):
        home.network_status();d=home.network_dialog;wait(lambda:d.job is None)
        home.network_status();assert home.network_dialog is d
        d.list.setCurrentRow(0);d.password.setText('fixture-password')
        connect.side_effect=net.NetworkError('Fixture failed') if i%2 else None
        d.connect_selected();wait(lambda:d.job is None)
        assert QThread.currentThread()==d.thread()
        if i%2:assert d.status.text()=='Fixture failed'
        else:assert scan.call_args.kwargs=={'scan':False}
        assert not d.password.text() and d.done_button.isEnabled()
        d.showMinimized();app.processEvents()
        assert app.activeModalWidget() is None
        app.sendEvent(button,QMouseEvent(QEvent.MouseButtonPress,QPointF(10,10),Qt.LeftButton,Qt.LeftButton,Qt.NoModifier))
        app.sendEvent(button,QMouseEvent(QEvent.MouseButtonRelease,QPointF(10,10),Qt.LeftButton,Qt.NoButton,Qt.NoModifier))
        assert len(clicks)==i+1
        home.network_status();assert not d.isMinimized()
        d.reject();wait(lambda:not nw._live_jobs)
        assert home.network_dialog is None
checks.append('15 reconnect/failure cycles, minimize, Home clicks and reopen; secrets cleared, no stuck worker')

# Close and destroy the chooser while an actual subprocess is hung.
children=[];real=net.subprocess.Popen
def spawn(*a,**kw):
    p=real(*a,**kw);children.append(p);return p
def hung():return net.run_command(['/usr/bin/python3','-c','import time;time.sleep(60)'],timeout=65)
with patch.object(net,'snapshot',side_effect=hung),patch.object(net.subprocess,'Popen',side_effect=spawn):
    home.network_status();d=home.network_dialog;wait(lambda:bool(children))
    start=time.monotonic();d.reject();app.processEvents()
    assert time.monotonic()-start<.25 and home.network_dialog is None
    wait(lambda:not nw._live_jobs)
    assert all(p.poll() is not None for p in children)
checks.append('destroying a window during a real hung scan cancels its child without blocking Home')

# Starting Core can immediately follow the network check, without a timing delay.
outcomes=[]
def chained(value):
    assert home.job is None and QThread.currentThread()==home.thread()
    outcomes.append(value)
    if value<20:home.start(lambda:value+1,chained)
home.start(lambda:0,chained);wait(lambda:len(outcomes)==21)
assert outcomes==list(range(21)) and home.job is None
checks.append('21 real worker continuations start immediately on GUI thread after prior job cleanup')

result=dict(status='passed',checks=checks)
if len(sys.argv)>1:Path(sys.argv[1]).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
