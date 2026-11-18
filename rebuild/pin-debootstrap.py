"""Check debootstrap's own signed release before it selects bootstrap packages."""
from pathlib import Path
import sys

functions = Path(sys.argv[1])
script = functions.read_text()
download = '\t\tdownload_release_sig "$m1" "$s" "$inreldest" "$reldest" "$relsigdest"\n'
if script.count(download) != 1:
    raise SystemExit("Unrecognized debootstrap release verification")

# This release bootstraps one base suite. A change of suite must also update the lock.
lockfile = Path(__file__).with_name("InRelease.sha256")
digest, = [line.split()[0] for line in lockfile.read_text().splitlines()
           if line.split()[1] == "trixie.InRelease"]
check = (
    '\t\t[ "$s" = trixie ] && '
    f'printf "%s  %s\\n" "{digest}" "$inreldest" | sha256sum --check --status || '
    'error 1 NODEPIN "Bootstrap metadata does not match the pinned trixie snapshot"\n'
)
functions.write_text(script.replace(download, download + check))
