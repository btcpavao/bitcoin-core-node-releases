#!/bin/bash
# Manual UI review in a separate UEFI virtual disk; does not reuse earlier test disks.
set -euo pipefail
NODE_TEST_ARTIFACT="$HOME/node-v1-validation/ui-20261021-r3"
NODE_TEST_ISO="$NODE_TEST_ARTIFACT/bitcoin-core-node-development-amd64.iso"
NODE_TEST_VM="$HOME/node-vm-manual-ui-20261021-r3"
NODE_TEST_CODE="/usr/share/OVMF/OVMF_CODE_4M.fd"
NODE_TEST_VARS="/usr/share/OVMF/OVMF_VARS_4M.fd"
if [[ ! -f "$NODE_TEST_ISO" || ! -f "$NODE_TEST_ARTIFACT/SHA256SUMS" ]]; then
    echo "Please download the native Core test artifact to $NODE_TEST_ARTIFACT first." >&2
    exit 1
fi
if [[ ! -f "$NODE_TEST_CODE" || ! -f "$NODE_TEST_VARS" ]]; then
    echo "UEFI firmware is missing (Debian package: ovmf)." >&2
    exit 1
fi
(cd "$NODE_TEST_ARTIFACT" && sha256sum --check SHA256SUMS)
mkdir -p "$NODE_TEST_VM"
if [[ ! -e "$NODE_TEST_VM/node.qcow2" ]]; then
    qemu-img create -f qcow2 "$NODE_TEST_VM/node.qcow2" 48G
fi
if [[ ! -e "$NODE_TEST_VM/vars.fd" ]]; then
    cp "$NODE_TEST_VARS" "$NODE_TEST_VM/vars.fd"
fi
# Explicit disk serial is required by the installer security guard.
# Preserve this UI review disk on subsequent launches.
exec qemu-system-x86_64 \
    -name "Bitcoin Core Node - UI review 2026-10-21 revision 3" \
    -machine q35 -enable-kvm -m 3072 -smp 2 \
    -display gtk -vga std \
    -device qemu-xhci,id=xhci -device usb-tablet \
    -nic user,model=virtio-net-pci \
    -drive "if=pflash,format=raw,readonly=on,file=$NODE_TEST_CODE" \
    -drive "if=pflash,format=raw,file=$NODE_TEST_VM/vars.fd" \
    -drive "file=$NODE_TEST_VM/node.qcow2,format=qcow2,if=none,id=node-disk" \
    -device "virtio-blk-pci,drive=node-disk,serial=NODE-UI-20261021-R3" \
    -cdrom "$NODE_TEST_ISO" -boot order=cd
