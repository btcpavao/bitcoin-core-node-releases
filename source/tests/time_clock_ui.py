#!/usr/bin/python3
"""Real Qt interaction/layout checks; privileged time commands are intercepted."""
import json,os,sys,time
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtCore import QDate,QTime,QDateTime,Qt,QPoint
from PySide6.QtWidgets import QApplication,QLabel,QPushButton
import ui,time_ui
from launcher_ui import NodeSettingsDialog,ToolCard
from wallets import WalletError
app=QApplication([]);ui.configure_ui(app);app.setQuitOnLastWindowClosed(False)
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
state=dict(timezone='UTC',automatic=True,synchronized=False,can_automatic=True)
checks=[]
def wait(condition,seconds=5):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  app.processEvents()
  if condition():return
  time.sleep(.01)
 raise AssertionError('UI deadline')
with patch('ui.CoreRPC'):
 home=ui.Home();home.timer.stop();home.wallet_inventory_timer.stop();home.show()
for state_name in ('stopped','syncing','synchronized','stopped')*4:
 value=(state_name,'Synthetic '+state_name,False)
 with patch('ui.node_activity',return_value=value):
  home.poll_activity();wait(lambda:home.activity_job is None)
  assert home.activity_text.text()==value[1]
for available in (False,True,False,True)*3:
 with patch('ui.watch_only_wallets_present',return_value=available):
  home.poll_wallets();wait(lambda:home.wallet_inventory_job is None)
  assert home.watch_only_available is available
checks.append('repeated Core activity and wallet worker completion keeps polling alive; GUI-thread cleanup precedes deletion')
for active in (False,True):
 home.show_activity(('syncing' if active else 'stopped','Blockchain download and validation in progress' if active else 'Bitcoin Core is stopped.',False))
 for wallet in (False,True):
  home.set_watch_only_available(wallet)
  for width,height in ((800,600),(1024,768),(1280,720),(1366,768),(1920,1080)):
   home._test_size=(width,height);home.fit_screen()
   for _ in range(15):app.processEvents();home.layout_cards()
   assert home.clock.isVisible()
   point=home.clock.mapTo(home,QPoint(0,0))
   assert point.y()>=0 and point.y()>=home.footer.y() and point.y()+home.clock.height()<=home.footer.y()+home.footer.height()
   if active:
    end=home.activity_row.mapTo(home,QPoint(0,home.activity_row.height()))
    assert point.y()>=end.y()
   connection=home.connection_button.mapTo(home,QPoint(0,0))
   network=home.network_button.mapTo(home,QPoint(0,0))
   credit=home.credit_box.mapTo(home,QPoint(0,0))
   # Right footer stack: Core status first, then clock, then three controls.
   assert credit.x()+home.credit_box.width()<=network.x()
   assert abs(credit.x()+home.credit_box.width()/2-home.width()/2)<=1
   assert home.connection_button.text().replace('\n',' ') in (
       'Checking Bitcoin Core','Bitcoin Core is offline','Bitcoin Core is online',
       'Bitcoin Core is starting','Bitcoin Core error')
   assert connection.y()<point.y()<network.y()
   assert connection.x()+home.connection_button.width()<=home.width()-home.outer.contentsMargins().right()
   assert point.x()+home.clock.width()<=home.width()-home.outer.contentsMargins().right()
   restart=home.restart_button.mapTo(home,QPoint(0,0))
   shutdown=home.shutdown_button.mapTo(home,QPoint(0,0))
   assert network.y()==restart.y()==shutdown.y()
   assert network.x()<restart.x()<shutdown.x()
   group_center=(network.x()+shutdown.x()+home.shutdown_button.width())/2
   footer_center=home.power_box.mapTo(home,QPoint(0,0)).x()+home.power_box.width()/2
   assert abs(group_center-footer_center)<=1
   status_center=connection.x()+home.connection_button.width()/2
   clock_center=point.x()+home.clock.width()/2
   assert abs(status_center-footer_center)<=1
   assert abs(clock_center-footer_center)<=1
   assert home.clock.width() >= (
       home.clock.fontMetrics().horizontalAdvance(home.clock.text())+
       home.clock.iconSize().width()+40)
   assert home.scroll.verticalScrollBar().maximum()==0
   home.grab().save(str(out/f'home-{width}x{height}-active-{active}-wallet-{wallet}.png'))
