import os,sys,runpy,json
from pathlib import Path
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication,QLabel
from PySide6.QtGui import QFont
from PySide6.QtCore import QPoint
app=QApplication([]);app.setStyle('Fusion');app.setFont(QFont('DejaVu Sans',10))
out=Path(sys.argv[2]);out.mkdir(exist_ok=True)
product=sys.argv[1]
root=Path(__file__).resolve().parents[1 if product=='node' else 2]
if product=='node':
 sys.path.insert(0,str(root/'app'))
 import ui
 ui.configure_ui(app)
 with patch('ui.CoreRPC'):
  home=ui.Home();home.timer.stop();home.wallet_inventory_timer.stop()
else:
 with patch.object(sys,'argv',['core-vault-home','--self-test','--assets',str(root/'config/includes.chroot/usr/share/core-vault')]):
  home=runpy.run_path(str(root/'tools/core-vault/runtime-template/usr/local/bin/core-vault-home'),run_name='test_fit')['VaultHome']()
failures=[]
for product,home in [(product,home)]:
 home.show()
 for wallet in [False,True,False,True]:
  home.set_watch_only_available(wallet)
  for width,height in [(800,600),(1024,768),(1280,720),(1366,768),(1920,1080)]:
   for active in ([False,True] if product=='node' else [False]):
    if product=='node':
     home.activity_seen=active
     home.show_activity(('syncing' if active else 'stopped','Blockchain download and validation in progress · 25.00%' if active else 'Bitcoin Core is stopped.',False))
    home._test_size=(width,height);home.fit_screen()
    for _ in range(20):app.processEvents();home.layout_cards()
    row=dict(product=product,wallet=wallet,width=width,height=height,active=active,density=home._home_density,card=[home.cards[0].width(),home.cards[0].height()],viewport=home.scroll.viewport().height(),body=home.body.height(),scroll=home.scroll.verticalScrollBar().maximum())
    print(json.dumps(row),flush=True)
    if row['scroll'] or home.scroll.horizontalScrollBar().maximum():failures.append(row)
    for card in home.cards:
     for label in [card.icon_label,card.title_label,card.description_label]:
      pos=label.mapTo(card,QPoint(0,0))
      if pos.y()<0 or pos.y()+label.height()>card.height():failures.append(dict(row,clipped=card.tool['title']))
     point=card.mapTo(home,QPoint(0,card.height()))
     if point.y()>home.footer.y():failures.append(dict(row,footer_overlap=card.tool['title']))
    home.grab().save(str(out/f'{product}-{width}x{height}-wallet-{wallet}-active-{active}.png'))
 home.hide()
assert not failures,failures
print('PASS: all Home states fit vertically and horizontally, with visible card contents and footer.')
