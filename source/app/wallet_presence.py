"""Read-only wallet presence for the Home card; never load or create a wallet."""
import json
from pathlib import Path
import re

from rpc import CoreError
from wallets import read_file, WalletError


def watch_only_wallets_present(rpc, directory=None):
    directory = Path(directory) if directory else Path.home()/'.local/state/bitcoin-core-node'
    registered = set()
    for path in (directory/'imports').glob('*.json'):
        if not re.fullmatch('[a-zA-Z0-9_-]{1,64}', path.stem):
            continue
        try:
            record = json.loads(read_file(path, 512*1024))
            if record.get('status') in ('importing', 'incomplete', 'complete'):
                registered.add(path.stem)
        except (OSError, ValueError, TypeError, AttributeError, WalletError):
            continue

    try:
        loaded = rpc('listwallets')
    except CoreError:
        # Existing import receipts keep management discoverable across a restart.
        # With no receipt, an outage is unknown rather than proof of no wallets.
        return True if registered else None

    uncertain = False
    for name in loaded:
        try:
            info = rpc('getwalletinfo', wallet=name)
        except CoreError:
            uncertain = True
            continue
        if info.get('private_keys_enabled') is False and info.get('descriptors') is True:
            return True
        # A stale receipt must not classify a loaded signing wallet as watch-only.
        registered.discard(name)

    if registered:
        try:
            on_disk = {row['name'] for row in rpc('listwalletdir')['wallets']}
        except CoreError:
            return None
        if registered & on_disk:
            return True
    return None if uncertain else False
