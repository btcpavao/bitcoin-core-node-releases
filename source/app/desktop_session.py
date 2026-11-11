"""Resolve the installed Node desktop before binding the native Core service."""
import pwd
import re
import subprocess

ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}

def active_desktop_scope():
    account = pwd.getpwnam('node')
    def query(*args):
        return subprocess.check_output(
            ['/usr/bin/loginctl', *args], text=True, timeout=15, env=ENV).strip()
    session = query('show-user', 'node', '--property=Display', '--value')
    if not re.fullmatch(r'[a-zA-Z0-9_]+', session):
        raise RuntimeError('No installed Node desktop session is available.')
    values = dict(line.split('=', 1) for line in query('show-session', session,
        '-p', 'User', '-p', 'Active', '-p', 'Remote', '-p', 'Type', '-p', 'Class', '-p', 'Scope').splitlines() if '=' in line)
    scope = values.get('Scope', '')
    if (values.get('User') != str(account.pw_uid) or account.pw_uid < 1000 or
            values.get('Active') != 'yes' or values.get('Remote') != 'no' or
            values.get('Type') != 'x11' or values.get('Class') != 'user' or
            scope != 'session-' + session + '.scope'):
        raise RuntimeError('Core requires the active local Node desktop.')
    return scope
