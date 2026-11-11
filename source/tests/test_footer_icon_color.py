"""Protect the original Vault power artwork and clear USB-network button glyph.

The Nov 3 ImageMagick SVG→PNG path silently flattened icons to dark outlines.
This checks the final bundled PNG pixels and the actual QIcon pixmaps used
in the GUI so a future remaster cannot ship the broken empty-ring versions.
"""
import hashlib
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon, QImage
from PySide6.QtCore import QSize

ROOT=Path(__file__).resolve().parents[1]
ICONS=ROOT/'runtime/usr/share/bitcoin-core-node/icons'

APP=None
def application():
    global APP
    APP=QApplication.instance() or APP or QApplication(['node-icon-qa'])
    return APP

class PowerAndNetworkIcons(unittest.TestCase):
    def test_exact_vault_blue_red_original_svg_sources(self):
        # The original artwork source must remain the same as the working
        # Vault. Runtime PNG is a high-fidelity rendering of these assets.
        originals={'system-reboot.svg':'adb5fcda8ef29b73de9e24481c1f439a92c29c8fa5952ae1a5c225f8a86da1df',
                   'system-shutdown.svg':'6591117fa3fa622a1214f7fca180e39b138aeffca11cbef4913b5bfa0ba95144'}
        for name,sha in originals.items():
            with self.subTest(name=name):
                with (ICONS/name).open('rb') as source:
                    self.assertEqual(hashlib.file_digest(source,'sha256').hexdigest(),sha)

    def test_raster_has_opaque_colored_body_not_old_black_circle(self):
        for name,expected in (('network-status','white'),('system-reboot','blue'),('system-shutdown','red')):
            image=QImage(str(ICONS/(name+'.png')))
            with self.subTest(name=name):
                self.assertFalse(image.isNull())
                self.assertEqual((image.width(),image.height()),(192,192))
                self.assertEqual(image.pixelColor(0,0).alpha(),0)
                self.assertEqual(image.pixelColor(191,191).alpha(),0)
                r,g,b=image.pixelColor(96,96).red(),image.pixelColor(96,96).green(),image.pixelColor(96,96).blue()
                if expected=='white':
                    self.assertTrue(min(r,g,b)>220,(name,r,g,b))
                elif expected=='blue':
                    self.assertTrue(b>200 and b>r+80,(name,r,g,b))
                else:
                    self.assertTrue(r>140 and r>g+65,(name,r,g,b))
                # Central circle must be colorful (or contain white artwork).
                # Previous broken PNG filled almost all central pixels black.
                samples=[image.pixelColor(x,y) for y in range(55,135,5)
                                                  for x in range(55,135,5)]
                colored=sum(1 for c in samples if c.alpha()>190 and
                            (max(c.red(),c.green(),c.blue())>130))
                self.assertGreater(colored,100,(name,'insufficient colored area',colored))

    def test_qt_button_icon_pixmaps_remain_visible_at_t550_scales(self):
        application()
        for scale in (44,48,64):
            for name in ('network-status','system-reboot','system-shutdown'):
                with self.subTest(size=scale,name=name):
                    icon=QIcon(str(ICONS/(name+'.png')))
                    self.assertFalse(icon.isNull())
                    output=icon.pixmap(QSize(scale,scale)).toImage()
                    self.assertFalse(output.isNull())
                    cx=output.pixelColor(scale//2,scale//2)
                    self.assertGreater(cx.alpha(),230)
                    if name=='network-status':
                        self.assertGreater(min(cx.red(),cx.green(),cx.blue()),200,
                                           'White network topology must be visible on button')
                    elif name=='system-reboot':
                        self.assertGreater(cx.blue(),cx.red()+70)
                    else:
                        self.assertGreater(cx.red(),cx.green()+60)

if __name__=='__main__': unittest.main(verbosity=2)
