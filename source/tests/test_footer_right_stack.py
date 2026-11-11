"""Standalone Qt regression guard for the Node's right-hand footer controls."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
import ui,connection_ui

_APPLICATION=None
def application():
    global _APPLICATION
    _APPLICATION=QApplication.instance() or _APPLICATION or QApplication(['node-footer-qa'])
    ui.configure_ui(_APPLICATION)
    return _APPLICATION

class RightFooter(unittest.TestCase):
    def test_right_stack_800_1024_1366_1920(self):
        instance=application()
        with patch.object(ui.Home,'poll_wallets',lambda self:None),\
             patch.object(ui.Home,'poll_activity',lambda self:None),\
             patch.object(connection_ui.ConnectionButton,'poll',lambda self:None):
            for width,height in ((800,600),(1024,768),(1366,768),(1920,1080)):
                home=ui.Home()
                home.clock.timer.stop()
                try:
                    home._test_size=(width,height)
                    home.fit_screen()
                    home.show()
                    home.show_activity(('syncing','Blockchain download and validation in progress · 73.25%',
                                        False,.7325,dict(total=850*1024**3,free=255*1024**3,
                                                         used_percent=70,free_percent=30)))
                    home.connection_button.update_record(dict(
                        state='online',label='Online',explanation='Connected to 8 Bitcoin peers.',
                        service='active',networkactive=True,peers=8))
                    for _ in range(22):
                        instance.processEvents()
                        home.layout_cards()
                    self.assertEqual(home.clock.compact,False)
                    self.assertEqual(home.connection_button.text(),'Bitcoin Core is online')
                    widgets=(home.connection_button,home.clock,home.network_button,
                             home.restart_button,home.shutdown_button)
                    for item in widgets:
                        self.assertTrue(item.isVisible(),(width,item.objectName()))
                        self.assertTrue(item.isEnabled())
                        self.assertEqual(item.parentWidget(),home.power_info if item in widgets[:2] else home.power_icon_row)
                        x,y=item.mapTo(home,QPoint(0,0)).toTuple()
                        self.assertGreaterEqual(x,0)
                        self.assertLessEqual(x+item.width(),home.width())
                        self.assertGreaterEqual(y,0)
                        self.assertLessEqual(y+item.height(),home.height())
                    status_y=widgets[0].mapTo(home,QPoint(0,0)).y()
                    time_y=widgets[1].mapTo(home,QPoint(0,0)).y()
                    buttons_y=widgets[2].mapTo(home,QPoint(0,0)).y()
                    self.assertLess(status_y,time_y)
                    self.assertLess(time_y,buttons_y)
                    self.assertEqual(buttons_y,widgets[3].mapTo(home,QPoint(0,0)).y())
                    self.assertEqual(buttons_y,widgets[4].mapTo(home,QPoint(0,0)).y())
                    self.assertLess(widgets[2].x(),widgets[3].x())
                    self.assertLess(widgets[3].x(),widgets[4].x())
                    self.assertLessEqual(abs(home.credit_box.mapTo(home,QPoint(0,0)).x()+
                                                 home.credit_box.width()/2-home.width()/2),1.0)
                    # Both labels and all three icons must be horizontally
                    # centered on the same right-hand 248px footer zone.
                    def midpoint(widget):
                        return widget.mapTo(home,QPoint(0,0)).x()+widget.width()/2
                    center=midpoint(home.power_box)
                    self.assertLessEqual(abs(midpoint(home.connection_button)-center),1.0)
                    self.assertLessEqual(abs(midpoint(home.clock)-center),1.0)
                    icon_mid=(widgets[2].mapTo(home,QPoint(0,0)).x()+
                              widgets[4].mapTo(home,QPoint(0,0)).x()+widgets[4].width())/2
                    self.assertLessEqual(abs(icon_mid-center),1.0)
                    self.assertGreaterEqual(home.clock.width(),
                                            home.clock.fontMetrics().horizontalAdvance(home.clock.text())+
                                            home.clock.iconSize().width()+40)
                    self.assertGreaterEqual(home.clock.width(),home.clock.sizeHint().width()+8)
                    logo_y=home.debian_logo.mapTo(home,QPoint(0,0)).y()
                    caption_y=home.debian_caption.mapTo(home,QPoint(0,0)).y()
                    footer_y=home.footer.mapTo(home,QPoint(0,0)).y()
                    self.assertGreaterEqual(logo_y-footer_y,48)
                    self.assertEqual(caption_y,logo_y+home.debian_logo.height()+2)
                    self.assertLessEqual(home.footer.mapTo(home,QPoint(0,0)).y()+
                                         home.footer.height()-(caption_y+home.debian_caption.height()),10)
                    self.assertEqual(home.scroll.verticalScrollBar().maximum(),0,(width,height))
                    self.assertTrue(home.network_button.icon().isNull() is False)
                    self.assertTrue(home.restart_button.icon().isNull() is False)
                    self.assertTrue(home.shutdown_button.icon().isNull() is False)
                    # Reproduce the reported T550 clipping at 16:30 (last 0)
                    # and the widest minute at 23:59, without waiting for a
                    # real clock tick or relying on its current time.
                    from datetime import datetime
                    from zoneinfo import ZoneInfo
                    from unittest.mock import patch as mock_patch
                    for hour,minute in ((16,30),(16,39),(23,59),(0,0)):
                        with mock_patch('time_ui.datetime') as clock:
                            clock.now.return_value=datetime(2026,11,3,hour,minute).astimezone()
                            home.clock.refresh()
                            home.layout_footer()
                        for _ in range(3):instance.processEvents()
                        self.assertTrue(home.clock.text().endswith('%02d:%02d'%(hour,minute)))
                        full=home.clock.fontMetrics().horizontalAdvance(home.clock.text())
                        self.assertGreaterEqual(home.clock.width(),full+home.clock.iconSize().width()+40,
                            (width,hour,minute,home.clock.width(),full))
                        self.assertLessEqual(abs(midpoint(home.clock)-center),1.0)
                    home.clock.refresh()
                    home.connection_button.update_record(dict(
                        state='offline',label='Offline',explanation='No Bitcoin peers.',
                        service='inactive',networkactive=False,peers=0))
                    self.assertEqual(home.connection_button.text(),'Bitcoin Core is offline')
                    for _ in range(2):instance.processEvents()
                    self.assertEqual(home.scroll.verticalScrollBar().maximum(),0,(width,height,'offline'))
                finally:
                    home.connection_button.timer.stop()
                    home.clock.timer.stop()
                    home.timer.stop()
                    home.wallet_inventory_timer.stop()
                    home.hide();home.close();home.deleteLater()
                    instance.processEvents()

if __name__=='__main__':
    unittest.main(verbosity=2)
