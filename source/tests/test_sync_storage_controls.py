"""QTest-style headless safety gates for Core progress, disk usage and controls."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtWidgets import QApplication,QMessageBox,QWidget
from PySide6.QtGui import QColor
from activity_ui import ActivityIndicator,StorageBar,storage_usage,chain_activity
from connection_ui import ConnectionButton
import activity_ui

APP=None
def application():
    global APP
    APP=QApplication.instance() or APP or QApplication(['node-sync-tests'])
    return APP

class ProgressAndStorage(unittest.TestCase):
    def test_100_segments_render_completed_integer_percent_only(self):
        application()
        widget=ActivityIndicator()
        widget.resize(501,13)
        widget.show()
        widget.set_state('syncing',True,0.256)
        application().processEvents()
        image=widget.grab().toImage()
        self.assertIn('25.60%',widget.accessibleName())
        orange=QColor('#f7931a').rgb()
        grey=QColor('#353535').rgb()
        def pixel(segment):
            # 100 segments with a 1px gap, centered y=6.
            step=(widget.width()-99)/100+1
            x=round(segment*step+1)
            return image.pixelColor(x,6).rgb()
        self.assertEqual(pixel(0),orange)
        self.assertEqual(pixel(24),orange)
        self.assertEqual(pixel(25),grey)
        self.assertEqual(pixel(99),grey)
        widget.set_state('synchronized',False,1.0)
        application().processEvents()
        self.assertEqual(widget.grab().toImage().pixelColor(499,6).rgb(),orange)
        widget.close()

    def test_storage_shows_blockchain_full_percentage_not_whole_disk(self):
        from chain_storage import reading
        expected=reading(30*1024**3,60*1024**3)
        with patch('chain_storage.storage_usage',return_value=expected):
            result=storage_usage()
        self.assertEqual(result['total'],90*1024**3)
        self.assertEqual(result['used_percent'],33.3)
        application();bar=StorageBar();bar.update_space(result)
        self.assertIn('33.3% full',bar.caption.text())
        self.assertEqual(bar.bar.value(),333);bar.close()

    def test_unavailable_storage_hides_instead_of_showing_root_space(self):
        with patch('chain_storage.storage_usage',return_value=None):
            self.assertIsNone(storage_usage())

    def test_node_activity_keeps_real_verificationprogress(self):
        fake_chain=dict(initialblockdownload=True,blocks=520000,headers=600000,
                        time=50000,verificationprogress=.427)
        data=[fake_chain,dict(networkactive=True,connections=3),[]]
        with patch.object(activity_ui.subprocess,'run',return_value=type('Proc',(),dict(returncode=0,stdout='ActiveState=active\n'))()),\
             patch.object(activity_ui,'CoreRPC',return_value=lambda _method:data.pop(0)),\
             patch.object(activity_ui,'storage_usage',return_value={'free_percent':60}):
            result=activity_ui.node_activity()
        self.assertEqual(result[0],'syncing')
        self.assertEqual(result[3],.427)
        self.assertEqual(result[4]['free_percent'],60)
        self.assertIn('42.70%',result[1])

class ConnectionActions(unittest.TestCase):
    def prepare(self,state='online',active=True):
        application()
        home=QWidget()
        home.job=None
        home.start=Mock()
        home.control=Mock()
        home.poll_activity=Mock()
        home.network_status=Mock()
        home.show_card_help=lambda *_:None
        home.hide_card_help=lambda *_:None
        with patch.object(ConnectionButton,'poll',lambda self:None):
            button=ConnectionButton(home)
        button.timer.stop()
        button.poll=Mock()
        record=dict(state=state,label=state.title(),explanation='Synthetic Bitcoin test',
                    service='active' if active else 'inactive',
                    networkactive=True if active else None, peers=4)
        button.update_record(record)
        button.show_details()
        return home,button

    def test_pause_sync_uses_exact_allowed_rpc_only_no_service_stop(self):
        home,button=self.prepare()
        button.perform_action('pause')
        home.start.assert_called_once()
        work,callback=home.start.call_args.args
        with patch('rpc.CoreRPC',return_value=lambda *args:args) as rpc:
            self.assertIs(work(),False)
            rpc.assert_called_once_with(timeout=7)
        home.control.assert_not_called()
        button.dialog.close()
        button.timer.stop()

    def test_resume_sync_sets_true_and_stop_has_confirmation(self):
        home,button=self.prepare()
        button.update_record(dict(button.record,networkactive=False,state='offline'))
        self.assertEqual(button.pause_button.text(),'Resume sync')
        button.perform_action('pause')
        work,_=home.start.call_args.args
        with patch('rpc.CoreRPC',return_value=lambda *args:args) as rpc:
            self.assertIs(work(),True)
            rpc.assert_called_once_with(timeout=7)
        with patch('connection_ui.QMessageBox.question',return_value=QMessageBox.Yes):
            button.perform_action('stop')
        home.control.assert_called_once_with('stop')
        button.dialog.close()
        button.timer.stop()

    def test_stopped_state_has_start_only_and_descriptive_heading(self):
        home,button=self.prepare(state='stopped',active=False)
        self.assertEqual(button.dialog.windowTitle(),'Bitcoin Core')
        self.assertTrue(button.start_button.isEnabled())
        self.assertFalse(button.pause_button.isEnabled())
        self.assertFalse(button.stop_button.isEnabled())
        button.perform_action('start')
        home.control.assert_called_once_with('start')
        button.dialog.close()
        button.timer.stop()

if __name__=='__main__':unittest.main(verbosity=2)
