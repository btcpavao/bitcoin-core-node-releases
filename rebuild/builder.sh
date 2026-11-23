#!/bin/bash
# This script runs inside a fresh, privileged Docker container in a disposable VM.
set -euo pipefail
umask 022
source /recipe/inputs.env
export NODE_RECIPE=/recipe NODE_DISPOSABLE_BUILDER=1
export SOURCE_DATE_EPOCH DEBIAN_SNAPSHOT SECURITY_SNAPSHOT
export TZ=UTC LC_ALL=C LANG=C PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1
export DEBIAN_FRONTEND=noninteractive
test "$(id -u)" = 0
test "$(dpkg --print-architecture)" = amd64
test ! -e /build/node
test -d /inputs/app
# The pinned minimal image needs a CA bundle for its first HTTPS apt operation.
# The caller mounts a bundle read-only. Debian archive signatures are mandatory.
test -s /host-ca.pem
cat > /etc/apt/apt.conf.d/98-rebuild <<'APT'
Acquire::https::CaInfo "/host-ca.pem";
Acquire::Retries "5";
APT
cat > /etc/apt/sources.list.d/debian.sources <<APT
Types: deb deb-src
URIs: $DEBIAN_SNAPSHOT
Suites: trixie trixie-updates
Components: main non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
Check-Valid-Until: no

Types: deb deb-src
URIs: $SECURITY_SNAPSHOT
Suites: trixie-security
Components: main non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
Check-Valid-Until: no
APT
bash /recipe/apt-pin-config.sh > /etc/apt/apt.conf.d/99node-snapshot.conf
apt-get update
apt-get install -y --no-install-recommends ca-certificates python3 gnupg patch
mkdir -p /build/node
cp -a /inputs/. /build/node/
cd /build/node
# Files from the user's checkout are copied as root in the output regardless
# of the host user's UID; retain execute bits and the signed source tree.
chown -hR 0:0 .
bash ./build-iso.sh
mkdir -p /out
install -m 644 artifacts/bitcoin-core-node-development-amd64.iso /out/bitcoin-core-node-candidate-amd64.iso
cp build/chroot.packages.live /out/filesystem.packages
# Retain the exact corresponding native installer source with the candidate.
test -d artifacts/calamares-source
cp -a artifacts/calamares-source /out/calamares-source
(cd /out/calamares-source && sha256sum --strict --check SHA256SUMS)
(cd /out && sha256sum bitcoin-core-node-candidate-amd64.iso > SHA256SUMS)
dpkg-query -W > /out/builder.packages
# Mastering adds the El Torito catalog and patches the ISOLINUX boot image.
# Read the finished ISO so each manifest entry verifies against that image.
iso_tree=$(mktemp -d)
trap 'find "$iso_tree" -type d -exec chmod u+w {} +; rm -rf -- "$iso_tree"' EXIT
xorriso -abort_on FAILURE -osirrox on -indev /out/bitcoin-core-node-candidate-amd64.iso \
    -extract / "$iso_tree"
(cd "$iso_tree" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0r sha256sum) > /out/iso-files.sha256
