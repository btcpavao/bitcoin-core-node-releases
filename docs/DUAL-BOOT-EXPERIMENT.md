# Experimental Node installation on a separate partition

**Status: candidate source only; not a published or hardware-tested release.**
Do not treat a passing build or this document as proof of T2 Mac support.

## What changes

The original Node installation workflow remains available: select a disk and
explicitly choose to erase it. The advanced **Manual partitioning** choice is
now also visible in Calamares. No destructive option is preselected. The
default ext4 root layout, no-swap policy and no installer disk encryption are
unchanged. The EFI partition's **recommended** size is still 512 MiB, but the
**minimum** is 128 MiB to permit reuse of an existing ~200 MB Apple EFI
system partition when its free space is sufficient.

This is not an automatic dual-boot wizard, and Calamares does not automatically
protect Apple APFS data or its EFI partition. A wrong click can destroy macOS.

## Mac mini 2018 (Apple T2): proposed expert-only test

1. Back up all macOS data, and ensure Recovery works. Keep a recovery USB
   and access to the Mac's boot-security settings.
2. In **macOS Disk Utility**, select **View → Show All Devices**, select the
   target container, click **Partition → + → Add Partition** (**not** Add
   Volume), create a separate exFAT partition named e.g. "Bitcoin Node".
   Allocate sufficient persistent space; for a pruned node allow at least
   64 GiB (more is better), and for an unpruned node much more space is
   required. Do not erase or resize other partitions in the Linux installer.
3. Boot the **candidate** Node ISO using the Apple Option-key startup picker
   after adjusting T2 Startup Security settings as described by t2linux.
   Have wired keyboard/mouse and Ethernet available.
4. At **Disk**, use **Manual partitioning** (not Erase disk, Replace, or
   Install alongside). Precisely identify the newly created exFAT partition
   by size, label and disk. Set **only that partition** to ext4, format on,
   mount point `/`. Never select the macOS APFS container for formatting.
5. Reuse the existing FAT32 **EFI System Partition** at `/boot/efi` with
   **format OFF**. Do not erase it, create a new table, or format APFS.
   Verify the complete partitioning summary before committing. If any
   mount or format action is unclear, **cancel installation**.
6. Even with a successful install, bootloader or T2 drivers may fail. Do not
   assume a working Linux desktop, network, disk I/O or Bitcoin Core until
   tested. Do not store valuable wallets on an unvalidated installation.

Official technical guidance:
- https://wiki.t2linux.org/guides/preinstall/
- https://wiki.t2linux.org/distributions/debian/installation/

t2linux documents potential GRUB/EFI runtime issues and a custom kernel.
The 2018 T2 Mac mini is **not** currently an accepted hardware target for
this ISO. In particular, changing Calamares configuration alone does not add
T2 kernel patches, Apple firmware or a validated T2-compatible bootloader.

## Build verification

```sh
python3 -m unittest discover -s rebuild/tests -v
bash rebuild/node source ../node-manual-source
grep -E 'allowManualPartitioning|initialPartitioningChoice|recommendedSize|minimumSize' \
    ../node-manual-source/runtime/etc/calamares/modules/partition.conf
```

The `rebuild/node` entry point first authenticates the pinned source archive,
applies the existing RC3 patch and then applies the guarded, two-field
partition configuration change. GitHub Actions independently builds and
compares two complete ISOs on a new feature-branch revision. These source
checks are not an actual installation or data-preservation test.

**Release gate:** require UEFI VM tests on (a) a disposable blank disk and
(b) a disk containing a disposable simulated existing-OS + EFI partition,
verify preservation of the other filesystems and boot entries, then obtain
real T2 Mac hardware feedback before publishing a T2-compatibility claim.
