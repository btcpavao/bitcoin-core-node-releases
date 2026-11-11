"""Fixed Debian 13 + signed KeePassXC maintenance, independent of the desktop."""
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from keepass_updates import UpdateError, current_release, latest_release, install_release, version

STATUS = Path('/var/lib/core-node-updates/status.json')
LOCK = Path('/run/lock/core-node-software.lock')
SOURCES = '/etc/apt/sources.list.d/core-node.sources'
UNITS = ('core-node-software-check.service', 'core-node-software-install.service')
ENV = dict(PATH='/usr/sbin:/usr/bin:/sbin:/bin', LANG='C.UTF-8', LC_ALL='C.UTF-8',
           DEBIAN_FRONTEND='noninteractive', NEEDRESTART_MODE='l')
APT = ['/usr/bin/apt-get', '-o', 'Dir::Etc::sourcelist=' + SOURCES,
       '-o', 'Dir::Etc::sourceparts=-', '-o', 'APT::Update::Error-Mode=any',
       '-o', 'DPkg::Lock::Timeout=30', '-o', 'Dpkg::Options::=--force-confold']


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def busy():
    return any(subprocess.run(['/usr/bin/systemctl', 'is-active', '--quiet', unit],
                              env=ENV, timeout=5).returncode == 0 for unit in UNITS)


def read_status():
    try:
        info = STATUS.lstat()
        if not STATUS.is_file() or STATUS.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 2*1024*1024:
            raise ValueError()
        record = json.loads(STATUS.read_bytes())
        if not isinstance(record, dict):
            raise ValueError()
        if record.get('busy') and record.get('boot_id') != boot_id():
            return dict(record, busy=False, stage='interrupted',
                        message='The previous update was interrupted by a restart. Check for updates again before retrying.')
        return record
    except (OSError, ValueError):
        return dict(busy=False, stage='idle', message='Check for Debian and KeePassXC updates. Bitcoin Core is managed separately.')


def write_status(**record):
    STATUS.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    record.update(boot_id=boot_id(), time=int(time.time()))
    fd, name = tempfile.mkstemp(prefix='.status-', dir=STATUS.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o644)
            json.dump(record, stream, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, STATUS)
    finally:
        Path(name).unlink(missing_ok=True)


