#!/bin/bash
# Compile the Vault-derived installer only inside the disposable Debian ISO builder.
set -euo pipefail
[[ ${NODE_DISPOSABLE_BUILDER:-} == 1 && $(id -u) == 0 ]] || exit 1
NODE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
NODE_PACKAGE_VERSION=3.3.14-1+corenode2
NODE_WORK="$NODE_ROOT/calamares-build"
[[ ! -e "$NODE_WORK" ]] || { echo 'Please use a fresh disposable builder.' >&2; exit 1; }
mkdir -p "$NODE_WORK" "$NODE_ROOT/artifacts/calamares-source"
# Extend the container's signed Debian source configuration without changing its keyring.
python3 - <<'APT_SOURCE'
from pathlib import Path
source=Path('/etc/apt/sources.list.d/debian.sources')
text=source.read_text()
assert 'Types: deb' in text
source.write_text(text.replace('Types: deb\n','Types: deb deb-src\n'))
APT_SOURCE
apt-get update
apt-get install -y --no-install-recommends build-essential dpkg-dev devscripts equivs python3
apt-get build-dep -y calamares=3.3.14-1
cd "$NODE_WORK"
apt-get source calamares=3.3.14-1
cd calamares-3.3.14
python3 "$NODE_ROOT/installer/calamares/patch_node.py" .
EDITOR=true dpkg-source --commit . core-node-vault-installer
DEBEMAIL=builder@localhost DEBFULLNAME='Bitcoin Core Node builder' \
    dch --newversion "$NODE_PACKAGE_VERSION" --distribution trixie \
    'Use Bitcoin Core Vault installer layout with persistent Node copy and guarded disk selection.'
# Retain the corresponding, patched source before binary build staging appears.
dpkg-buildpackage -us -uc -S -d
DEB_BUILD_OPTIONS='nocheck parallel=2' dpkg-buildpackage -us -uc -b -j2
cd "$NODE_WORK"
test "$(dpkg-deb -f "calamares_${NODE_PACKAGE_VERSION}_amd64.deb" Version)" = "$NODE_PACKAGE_VERSION"
cp "calamares_${NODE_PACKAGE_VERSION}_amd64.deb" "$NODE_ROOT/artifacts/"
find . -maxdepth 1 -type f \( -name '*.dsc' -o -name '*.tar.*' -o -name '*.buildinfo' -o -name '*.changes' \) \
    -exec cp '{}' "$NODE_ROOT/artifacts/calamares-source/" \;
cp -a "$NODE_ROOT/installer/calamares" "$NODE_ROOT/artifacts/calamares-source/patch-inputs"
dpkg-query -W > "$NODE_ROOT/artifacts/calamares-source/build-environment.packages"
cd "$NODE_ROOT/artifacts/calamares-source"
find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
