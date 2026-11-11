"""Bounded operating-system time settings; no clock changes during observation."""
from datetime import datetime
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo, available_timezones

ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
ZONE_ROOT = Path('/usr/share/zoneinfo')


class TimeError(RuntimeError):
    pass


def zone_names():
    return sorted(available_timezones() - {'localtime', 'posixrules'})


def zone(value):
    if (not isinstance(value, str) or len(value) > 128
            or value in ('localtime', 'posixrules')
            or not re.fullmatch(r'[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)*', value)
            or any(part in ('.', '..') for part in value.split('/'))):
        raise TimeError('Please select a time zone from the list.')
    try:
        path = (ZONE_ROOT / value).resolve(strict=True)
        if not path.is_relative_to(ZONE_ROOT) or value.startswith(('right/', 'posix/')):
            raise ValueError()
        with path.open('rb') as stream:
            return ZoneInfo.from_file(stream, key=value)
    except (OSError, ValueError):
        raise TimeError('Please select an available time zone from the list.') from None


def runctl(*args):
    return subprocess.run(['/usr/bin/timedatectl', '--no-ask-password', *args],
        check=True, capture_output=True, text=True, timeout=15, env=ENV).stdout


def snapshot():
    try:
        text = runctl('show', '--property=Timezone', '--property=NTP',
                      '--property=NTPSynchronized', '--property=CanNTP')
        fields = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
        if set(fields) != {'Timezone', 'NTP', 'NTPSynchronized', 'CanNTP'}:
            raise ValueError()
        for name in ('NTP', 'NTPSynchronized', 'CanNTP'):
            if fields[name] not in ('yes', 'no'):
                raise ValueError()
        zone(fields['Timezone'])
        return {'timezone': fields['Timezone'], 'automatic': fields['NTP'] == 'yes',
                'synchronized': fields['NTPSynchronized'] == 'yes',
                'can_automatic': fields['CanNTP'] == 'yes'}
    except (ValueError, OSError, subprocess.SubprocessError):
        raise TimeError('System time settings are unavailable. Please try again or inspect local service status.') from None


def validate_request(request):
    if not isinstance(request, dict) or type(request.get('automatic')) is not bool:
        raise TimeError('Invalid date and time request.')
    automatic = request['automatic']
    if set(request) != ({'timezone', 'automatic'} if automatic
                         else {'timezone', 'automatic', 'local_time'}):
        raise TimeError('Invalid date and time request.')
    selected = zone(request['timezone'])
    epoch = None
    if not automatic:
        value = request['local_time']
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d', value):
            raise TimeError('Please enter a valid date and time.')
        try:
            local = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            if not 2000 <= local.year <= 2100:
                raise ValueError()
        except ValueError:
            raise TimeError('Please enter a valid date between 2000 and 2100.') from None
        candidates = set()
        for fold in (0, 1):
            stamp = int(local.replace(tzinfo=selected, fold=fold).timestamp())
            if datetime.fromtimestamp(stamp, selected).replace(tzinfo=None) == local:
                candidates.add(stamp)
        if not candidates:
            raise TimeError('That local time is skipped by the daylight-saving change. Please choose another time.')
        if len(candidates) != 1:
            raise TimeError('That local time occurs twice during the daylight-saving change. Please choose another time.')
        epoch = candidates.pop()
    return request['timezone'], automatic, epoch


def apply_settings(request):
    # Fully validate every field before the first privileged side effect.
    name, automatic, epoch = validate_request(request)
    before = snapshot()
    if automatic and not before['can_automatic']:
        raise TimeError('Automatic time is unavailable. Please check the installed time synchronization service.')
    try:
        if not automatic:
            runctl('set-ntp', 'false')
        runctl('set-timezone', name)
        if automatic:
            runctl('set-ntp', 'true')
        else:
            # Absolute epoch avoids local-time parsing and DST ambiguity.
            # timedated also writes the emulated/physical hardware clock.
            runctl('set-time', '@' + str(epoch))
        return {'ok': True, 'time': snapshot()}
    except (OSError, subprocess.SubprocessError):
        raise TimeError('Date and time changes did not finish. Some settings may have changed. Please reopen Date & Time to check them.') from None
