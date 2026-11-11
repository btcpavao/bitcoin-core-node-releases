"""Bitcoin peer connectivity, distinct from a Wi-Fi/Ethernet link."""
import subprocess


def peer_state(service, network=None):
    if service == 'failed':
        return 'error', 'Error', 'Bitcoin Core reported a service error.'
    if service in ('inactive', 'deactivating'):
        return 'stopped', 'Stopped', 'Bitcoin Core is stopped.'
    if service == 'activating':
        return 'starting', 'Starting', 'Bitcoin Core is starting.'
    if service != 'active' or network is None:
        return 'unknown', 'Checking', 'Bitcoin peer connectivity is not available yet.'
    if not network.get('networkactive', False):
        return 'offline', 'Offline', 'Bitcoin network activity is paused in Bitcoin Core.'
    count = network.get('connections', 0)
    if count > 0:
        return 'online', 'Online', f'Connected to {count} Bitcoin peers.'
    return 'offline', 'Offline', 'Bitcoin Core has no peer connections. A connected Wi-Fi link alone does not establish a Bitcoin connection.'


def snapshot():
    from rpc import CoreRPC, CoreError
    status = subprocess.run(['/usr/bin/systemctl', 'show', 'bitcoin-core-node.service',
                             '--property=ActiveState', '--value'], capture_output=True,
                            text=True, timeout=3)
    service = status.stdout.strip() if status.returncode == 0 else 'unknown'
    network = None
    detail = ''
    if service == 'active':
        try:
            network = CoreRPC(timeout=2)('getnetworkinfo')
        except CoreError as exc:
            if exc.code == -28:
                service = 'activating'
            detail = 'Bitcoin Core is loading or its local RPC is not responding yet.'
    state, label, explanation = peer_state(service, network)
    try:
        from network_access import snapshot as network_snapshot
        link = network_snapshot(scan=False)
        connections = ', '.join(link['connections']) if link['connected'] else 'No connected Wi-Fi or Ethernet link'
    except Exception:
        connections = 'Operating-system network information is unavailable'
    return dict(state=state, label=label, explanation=explanation, detail=detail,
                service=service, connections=connections,
                peers=network.get('connections') if network else None,
                incoming=network.get('connections_in') if network else None,
                outgoing=network.get('connections_out') if network else None,
                networkactive=network.get('networkactive') if network else None,
                version=network.get('subversion') if network else None)
