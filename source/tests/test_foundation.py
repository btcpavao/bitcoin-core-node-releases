"""Boundary tests. Kernel/VM acceptance is separate and mandatory for release."""
import base64
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from state import validate_setup,load_setup,SetupError,core_arguments
from network import wireguard,NetworkError,firewall,core_config

DEFAULT={'version':1,'confirmed':True,'profile':'clearnet','network':'main',
         'prune_mib':0,'data_uuid':None,'private_broadcast':False}
KEY=base64.b64encode(b'\x42'*32).decode()
WG=f'[Interface]\nPrivateKey = {KEY}\nAddress = 10.8.0.2/32\nDNS = 10.8.0.1\n\n[Peer]\nPublicKey = {KEY}\nAllowedIPs = 0.0.0.0/0\nEndpoint = 192.0.2.2:51820\n'


class Foundation(unittest.TestCase):
    def test_setup_requires_explicit_confirmation_and_fixed_fields(self):
        self.assertEqual(validate_setup(DEFAULT),DEFAULT)
        for field,value in [('confirmed',False),('confirmed',1),('version',True),('profile','automatic'),
                            ('prune_mib',1),('prune_mib',True),('data_uuid','../../other'),('network','custom')]:
            with self.subTest(field=field,value=value),self.assertRaises(SetupError):
                validate_setup({**DEFAULT,field:value})
        with self.assertRaises(SetupError):validate_setup({**DEFAULT,'arbitrary_config':'/tmp/bitcoin.conf'})

    def test_config_permission_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'setup.json';path.write_text(json.dumps(DEFAULT));path.chmod(0o600)
            self.assertEqual(load_setup(path,require_root=False),DEFAULT)
            path.chmod(0o666)
            with self.assertRaises(SetupError):load_setup(path,require_root=False)
            path.chmod(0o600);link=Path(temp)/'link';link.symlink_to(path)
            with self.assertRaises(SetupError):load_setup(link,require_root=False)

    def test_wireguard_scripts_and_unsupported_values_rejected(self):
        clean,endpoint,port=wireguard(WG)
        self.assertEqual(str(endpoint),'192.0.2.2');self.assertEqual(port,51820)
        self.assertEqual(wireguard(clean)[0],clean)
        for bad in [WG.replace('Address =','PostUp = touch /tmp/unsafe\nAddress ='),
                    WG.replace('Endpoint = 192.0.2.2','Endpoint = vpn.example.org'),
                    WG.replace('0.0.0.0/0','10.0.0.0/8'),WG.replace('51820','0'),
                    WG.replace('DNS = 10.8.0.1','DNS = 2001:db8::53'),
                    WG+'\n[Peer]\nPublicKey = '+KEY,WG.replace(KEY,'invalid',1)]:
            with self.subTest(),self.assertRaises(NetworkError):wireguard(bad)

    def test_tor_and_vpn_have_distinct_scope_and_no_established_output_bypass(self):
        _,endpoint,port=wireguard(WG)
        tor=firewall('tor',62000)
        self.assertIn('meta skuid 62000 reject',tor)
        vpn=firewall('wireguard',62000,endpoint,port)
        output=vpn.split('chain output',1)[1]
        self.assertNotIn('established',output)
        self.assertIn('policy drop',output)
        self.assertIn('oifname "core-node" accept',output)
        self.assertNotIn('udp dport 53 accept',output)
        with self.assertRaises(NetworkError):firewall('wireguard',62000)
        with self.assertRaises(NetworkError):firewall('unknown',62000)

    def test_core_policies_use_loopback_cookie_and_explicit_privacy(self):
        args=core_arguments(DEFAULT)
        self.assertIn('-rpcbind=127.0.0.1',args)
        self.assertIn('-settings=/var/lib/bitcoin-core-node/data/settings.json',args)
        self.assertNotIn('-rpcbind=0.0.0.0',args)
        tor=core_config({**DEFAULT,'profile':'tor'})
        self.assertIn('onlynet=onion',tor);self.assertIn('dns=0',tor)
        direct=core_config(DEFAULT)
        self.assertNotIn('proxy=',direct)
        private=core_config({**DEFAULT,'private_broadcast':True})
        self.assertIn('onion=127.0.0.1:9050',private)


if __name__=='__main__':unittest.main()
