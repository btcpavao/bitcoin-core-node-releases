# Settings and dual-boot testing

Use the supplied candidate ISOs and record their filenames and SHA-256 checksums.
Please back up existing files and use disposable test data. Results are pending
until these checks are completed.

## 1. Identify the installation drive

Boot the USB in **UEFI mode** for Advanced partitioning and dual boot. Identify
the actual disks in Terminal with this read-only command:

```sh
lsblk -d -o NAME,SIZE,MODEL,SERIAL
```

Match the model, serial and device path to the intended drive. **Review** shows
model, capacity and path; cross-check the serial above. Repeat after booting the
other ISO because device names such as `/dev/sda` can change.

Follow **Keyboard → Disk → Review**. At **Disk**, choose:

| Option | What it does |
| --- | --- |
| **Install to disk** | Erases the selected physical disk and installs the product. |
| **Advanced partitioning** | Selects an exact partition or creates a layout in **Unallocated space**, optionally reserving space for the other product. |

Advanced preservation requires GPT. Existing partitions are never shrunk or
moved; free space inside a filesystem is not unallocated disk space.

## 2. Test both installation orders on one disk

Use a separate fresh test layout for each order:

| First installation | Reservation to enable | Second installation |
| --- | --- | --- |
| Node | **Reserve unformatted space for Vault** | Vault in the reserved partition |
| Vault | **Reserve unformatted space for Node** | Node in the reserved partition |

1. Choose **Advanced partitioning**, the intended **Installation drive:**, then
   **Unallocated space → Create layout…**. For an empty disk without GPT, use
   **Erase selected disk…** first; this schedules deletion of every existing
   partition if the disk contains any.
2. Set the root size, enable the reservation above, and set **Reserved size:**
   within the available space. Confirm the layout, then complete **Review**.
3. Restart without the installation USB and confirm the first product boots.
4. Boot the other ISO in UEFI mode. Choose **Advanced partitioning** on that
   disk. Select the intended unformatted partition, marked **verified reserved
   space** when recognized, then **Edit…**. Check its path and size and acknowledge
   **Format this partition. Its current files will be erased.** It becomes ext4
   mounted at `/`.
5. Reuse the existing EFI partition at `/boot/efi` without formatting. Select it
   and choose **Edit…** if needed. The first product's root must be **Keep
   unchanged** in Review.

The second ISO installs the reserved product. If the expected partition is
unclear, please stop before confirming Review.

## 3. Two-disk example: 1 TB for Node, 128 GB for Vault

Verify actual capacities, models and serials first; these sizes are examples.
Install Node on the identified 1 TB disk with **Install to disk**, then boot it.
Install Vault on the identified 128 GB disk the same way. Each selected disk is
erased and gets its own root and EFI partitions; the Node disk must remain
untouched during Vault installation. No companion reservation is needed.

To retain existing partitions on either target disk, use **Advanced partitioning**
with an exact target partition or genuine unallocated area instead.

## 4. Review and boot verification

Before **Install Bitcoin Core Node** or **Install Bitcoin Core Vault**, check the
selected disk, root and every action. Confirm **Reuse EFI; do not format** and
**Keep unchanged** wherever preservation is intended. Use **Back** or **Revert
changes** if the plan is wrong.

After installation, restart and remove the installation USB. Boot both products
using UEFI boot selection or the available Node/Vault menu. Confirm the first
installation and its test files still work after installing the second product.

## 5. Settings checks on both desktops

- Check the lower-right **Settings**, **Restart** and shutdown controls. The gear
  must open Settings.
- Open **Display Settings**, change a supported resolution or **Interface
  size**, then choose **Apply → Keep changes** within **15 seconds**. Repeat
  once without confirming and check that the previous display settings return.
- With a second display, test available **Mirror displays** and **Extend desktop**
  modes. Check that Settings remains reachable.
- Change a **Keyboard and Mouse** preference. Restart: installed Node should
  retain its saved input/display preferences on the same display setup. Vault
  preferences belong to the current RAM session and should reset in a new
  session, including installed Vault.
- Optionally test **Export device settings…** to USB and **Import device settings…**
  in a new Vault session. Display imports still need **Apply → Keep changes**.
  The file contains device preferences, not a wallet backup.

## 6. Send the result

Please reply with ISO filenames, computer/disk models, scenario, boot results and
Settings results after restart. Include the exact step and error text for any
problem. No photos or screenshots are required.
