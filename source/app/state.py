"""Persistent setup contract, also checked by the service before any networking."""
import json
import os
from pathlib import Path
import stat
import subprocess
import re

CONFIG = Path('/etc/bitcoin-core-node')
DATA = Path('/var/lib/bitcoin-core-node/data')
CORE_SHA256 = '580ac61190154da31aac3f82d13c4254ef453d70e1bf2c39d338dac5129c92ac'
CORE_GUI_SHA256 = 'd43632a3e54dfb181ba045db2a5b1ec2396a1acdda010e3b6d07b2e21c69c183'
CHAIN_IMPORT_RECEIPT = '.core-node-chain-import.json'


def validate_chain_receipt(record):
    if (not isinstance(record,dict) or set(record)!={'version','network','core_version','height','bestblockhash'}
            or type(record['version']) is not int or record['version']!=1
            or record['network'] not in ('main','signet','regtest')
            or not isinstance(record['core_version'],str) or not re.fullmatch(r'32\.[0-9]{1,3}(?:\.[0-9]{1,3})?',record['core_version'])
            or type(record['height']) is not int or not 0<=record['height']<2**32
            or not isinstance(record['bestblockhash'],str) or not re.fullmatch('[a-f0-9]{64}',record['bestblockhash'])):
        raise SetupError('The imported blockchain record is invalid. Core remains stopped.')
    return record


def has_imported_chain(setup,data=DATA):
    path=data/CHAIN_IMPORT_RECEIPT
    try:info=path.lstat()
    except FileNotFoundError:return False
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or info.st_nlink!=1 or info.st_size>4096:
        raise SetupError('The imported blockchain record is unsafe. Core remains stopped.')
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:
            opened=os.fstat(stream.fileno())
            if (opened.st_dev,opened.st_ino)!=(info.st_dev,info.st_ino):raise ValueError()
            record=validate_chain_receipt(json.loads(stream.read(4097)))
    except (OSError,ValueError):
        raise SetupError('The imported blockchain record is unavailable. Core remains stopped.') from None
    return record['network']==setup['network']


def default_setup():
    """Fresh installed default; existing settings never fall back to this."""
    return {'version':1,'confirmed':True,'profile':'clearnet','network':'main',
            'prune_mib':0,'data_uuid':None,'private_broadcast':False}


class SetupError(RuntimeError):
    pass


def load_setup(path=CONFIG / 'setup.json', *, require_root=True):
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or
                (require_root and info.st_uid != 0) or info.st_size > 4096):
            raise SetupError('Setup permissions are unsafe.')
        data = json.loads(path.read_bytes())
    except (OSError, ValueError):
        raise SetupError('Node configuration is unavailable. Please inspect local service status.') from None
    return validate_setup(data)


def validate_setup(data):
    expected = {'version', 'confirmed', 'profile', 'network', 'prune_mib', 'data_uuid', 'private_broadcast'}
    if not isinstance(data, dict) or set(data) != expected or type(data['version']) is not int or data['version'] != 1:
        raise SetupError('Unsupported node configuration.')
    if data['confirmed'] is not True or data['profile'] not in ('clearnet', 'tor', 'wireguard'):
        raise SetupError('The stored network profile is invalid.')
    if data['network'] not in ('main', 'signet', 'regtest'):
        raise SetupError('Unsupported Bitcoin network.')
    if type(data['prune_mib']) is not int or (data['prune_mib'] != 0 and not 550 <= data['prune_mib'] <= 2**31-1):
        raise SetupError('Invalid pruning target.')
    if type(data['private_broadcast']) is not bool or not isinstance(data['data_uuid'], (str, type(None))):
        raise SetupError('Invalid node storage or broadcast settings.')
    if data['data_uuid'] is not None and not re.fullmatch('[a-fA-F0-9-]{8,64}', data['data_uuid']):
        raise SetupError('Invalid data filesystem UUID.')
    return data


def verify_data_mount(setup, data=DATA):
    if data.is_symlink() or not data.is_dir():
        raise SetupError('The selected data directory is unavailable.')
    result = subprocess.run(['/usr/bin/findmnt', '-J', '-T', str(data), '-o', 'TARGET,UUID,FSTYPE,OPTIONS'],
                            check=True, capture_output=True, text=True, timeout=10)
    rows = json.loads(result.stdout).get('filesystems', [])
    if len(rows) != 1 or rows[0]['fstype'] in ('tmpfs', 'ramfs', 'overlay'):
        raise SetupError('Node data must use a persistent installed filesystem.')
    if 'rw' not in rows[0]['options'].split(','):
        raise SetupError('The data filesystem is not writable.')
    if setup['data_uuid'] is not None and rows[0].get('uuid') != setup['data_uuid']:
        raise SetupError('The selected data SSD is missing. The node remains stopped.')
    if setup['data_uuid'] is not None and rows[0].get('target') != str(data):
        raise SetupError('The external data SSD is not mounted at its expected location.')
    return rows[0]


def core_arguments(setup, *, gui=False):
    # P2P configuration is generated only by the privileged privacy controller.
    # Do not accept user-provided config paths or arbitrary command-line flags.
    from network import core_config
    network_args = ['-' + line for line in core_config(setup).splitlines()
                    if line and not line.startswith(('#', '['))]
    arguments = ['-conf=' + str(DATA / 'bitcoin.conf'), '-datadir=' + str(DATA),
            '-walletdir=' + str(DATA / 'wallets'), '-server=1', '-daemon=0',
            '-rpcbind=127.0.0.1', '-rpcallowip=127.0.0.1', '-rpcport=8332',
            '-rpccookiefile=/run/bitcoin-core-node/auth.cookie', '-rpccookieperms=group',
            '-settings=' + str(DATA / 'settings.json'), '-natpmp=0', '-discover=0', '-listen=0', '-listenonion=0',
            '-prune=' + str(setup['prune_mib']),
            '-chain=' + setup['network'], '-privatebroadcast=' + str(int(setup['private_broadcast'])), *network_args]

    # Let the unmodified upstream GUI show its Intro and own its persistent
    # pruning preference. Privacy, RPC and the shared wallet directory stay fixed.
    if gui:
        excluded=('-prune=','-daemon=')
        # A verified import has already chosen the managed data directory and
        # pruning setting. Passing datadir skips Core's first-start picker,
        # which otherwise runs before settings.json and can override pruning.
        if not has_imported_chain(setup):excluded+=('-datadir=',)
        return [arg for arg in arguments if not arg.startswith(excluded)]
    return arguments
