"""Portable settings schema, native NM, path guards and actual GnuPG round trips."""
import copy,json,os,sys,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import settings_snapshot as s
import settings_restore as r

WIFI='''[connection]
id=Fixture Network
uuid=75fd6c44-f5bf-4d88-9714-256b511aba38
type=wifi
interface-name=wlan-source
permissions=user:old-user:;
[wifi]
mode=infrastructure
ssid=Fixture Network
mac-address=00:11:22:33:44:55
bssid=00:11:22:33:44:56
[wifi-security]
key-mgmt=wpa-psk
psk=synthetic-wifi-password-for-tests
[ipv4]
method=auto
[ipv6]
method=auto
'''
WG='[Interface]\nPrivateKey = '+('A'*43+'=')+'\nAddress = 10.73.0.2/32\nDNS = 9.9.9.9\n\n[Peer]\nPublicKey = '+('B'*42+'A=')+'\nAllowedIPs = 0.0.0.0/0\nEndpoint = 203.0.113.7:51820\n'

def payload():
    return dict(format=s.FORMAT,version=1,created_utc='2026-11-06T12:00:00Z',core_version='32.1',
                node=dict(profile='clearnet',network='main',prune_mib=0,private_broadcast=False),
                wireguard=None,clock=dict(timezone='Europe/Zagreb',automatic=True),
                keyboard=dict(XKBMODEL='pc105',XKBLAYOUT='hr',XKBVARIANT='',XKBOPTIONS=''),
                display_scale='auto',pointer={'Fixture Mouse':0.35},core={'dbcache':'256'},
                core_gui={'fCoinControlFeatures':'true'},connections=[s.nm_profile(WIFI)],not_included=list(s.EXCLUSIONS))

class PortableSchema(unittest.TestCase):
    def test_native_nm_keeps_secret_and_removes_physical_identity(self):
        p=s.nm_profile(WIFI)
        self.assertEqual(p['type'],'wifi');self.assertFalse(p['needs_secret'])
        self.assertIn('synthetic-wifi-password-for-tests',p['keyfile'])
        for value in ('wlan-source','00:11:22:33:44:55','00:11:22:33:44:56','old-user'):
            self.assertNotIn(value,p['keyfile'])
        self.assertEqual(s.nm_profile(p['keyfile']),p)

    def test_no_secret_yet_is_reported(self):
        self.assertTrue(s.nm_profile(WIFI.replace('psk=synthetic-wifi-password-for-tests\n',''))['needs_secret'])

    def test_external_certificate_and_vpn_plugin_refused(self):
        for group in ('802-1x','vpn','proxy','wireguard','user'):
            with self.subTest(group=group),self.assertRaises(s.SettingsError):s.nm_profile(WIFI+'\n['+group+']\nfoo=bar\n')

    def test_invalid_profile_does_not_leak_secret(self):
        with self.assertRaises(s.SettingsError) as error:s.nm_profile(WIFI.replace('type=wifi','type=unsupported'))
        self.assertNotIn('synthetic-wifi-password',str(error.exception))

    def test_semantic_payload_roundtrip_and_explicit_exclusions(self):
        data=payload();self.assertEqual(s.validate(s.json_load(s.canonical(data))),data)
        self.assertIn('Login password',s.summary(data)['not_included'][1])

    def test_never_accept_arbitrary_files_or_account_database(self):
        for key in ('files','shadow','wallets','script','datadir','hostname','machine_id'):
            data=payload();data[key]='/etc/shadow'
            with self.subTest(key=key),self.assertRaises(s.SettingsError):s.validate(data)

    def test_validation_rejects_unsupported_or_injected_values(self):
        cases=[('format','bad'),('version',True),('core_version','999.1'),('display_scale','$(id)'),
               ('pointer',{'Mouse':float('nan')}),('core',{'walletnotify':'touch /tmp/evil'}),
               ('core_gui',{'language':'\nstrDataDir=/tmp'}),('connections',[{'uuid':'x'}])]
        for key,value in cases:
            data=payload();data[key]=value
            with self.subTest(key=key),self.assertRaises(Exception):s.validate(data)

    def test_keyboard_cannot_inject_shell(self):
        for value in ('us"; id; #','us\nCOMMAND=bad','../../tmp','us$(id)'):
            data=payload();data['keyboard']['XKBLAYOUT']=value
            with self.assertRaises(s.SettingsError):s.validate(data)

    def test_utc_and_local_timezone_validated_without_restoring_old_clock(self):
        data=payload();data['clock']['local_time']='2020-01-01'
        with self.assertRaises(s.SettingsError):s.validate(data)
        data=payload();data['clock']['timezone']='../../etc/shadow'
        with self.assertRaises(Exception):s.validate(data)

    def test_wireguard_is_validated_and_scripts_refused(self):
        data=payload();data['wireguard']=WG;data['node']['profile']='wireguard'
        self.assertIsNotNone(s.validate(data)['wireguard'])
        data['wireguard']=WG.replace('Address =','PostUp = touch /tmp/evil\nAddress =')
        with self.assertRaises(Exception):s.validate(data)

    def test_duplicates_and_nan_refused(self):
        for raw in (b'{"version":1,"version":2}',b'{"x":NaN}'):
            with self.assertRaises(s.SettingsError):s.json_load(raw)

    def test_prune_bounds_boolean_and_unknown_core_options_refused(self):
        for value in ('2',True,'-1','1; shell'):
            with self.assertRaises(s.SettingsError):s.numeric_preferences({'prune':value})
        self.assertEqual(s.numeric_preferences({'wallet':['Keep'],'dbcache':256}),{'dbcache':'256'})

    def test_duplicate_network_profiles_refused(self):
        data=payload();data['connections']*=2
        with self.assertRaises(s.SettingsError):s.validate(data)

