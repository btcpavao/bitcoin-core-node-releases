"""Generate bounded Core/nftables/WireGuard policy; never execute imported hooks."""
import base64
import configparser
import ipaddress
import re


class NetworkError(RuntimeError):
    pass


def key(value):
    try:
        if len(base64.b64decode(value, validate=True)) != 32:
            raise ValueError()
    except (ValueError, TypeError):
        raise NetworkError('A WireGuard key is invalid.') from None
    return value


def wireguard(text):
    """Accept a single-peer full tunnel with numeric endpoint and explicit DNS.

    Refusing hostname endpoints avoids pre-tunnel DNS resolution and ambiguous
    firewall exceptions. Scripts, includes and arbitrary wg-quick options fail.
    """
    if not isinstance(text, str) or len(text.encode()) > 16384 or '\x00' in text:
        raise NetworkError('Invalid WireGuard configuration size.')
    config = configparser.ConfigParser(interpolation=None, strict=True)
    config.optionxform = str
    try:
        config.read_string(text)
    except configparser.Error:
        raise NetworkError('Malformed WireGuard configuration.') from None
    if config.defaults() or set(config.sections()) != {'Interface', 'Peer'}:
        raise NetworkError('Please use a single-peer WireGuard configuration.')
    interface, peer = dict(config['Interface']), dict(config['Peer'])
    if set(interface) - {'PrivateKey', 'Address', 'DNS', 'MTU'} or set(peer) - {
            'PublicKey', 'PresharedKey', 'AllowedIPs', 'Endpoint', 'PersistentKeepalive'}:
        raise NetworkError('WireGuard scripts and unsupported configuration options are not permitted.')
    if not {'PrivateKey', 'Address', 'DNS'} <= set(interface) or not {'PublicKey', 'AllowedIPs', 'Endpoint'} <= set(peer):
        raise NetworkError('WireGuard requires keys, tunnel addresses, DNS, default routes and an endpoint.')
    interface['PrivateKey'] = key(interface['PrivateKey'])
    peer['PublicKey'] = key(peer['PublicKey'])
    if 'PresharedKey' in peer:
        peer['PresharedKey'] = key(peer['PresharedKey'])
    try:
        addresses = [ipaddress.ip_interface(x.strip()) for x in interface['Address'].split(',')]
        dns = [ipaddress.ip_address(x.strip()) for x in interface['DNS'].split(',')]
        routes = {str(ipaddress.ip_network(x.strip())) for x in peer['AllowedIPs'].split(',')}
    except ValueError:
        raise NetworkError('Invalid WireGuard address, DNS server or route.') from None
    if not addresses or not dns or not 1 <= len(addresses) <= 4 or not 1 <= len(dns) <= 4:
        raise NetworkError('Unsupported WireGuard address or DNS configuration.')
    if routes not in ({'0.0.0.0/0'}, {'0.0.0.0/0', '::/0'}):
        raise NetworkError('A full IPv4 tunnel is required. IPv6 must use ::/0 or remain blocked.')
    if any(x.version == 6 for x in dns) and '::/0' not in routes:
        raise NetworkError('IPv6 DNS requires an IPv6 tunnel route.')
    match = re.fullmatch(r'(?:\[([^\]]+)\]|([^:\s]+)):(\d{1,5})', peer['Endpoint'])
    if not match:
        raise NetworkError('Please use a numeric WireGuard endpoint IP and port.')
    try:
        endpoint = ipaddress.ip_address(match[1] or match[2])
        port = int(match[3])
        if endpoint.is_multicast or endpoint.is_unspecified or endpoint.is_loopback or not 1 <= port <= 65535:
            raise ValueError()
    except ValueError:
        raise NetworkError('Please use a valid numeric WireGuard endpoint IP and port.') from None
    for section, field, lower, upper in ((interface, 'MTU', 576, 9000), (peer, 'PersistentKeepalive', 0, 65535)):
        if field in section and (not section[field].isdigit() or not lower <= int(section[field]) <= upper):
            raise NetworkError('Invalid WireGuard numeric setting.')
    interface['Address'] = ', '.join(map(str, addresses))
    interface['DNS'] = ', '.join(map(str, dns))
    peer['AllowedIPs'] = ', '.join(sorted(routes))
    peer['Endpoint'] = ('[' + str(endpoint) + ']' if endpoint.version == 6 else str(endpoint)) + ':' + str(port)
    clean = '[Interface]\n' + ''.join(k + ' = ' + v + '\n' for k, v in interface.items())
    clean += '\n[Peer]\n' + ''.join(k + ' = ' + v + '\n' for k, v in peer.items())
    return clean, endpoint, port


def core_config(setup):
    profile = setup['profile']
    lines = ['# Generated from the explicitly confirmed Node privacy profile.']
    if setup['network'] != 'main':
        lines += ['[' + setup['network'] + ']']
    lines += ['server=1', 'rpcport=8332', 'rpcbind=127.0.0.1', 'rpcallowip=127.0.0.1',
             'listen=0', 'listenonion=0', 'discover=0', 'natpmp=0']
    if profile == 'tor':
        lines += ['onlynet=onion', 'proxy=127.0.0.1:9050', 'onion=127.0.0.1:9050',
                  'dns=0', 'dnsseed=0', 'fixedseeds=1']
    elif profile in ('clearnet', 'wireguard'):
        lines += ['onlynet=ipv4', 'onlynet=ipv6', 'dns=1', 'dnsseed=1']
        if setup['private_broadcast']:
            # Core 32.1 rejects privatebroadcast if onlynet excludes onion/I2P.
            # Enabling onion also makes it available for ordinary peer selection.
            lines += ['onlynet=onion', 'onion=127.0.0.1:9050']
    else:
        raise NetworkError('The privacy profile has not been confirmed.')
    return '\n'.join(lines) + '\n'


def firewall(profile, uid, endpoint=None, port=None, *, replace=False):
    if type(uid) is not int or uid < 1:
        raise NetworkError('The dedicated daemon account is unavailable.')
    # No generic established-output bypass: old clearnet flows must not survive
    # switching to VPN. Both address families share this inet output chain.
    output = ['oifname "lo" accept']
    if profile == 'tor':
        output += [f'meta skuid {uid} reject', 'accept']
    elif profile == 'clearnet':
        output += ['accept']
    elif profile == 'wireguard':
        if not isinstance(endpoint, (ipaddress.IPv4Address, ipaddress.IPv6Address)) or type(port) is not int or not 1 <= port <= 65535:
            raise NetworkError('A validated WireGuard endpoint is required.')
        output += ['oifname "core-node" accept',
                   ('ip' if endpoint.version == 4 else 'ip6') + f' daddr {endpoint} udp dport {port} accept',
                   'udp sport 68 udp dport 67 accept',
                   'icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert, nd-router-solicit } accept']
    elif profile == 'unconfirmed':
        output += [f'meta skuid {uid} reject', 'accept']
    else:
        raise NetworkError('Unsupported firewall profile.')
    return ('delete table inet core_node\n' if replace else '') + '''table inet core_node {
  chain input {
    type filter hook input priority -10; policy drop;
    iifname "lo" accept
    ct state established,related accept
    udp sport 67 udp dport 68 accept
    icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert, nd-router-advert, packet-too-big, destination-unreachable, time-exceeded } accept
    ip protocol icmp icmp type { destination-unreachable, time-exceeded, parameter-problem } accept
  }
  chain output {
    type filter hook output priority -10; policy drop;
    ''' + '\n    '.join(output) + '\n  }\n}\n'
