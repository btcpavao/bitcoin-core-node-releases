"""Fake-access-point and real GI profile tests; no live Wi-Fi credentials."""
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
import subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import gi
gi.require_version("NM","1.0")
from gi.repository import NM,GLib
import nm_connect as helper
import network_access as net

class FakeAP:
    def __init__(self,ssid,bssid,signal,flags,privacy=0):
        self.bytes=GLib.Bytes.new(ssid.encode('utf-8'))
        self.bssid=bssid;self.signal=signal;self.flags=flags;self.privacy=privacy
    def get_ssid(self):return self.bytes
    def get_bssid(self):return self.bssid
    def get_strength(self):return self.signal
    def get_rsn_flags(self):return self.flags
    def get_wpa_flags(self):return 0
    def get_flags(self):return self.privacy
    def get_path(self):return '/org/freedesktop/NetworkManager/AccessPoint/3'
    def connection_valid(self,record):return False

class FakeWifi:
    def __init__(self,access):self.access=access
    def get_access_points(self):return self.access

class HotspotTests(unittest.TestCase):
    def test_iphone_hotspot_bssid_changes_to_same_ssid_only(self):
        access=[FakeAP('Pavao’s iPhone','11:11:11:11:11:11',92,helper.SEC.KEY_MGMT_PSK),
                FakeAP('Other Network','22:22:22:22:22:22',100,helper.SEC.KEY_MGMT_PSK)]
        selected=helper.choose_access_point(FakeWifi(access),dict(ssid='Pavao’s iPhone',bssid='00:00:00:00:00:00',security='WPA2'))
        self.assertEqual(selected.get_bssid(),'11:11:11:11:11:11')
    def test_empty_or_changed_secure_ssid_rejected(self):
        access=FakeAP('Other Network','11:11:11:11:11:11',99,helper.SEC.KEY_MGMT_PSK)
        with self.assertRaisesRegex(helper.ConnectFailure,'not-visible'):
            helper.choose_access_point(FakeWifi([access]),dict(ssid='Pavao’s iPhone',bssid=access.get_bssid(),security='WPA2'))
        # Reject downgrade with either a changed or identical BSSID.
        for bssid in ('22:22:22:22:22:22','11:11:11:11:11:11'):
            open_ap=FakeAP('Pavao’s iPhone',bssid,98,0)
            with self.assertRaisesRegex(helper.ConnectFailure,'security'):
                helper.choose_access_point(FakeWifi([open_ap]),dict(ssid='Pavao’s iPhone',bssid='11:11:11:11:11:11',security='WPA2'))
    def test_real_nm_wpa2_wpa3_profiles_validate_without_live_access(self):
        ssid=GLib.Bytes.new(b'iPhone Hotspot')
        for label,flags,mode in [('wpa2',helper.SEC.KEY_MGMT_PSK,'wpa-psk'),
                                 ('wpa3',helper.SEC.KEY_MGMT_SAE,'sae'),
                                 ('transitional',helper.SEC.KEY_MGMT_PSK|helper.SEC.KEY_MGMT_SAE,'wpa-psk')]:
            with self.subTest(label=label):
                connection=helper.build_profile('iPhone Hotspot',ssid,flags,0,'synthetic-passphrase-not-a-secret')
                self.assertEqual(connection.get_setting_wireless_security().get_property('key-mgmt'),mode)
        with self.assertRaisesRegex(helper.ConnectFailure,'password-required'):
            helper.build_profile('iPhone Hotspot',ssid,helper.SEC.KEY_MGMT_PSK,0,'short')
    def test_distinct_failure_messages_and_no_secret_leak(self):
        secret='super-private-synthetic-PSK'
        for code in ('authentication','not-visible','security','permission','timeout','adapter','network','unknown'):
            response=subprocess.CompletedProcess([],1,'private',f'NODE-WIFI-ERROR:{code}\n')
            with patch.object(net,'run_command',return_value=response):
                with self.assertRaises(net.NetworkError) as e:
                    net.connect(dict(ssid='Pavao iPhone',bssid='08:00:20:00:00:00',device='wlan0',security='WPA2'),secret)
            self.assertNotIn(secret,str(e.exception))
            self.assertNotIn('private',str(e.exception))
        with patch.object(net,'run_command',return_value=subprocess.CompletedProcess([],1,'',secret)):
            with self.assertRaises(net.NetworkError) as e:
                net.connect(dict(ssid='Pavao iPhone',device='wlan0'),secret)
            self.assertNotIn(secret,str(e.exception))
    def test_code_mapping_from_nm_errors(self):
        self.assertEqual(helper.error_from_network_manager('Not authorized to control networking'),'permission')
        self.assertEqual(helper.error_from_network_manager('No secrets were provided'),'authentication')
        self.assertEqual(helper.error_from_network_manager('Supplicant config failed'),'security')
        self.assertEqual(helper.error_from_network_manager('timed out'),'timeout')
        self.assertEqual(helper.reason_from_device(type('D',(),{'get_state_reason':lambda self:NM.DeviceStateReason.NO_SECRETS})()),'authentication')
    def test_never_publishes_unapproved_error_details(self):
        self.assertEqual(helper.ConnectFailure('secret=abcdef').code,'unknown')
        self.assertTrue(all(s in helper.CODES for s in ('adapter','permission','authentication','security')))

if __name__=='__main__':unittest.main(verbosity=2)
