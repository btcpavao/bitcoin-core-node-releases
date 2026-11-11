#!/usr/bin/python3
"""Synthetic failure/process-control fixture, never runtime cryptography."""
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time

args = sys.argv[1:]
status = int(args[args.index('--status-fd')+1])
password_fd = int(args[args.index('--passphrase-fd')+1])
secret = os.read(password_fd, 1024).rstrip(b'\n')
data = sys.stdin.buffer.read()
work = Path(args[args.index('--homedir')+1]).parent
root = work.parent
safe = {'argv':args, 'environment':dict(os.environ),
        'secret_absent_argv':all(secret not in a.encode() for a in args),
        'secret_absent_env':all(secret not in v.encode() for v in os.environ.values()),
        'passphrase_fd_is_pipe':os.readlink('/proc/self/fd/'+str(password_fd)).startswith('pipe:'),
        'core_limit':resource.getrlimit(resource.RLIMIT_CORE)[0], 'pid':os.getpid()}
if data == b'HANG':
    child = os.fork()
    if child == 0:
        while True: time.sleep(1)
    safe['child_pid'] = child
    (root/'fixture-proof.json').write_text(json.dumps(safe))
    sys.stdout.buffer.write(b'provisional synthetic plaintext');sys.stdout.buffer.flush()
    while True: time.sleep(1)
(root/'fixture-proof.json').write_text(json.dumps(safe))
events = ['BEGIN_DECRYPTION','DECRYPTION_INFO 0 9 2','PLAINTEXT 62 0 ',
          'DECRYPTION_OKAY','GOODMDC','END_DECRYPTION']
if data == b'WRONG_PROFILE': events[1]='DECRYPTION_INFO 0 7 2'
elif data == b'MISSING_AUTH': events.remove('DECRYPTION_OKAY')
elif data == b'GOODMDC_ABSENT': events.remove('GOODMDC')
elif data == b'GOODMDC_DUPLICATE': events.insert(-1,'GOODMDC')
elif data == b'GOODMDC_WRONG_POSITION': events.remove('GOODMDC');events.insert(0,'GOODMDC')
elif data == b'MISSING_INFO': events.pop(1)
elif data == b'LITERAL_ONLY': events=['PLAINTEXT 62 0 ']
elif data == b'MULTIPLE': events += events
elif data == b'FAILURE_EXIT_ZERO': events.append('FAILURE gpg-exit 1')
elif data == b'ERROR_EXIT_ZERO': events.append('ERROR synthetic 1')
elif data == b'ERRMDC_EXIT_ZERO': events.append('ERRMDC')
elif data == b'NODATA_EXIT_ZERO': events.append('NODATA 1')
elif data == b'INCOMPLETE_STATUS': events=events[:-1]
if '--symmetric' in args: events=['BEGIN_ENCRYPTION 2 9','END_ENCRYPTION']
sys.stdout.buffer.write(b'provisional synthetic plaintext');sys.stdout.buffer.flush()
for event in events: os.write(status, ('[GNUPG:] '+event+'\n').encode())
raise SystemExit(2 if data == b'NONZERO_WITH_SUCCESS' else 0)
