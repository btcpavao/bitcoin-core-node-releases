"""Only authenticated, published recovery opens the RAM workspace in Files."""
import contextlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
import file_crypto as crypto
import private_workspace as workspace
import recovery_dialog
from layered_backend import LayerError, MorePassphrases


class RecoveryHandoff(unittest.TestCase):
    @contextlib.contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            private = base / 'workspace'
            private.mkdir()
            source = base / 'fixture.gpg'
            source.write_bytes(b'disposable mocked ciphertext')
            result = private / 'decrypted-test'
            result.mkdir()
            with patch.object(workspace, 'PRIVATE', private), \
                 patch.object(workspace, 'check_storage', return_value=private), \
                 patch.object(crypto, 'selected_paths', return_value=[source]), \
                 patch.object(crypto, 'Progress') as progress, \
                 patch.object(crypto, 'decrypt_files', return_value=result) as decrypt, \
                 patch.object(recovery_dialog, 'get_recovery_request', return_value=(result, ['fixture'], False)) as request, \
                 patch.object(crypto.subprocess, 'Popen') as launch, \
                 patch.object(crypto, 'message') as message:
                launch.return_value.wait.return_value = 0
                yield SimpleNamespace(private=private, source=source, result=result,
                    progress=progress, decrypt=decrypt, request=request, launch=launch, message=message)

    def test_success_opens_workspace_root_after_progress_closes_without_popup(self):
        with self.fixture() as f:
            order = []
            f.decrypt.side_effect = lambda *a, **kw: (order.append('verified'), f.result)[1]
            f.progress.return_value.close.side_effect = lambda: order.append('progress closed')
            def launch(*args, **kwargs):
                order.append('files opened')
                self.assertEqual(args[0], ['/usr/bin/thunar', str(f.private)])
                self.assertTrue(kwargs['close_fds'])
                self.assertTrue(kwargs['start_new_session'])
                self.assertNotIn('shell', kwargs)
                return Mock(wait=Mock(return_value=0))
            f.launch.side_effect = launch
            crypto.decrypt_ui([str(f.source)])
            self.assertEqual(order, ['verified', 'progress closed', 'files opened'])
            f.message.assert_not_called()
            self.assertEqual(f.source.read_bytes(), b'disposable mocked ciphertext')

    def test_cancel_before_decryption_never_opens_files(self):
        with self.fixture() as f:
            f.request.return_value = None
            with self.assertRaises(crypto.Cancelled):
                crypto.decrypt_ui([str(f.source)])
            f.decrypt.assert_not_called()
            f.launch.assert_not_called()

    def test_wrong_passphrase_then_cancel_never_opens_files(self):
        with self.fixture() as f:
            f.decrypt.side_effect = MorePassphrases('Wrong passphrase')
            f.request.side_effect = [(f.result, ['wrong'], False), None]
            with self.assertRaises(crypto.Cancelled):
                crypto.decrypt_ui([str(f.source)])
            f.launch.assert_not_called()
            f.progress.return_value.close.assert_called_once()

    def test_retry_opens_only_after_the_successful_attempt(self):
        with self.fixture() as f:
            f.decrypt.side_effect = [MorePassphrases('Another layer'), f.result]
            f.request.side_effect = [(f.result, ['first'], False), (f.result, ['first', 'second'], False)]
            crypto.decrypt_ui([str(f.source)])
            self.assertEqual(f.decrypt.call_count, 2)
            self.assertEqual(f.progress.return_value.close.call_count, 2)
            f.launch.assert_called_once()
            f.message.assert_not_called()

    def test_authentication_failure_io_failure_or_cancel_never_opens_files(self):
        for error in (LayerError('Authentication failed'), OSError('Media removed'), crypto.Cancelled()):
            with self.subTest(error=type(error).__name__), self.fixture() as f:
                f.decrypt.side_effect = error
                with self.assertRaises(type(error)):
                    crypto.decrypt_ui([str(f.source)])
                f.launch.assert_not_called()
                f.progress.return_value.close.assert_called_once()

    def test_single_layer_mode_uses_the_same_success_handoff(self):
        with self.fixture() as f:
            f.request.return_value = (f.result, ['fixture'], True)
            crypto.decrypt_ui([str(f.source)])
            self.assertTrue(f.decrypt.call_args.kwargs['ordinary'])
            f.launch.assert_called_once()

    def test_thunar_start_failure_is_not_reported_as_failed_decryption(self):
        with self.fixture() as f:
            f.launch.side_effect = OSError('Unavailable')
            crypto.decrypt_ui([str(f.source)])
            f.message.assert_called_once()
            text = f.message.call_args.args[0]
            self.assertIn('Files decrypted and authenticated:', text)
            self.assertIn('Please open Private Workspace', text)
            self.assertNotIn('error', f.message.call_args.kwargs)
            self.assertTrue(f.result.is_dir())
            f.decrypt.assert_called_once()

    def test_thunar_immediate_nonzero_exit_has_readable_fallback(self):
        with self.fixture() as f:
            f.launch.return_value.wait.return_value = 1
            crypto.decrypt_ui([str(f.source)])
            self.assertIn('could not open automatically', f.message.call_args.args[0])

    def test_running_file_manager_is_not_killed_or_treated_as_failure(self):
        with self.fixture() as f:
            f.launch.return_value.wait.side_effect = subprocess.TimeoutExpired('thunar', 1)
            crypto.decrypt_ui([str(f.source)])
            f.launch.return_value.kill.assert_not_called()
            f.launch.return_value.terminate.assert_not_called()
            f.message.assert_not_called()

    def test_missing_or_symlink_recovery_refused_before_launch(self):
        with self.fixture() as f:
            f.result.rmdir()
            with self.assertRaises(crypto.BackupError):
                crypto.open_recovered_workspace(f.result, policy=workspace)
            f.result.symlink_to(f.private, target_is_directory=True)
            with self.assertRaises(crypto.BackupError):
                crypto.open_recovered_workspace(f.result, policy=workspace)
            f.launch.assert_not_called()

    def test_workspace_check_failure_never_opens_an_unverified_location(self):
        with self.fixture() as f, patch.object(workspace, 'check_storage', side_effect=workspace.WorkspaceError('RAM unavailable')):
            with self.assertRaises(workspace.WorkspaceError):
                crypto.open_recovered_workspace(f.result, policy=workspace)
            f.launch.assert_not_called()

    def test_guide_copies_explain_automatic_open_and_ram_lifetime(self):
        for relative in ('app/guide_content.py', 'runtime/usr/share/bitcoin-core-node/GUIDE.html',
                         'runtime/usr/share/bitcoin-core-node/GUIDE.txt'):
            text = (ROOT / relative).read_text()
            self.assertIn('Files opens Private Workspace automatically', text)
            self.assertIn('Wrong passphrases, failed checks and cancellation', text)
            self.assertIn('Recovered files remain in RAM', text)


if __name__ == '__main__':
    unittest.main()
