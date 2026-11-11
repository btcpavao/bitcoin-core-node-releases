"""NetworkManager operations. No changes to Bitcoin privacy policy."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from contextlib import contextmanager

class NetworkError(Exception):
    pass

class NetworkCancelled(Exception):
    pass

_local = threading.local()

@contextmanager
def cancellation_scope(event):
    _local.cancel = event
    try: yield
    finally: _local.cancel = None

def run_command(command, *, input=None, timeout=25):
    """Bounded, cancellable child; never run a shell or expose secret output."""
    event = getattr(_local, 'cancel', None)
    if event is not None and event.is_set(): raise NetworkCancelled()
    process = subprocess.Popen(command, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={**os.environ,'LC_ALL':'C.UTF-8'})
    deadline = time.monotonic() + timeout
    try:
        while True:
            if event is not None and event.is_set(): raise NetworkCancelled()
            if time.monotonic() >= deadline: raise subprocess.TimeoutExpired(command,timeout)
            try:
                stdout,stderr = process.communicate(input=input,timeout=min(.1,max(.001,deadline-time.monotonic())))
                return subprocess.CompletedProcess(command,process.returncode,stdout,stderr)
            except subprocess.TimeoutExpired:
                input = None
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate()

def nmcli(*args):
    try:
        result = run_command(['/usr/bin/nmcli', '--colors', 'no', '--wait', '12', *args],timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        raise NetworkError('NetworkManager did not respond. You can close this window and try again.')
    if result.returncode:
        raise NetworkError('Wi-Fi scan or setup failed. Check the wireless switch and try Refresh. You can close this window at any time.')
    return result.stdout.strip()

def fields(line):
    result = []; value = ''; escaped = False
    for char in line:
        if escaped: value += char; escaped = False
        elif char == '\\': escaped = True
        elif char == ':': result.append(value); value = ''
        else: value += char
    result.append(value)
    return result

def snapshot(scan=True):
    devices = [fields(line) for line in nmcli('-t','-f','DEVICE,TYPE,STATE,CONNECTION','device','status').splitlines()]
    devices = [row for row in devices if len(row) == 4 and row[1] != 'loopback']
    connected = [row for row in devices if row[2] == 'connected']
    radio = nmcli('-t','-f','WIFI','radio') == 'enabled'
    wifi = [row for row in devices if row[1] == 'wifi']
    aps = []
    if wifi and radio and scan and any(r[2] not in ('unavailable','unmanaged') for r in wifi):
        output = nmcli('-t','-f','IN-USE,BSSID,SSID,SIGNAL,SECURITY,DEVICE','device','wifi','list','--rescan','yes')
        for line in output.splitlines():
            row = fields(line)
            if len(row) != 6 or not row[2]: continue
            active,bssid,ssid,signal,security,device = row
            try: signal = int(signal)
            except ValueError: continue
            aps.append(dict(active=active=='*', bssid=bssid, ssid=ssid,
                signal=signal, security=security, device=device))
        # Retain the strongest AP for each network/security pair on each adapter.
        unique = {}
        for ap in sorted(aps, key=lambda a:(a['active'],a['signal']), reverse=True):
            unique.setdefault((ap['ssid'],ap['security'],ap['device']),ap)
        aps = list(unique.values())
    return dict(connected=bool(connected), connections=[r[3] for r in connected],
                wifi=bool(wifi), radio=radio, aps=aps,
                unavailable=bool(wifi) and all(r[2] in ('unavailable','unmanaged') for r in wifi))

def enable_wifi():
    nmcli('radio','wifi','on')

def connect(ap, password):
    request = dict(ap=ap, password=password)
    try:
        result = run_command(['/usr/bin/python3', str(Path(__file__).with_name('nm_connect.py'))],
            input=json.dumps(request), timeout=65)
    except (OSError, subprocess.TimeoutExpired):
        raise NetworkError('Connection timed out. Please check the password and try again.')
    finally:
        request.clear()
    if result.returncode:
        # Only receive fixed, sanitized codes from the private helper. Never
        # echo raw GPG/NetworkManager output (it may contain passwords/SSID).
        raw=(result.stderr or '').strip()
        code=raw.removeprefix('NODE-WIFI-ERROR:') if raw.startswith('NODE-WIFI-ERROR:') else 'unknown'
        descriptions={
            'adapter':'The Wi-Fi adapter is unavailable. Check the hardware switch, firmware and Bluetooth/Wi-Fi settings.',
            'not-visible':'The hotspot disappeared or changed its Wi-Fi channel. Keep Personal Hotspot open on your iPhone, then Refresh and retry.',
            'security':'The hotspot security mode is not supported by this Wi-Fi adapter. On iPhone, enable Settings → Personal Hotspot → Maximize Compatibility, then retry.',
            'password-required':'Please enter the hotspot password (8–63 UTF-8 bytes). Check the displayed password on the iPhone.',
            'authentication':'The hotspot could not authenticate this connection. Confirm the password on the iPhone, or remove an old saved Wi-Fi connection and retry.',
            'permission':'NetworkManager did not authorize the connection. Please open Advanced settings and inspect network permissions.',
            'timeout':'The hotspot did not finish connecting in time. Keep the iPhone hotspot settings open, move closer, enable Maximize Compatibility and retry.',
            'network':'NetworkManager failed to activate the Wi-Fi connection. Try Refresh and Advanced settings; check Wi-Fi adapter compatibility.',
            'unknown':'Wi-Fi could not connect. Please open Advanced settings to inspect the connection.'
        }
        raise NetworkError(descriptions.get(code,descriptions['unknown']))
