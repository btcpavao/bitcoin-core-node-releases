"""Local login policy; only the fixed installed account can be changed."""
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import tempfile
from wallets import WalletError

ACCOUNT = 'node'
CONFIG = Path('/etc/bitcoin-core-node')
MARKER = CONFIG / 'passwordless-login'
LIGHTDM = Path('/etc/lightdm/lightdm.conf.d/99-node-login.conf')
SHADOW = Path('/etc/shadow')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}
# Debian's libxcrypt reserves one byte of its 512-byte input for NUL. This
# is a system compatibility boundary, not a Node password-strength policy.
MAX_PASSWORD_BYTES = 511

def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.login-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def passwordless():
    try:
        info = MARKER.lstat()
        return (stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
                not info.st_mode & 0o022 and MARKER.read_text() == ACCOUNT + '\n')
    except OSError:
        return False

def validate_request(request):
    if not isinstance(request, dict) or type(request.get('required')) is not bool:
        raise WalletError('Please choose whether a login password is required.')
    expected = {'required', 'password'} if request['required'] else {'required'}
    if set(request) != expected:
        raise WalletError('Invalid login settings.')
    if request['required']:
        password = request['password']
        if not isinstance(password, str) or not password:
            raise WalletError('Please enter a password. To sign in automatically, remove the login password instead.')
        # chpasswd reads one account:password line. Preserve spaces, Unicode
        # and punctuation exactly; never trim or silently truncate a password.
        if any(c in password for c in ('\0', '\n', '\r')):
            raise WalletError('Please enter the password on one line, without null characters.')
        try:
            encoded = password.encode('utf-8')
        except UnicodeEncodeError:
            raise WalletError('Please enter valid text for the password.') from None
        if len(encoded) > MAX_PASSWORD_BYTES:
            raise WalletError('The Linux login system supports up to 511 bytes of password text. Please use a shorter password; nothing has been changed.')
    return request

def lightdm_text(required):
    return '[Seat:*]\nautologin-user=' + ('' if required else ACCOUNT) + '\nautologin-user-timeout=0\nuser-session=core-node\n'

def configure(request):
    validate_request(request)
    if os.geteuid() != 0 or not (CONFIG / 'installed').is_file():
        raise WalletError('Please install the system before changing login settings.')
    account = pwd.getpwnam(ACCOUNT)
    caller = int(os.environ.get('PKEXEC_UID', '0'))
    if caller not in (0, account.pw_uid):
        raise WalletError('Login settings belong to the installed Node account.')
    if account.pw_uid < 1000:
        raise WalletError('The installed account is invalid.')
    # Keep the previous hash in root memory only, so a failed file update can
    # restore the previous login policy without logging or exposing a password.
    shadow = SHADOW.read_text().splitlines()
    old_hash = next(line.split(':')[1] for line in shadow if line.startswith(ACCOUNT + ':'))
    old_conf = LIGHTDM.read_text()
    was_passwordless = passwordless()
    def run(command, **kwargs):
        return subprocess.run(command, check=True, capture_output=True, text=True,
                              timeout=30, env=ENV, **kwargs)
    try:
        if request['required']:
            run(['/usr/sbin/chpasswd'], input=ACCOUNT + ':' + request['password'] + '\n')
            MARKER.unlink(missing_ok=True)
            atomic(LIGHTDM, lightdm_text(True))
        else:
            atomic(LIGHTDM, lightdm_text(False))
            run(['/usr/sbin/usermod', '--lock', ACCOUNT])
            atomic(MARKER, ACCOUNT + '\n')
    except Exception:
        # Restore the exception-free previous state. Never enable passwordless
        # authorization if restoration of the account or display policy fails.
        MARKER.unlink(missing_ok=True)
        try:
            run(['/usr/sbin/chpasswd', '--encrypted'], input=ACCOUNT + ':' + old_hash + '\n')
            atomic(LIGHTDM, old_conf)
            if was_passwordless: atomic(MARKER, ACCOUNT + '\n')
        except Exception:
            pass
        raise WalletError('Login settings could not be saved. Please keep this session open and inspect local account settings.') from None
    finally:
        request.pop('password', None)
        old_hash = None
    return {'ok': True, 'password_required': request['required']}
