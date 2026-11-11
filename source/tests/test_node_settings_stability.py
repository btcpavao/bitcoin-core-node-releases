"""Offline mock-based smoke gates for user-reported Node interaction regressions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtWidgets import QApplication,QDialog
from PySide6.QtCore import QTimer,QEventLoop
import pointer_control as mouse
import system_updates as updates
import connection_ui
from connection_state import peer_state
import desktop_surface
import ui

_APP=None
def app():
    global _APP
    _APP=QApplication.instance() or _APP or QApplication(['node-stability-tests'])
    ui.configure_ui(_APP)
    return _APP

class MouseSafety(unittest.TestCase):
    def test_parse_bluetooth_and_usb_pointers_and_filter_virtual_devices(self):
        output='''⎡ Virtual core pointer                    id=2 [master pointer (3)]
⎜   ↳ Virtual core XTEST pointer           id=4 [slave pointer (2)]
⎜   ↳ Logitech Bluetooth Mouse            id=12 [slave pointer (2)]
⎜   ↳ USB Optical Mouse                    id=13 [slave pointer (2)]
⎣ Virtual core keyboard                   id=3 [master keyboard (2)]'''
        def fake(*args):
            if args==('--list','--short'):return output
            if args==('--list-props',4):return 'Device Enabled (135): 1\n'
            if args in (('--list-props',12),('--list-props',13)):
                return 'libinput Accel Speed (312):  -0.200000\n'
            raise AssertionError(args)
        with patch.object(mouse,'xinput',side_effect=fake):
            value=mouse.get_devices()
        self.assertEqual([d['id'] for d in value],[12,13])
        self.assertEqual([d['name'] for d in value],['Logitech Bluetooth Mouse','USB Optical Mouse'])
        self.assertEqual(value[0]['speed'],-0.2)

    def test_mouse_preferences_are_persistent_safely_bounded(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            path=Path(td)/'.config/node/mouse.json'
            with patch.object(mouse,'PREFS',path):
                mouse.save_preference('Bluetooth Mouse',-0.70)
                self.assertEqual(mouse.load_preferences(),{'Bluetooth Mouse':-0.7})
                self.assertEqual(path.stat().st_mode & 0o777,0o600)
                with self.assertRaises(mouse.PointerError):mouse.save_preference('Bad\nName',0.5)
                with self.assertRaises(mouse.PointerError):mouse.set_speed(4,2)

    def test_real_xinput_args_reject_shell_injection(self):
        with patch.object(mouse,'xinput',return_value='') as tool:
            mouse.set_speed(12,-0.65)
        tool.assert_called_once_with('--set-prop',12,'libinput Accel Speed','-0.65')

class UpdateStability(unittest.TestCase):
    def test_software_upgrade_never_stops_or_restarts_core(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            reports=[];cmds=[]
            package=dict(name='libfoo',previous='1.0',version='1.1')
            old=dict(version='2.8.0',source='https://trusted.example/image')
            latest=dict(version='2.8.0',url='https://trusted.example/image')
            def command(args,**kw):
                cmds.append(args)
                on_line=kw.get('on_line')
                if on_line:
                    if '--download-only' in args:on_line('Get:1 https://debian.example foo 1.1 [10 kB]\n')
                    elif 'upgrade' in args:on_line('Setting up libfoo (1.1) ...\n')
            with patch.object(updates,'LOCK',Path(td)/'software.lock'),\
                 patch.object(updates.os,'geteuid',return_value=0),\
                 patch.object(updates,'write_status',side_effect=lambda **k:reports.append(k)),\
                 patch.object(updates,'command',side_effect=command),\
                 patch.object(updates,'plan',side_effect=[[package],[]]),\
                 patch.object(updates,'current_release',return_value=old),\
                 patch.object(updates,'latest_release',return_value=latest),\
                 patch.object(updates,'reboot_required',return_value=False),\
                 patch.object(updates.shutil,'disk_usage',return_value=type('Disk',(),{'free':100*1024**3})()),\
                 patch.object(updates.subprocess,'run') as process:
                updates.perform('install')
            process.assert_not_called()  # No deliberate systemctl stop/start.
            self.assertNotIn('bitcoin-core-node.service',' '.join(' '.join(c) for c in cmds))
            self.assertIn('downloading',[r['stage'] for r in reports])
            self.assertIn('installing',[r['stage'] for r in reports])
            self.assertEqual(reports[-1]['stage'],'complete')
            self.assertEqual(reports[-1]['progress'],100)
            self.assertTrue(any(r.get('progress',0) and r['progress']>=50 for r in reports))

    def test_reboot_preview_flags_kernel_and_core_independent(self):
        self.assertTrue(updates.restart_likely([dict(name='linux-image-6.12.1-amd64')]))
        self.assertFalse(updates.restart_likely([dict(name='thunar')]))
        self.assertEqual(peer_state('inactive')[0],'stopped')

class HomeResponsiveness(unittest.TestCase):
    def test_stopped_core_retains_main_event_loop_and_cards_click(self):
        instance=app()
        with patch.object(ui.Home,'poll_wallets',lambda self:None),\
             patch.object(ui.Home,'poll_activity',lambda self:None),\
             patch.object(connection_ui.ConnectionButton,'poll',lambda self:None):
            home=ui.Home()
            home._test_size=(1366,768)
            home.show()
            home.set_watch_only_available(False)
            home.show_activity(('synchronized','Blockchain synchronized.',False))
            home.show_activity(('stopped','Bitcoin Core is stopped. Open Bitcoin Core to resume validation.',False))
            self.assertEqual(home.activity.state,'stopped')
            self.assertEqual(len(home.cards)>0,True)
            clicked=[]
            target=home.cards[0]
            with patch.object(home,'activate_tool',side_effect=lambda *args:clicked.append(args)):
                # Connection established during build_ui cannot be changed after
                # connecting it. Add an independent click probe as a liveness gate.
                target.clicked.connect(lambda:clicked.append('click'))
                ticks=[]
                loop=QEventLoop()
                timer=QTimer()
                timer.timeout.connect(lambda:ticks.append(1))
                timer.start(20)
                QTimer.singleShot(130,loop.quit)
                loop.exec()
                timer.stop()
                target.clicked.disconnect()
            self.assertGreaterEqual(len(ticks),2,'Qt main loop was starved after Core stopped')
            self.assertTrue(home.cards[0].isEnabled())
            home.timer.stop();home.wallet_inventory_timer.stop();home.connection_button.timer.stop()
            home.close();home.deleteLater()

    def test_modal_dialog_cannot_be_iconified_by_background_click(self):
        app()
        with patch.object(ui.Home,'poll_wallets',lambda self:None),\
             patch.object(ui.Home,'poll_activity',lambda self:None),\
             patch.object(connection_ui.ConnectionButton,'poll',lambda self:None):
            home=ui.Home()
            home.show()
            home.self_test=False
            dialog=QDialog(home);dialog.setModal(True);dialog.show()
            app().processEvents()
            with patch.object(desktop_surface.subprocess,'Popen',side_effect=AssertionError('Modal dialog hidden!')) as spawn:
                home.show_home_from_background_click()
                spawn.assert_not_called()
            dialog.close();home.self_test=True
            home.timer.stop();home.wallet_inventory_timer.stop();home.connection_button.timer.stop()
            home.close();home.deleteLater()

    def test_descriptive_connection_indicator_always_red_for_stopped(self):
        app()
        fake_home=Mock()
        fake_home.show_card_help=lambda *_:None
        fake_home.hide_card_help=lambda *_:None
        with patch.object(connection_ui.ConnectionButton,'poll',lambda self:None):
            button=connection_ui.ConnectionButton(fake_home)
            button.timer.stop()
            button.update_record(dict(state='stopped',label='Stopped',explanation='Core is stopped'))
            self.assertEqual(button.text(),'Bitcoin Core is offline')
            self.assertEqual(button.icon().pixmap(18,18).toImage().pixelColor(9,9).name().lower(),'#ff5151')
            button.update_record(dict(state='online',label='Online',explanation='Peers connected'))
            self.assertEqual(button.text(),'Bitcoin Core is online')
            self.assertEqual(button.icon().pixmap(18,18).toImage().pixelColor(9,9).name().lower(),'#1cf46b')
            button.set_compact(True)
            self.assertEqual(button.text().replace('\n',' '),'Bitcoin Core is online')
            button.update_record(dict(state='stopped',label='Stopped',explanation='Core stopped'))
            self.assertEqual(button.text().replace('\n',' '),'Bitcoin Core is offline')
            self.assertEqual(button.icon().pixmap(18,18).toImage().pixelColor(9,9).name().lower(),'#ff5151')
            button.deleteLater()

if __name__=='__main__':unittest.main(verbosity=2)
