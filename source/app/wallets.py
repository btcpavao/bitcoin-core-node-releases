"""Watch-only orchestration. All Bitcoin parsing/accounting is done by Core."""
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import stat


MAX_STATE = 512 * 1024
SAT = Decimal('100000000')


class WalletError(RuntimeError):
    pass


def amount(value, *, positive=False):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > 21000000 or number * SAT != (number * SAT).to_integral_value():
            raise ValueError()
        if positive and number == 0:
            raise ValueError()
        return format(number, '.8f')
    except (ValueError, InvalidOperation):
        raise WalletError('Please enter a valid Bitcoin amount with at most eight decimal places.') from None


def read_file(path, limit=MAX_STATE):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise WalletError('Please choose a regular file within the supported size limit.')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise WalletError('The selected file is too large.')
    return data


class WalletService:
    def __init__(self, rpc, directory=None):
        self.rpc = rpc
        self.directory = Path(directory) if directory else Path.home()/'.local/state/bitcoin-core-node'
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.directory.is_symlink() or self.directory.stat().st_uid != os.getuid():
            raise WalletError('Unsafe local wallet state directory.')
        self.directory.chmod(0o700)

    def watch(self, wallet):
        info = self.rpc('getwalletinfo', wallet=wallet)
        if info.get('private_keys_enabled') is not False or info.get('descriptors') is not True:
            raise WalletError('This workflow accepts only private-key-disabled descriptor wallets.')
        return info

    def inventory(self):
        return [r['name'] for r in self.rpc('listwalletdir')['wallets']]

    def import_status(self, wallet):
        # Native Core restores need no application receipt. Preserve any old
        # incomplete-import marker as a block; never certify an interrupted scan.
        if not re.fullmatch('[a-zA-Z0-9_-]{1,64}', wallet): return 'native'
        path = self.directory/'imports'/(wallet+'.json')
        try: return json.loads(read_file(path, 512*1024))['status']
        except FileNotFoundError: return 'native'
        except (OSError, ValueError, KeyError, TypeError, WalletError): return 'incomplete'

    def snapshot(self, wallet):
        info = self.watch(wallet)
        chain = self.rpc('getblockchaininfo')
        pending = (info.get('scanning') is not False or chain['initialblockdownload'] or
                   self.import_status(wallet) not in ('complete', 'native') or
                   info.get('lastprocessedblock', {}).get('height', chain['blocks']) < chain['blocks'])
        return {'name': wallet, 'info': info, 'chain': chain, 'incomplete': pending,
                'balances': self.rpc('getbalances', wallet=wallet),
                'utxos': self.rpc('listunspent', 0, wallet=wallet),
                'transactions': self.rpc('listtransactions', '*', 100, 0, True, wallet=wallet)}

    def receive(self, wallet, label='', kind='bech32'):
        self.watch(wallet)
        if self.import_status(wallet) not in ('complete', 'native'):
            raise WalletError('This wallet has an incomplete legacy import. Please restore a fresh native watch-only export in Bitcoin Core.')
        if kind not in ('legacy', 'p2sh-segwit', 'bech32', 'bech32m'):
            raise WalletError('Unsupported address type.')
        return self.rpc('getnewaddress', label, kind, wallet=wallet)
