"""Prevent Core shutdown or data loss before every required user decision."""
import os,sys,unittest
from pathlib import Path
from unittest.mock import patch,call
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtCore import Qt,QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication,QDialog
import power_ui as p

app=QApplication.instance() or QApplication([])

class PowerFlow(unittest.TestCase):
 def test_empty_workspace_has_only_one_confirmation(self):
  for restart in (False,True):
   with patch.object(p,'ordinary_confirmation',return_value=True) as normal,patch.object(p,'confirmation') as warnings,patch.object(p,'CountdownDialog') as timer:
    self.assertTrue(p.confirm_power_action(restart,occupied=lambda:False))
    normal.assert_called_once_with(restart,None);warnings.assert_not_called();timer.assert_not_called()
 def test_new_file_during_normal_confirmation_gets_the_full_protection(self):
  with patch.object(p,'ordinary_confirmation',return_value=True),patch.object(p,'confirmation',return_value=True) as warnings,patch.object(p,'CountdownDialog') as timer:
   timer.return_value.exec.return_value=QDialog.DialogCode.Rejected
   values=iter([False,True])
   self.assertFalse(p.confirm_power_action(True,occupied=lambda:next(values)))
   self.assertEqual(warnings.call_args_list,[call(True,1,None),call(True,2,None)])
   timer.assert_called_once_with(True,None)
 def test_each_warning_and_countdown_can_cancel(self):
  for restart in (False,True):
   for answers in ([False],[True,False],[True,True]):
    with patch.object(p,'ordinary_confirmation') as normal,patch.object(p,'confirmation',side_effect=answers) as warnings,patch.object(p,'CountdownDialog') as timer:
     timer.return_value.exec.return_value=QDialog.DialogCode.Rejected
     self.assertFalse(p.confirm_power_action(restart,occupied=lambda:True))
     normal.assert_not_called();self.assertEqual(warnings.call_count,len(answers))
     self.assertEqual(timer.call_count,int(len(answers)==2 and all(answers)))
 def test_only_accepted_countdown_allows_power(self):
  for restart in (False,True):
   with patch.object(p,'confirmation',return_value=True),patch.object(p,'CountdownDialog') as timer:
    timer.return_value.exec.return_value=QDialog.DialogCode.Accepted
    self.assertTrue(p.confirm_power_action(restart,occupied=lambda:True))
 def test_countdown_uses_elapsed_time_and_finishes_once(self):
  for restart in (False,True):
   now=[10.0];dialog=p.CountdownDialog(restart,clock=lambda:now[0]);events=[]
   dialog.finished.connect(events.append)
   self.assertEqual(dialog.remaining.text(),'05:00')
   now[0]=309.01;dialog.tick();self.assertEqual(dialog.remaining.text(),'00:01');self.assertEqual(events,[])
   now[0]=310;dialog.tick();dialog.tick();dialog.now_button.click()
   self.assertEqual(events,[QDialog.DialogCode.Accepted]);self.assertFalse(dialog.timer.isActive())
   dialog.deleteLater();app.processEvents()
 def test_cancel_escape_close_and_now_buttons(self):
  for action in ('cancel','escape','close','now'):
   dialog=p.CountdownDialog();dialog.show();app.processEvents()
   if action=='cancel':dialog.cancel_button.click()
   elif action=='escape':QApplication.sendEvent(dialog,QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Escape,Qt.KeyboardModifier.NoModifier))
   elif action=='close':dialog.close()
   else:dialog.now_button.click()
   self.assertEqual(dialog.result(),QDialog.DialogCode.Accepted if action=='now' else QDialog.DialogCode.Rejected)
   self.assertFalse(dialog.timer.isActive());dialog.deleteLater();app.processEvents()

if __name__=='__main__':unittest.main()
