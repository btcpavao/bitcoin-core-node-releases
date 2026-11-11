"""Validate logind session identity without changing host services."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from desktop_session import active_desktop_scope

class DesktopSession(unittest.TestCase):
    def resolve(self, session='3', **changes):
        values = dict(User='1000', Active='yes', Remote='no', Type='x11',
                      Class='user', Scope='session-3.scope')
        values.update(changes)
        with patch('desktop_session.pwd.getpwnam', return_value=SimpleNamespace(pw_uid=1000)), \
             patch('desktop_session.subprocess.check_output',
                   side_effect=[session, '\n'.join(k+'='+v for k,v in values.items())]) as query:
            result = active_desktop_scope()
            self.assertEqual(query.call_args_list[0].args[0][2], 'node')
            return result

    def test_active_local_fixed_account(self):
        self.assertEqual(self.resolve(), 'session-3.scope')

    def test_other_or_inactive_sessions_refused(self):
        for values in [dict(User='0'), dict(User='1001'), dict(Active='no'),
                       dict(Remote='yes'), dict(Type='tty'), dict(Class='greeter'),
                       dict(Scope='session-4.scope')]:
            with self.subTest(values=values), self.assertRaises(RuntimeError):
                self.resolve(**values)

    def test_missing_or_injected_session_identifier_refused(self):
        for session in ['', '../x', '3\nBefore=shutdown.target', '3.scope']:
            with self.subTest(session=session), self.assertRaises(RuntimeError):
                self.resolve(session=session)
