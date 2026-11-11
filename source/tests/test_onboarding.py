"""Login policy boundaries without changing host accounts."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from state import default_setup, validate_setup, load_setup, SetupError
import login

class Onboarding(unittest.TestCase):
    def test_gui_keeps_privacy_and_rpc_but_owns_native_storage_choice(self):
        from state import core_arguments
        args = core_arguments(default_setup(), gui=True)
        self.assertFalse(any(x.startswith(('-datadir=', '-prune=', '-daemon=')) for x in args))
        for required in ['-server=1', '-listen=0', '-rpcbind=127.0.0.1',
                         '-rpccookiefile=/run/bitcoin-core-node/auth.cookie']:
            self.assertIn(required, args)
        tor = {**default_setup(), 'profile': 'tor'}
        self.assertIn('-onlynet=onion', core_arguments(tor, gui=True))
        self.assertIn('-proxy=127.0.0.1:9050', core_arguments(tor, gui=True))

    def test_default_is_valid_and_independent(self):
        one = default_setup()
        self.assertEqual(validate_setup(one)['profile'], 'clearnet')
        self.assertEqual(one['network'], 'main')
        one['profile'] = 'tor'
        self.assertEqual(default_setup()['profile'], 'clearnet')

    def test_missing_or_corrupt_settings_never_fall_back_to_clearnet(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'setup.json'
            with self.assertRaises(SetupError): load_setup(path, require_root=False)
            path.write_text('{broken'); path.chmod(0o600)
            with self.assertRaises(SetupError): load_setup(path, require_root=False)

    def test_login_requests_are_bounded_and_fixed(self):
        self.assertEqual(login.validate_request({'required': False}), {'required': False})
        login.validate_request({'required': True, 'password': 'fixture-long-password'})
        for request in [{'required': 1}, {'required': False, 'account': 'root'},
                        {'required': True, 'password': ''},
                        {'required': True, 'password': 'with\ncontrol'},
                        {'required': True, 'password': 'x' * 512}]:
            with self.subTest(request=request), self.assertRaises(Exception):
                login.validate_request(request)

    def test_login_helper_refuses_unprivileged_changes(self):
        with patch('login.os.geteuid', return_value=1000), patch('login.subprocess.run') as run:
            with self.assertRaises(Exception): login.configure({'required': False})
            run.assert_not_called()

    def test_password_marker_missing_or_symlink_is_not_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'passwordless-login'
            with patch('login.MARKER', marker):
                self.assertFalse(login.passwordless())
                target = Path(folder) / 'target'; target.write_text('node\n')
                marker.symlink_to(target)
                self.assertFalse(login.passwordless())

if __name__ == '__main__': unittest.main()
