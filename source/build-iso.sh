#!/bin/bash
# Development ISO only. Run in an owned disposable Debian 13 builder.
set -euo pipefail
umask 022
[[ ${NODE_DISPOSABLE_BUILDER:-} == 1 && $(id -u) == 0 ]] || {
    echo 'Please run in a disposable Debian 13 builder with NODE_DISPOSABLE_BUILDER=1.' >&2; exit 1;
}
. /etc/os-release
[[ $ID == debian && $VERSION_ID == 13 && $(dpkg --print-architecture) == amd64 ]]
NODE_SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ ! -e $NODE_SOURCE/build ]] || { echo 'Please use a fresh checkout; build/ already exists.' >&2; exit 1; }
python3 "$NODE_SOURCE/tests/check_core_release.py"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends live-build debootstrap ca-certificates curl \
    xorriso squashfs-tools syslinux-common syslinux-utils isolinux grub-pc-bin \
    grub-efi-amd64-bin mtools dosfstools python3 libusb-1.0-0
bash "$NODE_SOURCE/installer/build-calamares.sh"
bash "$NODE_SOURCE/installer/build-greeter.sh"
mkdir "$NODE_SOURCE/build"
cd "$NODE_SOURCE/build"
lb config --mode debian --distribution trixie --architectures amd64 \
    --mirror-bootstrap https://deb.debian.org/debian --mirror-chroot https://deb.debian.org/debian \
    --mirror-chroot-security https://security.debian.org/debian-security \
    --binary-images iso-hybrid --bootloaders 'syslinux,grub-efi' \
    --debian-installer none --archive-areas 'main non-free-firmware' --firmware-chroot false --apt-recommends false \
    --bootappend-live 'boot=live components username=node-live hostname=bitcoin-core-node locales=en_US.UTF-8 keyboard-layouts=us quiet splash loglevel=3 systemd.show_status=false rd.systemd.show_status=false vt.global_cursor_default=0' \
    --iso-application 'Bitcoin Core Node development' --iso-volume 'CORE_NODE_DEV'
mkdir -p config/includes.chroot/usr/lib/bitcoin-core-node config/package-lists config/hooks/live config/packages.chroot
cp "$NODE_SOURCE/artifacts/calamares_3.3.14-1+corenode2_amd64.deb" config/packages.chroot/
cp "$NODE_SOURCE/artifacts/lightdm-gtk-greeter_2.0.9-1+corenode1_amd64.deb" config/packages.chroot/
cp -a "$NODE_SOURCE/runtime/." config/includes.chroot/
# Checkout umask must not make shipped runtime files unreadable.
find config/includes.chroot -type d -exec chmod 755 {} +
find config/includes.chroot -type f -perm /u=x -exec chmod 755 {} +
find config/includes.chroot -type f ! -perm /u=x -exec chmod 644 {} +
cp "$NODE_SOURCE"/app/*.py config/includes.chroot/usr/lib/bitcoin-core-node/
cp "$NODE_SOURCE/packages.list" config/package-lists/node.list.chroot
cp "$NODE_SOURCE/prepare-image.sh" config/hooks/live/0900-node.hook.chroot
chmod 755 config/hooks/live/0900-node.hook.chroot
find config/includes.chroot/usr/libexec config/includes.chroot/usr/local/bin -type f -exec chmod 755 {} +
curl --fail --location --proto '=https' --tlsv1.2 --output core.tar.gz \
    https://bitcoincore.org/bin/bitcoin-core-32.1/bitcoin-32.1-x86_64-linux-gnu.tar.gz
echo '61545c17c3120fb7412f896d248b11993af04ec8817aad3649c55b2afb044963  core.tar.gz' | sha256sum --check
mkdir -p config/includes.chroot/opt/bitcoin-core
tar -xzf core.tar.gz -C config/includes.chroot/opt/bitcoin-core
mv config/includes.chroot/opt/bitcoin-core/bitcoin-32.1 config/includes.chroot/opt/bitcoin-core/32.1
python3 "$NODE_SOURCE/tools/install-keepassxc.py" --root "$PWD/config/includes.chroot" --version 2.8.0
lb build
# Catch remaster regressions which break KPMcore D-Bus disk discovery.
python3 "$NODE_SOURCE/tests/check_ownership.py" --iso live-image-amd64.hybrid.iso
python3 "$NODE_SOURCE/tests/check_iso_boot_paths.py" --iso live-image-amd64.hybrid.iso
python3 "$NODE_SOURCE/tests/check_iso_hardware.py" --iso live-image-amd64.hybrid.iso
mkdir -p "$NODE_SOURCE/artifacts"
cp live-image-amd64.hybrid.iso "$NODE_SOURCE/artifacts/bitcoin-core-node-development-amd64.iso"
cd "$NODE_SOURCE/artifacts"
sha256sum bitcoin-core-node-development-amd64.iso calamares_3.3.14-1+corenode2_amd64.deb lightdm-gtk-greeter_2.0.9-1+corenode1_amd64.deb > SHA256SUMS
printf '%s\n' 'Development image built. BIOS/UEFI installation, persistence, network leakage and RAM/GPG acceptance are still required. This is not a stable release.' > STATUS.txt
