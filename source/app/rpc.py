"""Local Core JSON-RPC client; cookie authentication, no proxy or remote endpoint."""
import base64
import http.client
import json
from pathlib import Path
from urllib.parse import quote


class CoreError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class CoreRPC:
    def __init__(self, cookie='/run/bitcoin-core-node/auth.cookie', port=8332, timeout=30):
        self.cookie, self.port, self.timeout = Path(cookie), port, timeout

    def __call__(self, method, *params, wallet=None):
        # Literal loopback endpoint and direct HTTPConnection deliberately ignore
        # proxy environment variables. Never log authentication or RPC payloads.
        try:
            cookie = self.cookie.read_bytes().strip()
            if not cookie or len(cookie) > 1024 or b':' not in cookie:
                raise ValueError()
        except (OSError, ValueError):
            raise CoreError('Bitcoin Core is not ready or local RPC access is unavailable.') from None
        path = '/' if wallet is None else '/wallet/' + quote(wallet, safe='')
        body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': list(params)})
        # A historical import/rescan may legitimately take hours. Its worker and
        # UI keep it explicit; never mistake an RPC timeout for successful sync.
        timeout = max(self.timeout, 86400) if method in ('importdescriptors', 'rescanblockchain') else self.timeout
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
        try:
            connection.request('POST', path, body, {
                'Authorization': 'Basic ' + base64.b64encode(cookie).decode('ascii'),
                'Content-Type': 'application/json',
            })
            response = connection.getresponse()
            raw = response.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise CoreError('Bitcoin Core returned an excessive response.')
            result = json.loads(raw)
            if response.status != 200 or not isinstance(result, dict) or result.get('error'):
                code = (result.get('error') or {}).get('code') if isinstance(result, dict) else None
                raise CoreError('Bitcoin Core could not complete this operation (code ' + str(code) + ').', code)
            return result['result']
        except (OSError, ValueError, KeyError, http.client.HTTPException):
            raise CoreError('The local Bitcoin Core connection failed.') from None
        finally:
            connection.close()
