"""Native password compatibility, rollback, and UI flow without host changes."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from PySide6.QtWidgets import QApplication, QWidget
import login
import login_ui
from wallets import WalletError

APP = None


class PasswordCompatibility(unittest.TestCase):
    def test_short_spaces_unicode_and_long_passwords_are_preserved(self):
        for password in ('1', 'a', ' ', ' two words ', 'node', '1234',
                         'čćžšđ!:$', 'x' * 129, 'x' * 511, 'č' * 255):
            with self.subTest(length=len(password)):
                request = {'required': True, 'password': password}
                self.assertIs(login.validate_request(request), request)
                self.assertEqual(request['password'], password)

    def test_native_byte_boundary_never_silently_truncates(self):
        for password in ('x' * 512, 'č' * 256, '\nroot:password', 'x\r', 'x\0', '\ud800'):
            with self.subTest(length=len(password)), self.assertRaises(WalletError):
                login.validate_request({'required': True, 'password': password})

    def test_failed_policy_write_restores_previous_login(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'installed').touch()
            shadow = root/'shadow'; shadow.write_text('node:!old-hash:20000:0:99999:7:::\n')
            conf = root/'login.conf'; conf.write_text(login.lightdm_text(False))
            marker = root/'passwordless-login'; marker.write_text('node\n')
            original_atomic = login.atomic
            def fail_required(path, text):
                if path == conf and text == login.lightdm_text(True):
                    raise OSError('fixture write failure')
                original_atomic(path, text)
            request = {'required': True, 'password': '1'}
            with patch.multiple(login, CONFIG=root, LIGHTDM=conf, MARKER=marker, SHADOW=shadow), \
                 patch.object(login.os, 'geteuid', return_value=0), \
                 patch.object(login.pwd, 'getpwnam', return_value=Mock(pw_uid=1000)), \
                 patch.dict(os.environ, {'PKEXEC_UID': '1000'}), \
                 patch.object(login, 'passwordless', return_value=True), \
                 patch.object(login, 'atomic', side_effect=fail_required), \
                 patch.object(login.subprocess, 'run') as run:
                with self.assertRaises(WalletError):
                    login.configure(request)
                self.assertEqual(run.call_args_list[0].kwargs['input'], 'node:1\n')
                self.assertEqual(run.call_args_list[1].kwargs['input'], 'node:!old-hash\n')
                self.assertEqual(conf.read_text(), login.lightdm_text(False))
                self.assertEqual(marker.read_text(), 'node\n')
                self.assertNotIn('password', request)


class LoginScreen(unittest.TestCase):
    def setUp(self):
        global APP
        APP = QApplication.instance() or QApplication([])
        self.parent = QWidget(); self.parent.rpc = Mock()
        self.patches = [patch.object(login_ui.Path, 'is_file', return_value=True),
                        patch.object(login_ui, 'passwordless', return_value=True)]
        for p in self.patches: p.start()
        self.dialog = login_ui.LoginDialog(self.parent)

    def tearDown(self):
        self.dialog.close(); self.dialog.deleteLater(); self.parent.deleteLater()
        APP.processEvents()
        for p in reversed(self.patches): p.stop()

    def test_mismatch_keeps_state_and_does_not_call_helper(self):
        self.dialog.password.setText('1'); self.dialog.confirm.setText('2')
        with patch.object(login_ui.subprocess, 'run') as run:
            self.dialog.save()
            run.assert_not_called()
        self.assertFalse(self.dialog.password_required)
        self.assertIn('same password', self.dialog.status.text())

    def test_save_preserves_text_in_stdin_and_can_return_to_auto_login(self):
        def synchronous(fn, done, message):
            done(fn()); self.dialog.refresh_actions()
        password = ' spaces and č: ' + 'x' * 129
        self.dialog.password.setText(password); self.dialog.confirm.setText(password)
        with patch.object(self.dialog, 'run', side_effect=synchronous), \
             patch.object(login_ui.subprocess, 'run', return_value=Mock(returncode=0, stdout='{"password_required": true}')) as run:
            self.dialog.save()
            self.assertEqual(json.loads(run.call_args.kwargs['input'])['password'], password)
            self.assertNotIn(password, str(run.call_args.args))
        self.assertTrue(self.dialog.password_required)
        self.assertEqual(self.dialog.save_button.text(), 'Change password')
        self.assertEqual(self.dialog.password.text(), '')
        with patch.object(self.dialog, 'run', side_effect=synchronous), \
             patch.object(login_ui.subprocess, 'run', return_value=Mock(returncode=0, stdout='{"password_required": false}')):
            self.dialog.apply({'required': False})
        self.assertFalse(self.dialog.password_required)
        self.assertTrue(self.dialog.remove_button.isHidden())

    def test_live_environment_does_not_offer_account_mutation(self):
        self.dialog.installed = False; self.dialog.refresh_actions()
        self.assertFalse(self.dialog.save_button.isEnabled())
        self.assertFalse(self.dialog.password.isEnabled())
        with patch.object(login_ui.subprocess, 'run') as run:
            self.dialog.save(); self.dialog.remove()
            run.assert_not_called()


if __name__ == '__main__': unittest.main()
