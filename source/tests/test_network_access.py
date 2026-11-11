import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import network_access as net

class NetworkTests(unittest.TestCase):
    def test_glib_preserves_unicode_network_names(self):
        # nmcli uses GLib output conversion; C locale replaces these characters.
        name = 'Pavao’s iPhone / Kuća'
        code = 'import locale,ctypes; locale.setlocale(locale.LC_ALL, ""); ctypes.CDLL("libglib-2.0.so.0").g_print(b"%s", '+repr(name)+'.encode("utf-8"))'
        result = net.run_command(['/usr/bin/python3','-c',code])
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.stdout,name)

    def test_escaped_names(self):
        self.assertEqual(net.fields(r'Office\: upstairs:back\\slash'),['Office: upstairs','back\\slash'])
    def test_scan_deduplicates_and_keeps_active(self):
        responses=['lo:loopback:connected:lo\nwlan0:wifi:disconnected:--','enabled',
            r':AA\:BB\:CC\:DD\:EE\:01:Office\: upstairs:90:WPA2:wlan0'+'\n'+
            r'*:AA\:BB\:CC\:DD\:EE\:02:Office\: upstairs:30:WPA2:wlan0'+'\n'+
            r':AA\:BB\:CC\:DD\:EE\:03::50:WPA2:wlan0']
        with patch.object(net,'nmcli',side_effect=responses):
            result=net.snapshot()
        self.assertFalse(result['connected'])
        self.assertEqual(len(result['aps']),1)
        self.assertTrue(result['aps'][0]['active'])
        self.assertEqual(result['aps'][0]['ssid'],'Office: upstairs')
    def test_ethernet_and_disabled_wifi(self):
        with patch.object(net,'nmcli',side_effect=['eth0:ethernet:connected:Wired\nwlan0:wifi:unavailable:--','disabled']) as call:
            result=net.snapshot()
        self.assertTrue(result['connected']);self.assertFalse(result['radio'])
        self.assertEqual(call.call_count,2)
    def test_no_adapter(self):
        with patch.object(net,'nmcli',side_effect=['lo:loopback:connected:lo','enabled']):
            result=net.snapshot()
        self.assertFalse(result['wifi']);self.assertFalse(result['connected'])
    def test_password_never_in_argv_or_error(self):
        secret='private-test-password'
        with patch.object(net,'run_command',return_value=subprocess.CompletedProcess([],1,secret,secret)) as call:
            with self.assertRaises(net.NetworkError) as error:net.connect({'ssid':'test'},secret)
        self.assertNotIn(secret,str(call.call_args.args))
        self.assertIn(secret,call.call_args.kwargs['input'])
        self.assertNotIn(secret,str(error.exception))
    def test_timeout_sanitized(self):
        with patch.object(net,'run_command',side_effect=subprocess.TimeoutExpired(['nmcli'],25)):
            with self.assertRaises(net.NetworkError):net.snapshot()

if __name__=='__main__':unittest.main()
