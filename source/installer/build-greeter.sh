#!/bin/bash
# Compile only in an owned disposable Debian 13 builder.
set -euo pipefail
umask 022
[[ ${NODE_DISPOSABLE_BUILDER:-} == 1 && $(id -u) == 0 ]] || exit 1
NODE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
NODE_GREETER_VERSION=2.0.9-1+corenode1
NODE_WORK=${NODE_GREETER_WORK:-"$NODE_ROOT/greeter-build"}
NODE_OUTPUT=${NODE_GREETER_OUTPUT:-"$NODE_ROOT/artifacts"}
[[ ! -e "$NODE_WORK" ]] || { echo 'Please use a fresh greeter build directory.' >&2; exit 1; }
mkdir -p "$NODE_WORK" "$NODE_OUTPUT/greeter-source"
cat > /etc/apt/sources.list.d/node-greeter-build.sources <<'APT_SOURCE'
Types: deb-src
URIs: https://deb.debian.org/debian
Suites: trixie
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
APT_SOURCE
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends build-essential dpkg-dev python3 xfce4-dev-tools
apt-get build-dep -y --no-install-recommends lightdm-gtk-greeter=2.0.9-1
cd "$NODE_WORK"
apt-get source lightdm-gtk-greeter=2.0.9-1
cd lightdm-gtk-greeter-2.0.9
python3 "$NODE_ROOT/installer/greeter/patch_greeter.py" .
EDITOR=true dpkg-source --commit . core-node-fixed-login
python3 - <<'CHANGELOG'
from pathlib import Path
import email.utils, os, time
p = Path('debian/changelog')
stamp = email.utils.formatdate(int(os.environ.get('SOURCE_DATE_EPOCH', time.time())), usegmt=False)
p.write_text('lightdm-gtk-greeter (2.0.9-1+corenode1) trixie; urgency=medium\n\n'
             '  * Fixed-account Bitcoin Core Node presentation using native LightDM authentication.\n\n'
             ' -- Bitcoin Core Node builder <builder@localhost>  ' + stamp + '\n\n' + p.read_text())
CHANGELOG
dpkg-buildpackage -us -uc -S -d
DEB_BUILD_OPTIONS='nocheck parallel=2' dpkg-buildpackage -us -uc -b -j2
cd "$NODE_WORK"
test "$(dpkg-deb -f "lightdm-gtk-greeter_${NODE_GREETER_VERSION}_amd64.deb" Version)" = "$NODE_GREETER_VERSION"
cp "lightdm-gtk-greeter_${NODE_GREETER_VERSION}_amd64.deb" "$NODE_OUTPUT/"
find . -maxdepth 1 -type f \( -name '*.dsc' -o -name '*.tar.*' -o -name '*.buildinfo' -o -name '*.changes' \) \
    -exec cp '{}' "$NODE_OUTPUT/greeter-source/" \;
cp "$NODE_ROOT/installer/greeter/patch_greeter.py" "$NODE_OUTPUT/greeter-source/"
dpkg-query -W > "$NODE_OUTPUT/greeter-source/build-environment.packages"
cd "$NODE_OUTPUT/greeter-source"
find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
