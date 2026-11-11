"""Read portable evidence from two candidate images; execute no payload."""
from pathlib import Path
import filecmp
import gzip
import hashlib
import subprocess

results = Path('results')
evidence = Path('evidence')
evidence.mkdir(exist_ok=True)
def run(*cmd, capture=False):
    return subprocess.run(cmd, check=True, capture_output=capture)
def file_hash(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()
def manifest(path, compressed=False):
    op = gzip.open if compressed else open
    with op(path, 'rt') as f:
        return dict((name.rstrip('\n'), digest) for digest, name in (line.split('  ',1) for line in f))
for name in ('filesystem.packages','builder.packages','iso-files.sha256','root-files.sha256.gz'):
    a, b = (results / k / name for k in ('node-one','node-two'))
    print(name, file_hash(a), file_hash(b), flush=True)
    if name.endswith(('.sha256','.gz')):
        left, right = manifest(a, name.endswith('.gz')), manifest(b, name.endswith('.gz'))
        changed = [p for p in sorted(left.keys() | right.keys()) if left.get(p) != right.get(p)]
        print(f'{name}: {len(changed)} changed paths', flush=True)
        print('\n'.join(changed[:200]))
        (evidence / (name+'.diff.txt')).write_text('\n'.join(f'{p}\t{left.get(p)}\t{right.get(p)}' for p in changed)+'\n')
    elif not filecmp.cmp(a, b, shallow=False):
        diff=subprocess.run(['diff','-u',str(a),str(b)],capture_output=True)
        assert diff.returncode == 1
        (evidence/(name+'.diff.txt')).write_bytes(diff.stdout)
        print(diff.stdout[:1000].decode(errors='replace'))
