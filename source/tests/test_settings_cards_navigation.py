"""Settings tile parity, icon assignment, and back/close Core status navigation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtWidgets import QApplication,QDialog,QPushButton,QLabel,QStyle,QPlainTextEdit
from PySide6.QtCore import QPoint,QSize,QTimer
from PySide6.QtGui import QIcon
from launcher_ui import NodeSettingsDialog,ToolCard,themed_icon
from desktop_surface import optical_icon
import ui,connection_ui

_APP=None
def application():
    global _APP
    _APP=QApplication.instance() or _APP or QApplication(['settings-navigation'])
    ui.configure_ui(_APP)
    _APP.setQuitOnLastWindowClosed(False)
    return _APP

def home_fixture():
    application()
    return patch.object(ui.Home,'poll_wallets',lambda self:None),patch.object(ui.Home,'poll_activity',lambda self:None),patch.object(connection_ui.ConnectionButton,'poll',lambda self:None)

def stop_home(home):
    home.timer.stop();home.wallet_inventory_timer.stop()
    home.connection_button.timer.stop();home.clock.timer.stop()
    home.close();home.deleteLater()
    application().processEvents()

TITLES=(
    'Network Connections','Bitcoin Core Network & Privacy','Bitcoin Core Status',
    'Date & Time','Backup and Restore',
    'Bluetooth Devices','Mouse Speed','Login Password','Software Updates'
)

class SettingsCards(unittest.TestCase):
    def test_home_style_five_columns_with_centered_last_row(self):
        instance=application()
        a,b,c=home_fixture()
        with a,b,c:
            home=ui.Home()
            try:
                self.assertIn('Settings',home.actions)
                self.assertNotIn('Node Settings',home.actions)
                self.assertTrue(any(card.tool['title']=='Settings' for card in home.cards))
                for width,height in ((650,510),(760,550),(960,555)):
                    d=NodeSettingsDialog(home)
                    d.resize(width,height);d.show()
                    for _ in range(8):instance.processEvents()
                    self.assertEqual(d.windowTitle(),'Settings')
                    self.assertEqual(set(d.cards),set(TITLES))
                    self.assertEqual(d.card_order,TITLES)
                    heading=next(label for label in d.findChildren(QLabel) if label.text()=='Settings')
                    subtitle=next(label for label in d.findChildren(QLabel)
                                  if label.text().startswith('Configure Bitcoin Core,'))
                    for label in (heading,subtitle):
                        location=label.mapTo(d,QPoint(0,0))
                        self.assertAlmostEqual(location.x()+label.width()/2,d.width()/2,delta=2)
                    self.assertGreater(d.cards[TITLES[0]].mapTo(d,QPoint(0,0)).y(),
                                       subtitle.mapTo(d,QPoint(0,0)).y()+subtitle.height()+8)
                    self.assertEqual(len(d.findChildren(ToolCard)),9)
                    self.assertFalse(hasattr(d,'build_version'))
                    self.assertTrue(d.exit_button.isVisible())
                    self.assertEqual(d.exit_button.text(),'Exit')
                    self.assertLessEqual(d.exit_button.width(),90)
                    self.assertEqual(d.exit_button.accessibleName(),'Exit Settings')
                    self.assertFalse(any(b.accessibleName() in
                        ('Start Bitcoin Core','Stop Bitcoin Core','Restart Bitcoin Core')
                        for b in d.findChildren(QPushButton)))
                    coords=[]
                    dimensions=set()
                    for title in TITLES:
                        item=d.cards[title]
                        pos=item.mapTo(d,QPoint(0,0))
                        coords.append((pos.x(),pos.y()))
                        dimensions.add((item.width(),item.height()))
                        self.assertGreater(item.width(),105,(title,width))
                        self.assertGreaterEqual(pos.x(),0)
                        self.assertGreaterEqual(pos.y(),0)
                        self.assertLessEqual(pos.x()+item.width(),d.width())
                        self.assertLessEqual(pos.y()+item.height(),d.height())
                        labels=item.findChildren(QLabel)
                        self.assertEqual(len(labels),3,title)
                        self.assertIsNotNone(labels[0].pixmap())
                        self.assertFalse(labels[0].pixmap().isNull(),title)
                        for label in labels:
                            top=label.mapTo(item,QPoint(0,0))
                            self.assertGreaterEqual(top.y(),0)
                            self.assertLessEqual(top.y()+label.height(),item.height())
                    self.assertEqual({h for w,h in dimensions},{148})
                    self.assertLessEqual(max(w for w,h in dimensions)-min(w for w,h in dimensions),1)
                    self.assertEqual(len({y for x,y in coords}),2 if d.width()>=740 else 3)
                    self.assertEqual(len({x for x,y in coords}),9 if d.width()>=740 else 3)
                    self.assertLessEqual(d.exit_button.mapTo(d,QPoint(0,0)).y()+
                                         d.exit_button.height(),d.height())
                    d.reject();d.deleteLater();instance.processEvents()
            finally:stop_home(home)

    def test_original_network_icon_moved_and_both_bitcoin_cards_use_bitcoin_logo(self):
        application()
        a,b,c=home_fixture()
        with a,b,c:
            home=ui.Home()
            try:
                d=NodeSettingsDialog(home);d.show();application().processEvents()
                from ui import branding_file
                bitcoin=optical_icon(QIcon(str(branding_file('bitcoin-ui.png'))),42)
                def icon_image(title):
                    item=d.cards[title]
                    return item.findChildren(QLabel)[0].pixmap().toImage()
                self.assertEqual(icon_image('Bitcoin Core Network & Privacy'),bitcoin.toImage())
                self.assertEqual(icon_image('Bitcoin Core Status'),bitcoin.toImage())
                icons={
                    'Network Connections':'settings-network-connections.png',
                    'Date & Time':'settings-date-time.png',
                    'Backup and Restore':'settings-chain-backup.png',
                    'Bluetooth Devices':'settings-bluetooth.png',
                    'Mouse Speed':'settings-mouse.png',
                    'Login Password':'settings-login.png',
                    'Software Updates':'settings-software-updates.png',
                }
                for title,filename in icons.items():
                    path=branding_file('icons/'+filename)
                    self.assertTrue(path.is_file(),title)
                    icon=optical_icon(QIcon(str(path)),42)
                    self.assertFalse(icon.isNull(),title)
                    self.assertEqual(icon_image(title),icon.toImage(),title)
                d.close();d.deleteLater()
            finally:stop_home(home)

    def test_card_actions_keep_settings_open_and_exit_returns_home(self):
        app=application()
        a,b,c=home_fixture()
        with a,b,c:
            home=ui.Home()
            try:
                actions={
                  'Bitcoin Core Network & Privacy':('privacy',{}),
                  'Login Password':('login_settings',{}),
                  'Software Updates':('updates',{}),
                  'Date & Time':('date_time',{}),
                  'Backup and Restore':('backup_restore',{}),
                  'Network Connections':('network_status',{'from_settings':True}),
                  'Bluetooth Devices':('bluetooth_devices',{'from_settings':True}),
                  'Mouse Speed':('mouse_settings',{})
                }
                for title,(method,kwargs) in actions.items():
                    with patch.object(home,method) as action:
                        d=NodeSettingsDialog(home);d.show();app.processEvents()
                        d.cards[title].click()
                        action.assert_called_once_with(**kwargs)
                        self.assertTrue(d.isVisible(),title)
                        self.assertEqual(d.selected_action is not None,True)
                        self.assertTrue(d.exit_button.isVisible(),title)
                        d.exit_button.click()
                        self.assertEqual(d.result(),QDialog.Rejected)
                        self.assertFalse(d.isVisible())
                        d.deleteLater();app.processEvents()
                with patch.object(home,'refresh') as status:
                    d=NodeSettingsDialog(home);d.show();app.processEvents()
                    d.cards['Bitcoin Core Status'].click()
                    status.assert_called_once_with(from_settings=True)
                    self.assertTrue(d.isVisible())
                    d.exit_button.click()
                    self.assertFalse(d.isVisible())
                    d.deleteLater()
            finally:stop_home(home)

class StatusNavigation(unittest.TestCase):
    def test_status_back_reuses_existing_grid_close_settings_exits_to_home(self):
        from core_status_ui import CoreStatusDialog
        app=application();a,b,c=home_fixture()
        with a,b,c,patch.object(CoreStatusDialog,'poll',lambda self:None):
            home=ui.Home();root=home.settings();app.processEvents()
            d=home.refresh(from_settings=True);app.processEvents()
            self.assertFalse(d.isModal());self.assertTrue(root.isVisible())
            d.go_back();app.processEvents();self.assertIs(home.settings_dialog,root)
            d=home.refresh(from_settings=True);d.close_settings();app.processEvents()
            self.assertIsNone(home.settings_dialog)
            stop_home(home)

if __name__=='__main__':unittest.main()
