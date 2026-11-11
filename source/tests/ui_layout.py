#!/usr/bin/python3
"""Render native layout fixtures without connecting to a user's Bitcoin Core."""
import argparse
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from PySide6.QtWidgets import QApplication
from ui import Home, PrivacyDialog, STYLE, configure_ui
from state import SetupError
from wallet_ui import WalletDialog
from update_ui import UpdatesDialog
from login_ui import LoginDialog
from launcher_ui import NodeSettingsDialog
from guide_ui import Guide, SECTIONS

parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
app=QApplication([]);configure_ui(app)
class RPC:
    def __call__(self,method,*params,**kwargs):
        if method=='listwallets':return []
        raise RuntimeError('Layout fixture has no Bitcoin RPC connection.')

failures=[]
with patch('ui.load_setup',side_effect=SetupError('Unconfigured layout fixture')):
    home=Home();home.timer.stop();home.wallet_inventory_timer.stop();home.set_watch_only_available(True);home.rpc=RPC()
    for width,height in [(800,600),(1280,800)]:
        widgets=[('home',home),('privacy-clearnet',PrivacyDialog()),('privacy-vpn',PrivacyDialog())]
        widgets[-1][1].profile.setCurrentIndex(2)
        widgets += [(cls.__name__,cls(home)) for cls in (WalletDialog,UpdatesDialog,LoginDialog,NodeSettingsDialog)]
        for name,widget in widgets:
            if widget is home: widget._test_size=(width,height);widget.fit_screen()
            widget.resize(width,height);widget.show()
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                app.processEvents()
                job=getattr(widget,'job',None)
                if not job or not job.isRunning():
                    app.processEvents();break
                time.sleep(.02)
            if widget.width()>width or widget.height()>height:
                failures.append((name,width,height,widget.width(),widget.height()))
            widget.grab().save(str(args.output/(name+'-'+str(width)+'x'+str(height)+'.png')))
            widget.hide()
            if widget is not home:widget.close()
    # Exercise the actual reader, including first open, the sidebar breakpoint,
    # chapter changes and shrinking an already rendered wide illustration.
    guide=Guide(home)
    for width,height in [(800,600),(1000,700),(1024,768),(1280,800),(800,600)]:
        guide.resize(width,height);guide.show()
        for row,section in enumerate(SECTIONS):
            guide.nav.setCurrentRow(row)
            deadline=time.monotonic()+.2
            while time.monotonic()<deadline:
                app.processEvents();time.sleep(.01)
            assert guide.width()<=width and guide.height()<=height, (section,'dialog overflow')
            assert guide.viewer.horizontalScrollBar().maximum()==0, (section,width,'reader overflow')
            assert guide.nav.horizontalScrollBar().maximum()==0, (section,width,'sidebar overflow')
            assert guide.nav.isVisible()==(width>=1000), (width,'chapter navigation')
            assert guide.current_description, (section,'missing illustration description')
            guide.grab().save(str(args.output/('guide-'+str(row)+'-'+str(width)+'x'+str(height)+'.png')))
    guide.close()
    home.close()
if failures:raise SystemExit('Layout overflow: '+repr(failures))
print(f'PASS native Home, privacy and wallet layouts; all {len(SECTIONS)} Guide chapters have no horizontal overflow at 800, 1000, 1024 and 1280 pixels, including resize. Images: '+str(args.output))