checks.append('clock visible before/after Core; all wallet/layout states fit without scrolling or overlap')
with patch('time_ui.DateTimeDialog') as dialog:
 home.clock.click();dialog.assert_called_once_with(home);dialog.return_value.exec.assert_called_once()
 settings=NodeSettingsDialog(home);settings.show();app.processEvents()
 card=next(b for b in settings.findChildren(ToolCard) if b.accessibleName()=='Date & Time')
 card.click();assert settings.selected_action==home.date_time
 assert settings.isVisible() and dialog.call_count==2
 settings.reject()
checks.append('clock and Node Settings route to the same Date & Time dialog')
with patch.object(time_ui,'datetime') as clock:
 clock.now.return_value=datetime(2026,10,30,12,59,tzinfo=timezone.utc);home.clock.refresh();before=home.clock.text()
 clock.now.return_value=datetime(2026,10,30,13,0,tzinfo=timezone.utc);home.clock.refresh();assert before!=home.clock.text()
checks.append('minute rollover updates the Home clock')
for width,height in ((800,600),(1024,768),(1366,768)):
 with patch.object(time_ui,'snapshot',return_value=state):
  dialog=time_ui.DateTimeDialog(home);dialog.resize(min(610,width),min(520,height));dialog.show();wait(lambda:dialog.loaded and dialog.job is None)
  assert dialog.width()<=width and dialog.height()<=height,(dialog.width(),dialog.height(),width,height)
  for widget in dialog.findChildren(QPushButton)+dialog.findChildren(QLabel):
   if widget.isVisible():
    pos=widget.mapTo(dialog,QPoint(0,0));assert pos.y()>=0 and pos.y()+widget.height()<=dialog.height(),widget.objectName()
  dialog.grab().save(str(out/f'time-auto-{width}x{height}.png'))
  dialog.timezone.setCurrentText('Europe/Zagreb');dialog.automatic.setChecked(False)
  assert dialog.manual.isEnabled()
  dialog.manual.setDateTime(QDateTime(QDate(2026,10,30),QTime(14,35,0),Qt.UTC))
  result=dict(ok=True,time=dict(state,timezone='Europe/Zagreb',automatic=False))
  with patch('ui.admin',return_value=result) as admin:
   dialog.apply.click();wait(lambda:dialog.saved and dialog.job is None)
   admin.assert_called_once_with('time-settings',dict(timezone='Europe/Zagreb',automatic=False,local_time='2026-10-30 14:35:00'))
  assert dialog.feedback.text()=='Date and time settings saved.'
  dialog.grab().save(str(out/f'time-manual-{width}x{height}.png'))
  dialog.manual.setDateTime(QDateTime(QDate(2026,3,29),QTime(2,30),Qt.UTC))
  with patch('ui.admin') as admin:
   dialog.apply.click();admin.assert_not_called();assert 'skipped' in dialog.feedback.text()
  dialog.manual.setDateTime(QDateTime(QDate(2026,10,30),QTime(14,35),Qt.UTC))
  with patch('ui.admin',side_effect=WalletError('Synthetic authorization cancelled')):
   dialog.apply.click();wait(lambda:not dialog.busy and dialog.job is None)
   assert dialog.back.isEnabled() and 'cancelled' in dialog.feedback.text()
  dialog.reject()
checks.append('automatic/manual forms, strict DST validation, async Apply and failure recovery at supported sizes')
with patch.object(time_ui,'snapshot',side_effect=lambda:(time.sleep(.2),state)[1]):
 dialog=time_ui.DateTimeDialog(home);dialog.show();app.processEvents();job=dialog.job
 dialog.reject();assert not dialog.isVisible();wait(lambda:dialog.job is None)
checks.append('closing while read-only status loads leaves the UI responsive and worker alive until completion')
home.clock.timer.stop();home.hide()
(out/'result.json').write_text(json.dumps(dict(status='passed',checks=checks),indent=2)+'\n')
print('PASS '+json.dumps(checks),flush=True)
