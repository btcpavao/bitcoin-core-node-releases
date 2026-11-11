"""Exercise live nested Qt navigation without real network or OS modifications."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtWidgets import QApplication,QDialog,QPushButton
from PySide6.QtCore import QTimer,QEventLoop
import ui,connection_ui,time_ui,network_ui,network_access
from launcher_ui import NodeSettingsDialog
from chain_ui import ChainDialog

_APP=None
def application():
    global _APP
    _APP=QApplication.instance() or _APP or QApplication([])
    ui.configure_ui(_APP)
    _APP.setQuitOnLastWindowClosed(False)
    return _APP

def cleanup(home):
    for attr in ('timer','wallet_inventory_timer'):
        getattr(home,attr).stop()
    home.connection_button.timer.stop()
    home.clock.timer.stop()
    home.hide()
    home.deleteLater()
    application().processEvents()

def visible_child(home,klass):
    return next((x for x in [w for w in QApplication.topLevelWidgets() if isinstance(w,klass)] if x.isVisible()),None)

class SettingsApplyBack(unittest.TestCase):
    def test_apply_date_back_then_chain_and_wifi_back_reuses_one_settings(self):
        app=application()
        state=dict(timezone='UTC',automatic=True,can_automatic=True,synchronized=True)
        result=dict(ok=True,time=dict(state,timezone='Europe/Zagreb'))
        ap=dict(ssid='Synthetic hotspot',signal=90,security='WPA2',device='wlan0',
                bssid='02:00:00:00:00:01',active=True)
        network=dict(connected=True,connections=['Synthetic hotspot'],
                     wifi=True,radio=True,aps=[ap])
        errors=[]
        evidence=[]
        root_holder={}
        def safe(fn):
            try:fn()
            except BaseException as exc:
                errors.append(repr(exc))
                for dialog in reversed(QApplication.topLevelWidgets()):
                    if isinstance(dialog,QDialog) and dialog.isVisible():dialog.reject()
                if home.settings_dialog is not None:home.settings_dialog.reject()
        def later(ms,fn):
            QTimer.singleShot(ms,lambda:safe(fn))
        def root():
            item=home.settings_dialog
            assert isinstance(item,NodeSettingsDialog) and item.isVisible()
            assert item is root_holder.setdefault('root',item)
            assert len([x for x in [w for w in QApplication.topLevelWidgets() if isinstance(w,NodeSettingsDialog)] if x.isVisible()])==1
            return item
        def start_date():
            current=root()
            evidence.append('Settings menu opened')
            later(25,await_date_load)
            current.cards['Date & Time'].click()
        def await_date_load():
            dialog=visible_child(home,time_ui.DateTimeDialog)
            if dialog is None or not dialog.loaded or dialog.job is not None:
                later(20,await_date_load);return
            assert dialog.timezone.isEnabled()
            dialog.timezone.setCurrentText('Europe/Zagreb')
            dialog.apply.click()
            later(20,await_date_save)
        def await_date_save():
            dialog=visible_child(home,time_ui.DateTimeDialog)
            assert dialog is not None
            if dialog.job is not None or not dialog.saved:
                later(20,await_date_save);return
            assert dialog.feedback.text()=='Date and time settings saved.'
            evidence.append('Date & Time Apply saved')
            dialog.back.click()
            later(20,start_chain)
        def start_chain():
            current=root()
            evidence.append('Date & Time Back returned to the same Settings menu')
            later(30,open_chain_in_group)
            current.cards['Backup and Restore'].click()
        def open_chain_in_group():
            from backup_restore_ui import BackupRestoreDialog
            hub=visible_child(home,BackupRestoreDialog)
            assert hub is not None
            later(30,finish_chain)
            hub.actions[('chain',False)].click()
        def finish_chain():
            child=visible_child(home,ChainDialog)
            assert child is not None and child.back.text()=='Back to Backup and Restore'
            child.back.click()
            later(20,close_backup_group)
        def close_backup_group():
            from backup_restore_ui import BackupRestoreDialog
            hub=visible_child(home,BackupRestoreDialog)
            assert hub is not None
            hub.reject()
            later(20,start_wifi)
        def start_wifi():
            current=root()
            evidence.append('Backup Chain State Back returned to Settings')
            later(100,finish_wifi)
            current.cards['Network Connections'].click()
        def finish_wifi():
            child=visible_child(home,network_ui.NetworkDialog)
            assert child is not None
            assert child.done_button.text()=='Back to Settings'
            child.done_button.click()
            later(20,exit_settings)
        def exit_settings():
            current=root()
            evidence.append('Network Connections Back returned to Settings')
            current.exit_button.click()
        def watchdog():
            if home.settings_dialog is not None:
                errors.append('Settings watchdog: modal flow failed to close')
                for dialog in reversed(QApplication.topLevelWidgets()):
                    if isinstance(dialog,QDialog) and dialog.isVisible():dialog.reject()
                if home.settings_dialog is not None:home.settings_dialog.reject()
        a=patch.object(ui.Home,'poll_wallets',lambda self:None)
        b=patch.object(ui.Home,'poll_activity',lambda self:None)
        c=patch.object(connection_ui.ConnectionButton,'poll',lambda self:None)
        with a,b,c,patch.object(time_ui,'snapshot',return_value=state),\
              patch.object(network_access,'snapshot',return_value=network),\
              patch.object(ui,'admin',return_value=result) as admin:
            home=ui.Home();home.show()
            try:
                later(0,start_date)
                watch=QTimer();watch.setSingleShot(True);watch.timeout.connect(watchdog);watch.start(8000)
                home.settings()
                loop=QEventLoop();home.settings_dialog.finished.connect(loop.quit);loop.exec();watch.stop()
                self.assertFalse(errors,errors)
                self.assertEqual(evidence,[
                    'Settings menu opened',
                    'Date & Time Apply saved',
                    'Date & Time Back returned to the same Settings menu',
                    'Backup Chain State Back returned to Settings',
                    'Network Connections Back returned to Settings'
                ])
                admin.assert_called_once()
                self.assertEqual(admin.call_args.args[0],'time-settings')
                self.assertEqual(admin.call_args.args[1]['timezone'],'Europe/Zagreb')
                self.assertIsNone(home.settings_dialog)
            finally:cleanup(home)

if __name__=='__main__':
    unittest.main()
