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
apt-get update
# Check signed metadata bytes APT actually selected before installing anything.
cd /var/lib/apt/lists
for spec in \
 '0584fba32e13e0ab8285fb16c27adea1ec03a73669c18702821094fd6ca86675 trixie' \
 '877205fdc4edad023f4441f11f8de0e3e85af9f52ac5de92022669ace8a455c6 trixie-updates' \
 '3b638178819e5b4a01a9d9ed333410a3a1b2cda026aaee9cd05741981f1f4f6f trixie-security'; do
    read -r digest suite <<< "$spec"
    files=( *_dists_"${suite}"_InRelease )
    [[ ${#files[@]} == 1 && -f ${files[0]} ]]
    echo "$digest  ${files[0]}" | sha256sum --check --strict
done
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
(cd /out && sha256sum bitcoin-core-node-candidate-amd64.iso > SHA256SUMS)
dpkg-query -W > /out/builder.packages
(cd build/binary && find . -type f -print0 | LC_ALL=C sort -z | xargs -0r sha256sum) > /out/iso-files.sha256
