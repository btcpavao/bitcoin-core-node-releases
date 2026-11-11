import json
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import keepass_updates as keepass
import system_updates as updates
from connection_state import peer_state


class SoftwareUpdatesTests(unittest.TestCase):
    def record(self):
        number = '2.8.0'
        name = 'KeePassXC-' + number + '-1-x86_64.AppImage'
        return dict(tag_name=number, draft=False, prerelease=False,
                    assets=[dict(name=name, browser_download_url=keepass.DOWNLOAD + number + '/' + name)])

    def test_accepts_official_stable_revision(self):
        result = keepass.release_record(self.record())
        self.assertEqual(result['version'], '2.8.0')
        self.assertTrue(result['name'].endswith('-1-x86_64.AppImage'))

    def test_rejects_prerelease_and_injected_downloads(self):
        for change in [dict(prerelease=True), dict(draft=True), dict(tag_name='2.8.0/../x'),
                       dict(assets=[dict(name='KeePassXC-2.8.0-1-x86_64.AppImage',
                                         browser_download_url='https://example.invalid/malware')])]:
            with self.subTest(change=change), self.assertRaises(keepass.UpdateError):
                keepass.release_record(dict(self.record(), **change))

    def test_signature_must_chain_to_pinned_primary(self):
        class Image:
            def __str__(self): return '/test/appimage'
        response = type('Response', (), dict(returncode=0, stdout='[GNUPG:] VALIDSIG ' + 'A'*40 + ' 2026 1 0 4 0 1 8 00 ' + 'A'*40))()
        key = type('Key', (), dict(read_bytes=lambda self: b'test-key'))()
        dearmor = type('Response', (), dict(returncode=0, stdout=b'ring'))()
        with patch.object(keepass.subprocess, 'run', side_effect=[dearmor, response]):
            with self.assertRaisesRegex(keepass.UpdateError, 'signature verification failed'):
                keepass.verify_image(Image(), Path('/test/sig'), key)

    def test_package_plan_includes_new_dependencies(self):
        output = 'Inst libnss3 [2:3.110-1+deb13u4] (2:3.110-1+deb13u5 Debian-Security:13/stable-security [amd64])\nInst linux-image-6.12.1-amd64 (6.12.1-1 Debian:13/stable [amd64])\n'
        plan = updates.package_plan(output)
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[1]['previous'], 'new dependency')

    def test_package_removal_and_managed_binaries_are_refused(self):
        for output in ['Remv thunar [4.20]', 'Inst bitcoin-qt [32.1] (33.0 Debian [amd64])',
                       'Inst calamares [3.3.14-1+corenode2] (3.3.15 Debian [amd64])']:
            with self.subTest(output=output), self.assertRaises(keepass.UpdateError):
                updates.package_plan(output)

    def test_failed_fresh_check_never_installs_cached_updates(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(updates, 'LOCK', Path(directory) / 'update.lock'), \
             patch.object(updates.os, 'geteuid', return_value=0), \
             patch.object(updates, 'write_status'), \
             patch.object(updates, 'command', side_effect=keepass.UpdateError('Network unavailable')), \
             patch.object(updates, 'install_release') as install:
            with self.assertRaises(keepass.UpdateError):
                updates.perform('install')
            install.assert_not_called()

    def test_online_requires_live_peers_not_a_running_service(self):
        for network in [dict(networkactive=True, connections=0), dict(networkactive=False, connections=4)]:
            self.assertEqual(peer_state('active', network)[0], 'offline')
        self.assertEqual(peer_state('active', dict(networkactive=True, connections=4))[0], 'online')
        self.assertEqual(peer_state('inactive', dict(networkactive=True, connections=4))[0], 'stopped')
        self.assertEqual(peer_state('failed')[0], 'error')


if __name__ == '__main__':
    unittest.main()
