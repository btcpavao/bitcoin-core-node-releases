"""Qt interaction checks with fake networking; never changes host connections."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtWidgets import QApplication,QDialog,QLineEdit,QLabel
from PySide6.QtCore import Qt
from ui import configure_ui,STYLE,Home
from network_ui import NetworkDialog
import network_access as net
app=QApplication([]);configure_ui(app);app.setStyleSheet(STYLE)
ap=dict(ssid='Office Wi-Fi',signal=87,security='WPA2',device='wlan0',bssid='AA:BB:CC:DD:EE:01',active=False)
data=dict(connected=False,connections=[],wifi=True,radio=True,aps=[ap,dict(ap,ssid='Guest',security='--',bssid='AA:BB:CC:DD:EE:02')])
def settle(d):
    until=time.monotonic()+3
    while time.monotonic()<until:
        app.processEvents();time.sleep(.01)
        if d.job is None:return
    raise AssertionError('Worker stuck')
out=Path('/home/pavao/node-local-build-wifi-20261028/qa');out.mkdir(exist_ok=True)
with patch.object(net,'snapshot',return_value=data),patch.object(net,'connect') as connect:
    d=NetworkDialog(for_core=True);d.timer.stop();d.show();app.processEvents();settle(d)
    d.list.setCurrentRow(0);app.processEvents()
    assert d.password.isVisible() and d.connect_button.isEnabled()
    assert d.password.echoMode()==QLineEdit.Password
    d.password.setText('test-password')
    d.list.setCurrentRow(1);assert not d.password.text() and not d.password.isVisible()
    d.list.setCurrentRow(0);d.password.setText('test-password')
    d.connect_selected();settle(d)
    connect.assert_called_once_with(ap,'test-password');assert not d.password.text()
    for size in ((760,550),(660,550)):
        d.resize(*size);app.processEvents()
        assert d.height()<=560,(size,d.minimumSizeHint().height(),d.height())
        for w in (d.done_button,d.connect_button,d.advanced,d.password):
            assert d.rect().contains(w.geometry())
        d.grab().save(str(out/('wifi-'+str(size[0])+'.png')))
    d.display(dict(data,connected=True,connections=['Office Wi-Fi']))
    assert d.done_button.text()=='Continue to Bitcoin Core'
    d.display(dict(data,wifi=False,aps=[]));assert 'No Wi-Fi adapter' in d.status.text()
    d.display(dict(data,radio=False,aps=[]));assert d.enable.isVisible()
    d.display(dict(data,aps=[]));assert 'No Wi-Fi networks' in d.status.text()
    d.display(dict(data,aps=[dict(ap,ssid='<b>not markup</b>')]))
    d.list.setCurrentRow(0);d.connect_selected();settle(d)
    assert d.status.textFormat()==Qt.PlainText
    d.reject()

# Exercise the Home continuation without constructing or starting Core.
class Fake:
    def __init__(self):self.actions=[]
    def control(self,action):self.actions.append(action)
f=Fake()
Home.offer_network(f,{'connected':True});assert f.actions==['start']
with patch('network_ui.NetworkDialog') as dialog:
    dialog.return_value.exec.return_value=QDialog.Rejected
    Home.offer_network(f,{'connected':False});assert f.actions==['start']
    dialog.return_value.exec.return_value=QDialog.Accepted
    Home.offer_network(f,{'connected':False});assert f.actions==['start','start']
print('PASS: Wi-Fi selection/password/connection, empty/off/absent states, compact layout, Core online/offline/cancel paths')
