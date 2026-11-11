"""Density detection and bounds: synthetic displays, no host desktop changes."""
from pathlib import Path
import runpy
import unittest
ROOT=Path(__file__).resolve()
# Same tests live in both product trees.
if ROOT.parent.name == 'tests':
    HELPER=ROOT.parents[1]/'runtime/usr/local/bin/core-display-scale'
else:
    HELPER=ROOT.parent/'runtime-template/usr/local/bin/core-display-scale'
mod=runpy.run_path(str(HELPER),run_name='display_test_module')
choose,displays=mod['choose'],mod['displays']

def screen(w=1920,h=1080,mw=344,mh=194,name='eDP-1',primary=True):
    return displays(f"{name} connected {'primary ' if primary else ''}{w}x{h}+0+0 (normal) {mw}mm x {mh}mm")[0]

class DisplayScale(unittest.TestCase):
    def test_laptop_densities(self):
        for w,h,expected in [(1366,768,1),(1600,900,1.25),(1920,1080,1.5),(3840,2160,3)]:
            with self.subTest(width=w):
                result=choose([screen(w,h)])
                self.assertEqual(result['scale'],expected)
                self.assertGreaterEqual(result['logical_size'][0],800)
                self.assertGreaterEqual(result['logical_size'][1],600)

    def test_large_monitor_not_enlarged_by_resolution_alone(self):
        self.assertEqual(choose([screen(mw=531,mh=299,name='HDMI-1')])['scale'],1)
        self.assertEqual(choose([screen(mw=0,mh=0,name='HDMI-1')])['scale'],1)

    def test_missing_and_broken_edid(self):
        for mw,mh in [(0,0),(1,1),(1000,194)]:
            self.assertEqual(choose([screen(mw=mw,mh=mh)])['scale'],1.5)
        self.assertEqual(choose([])['scale'],1)

    def test_small_output_caps_session_scale(self):
        self.assertEqual(choose([screen(),screen(800,600,0,0,'HDMI-1',False)])['scale'],1)
        self.assertEqual(choose([screen(1024,768,180,135)])['scale'],1.25)

    def test_primary_output_and_disabled_outputs(self):
        outputs=displays('eDP-1 connected 1920x1080+0+0 (normal) 344mm x 194mm\nHDMI-1 connected primary 1920x1080+1920+0 (normal) 531mm x 299mm\nDP-1 disconnected\nDP-2 connected (normal)')
        self.assertEqual(len(outputs),2)
        self.assertEqual(choose(outputs)['scale'],1)
        self.assertEqual(choose(outputs)['output']['name'],'HDMI-1')

    def test_manual_and_invalid_preferences(self):
        self.assertEqual(choose([screen()], '1.25')['scale'],1.25)
        for value in ['0','4','nan','inf','$(bad)','']:
            with self.subTest(value=value),self.assertRaises(ValueError):
                choose([screen()],value)

if __name__=='__main__':
    unittest.main()
