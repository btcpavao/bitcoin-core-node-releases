#!/usr/bin/python3
"""Exercise real Home power controls with the privileged request intercepted."""
import argparse,json,os,sys,time
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtCore import QTimer,Qt,QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox,QLabel,QPushButton,QStyleOptionButton,QStyle
import ui,power_ui

p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);out=p.parse_args().output;out.mkdir(parents=True,exist_ok=True)
app=QApplication([]);ui.configure_ui(app);app.setQuitOnLastWindowClosed(False)
rows=[];active={};seen=[];errors=[];calls=[];occupied={'value':False}

def drive():
 try:
  if not active:return
  assert time.monotonic()<active['deadline'],'Dialog deadline'
  for dialog in app.topLevelWidgets():
   if not isinstance(dialog,QDialog) or not dialog.isVisible() or any(dialog is old for old in seen):continue
   seen.append(dialog)
   assert calls==[], 'Power requested before the final decision'
   assert home.power_flow_open
   # Re-entrant clicks cannot open another flow or bypass this dialog.
   home.power('poweroff' if active['action']=='reboot' else 'reboot')
   assert dialog.width()<=active['width'] and dialog.height()<=active['height'],(dialog.windowTitle(),dialog.size())
   for button in dialog.findChildren(QPushButton):
    if not button.isVisible():continue
    point=button.mapTo(dialog,button.rect().topLeft());right=point.x()+button.width();bottom=point.y()+button.height()
    assert 0<=point.x() and 0<=point.y() and right<=dialog.width() and bottom<=dialog.height(),(dialog.windowTitle(),button.text(),'clipped button')
    option=QStyleOptionButton();option.initFrom(button);option.text=button.text()
    content=button.style().subElementRect(QStyle.SubElement.SE_PushButtonContents,option,button)
    assert button.fontMetrics().horizontalAdvance(button.text().replace('&',''))<=content.width(),(dialog.windowTitle(),button.text(),'clipped button text')
   index=len(active['dialogs']);active['dialogs'].append(dialog.windowTitle())
   dialog.grab().save(str(out/(active['name']+'-'+str(index)+'.png')))
   mode=active['mode']
   if isinstance(dialog,power_ui.CountdownDialog):
    assert dialog.remaining.text() in ('05:00','04:59')
    if mode.endswith('expire'):
     dialog.deadline=dialog.clock()-1;dialog.tick()
    elif mode.endswith('now'):dialog.now_button.click()
    elif mode.endswith('close'):dialog.close()
    elif mode.endswith('escape'):
     QApplication.sendEvent(dialog,QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Escape,Qt.KeyboardModifier.NoModifier))
    else:dialog.cancel_button.click()
   else:
    assert isinstance(dialog,QMessageBox)
    cancel=dialog.defaultButton();assert cancel is not None
    text=cancel.text().replace('&','')
    assert text in ('Cancel','Keep session open'),text
    if mode=='empty_cancel' or (mode=='first_cancel' and index==0) or (mode=='second_cancel' and index==1):cancel.click()
    else:
     if mode=='race_cancel' and index==0:occupied['value']=True
     proceed=next(b for b in dialog.buttons() if dialog.buttonRole(b)==QMessageBox.ButtonRole.AcceptRole)
     proceed.click()
 except Exception as exc:
  errors.append(repr(exc))
  for dialog in app.topLevelWidgets():
   if isinstance(dialog,QDialog) and dialog.isVisible():dialog.reject()

with patch.object(ui,'admin',side_effect=lambda action,request=None:calls.append(action) or {'ok':True}),patch.object(power_ui,'has_contents',side_effect=lambda:occupied['value']):
 home=ui.Home();home.timer.stop();home.wallet_inventory_timer.stop()
 home.start=lambda fn,success:success(fn())
 timer=QTimer();timer.timeout.connect(drive);timer.start(40)
 try:
  for width,height in ((800,600),(1366,768)):
   home._test_size=(width,height);home.fit_screen();home.show();app.processEvents()
   for action in ('reboot','poweroff'):
    for mode in ('empty_accept','empty_cancel','first_cancel','second_cancel','count_cancel','count_close','count_escape','count_now','count_expire','race_cancel'):
     calls.clear();seen.clear();errors.clear();occupied['value']=not mode.startswith('empty') and mode!='race_cancel'
     active={'name':f'{width}-{action}-{mode}','mode':mode,'action':action,'width':width,'height':height,'dialogs':[],'deadline':time.monotonic()+8}
     home.power(action)
     assert not errors,(active,errors)
     assert home.power_flow_open is False
     expected=action if mode in ('empty_accept','count_now','count_expire') else None
     assert calls==([expected] if expected else []),(active,calls)
     expected_count={'empty_accept':1,'empty_cancel':1,'first_cancel':1,'second_cancel':2,'race_cancel':4}.get(mode,3)
     assert len(active['dialogs'])==expected_count,active
     rows.append(dict(active,calls=list(calls)))
     active={};app.processEvents()
 finally:
  active={};timer.stop();home.hide()
(out/'result.json').write_text(json.dumps({'status':'passed','cases':rows},indent=2)+'\n')
print('PASS 40 actual Home flows: empty, populated, race, both warnings, cancel/Escape/close, now, expiry, re-entrant calls and 800x600/1366x768 layouts.')
