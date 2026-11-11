"""Private stdin-only NetworkManager connection helper, run as the desktop user."""
import json
import sys
import uuid
import signal
import time
import gi
gi.require_version('NM','1.0')
from gi.repository import NM, GLib, Gio
import getpass
SEC = getattr(NM,'80211ApSecurityFlags')
AP = getattr(NM,'80211ApFlags')

# Only fixed, password-free codes may leave this helper. Never log a secret,
# raw NetworkManager error, connection name or SSID from a failed attempt.
CODES = frozenset(('adapter','not-visible','security','password-required',
                   'authentication','permission','timeout','network','unknown'))

class ConnectFailure(ValueError):
    def __init__(self,code):
        super().__init__(code if code in CODES else 'unknown')
        self.code=code if code in CODES else 'unknown'

def ssid_bytes(access):
    value=access.get_ssid()
    return bytes(value.get_data()) if value is not None else None

def choose_access_point(device,ap):
    # iPhones may rotate BSSID when the hotspot wakes or changes radio band.
    # Only allow the same exact, user-selected SSID; never silently choose an
    # open, WEP or enterprise network after a secure scan.
    expected=ap.get('ssid')
    if not isinstance(expected,str) or not 1<=len(expected.encode('utf-8'))<=32:
        raise ConnectFailure('not-visible')
    found=[item for item in device.get_access_points()
           if ssid_bytes(item)==expected.encode('utf-8')]
    if not found:
        raise ConnectFailure('not-visible')
    exact=next((item for item in found if item.get_bssid()==ap.get('bssid')),None)
    found.sort(key=lambda item:item.get_strength(),reverse=True)
    selected=exact if exact is not None else found[0]
    flags=selected.get_rsn_flags()|selected.get_wpa_flags()
    was_secure=ap.get('security') not in ('','--',None)
    is_secure=bool(flags & (SEC.KEY_MGMT_PSK|SEC.KEY_MGMT_SAE|SEC.KEY_MGMT_OWE))
    # Never silently downgrade secure Wi-Fi to an open connection.
    if was_secure and not is_secure:
        raise ConnectFailure('security')
    return selected

def error_from_network_manager(exc):
    # These are safe, standardized classifications, not error strings sent to UI.
    message=str(exc).lower()
    if any(token in message for token in ('not authorized','permission denied','not permitted','access denied')):
        return 'permission'
    if any(token in message for token in ('no secrets','secret required','authentication','bad password','wrong password')):
        return 'authentication'
    if any(token in message for token in ('supplicant','key-mgmt','security','incompatible')):
        return 'security'
    if any(token in message for token in ('timed out','timeout','not found','not available')):
        return 'timeout'
    return 'network'

def reason_from_device(device):
    # DeviceStateReason is reported by libnm after activation failure.
    try:
        reason=device.get_state_reason()
    except (AttributeError,ValueError):
        return 'network'
    if reason in (NM.DeviceStateReason.NO_SECRETS,):
        return 'authentication'
    if reason in (NM.DeviceStateReason.SUPPLICANT_CONFIG_FAILED,
                  NM.DeviceStateReason.SUPPLICANT_FAILED):
        return 'security'
    if reason in (NM.DeviceStateReason.SSID_NOT_FOUND,
                  NM.DeviceStateReason.SUPPLICANT_TIMEOUT,
                  NM.DeviceStateReason.SUPPLICANT_DISCONNECT):
        return 'timeout'
    if reason in (NM.DeviceStateReason.FIRMWARE_MISSING,):
        return 'adapter'
    return 'network'


def build_profile(name,ssid,flags,ap_flags,password):
    connection = NM.SimpleConnection.new()
    setting = NM.SettingConnection.new()
    setting.set_property('id',name)
    setting.set_property('uuid',str(uuid.uuid4()))
    setting.set_property('type','802-11-wireless')
    setting.set_property('autoconnect',True)
    setting.add_permission('user',getpass.getuser(),None)
    connection.add_setting(setting)
    wireless = NM.SettingWireless.new()
    wireless.set_property('ssid',ssid)
    wireless.set_property('mode','infrastructure')
    connection.add_setting(wireless)
    if flags & (SEC.KEY_MGMT_PSK | SEC.KEY_MGMT_SAE):
        if not isinstance(password,str) or not 8<=len(password.encode('utf-8'))<=63:
            raise ConnectFailure('password-required')
        security = NM.SettingWirelessSecurity.new()
        # Use only advertised WPA2-PSK or WPA3-SAE; do not allow insecure fallback.
        security.set_property('key-mgmt','wpa-psk' if flags & SEC.KEY_MGMT_PSK else 'sae')
        security.set_property('psk',password)
        connection.add_setting(security)
    elif flags & SEC.KEY_MGMT_OWE:
        security = NM.SettingWirelessSecurity.new()
        security.set_property('key-mgmt','owe')
        connection.add_setting(security)
    elif ap_flags & AP.PRIVACY:
        raise ConnectFailure('security')
    for klass in (NM.SettingIP4Config,NM.SettingIP6Config):
        ip = klass.new(); ip.set_property('method','auto'); connection.add_setting(ip)
    connection.verify()
    return connection

