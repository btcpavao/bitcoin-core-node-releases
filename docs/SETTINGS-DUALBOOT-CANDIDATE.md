# Settings and dual-boot candidate

This feature branch extends the published Node RC3 source and Vault v0.8.0.
It is a development candidate. A build is not described as ready until the
checks below have produced evidence for that exact image digest.

## Intended behavior

- Both desktops use Settings, Restart and Shutdown in the lower-right corner.
- Node's Settings shortcut opens its existing menu, including Network Connections.
- Vault gains local Display, Keyboard and Mouse, Date and Time, and Backup and
  Restore settings. Wallet data and the account home remain in RAM.
- Shared Display Settings discovers available modes, offers mirror and extended
  layouts, and requires confirmation within 15 seconds after applying a change.
- Installed Node remembers confirmed display preferences. Vault stores them in
  the current RAM session; explicit device-profile export/import contains only
  the supported device preferences.
- Both native installers retain Keyboard, Disk and Review. Disk offers Install
  to disk and Advanced partitioning. Advanced supports explicit root selection,
  existing EFI partition reuse, and a layout in genuinely unallocated space
  with an unformatted reservation for the other product.
- Preserving another installation and reservations require UEFI in this first
  version. Whole-disk installation retains the existing BIOS and UEFI paths.
- The final review lists the selected disk/partitions and their intended
  creation, formatting, preservation and reservation operations.

## Required evidence

| Area | Required checks | Current status |
| --- | --- | --- |
| Native installer | Compile both product adaptations from their recorded source | Pending |
| Partition plan | Reject protected disks, stale identity, unsafe jobs and overlap | Pending |
| UEFI single disk | Node then Vault, and Vault then Node; retain the first system | Pending |
| Two physical disks | Target selection preserves the other disk and its boot files | Pending |
| Boot | Installed Node and Vault boot independently after both installations | Pending |
| Desktop | Footer, Settings navigation, offline Vault input/time and backup routes | Pending |
| Display | Apply/Keep/Revert, process failure, hotplug fallback, supported modes | Pending |
| Storage | Node persistence; Vault device preferences remain in RAM by default | Pending |
| Reproduction | Record source commits, package inputs and final ISO SHA-256 hashes | Pending |

Tests use synthetic data and newly created disposable virtual disks. Physical
monitor/capture-device compatibility is reported separately from VM coverage.
Published stable downloads are not replaced by an unverified candidate.

## Exact candidate source and build

The `rebuild/node` entry point first verifies the signed RC2 source archive,
then applies the published RC3 changes in `rebuild/node.patch`, followed by
`rebuild/settings-dualboot.patch`. The latter includes executable file modes.
It does not use the stale private development branch as an implicit input.

Use a fresh disposable Debian builder with the dependencies described in
`docs/REBUILD.md`, and check out the full candidate commit recorded in the
download's `build-inputs.txt`. The stable release tag in that historical guide
reproduces RC3, not this candidate.

```sh
bash rebuild/node source ../settings-dualboot-source
sudo bash rebuild/node build ../settings-dualboot-result-one
```

Repeat the build from the same full commit on a second fresh builder, then
compare the two complete images:

```sh
bash rebuild/node compare \
  ../settings-dualboot-result-one/bitcoin-core-node-candidate-amd64.iso \
  ../settings-dualboot-result-two/bitcoin-core-node-candidate-amd64.iso
```

Each output directory contains the ISO, SHA256SUMS, build input identities,
installed package lists and the corresponding patched Calamares source.
The candidate checksum is independent of the historical RC3 checksum.

## VM evidence

`tests/settings_dualboot_vm.py` uses only newly created regular qcow2 files,
copied OVMF variables and an explicitly hashed, read-only ISO. It disables
networking and never passes a host block device to QEMU. Each GUI choice is
made from a retained screenshot of the actual wizard. Readback happens only
after the recorded QEMU process has stopped, without mounting guest disks.

The two installation orders use separate fixtures. The two-disk case hashes
the first disk's partitions before and after installing on the second disk.
The Settings guest probe uses synthetic removable media and an explicit
`SETTINGS-TEST-ONLY` marker; it does not use wallet files or real backups.