class Boundaries(unittest.TestCase):
    def test_every_writable_target_is_allowlisted(self):
        for path in ('etc/shadow','etc/sudoers','home/node/.ssh/authorized_keys','var/lib/bitcoin-core-node/data/wallets/wallet.dat',
                     'etc/NetworkManager/system-connections/../dispatcher.d/evil',NM_PREFIX if False else 'tmp/evil'):
            self.assertFalse(r.allowed(path),path)
        self.assertTrue(r.allowed('etc/NetworkManager/system-connections/Normal Profile.nmconnection'))

    def test_symlink_and_hardlink_configuration_refused(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'original';p.write_text('fixture')
            link=Path(td)/'link';link.symlink_to(p)
            with self.assertRaises(OSError):s.safe_read(link)
            link.unlink();os.link(p,link)
            with self.assertRaises(s.SettingsError):s.safe_read(link)

    def test_parent_symlink_cannot_escape(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'etc').symlink_to('/etc')
            with self.assertRaises(s.SettingsError):r.target(p,'etc/default/keyboard')

    def test_native_qt_opaque_target_values_are_preserved(self):
        raw=b'[General]\nfCoinControlFeatures=false\nopaque=@Variant(\\0\\0\\0z)\nstrDataDir=/target\n[Other]\nkeep=yes\n'
        result=r.update_ini(raw,{'fCoinControlFeatures':'true','language':'hr'})
        self.assertIn(b'opaque=@Variant(\\0\\0\\0z)',result)
        self.assertIn(b'strDataDir=/target',result)
        self.assertEqual(result.count(b'fCoinControlFeatures='),1)
        self.assertIn(b'language=hr',result)

    def test_read_no_changes_after_mutation_or_oversize(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'input';p.write_bytes(b'x'*100)
            with self.assertRaises(s.SettingsError):s.safe_read(p,10)

class RealEncryption(unittest.TestCase):
    def test_actual_encrypted_backup_authenticates_and_hides_network_secrets(self):
        from gpg_backend import encrypt_file,decrypt_file,GPGError
        with tempfile.TemporaryDirectory(dir='/dev/shm') as td:
            root=Path(td);root.chmod(0o700);plain=root/'payload';encrypted=root/'settings.gpg'
            plain.write_bytes(s.canonical(payload()));secret='synthetic settings backup passphrase'
            encrypt_file(plain,encrypted,secret,ram_root=root,max_output_bytes=s.MAX_PAYLOAD)
            self.assertNotIn(b'synthetic-wifi-password-for-tests',encrypted.read_bytes())
            restored=root/'restored';decrypt_file(encrypted,restored,secret,ram_root=root,max_output_bytes=s.MAX_PAYLOAD)
            self.assertEqual(plain.read_bytes(),restored.read_bytes())
            with self.assertRaises(GPGError):decrypt_file(encrypted,root/'wrong','wrong password',ram_root=root)
            self.assertFalse((root/'wrong').exists())
            data=bytearray(encrypted.read_bytes());data[len(data)//2]^=1;encrypted.write_bytes(data)
            with self.assertRaises(GPGError):decrypt_file(encrypted,root/'broken',secret,ram_root=root)
            self.assertFalse((root/'broken').exists())

if __name__=='__main__':unittest.main()
