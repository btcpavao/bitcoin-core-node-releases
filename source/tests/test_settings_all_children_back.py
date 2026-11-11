"""Every Settings child returns to the SAME menu; native system changes mocked."""
import os,sys,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QTimer,QEventLoop
from PySide6.QtWidgets import QApplication,QDialog,QPushButton
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import ui,bluetooth_ui,connection_ui,login_ui,network_access,pointer_control,software_ui
from launcher_ui import NodeSettingsDialog

_APP=None
def app():
    global _APP
    _APP=QApplication.instance() or _APP or QApplication([])
    ui.configure_ui(_APP);_APP.setQuitOnLastWindowClosed(False)
    return _APP

class SettingsAllChildrenBack(unittest.TestCase):
    def test_all_subdialogs_return_to_settings_without_second_root(self):
        app()
        state=dict(connected=False,connections=[],wifi=True,radio=True,aps=[])
        updates=dict(busy=True,message='Fixture update check in progress',
                     stage='checking',progress=None,packages=[])
        original_is_file=Path.is_file
        def installed_or_actual(path):
            return str(path)=='/etc/bitcoin-core-node/installed' or original_is_file(path)
        cases=[
            ('Bitcoin Core Network & Privacy','Network & Privacy','Back to Settings'),
            ('Backup and Restore','Backup and Restore','Back to Settings'),
            ('Bluetooth Devices','Bluetooth Devices','Back to Settings'),
            ('Mouse Speed','Mouse & Pointer','Back to Settings'),
            ('Login Password','Login Password','Back to Settings'),
            ('Software Updates','Software Updates','Back to Settings')
        ]
        events=[];errors=[];holder={}
        def fail(error):
            errors.append(repr(error))
            for dialog in reversed(QApplication.topLevelWidgets()):
                if isinstance(dialog,QDialog) and dialog.isVisible():dialog.reject()
            if getattr(home,'settings_dialog',None):home.settings_dialog.reject()
        def deferred(fn,delay=20):
            def wrapped():
                try:fn()
                except BaseException as exc:fail(exc)
            QTimer.singleShot(delay,wrapped)
        def root():
            current=home.settings_dialog
            assert isinstance(current,NodeSettingsDialog) and current.isVisible()
            assert holder.setdefault('root',current) is current
            assert len([x for x in [w for w in QApplication.topLevelWidgets() if isinstance(w,NodeSettingsDialog)] if x.isVisible()])==1
            return current
        def start(index=0):
            menu=root()
            if index==len(cases):
                events.append('all six submenu Back actions retained one Settings window')
                deferred(menu.exit_button.click,0)
                return
            title,window,back=cases[index]
            deferred(lambda:close(index,window,back),80)
            menu.cards[title].click()
        def close(index,window,back):
            dialog=next((x for x in QApplication.topLevelWidgets()
                         if x is not home.settings_dialog and x.windowTitle()==window and x.isVisible()),None)
            assert dialog is not None,(window,[x.windowTitle() for x in QApplication.topLevelWidgets() if x.isVisible()])
            button=next((b for b in dialog.findChildren(QPushButton)
                         if b.text()==back),None)
            assert button is not None,(window,back,[b.text() for b in dialog.findChildren(QPushButton)])
            button.click()
            events.append((window,back))
            deferred(lambda:start(index+1))
        def watchdog():
            if getattr(home,'settings_dialog',None) is not None:fail('Watchdog timeout waiting for Settings exit')
        from ui import Home
        with patch.object(Home,'poll_wallets',lambda self:None),\
             patch.object(Home,'poll_activity',lambda self:None),\
             patch.object(connection_ui.ConnectionButton,'poll',lambda self:None),\
             patch.object(ui,'load_setup',return_value=None),\
             patch.object(network_access,'snapshot',return_value=state),\
             patch.object(pointer_control,'get_devices',return_value=[]),\
             patch.object(software_ui,'read_status',return_value=updates),\
             patch.object(login_ui,'passwordless',return_value=True),\
             patch.object(bluetooth_ui.subprocess,'Popen') as native_manager,\
             patch.object(Path,'is_file',installed_or_actual):
            home=ui.Home();home.show()
            try:
                deferred(lambda:start(0),0)
                watch=QTimer();watch.setSingleShot(True);watch.timeout.connect(watchdog);watch.start(7000)
                home.settings()
                loop=QEventLoop();home.settings_dialog.finished.connect(loop.quit);loop.exec();watch.stop()
                self.assertFalse(errors,errors)
                self.assertEqual(len(events),len(cases)+1)
                self.assertIsNone(home.settings_dialog)
                native_manager.assert_called_once()
                self.assertEqual(native_manager.call_args.args[0],['/usr/bin/blueman-manager'])
            finally:
                home.timer.stop();home.wallet_inventory_timer.stop()
                home.connection_button.timer.stop();home.clock.timer.stop()
                home.hide();home.deleteLater();app().processEvents()

if __name__=='__main__':unittest.main()
