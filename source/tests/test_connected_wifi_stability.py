"""A connected Wi-Fi hotspot never triggers automatic rescans or UI flicker."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import network_ui
import network_access as network
from ui import configure_ui

APP=None
def application():
    global APP
    APP=QApplication.instance() or APP or QApplication([])
    configure_ui(APP)
    APP.setQuitOnLastWindowClosed(False)
    return APP

def settle(dialog):
    app=application()
    until=time.monotonic()+5
    while time.monotonic()<until:
        app.processEvents()
        if dialog.job is None:return
        time.sleep(.005)
    raise AssertionError('Network worker did not finish')

class StableHotspotUI(unittest.TestCase):
    def test_connected_hotspot_keeps_status_list_and_explicit_refresh(self):
        application()
        ap=dict(ssid="Pavao's iPhone",signal=83,security='WPA2',
                device='wlan0',bssid='02:00:00:00:00:01',active=False)
        other=dict(ap,ssid='Guest',security='--',
                   bssid='02:00:00:00:00:02',active=False)
        state={'connected':False}
        calls=[]
        def snapshot(scan=True):
            calls.append(scan)
            connected=state['connected']
            networks=[dict(ap,active=connected),other] if scan else []
            return dict(connected=connected,
                        connections=["Pavao's iPhone"] if connected else [],
                        wifi=True,radio=True,aps=networks)
        def connect(selected,password):
            self.assertEqual(selected['ssid'],ap['ssid'])
            self.assertEqual(password,'test-password')
            state['connected']=True
        with patch.object(network,'snapshot',side_effect=snapshot),patch.object(network,'connect',side_effect=connect):
            dialog=network_ui.NetworkDialog(for_core=False)
            dialog.timer.stop()
            try:
                settle(dialog)
                self.assertEqual(dialog.list.count(),2)
                dialog.list.setCurrentRow(0)
                dialog.password.setText('test-password')
                dialog.connect_selected()
                settle(dialog)
                self.assertTrue(dialog.connected)
                expected="Connected to Pavao's iPhone."
                self.assertEqual(dialog.status.text(),expected)
                self.assertEqual(dialog.list.count(),2)
                self.assertIn('Connected',dialog.list.item(0).text())
                self.assertEqual(dialog.list.currentRow(),0)
                self.assertEqual(dialog.done_button.text(),'Done')
                count_before=len(calls)
                for _ in range(6):
                    dialog.idle_scan()
                    self.assertEqual(dialog.status.text(),expected)
                    settle(dialog)
                    self.assertEqual(dialog.status.text(),expected)
                    self.assertEqual(dialog.list.count(),2)
                    self.assertEqual(dialog.list.currentRow(),0)
                self.assertEqual(calls[count_before:],[False]*6,
                                 'Connected hotspot must never auto-scan Wi-Fi')
                dialog.scan() # user deliberately presses Refresh
                settle(dialog)
                self.assertEqual(calls[-1],True)
                self.assertEqual(dialog.status.text(),expected)
                self.assertEqual(dialog.list.count(),2)
                state['connected']=False
                dialog.idle_scan();settle(dialog)
                self.assertFalse(dialog.connected)
                self.assertIn('Connection lost',dialog.status.text())
                self.assertEqual(dialog.list.count(),2)
                self.assertNotIn('Connected',dialog.list.item(0).text())
            finally:
                dialog.reject()
                for _ in range(10):application().processEvents()
if __name__=='__main__':unittest.main()
