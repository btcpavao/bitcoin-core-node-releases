"""The last letter of Cancel must remain visible in real Qt dialog styles."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtWidgets import (QApplication,QMessageBox,QPushButton,
                               QStyleOptionButton,QStyle)
from PySide6.QtCore import QPoint,QTimer
import power_ui

APP=None
def application():
    global APP
    APP=QApplication.instance() or APP or QApplication([])
    APP.setQuitOnLastWindowClosed(False)
    return APP

class CancelClipping(unittest.TestCase):
    def test_cancel_and_confirm_full_text_on_800_and_1366_layouts(self):
        a=application()
        for restart in (True,False):
            for scale in (1,1.5):
                title='Restart' if restart else 'Shutdown'
                box=QMessageBox()
                box.setWindowTitle(title)
                box.setStyleSheet(power_ui.STYLE)
                box.setText('Restart this computer?' if restart else 'Shut down this computer?')
                box.setInformativeText('Bitcoin Core will stop cleanly. Its saved blockchain and wallets remain on disk.')
                proceed=box.addButton(title,QMessageBox.AcceptRole)
                cancel=box.addButton('Cancel',QMessageBox.RejectRole)
                box.setDefaultButton(cancel);box.setEscapeButton(cancel)
                power_ui.fit_buttons(box)
                box.show()
                for _ in range(10):a.processEvents()
                for button in (cancel,proceed):
                    fm=button.fontMetrics()
                    option=QStyleOptionButton()
                    option.initFrom(button)
                    option.text=button.text()
                    contents=button.style().subElementRect(QStyle.SubElement.SE_PushButtonContents,option,button)
                    self.assertGreaterEqual(contents.width(),fm.horizontalAdvance(button.text())+16,
                                            (restart,scale,button.text(),contents.width()))
                    self.assertGreaterEqual(button.minimumWidth(),124)
                    self.assertGreaterEqual(button.width(),button.minimumWidth())
                    pos=button.mapTo(box,QPoint(0,0))
                    self.assertLessEqual(pos.x()+button.width(),box.width())
                self.assertEqual(cancel.text(),'Cancel')
                box.close()
                box.deleteLater()
                a.processEvents()

    def test_cancel_disallows_power_and_default_semantics_preserved(self):
        a=application()
        for restart in (True,False):
            def cancel_if_visible():
                window=next(w for w in a.topLevelWidgets() if isinstance(w,QMessageBox) and w.isVisible())
                self.assertEqual(window.defaultButton().text(),'Cancel')
                self.assertEqual(window.escapeButton().text(),'Cancel')
                window.defaultButton().click()
            QTimer.singleShot(0,cancel_if_visible)
            self.assertFalse(power_ui.ordinary_confirmation(restart))
if __name__=='__main__':unittest.main(verbosity=2)