def connect(request):
    client = NM.Client.new(None)
    ap = request['ap']
    password = request.pop('password')
    supplied = bool(password)
    device = next((d for d in client.get_devices() if d.get_iface() == ap.get('device')
                   and isinstance(d,NM.DeviceWifi)),None)
    if device is None:raise ConnectFailure('adapter')
    access = choose_access_point(device,ap)
    ssid = access.get_ssid()
    flags = access.get_rsn_flags()|access.get_wpa_flags()
    if flags & SEC.KEY_MGMT_802_1X:raise ConnectFailure('security')
    saved = next((c for c in device.get_available_connections() if access.connection_valid(c)),None)
    if not supplied and saved is None and flags & (SEC.KEY_MGMT_PSK|SEC.KEY_MGMT_SAE):
        raise ConnectFailure('password-required')
    connection = None if saved is not None and not supplied else build_profile(
        ap['ssid'],ssid,flags,access.get_flags(),password)
    password = None
    loop = GLib.MainLoop()
    cancel = Gio.Cancellable()
    outcome = {'ok':False,'active':None,'error':None}
    def matches_network():
        # Avoid reporting success for a different Wi-Fi connection.
        active_ap=device.get_active_access_point()
        return (active_ap is not None and ssid_bytes(active_ap)==ssid_bytes(access)
                and device.get_state()==NM.DeviceState.ACTIVATED)
    def finished(obj,result,_):
        try:
            outcome['active'] = (obj.activate_connection_finish(result) if saved is not None and not supplied
                                 else obj.add_and_activate_connection_finish(result))
        except GLib.Error as exc:
            outcome['error']=error_from_network_manager(exc)
            if matches_network():outcome['ok']=True
            loop.quit()
    def poll():
        active = outcome['active']
        if active is not None:
            state = active.get_state()
            if state == NM.ActiveConnectionState.ACTIVATED:
                if matches_network():
                    outcome['ok'] = True
                else:
                    outcome['error']='network'
                loop.quit()
                return False
            if state in (NM.ActiveConnectionState.DEACTIVATING,NM.ActiveConnectionState.DEACTIVATED):
                outcome['error']=reason_from_device(device)
                loop.quit()
                return False
        elif matches_network():
            outcome['ok']=True
            loop.quit()
            return False
        return True
    def timeout():
        outcome['error']='timeout'
        loop.quit()
        return False
    if saved is not None and not supplied:
        client.activate_connection_async(saved,device,access.get_path(),cancel,finished,None)
    else:
        client.add_and_activate_connection_async(connection,device,access.get_path(),cancel,finished,None)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,timeout)
    GLib.timeout_add(200,poll)
    GLib.timeout_add_seconds(50,timeout)
    loop.run()
    if not outcome['ok']:
        cancel.cancel()
        active = outcome['active']
        if active is not None:
            cleanup = GLib.MainLoop()
            def deactivated(obj,result,_):
                try:obj.deactivate_connection_finish(result)
                except GLib.Error:pass
                cleanup.quit()
            client.deactivate_connection_async(active,None,deactivated,None)
            GLib.timeout_add(800,lambda:(cleanup.quit(),False)[1])
            cleanup.run()
        raise ConnectFailure(outcome['error'] or reason_from_device(device))

if __name__ == '__main__':
    try:
        data=sys.stdin.read(16384)
        if len(data)>=16384:raise ConnectFailure('unknown')
        request=json.loads(data)
        if not isinstance(request,dict) or not isinstance(request.get('ap'),dict):
            raise ConnectFailure('unknown')
        connect(request)
    except ConnectFailure as exc:
        print('NODE-WIFI-ERROR:'+exc.code,file=sys.stderr)
        sys.exit(1)
    except Exception:
        # No tracebacks, SSIDs or passwords in error output.
        print('NODE-WIFI-ERROR:unknown',file=sys.stderr)
        sys.exit(1)
