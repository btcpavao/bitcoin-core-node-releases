"""UI/guide contracts without live wallets, physical media or changing host settings."""
import json,os,runpy,sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'app'))
from PySide6.QtWidgets import QApplication,QDialog,QPlainTextEdit
from PySide6.QtCore import Qt
from core_details_ui import TechnicalDetailsDialog
from core_status_ui import CoreStatusDialog
from modeless import open_window
from media_file_dialog import MediaFileDialog
import media_file_dialog as media
from guide_ui import SECTIONS,SECTION_ICONS,Guide
from guide_visuals import render_visual
APP=QApplication.instance() or QApplication([])

class Details(unittest.TestCase):
    def test_opens_independent_searchable_window_not_inline_scroll(self):
        owner=QDialog();d=CoreStatusDialog(owner,autostart=False);d.apply(dict(available=False,service='inactive',updated=0))
        first=d.show_details();second=d.show_details()
        self.assertIs(first,second);self.assertIsNone(first.parent());self.assertFalse(first.isModal())
        self.assertNotIn(first.raw,d.findChildren(QPlainTextEdit));self.assertEqual(first.tabs.count(),2)
        d.reject();self.assertTrue(first.isVisible());first.reject();APP.processEvents()
        self.assertNotIn('core-technical-details',owner._modeless_windows)
    def test_tree_filter_snapshot_not_replaced_without_refresh(self):
        d=TechnicalDetailsDialog(dict(available=True,chain={'blocks':42},net={'connections':3},updated=0))
        d.search.setText('blocks');APP.processEvents()
        visible=[d.tree.topLevelItem(i).text(0) for i in range(d.tree.topLevelItemCount()) if not d.tree.topLevelItem(i).isHidden()]
        self.assertEqual(visible,['Blockchain']);self.assertIn('42',d.raw.toPlainText());d.reject()
    def test_details_fits_compact_window(self):
        d=TechnicalDetailsDialog();d.resize(800,600);d.show();APP.processEvents()
        self.assertLessEqual(d.width(),800);self.assertLessEqual(d.height(),600);d.reject()

class Media(unittest.TestCase):
    def drive(self,**changes):
        return dict(path='/dev/sdb1',label='TEST USB',bytes=1024**3,fstype='exfat',uuid='fixture',read_only=False,mount=None,**changes)
    def test_external_media_list_and_no_mount_without_click(self):
        d=MediaFileDialog(autostart=False)
        with patch.object(d,'run_utility') as run:
            d.render_places([self.drive()]);run.assert_not_called()
        labels=[d.places.item(i).text() for i in range(d.places.count())]
        self.assertIn('USB / External media',labels);self.assertTrue(any('TEST USB' in t for t in labels))
        item=next(d.places.item(i) for i in range(d.places.count()) if d.places.item(i).data(Qt.UserRole)==('drive','/dev/sdb1'))
        with patch.object(d,'scan') as scan:d.visit(item);scan.assert_called_once()
        self.assertEqual(d.pending['uuid'],'fixture');d.reject()
    def test_readonly_drive_is_valid_input_but_not_save_target(self):
        for saving in (False,True):
            d=MediaFileDialog(autostart=False,saving=saving);entry=self.drive();entry['read_only']=True;d.render_places([entry])
            item=next(d.places.item(i) for i in range(d.places.count()) if d.places.item(i).data(Qt.UserRole)==('drive','/dev/sdb1'))
            with patch.object(d,'scan') as scan:d.visit(item);self.assertEqual(scan.call_count,0 if saving else 1)
            if saving:self.assertIn('read-only',d.media_status.text())
            d.reject()
    def test_mount_is_revalidated_and_removed_device_never_selected(self):
        d=MediaFileDialog(autostart=False);d.pending=self.drive();p=Mock();d.worker=p
        with patch.object(d,'read_output'),patch.object(d,'stop_worker',side_effect=lambda:setattr(d,'worker',None)),patch.object(media,'parse_lsblk',return_value=[]),patch.object(d,'setDirectory') as select:
            d.completed(p,'scan',0);select.assert_not_called()
        self.assertIsNone(d.pending);self.assertIn('removed',d.media_status.text());d.reject()
    def test_timer_and_process_stopped_on_close(self):
        d=MediaFileDialog(autostart=False);d.timer.start();d.done(QDialog.Rejected)
        self.assertFalse(d.timer.isActive());self.assertTrue(d.closed)
    def test_crypto_call_sites_use_new_picker_without_changing_decryption_ram_policy(self):
        crypto=(R/'app/file_crypto.py').read_text();password=(R/'app/password_dialog.py').read_text()
        self.assertIn('choose_media_file',crypto);self.assertIn('choose_media_file',password)
        self.assertIn('policy.check_storage()',crypto)
    def test_media_picker_fits_800px(self):
        d=MediaFileDialog(autostart=False);d.resize(800,600);d.show();APP.processEvents()
        self.assertLessEqual(d.width(),800);d.reject()

class GuideContents(unittest.TestCase):
    def test_current_backup_workflows_and_no_stale_restart_claim(self):
        text=' '.join(SECTIONS.values())
        for required in ['Node configuration','Core configuration','Watch-only backups','Blockchain backup','Encrypt & Decrypt Files','Status & diagnostics']:self.assertIn(required,SECTIONS)
        for phrase in ['Restore on next restart','Encrypt backup (optional)','PSBT Transfer Folder','Check pending restore']:
            self.assertIn(phrase,text)
        self.assertNotIn('Core starts again if it was running.',text)
        self.assertNotIn('<b>Public Wallet Transfer</b>',text)
        self.assertIn('Core remains stopped',SECTIONS['Blockchain backup'])
    def test_all_sections_have_local_icons_and_measured_visuals(self):
        assets=R/'runtime/usr/share/bitcoin-core-node'
        for name in SECTIONS:
            self.assertTrue((assets/SECTION_ICONS[name]).is_file(),name)
            for width in (490,960):
                svg,w,h,title,description,image=render_visual(name,width)
                self.assertTrue(title and description);self.assertGreater(h,0);self.assertFalse(image.isNull())
    def test_static_html_and_plain_text_include_new_chapters(self):
        html=(R/'runtime/usr/share/bitcoin-core-node/GUIDE.html').read_text();plain=(R/'runtime/usr/share/bitcoin-core-node/GUIDE.txt').read_text()
        for name in ['Node configuration','Watch-only backups','Core configuration','Blockchain backup']:
            self.assertIn(name,html);self.assertIn(name,plain)
        self.assertIn('HTTP 503',plain);self.assertIn('USB / External media',plain)
    def test_sidebar_floor_and_preserves_wider_preference(self):
        namespace=runpy.run_path(str(R/'runtime/usr/local/bin/core-node-file-places'))
        for current in (100,280,360):
            writes=[]
            def query(args):
                if args==['-l']:return '/last-separator-position'
                if args==['-p','/last-separator-position']:return str(current)
                writes.append(args);return ''
            self.assertEqual(namespace['ensure_sidebar_width'](query),max(320,current))
            self.assertEqual(len(writes),int(current<320))

if __name__=='__main__':unittest.main()
