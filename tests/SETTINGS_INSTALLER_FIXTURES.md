# Settings and native installer acceptance fixtures

These fixtures are owned regular files below
`/home/pavao/iso-settings-dualboot-20261123` on the QA host. They never attach a
host block device. Filesystem inspection uses sparse raw copies, mtools,
debugfs, sfdisk and hashes without mounting a filesystem.

Fixture preparation is not installation evidence. Use the exact reviewed ISO
path and SHA256, obtain an assigned VM slot, and keep at most two VMs running.
No prepared fixture should be started automatically by a seeding helper.

## Same-disk reciprocal installation

`qa-node-first` and `qa-vault-first` each have a 96 GiB UEFI disk:

| Partition | Size | Initial contents |
| --- | ---: | --- |
| 1, QA_ESP | 512 MiB | FAT32 ESP and two synthetic foreign EFI files |
| 2, QA_KEEP_DATA | 1 GiB | ext4 and a synthetic data sentinel |
| Unallocated | 94.499 GiB | No partition and no filesystem |

The foreign `EFI/BOOT/BOOTX64.EFI` is a nonbootable sentinel. Its preservation
does not prove another operating system can boot. Use the product's distinct
UEFI NVRAM entry to test installed boot behavior.

For Node first, choose Advanced, the real unallocated span, and Create layout.
Use Node root 62.00 GiB and a 32.00 GiB Vault reservation. For Vault first, use
Vault root 32.00 GiB and a 62.00 GiB Node reservation. Both leave approximately
0.499 GiB unallocated and retain the existing ESP and data partition.

Capture the actual table, creation dialog, and Review before executing. Review
must show only new root/reservation partitions and reuse of the existing ESP
without formatting.
After the first install, boot the installed product without an ISO and retain
the firmware boot entry evidence. Stop the VM before inspection.

Run the preservation helper after each phase with a new label:

```bash
python3 settings_seed_partition_fixture.py verify \
  --root /home/pavao/iso-settings-dualboot-20261123/qa-vault-first \
  --label after-vault
```

Before booting the second installer, checkpoint the first product's completed
root and ESP files. Compare the entire first root partition after the second
installation, as well as its product EFI loader/configuration. The original
seed baseline covers the preexisting synthetic data and foreign EFI files;
it does not include an operating system that was installed later.

The second installer must identify the verified matching reservation. Open
Edit, explicitly enable ext4 formatting at `/`, preserve the same ESP without
formatting, and inspect Review. After installation, use both product choices
to boot their installed roots. Verify the first root/EFI files, original data,
foreign fallback, disk GUID and preserved partition GUIDs/boundaries.

To reproduce a fresh reverse fixture, use a **new directory**:

```bash
python3 settings_seed_partition_fixture.py seed \
  --root /home/pavao/iso-settings-dualboot-20261123/qa-vault-first-new \
  --first-product vault
```

## Legacy BIOS whole-disk regression

`qa-bios-node` and `qa-bios-vault` each contain one initially blank 64 GiB disk
and use SeaBIOS, without OVMF or an EFI variable file. `bios-baseline.json`
records the entire zero-filled guest-visible extent, disk identity and empty
boot history. Creation uses the controller's ordinary `create --firmware bios`.

For each product:

1. Boot the exact candidate in its assigned slot. Capture the Disk page:
   **Install to disk** must work and **Advanced partitioning** must be disabled
   with the explanation that Advanced requires UEFI.
2. Select the sole 64 GiB internal fixture disk and Install to disk. Capture
   Review, the actual queued plan and the final success/error result. Existing
   automatic configuration chooses an MBR/msdos table in BIOS. Node normally
   has a 1 GiB ext4 `/boot` and an ext4 `/`; Vault has an ext4 `/`.
3. Confirm the installation finishes through partition operations, target
   configuration, bootloader and final validation. Save the confirmed plan and
   installer logs. MBR partitions have no GPT PARTLABEL, so this must not fail
   merely because the native model also carries filesystem labels.
4. Stop the VM. Inspect an owned sparse raw copy with `sfdisk --json` and bounded
   offset reads / `blkid -p`. Check the MBR signature, expected boundaries and
   ext4 filesystems. The GPT/ESP-specific `settings_disk_readback.checkpoint`
   helper is intentionally unsuitable for an MBR disk.
5. Boot the same fixture with no ISO attached. Retain evidence of the installed
   product reaching its desktop, with no `boot=live` kernel argument and `/`
   residing on the installed disk. Exercise the launcher briefly and shut down.

The BIOS scenario tests the existing whole-disk path. It does not claim BIOS
Advanced partitioning, reservations or dual-boot support.