def start(action):
    if action not in ('check', 'install'):
        raise UpdateError('Unsupported software operation.')
    if busy():
        return {'ok': True, 'busy': True}
    unit = UNITS[0 if action == 'check' else 1]
    subprocess.run(['/usr/bin/systemctl', 'reset-failed', unit], env=ENV,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    subprocess.run(['/usr/bin/systemctl', 'start', '--no-block', unit],
                   env=ENV, check=True, capture_output=True, timeout=15)
    return {'ok': True, 'busy': True}


def command(arguments, *, timeout=900, on_line=None):
    # APT continues independent of the desktop. Read bounded lines to update
    # status.json in real time, rather than pretending a fixed timer is progress.
    with open('/var/log/core-node-updates.log', 'a') as log:
        log.write('\n' + time.strftime('%Y-%m-%d %H:%M:%S') + ' ' + ' '.join(arguments) + '\n')
        log.flush()
        if on_line is None:
            try:
                result = subprocess.run(arguments, env=ENV, stdin=subprocess.DEVNULL,
                                        stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise UpdateError('The update took too long. Keep the computer on and inspect /var/log/core-node-updates.log before retrying.') from exc
        else:
            # For Debian upgrades (which are intentionally unbounded), every
            # actual APT/DPKG line can advance the package-step counter. This
            # is a package-step estimate, not a fabricated percentage of bytes.
            started=time.monotonic()
            process=subprocess.Popen(arguments, env=ENV, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, errors='replace', bufsize=1)
            try:
                for line in process.stdout:
                    log.write(line)
                    if len(line)<2048:
                        on_line(line)
                    if timeout is not None and time.monotonic()-started>timeout:
                        raise UpdateError('The update exceeded its safe time budget; inspect the maintenance log.')
                result=process.wait()
                if result:
                    raise UpdateError('Software updates failed. Inspect /var/log/core-node-updates.log.')
            finally:
                process.stdout.close()
                if process.poll() is None:
                    process.wait()  # Do not kill dpkg during package mutation.
            return
    if result.returncode:
        raise UpdateError('The software operation did not complete. Check the connection, system clock and free disk space, then retry. Details: /var/log/core-node-updates.log')


def package_plan(output):
    packages = []
    for line in output.splitlines():
        if line.startswith('Remv '):
            raise UpdateError('An update requiring package removal needs manual review.')
        if not line.startswith('Inst '):
            continue
        match = re.match(r'^Inst ([a-z0-9][a-z0-9+.:\-]*)(?: \[([^\]]+)\])? \(([^ ]+)', line)
        if not match:
            raise UpdateError('The Debian update plan could not be reviewed.')
        name, previous, latest = match.groups()
        if name.split(':')[0] == 'calamares' or name.startswith(('bitcoin', 'bitcoind', 'bitcoincore')):
            raise UpdateError('The package plan attempts to replace a separately managed component.')
        packages.append(dict(name=name, previous=previous or 'new dependency', version=latest))
    return packages


def plan():
    result = subprocess.run(APT + ['--simulate', '--with-new-pkgs', '--no-remove', 'upgrade'],
                            env=ENV, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise UpdateError('Debian could not prepare an update plan. Please inspect local package diagnostics.')
    return package_plan(result.stdout)


def restart_likely(packages):
    # This is a pre-install advisory. The final flag comes from the actual
    # reboot-required marker or active kernel mismatch after installation.
    return any(p['name'].split(':')[0].startswith(('linux-image-', 'linux-base'))
               or p['name'].split(':')[0] in ('systemd', 'libc6')
               for p in packages)


def reboot_required():
    if Path('/run/reboot-required').exists():
        return True
    result = subprocess.run(['/usr/bin/dpkg-query', '-W', '-f=${Package}\n', 'linux-image-*-amd64'],
                            env=ENV, capture_output=True, text=True, timeout=10)
    kernels = [line.removeprefix('linux-image-') for line in result.stdout.splitlines()
               if line.startswith('linux-image-') and line != 'linux-image-amd64']
    return bool(kernels and os.uname().release not in kernels)


def perform(action):
    if action not in ('check', 'install') or os.geteuid() != 0:
        raise UpdateError('Unsupported software operation.')
    os.umask(0o022)
    with LOCK.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        details = {}
        try:
            write_status(busy=True, stage='checking', progress=None,
                         message='Checking official Debian packages and KeePassXC releases…')
            command(APT + ['update'])
            packages = plan()
            details = dict(packages=packages, debian_checked=True, check_complete=False,
                           updates_available=False, reboot_likely=restart_likely(packages),
                           core_version='32.1 (managed separately)')
            current = current_release()
            details['keepass_current'] = current['version']
            write_status(busy=True, stage='checking-keepass', progress=None,
                         message='Debian check completed. Checking the official KeePassXC release…', **details)
            candidate = latest_release()
            if version(candidate['version']) < version(current['version']):
                raise UpdateError('The available KeePassXC release record is older than the installed version. No downgrade or up-to-date claim was made; please retry later.')
            available = (version(candidate['version']) > version(current['version']) or
                         (version(candidate['version']) == version(current['version']) and
                          candidate['url'] != current['source']))
            details = dict(packages=packages, debian_checked=True, check_complete=True,
                           keepass_source=candidate.get('metadata_source','GitHub release API'),
                           keepass_note=candidate.get('metadata_note',''), keepass_current=current['version'],
                           keepass_latest=candidate['version'], keepass_available=available,
                           updates_available=bool(packages or available),
                           reboot_likely=restart_likely(packages),
                           core_version='32.1 (managed separately)')
            if action == 'check':
                message = ('Updates are available. Install Updates applies this Debian and KeePassXC update set.'
                           if details['updates_available'] else 'Debian packages and KeePassXC are up to date.')
                write_status(busy=False, stage='checked', progress=0, message=message,
                             reboot_required=reboot_required(), **details)
                return
            if shutil.disk_usage('/').free < 2*1024**3:
                raise UpdateError('At least 2 GiB of free system disk space is needed before installing updates.')
            # Never stop or restart Bitcoin Core for OS/KeePassXC maintenance.
            # Core version changes use the separate signed Core update workflow.
            # Debian maintainer scripts may restart other OS services, so the
            # GUI warns users that a system reboot can be required.
            if available:
                write_status(busy=True, stage='keepass', progress=None,
                             message='Downloading, verifying and installing official KeePassXC…',
                             **details)
                install_release(candidate)
            if packages:
                count=len(packages)
                downloaded=0
                write_status(busy=True, stage='downloading', progress=5,
                             message=f'Downloading Debian packages (0 / {count})…',
                             **details)
                def download_line(line):
                    nonlocal downloaded
                    if line.lstrip().startswith('Get:'):
                        downloaded=min(count,downloaded+1)
                        write_status(busy=True, stage='downloading',
                                     progress=min(45,5+40*downloaded//max(1,count)),
                                     message=f'Downloading Debian packages ({downloaded} / {count} fetched)…',
                                     **details)
                # Fetch the complete set before APT invokes package maintainer
                # scripts; progress is tracked by real Get: records.
                command(APT+['--yes','--download-only','--with-new-pkgs','--no-remove','upgrade'],
                        timeout=1800,on_line=download_line)
                write_status(busy=True, stage='installing', progress=50,
                             message=f'Installing Debian packages (0 / {count})…', **details)
                configured=set()
                def install_line(line):
                    match=re.match(r'^Setting up ([^ :]+)(?::[^ ]+)? ',line)
                    if match and match.group(1) not in configured:
                        configured.add(match.group(1))
                        write_status(busy=True, stage='installing',
                                     progress=min(96,50+46*len(configured)//max(1,count)),
                                     message=f'Installing Debian packages ({min(len(configured),count)} / {count})…',
                                     **details)
                # Never kill dpkg because a desktop or network timeout elapsed.
                # NEEDRESTART_MODE=l requests reporting, not automatic restarts.
                command(APT+['--yes','--with-new-pkgs','--no-remove','upgrade'],
                        timeout=None,on_line=install_line)
                write_status(busy=True, stage='finishing', progress=97,
                             message='Verifying completed updates and cleaning package cache…',
                             **details)
                command(['/usr/bin/apt-get','clean'],timeout=120)
            remaining=plan()
            details.update(packages=remaining, keepass_current=current_release()['version'],
                           keepass_available=False, updates_available=bool(remaining))
            write_status(busy=False, stage='complete', progress=100,
                         message='Software updates completed. Bitcoin Core was not deliberately stopped.',
                         reboot_required=reboot_required(), **details)
        except Exception as exc:
            message = str(exc) if isinstance(exc, UpdateError) else 'Software maintenance did not complete. Details: /var/log/core-node-updates.log'
            details.update(check_complete=False, updates_available=False)
            write_status(busy=False, stage='error', progress=None,
                         message=message, **details)
            raise
