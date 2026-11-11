# Bitcoin Core Node — x86-64 hardware support audit

Audit date: 5 November 2026. Development source branch created from
`fix/node-optional-login-20261105` (Core 32.1). This is a **source proposal**;
adding packages to source does not retroactively update an existing ISO.

## Target and limits

Aim for a single Debian 13 amd64 image that boots on common Intel and AMD PCs,
older ThinkPads and non-T2 Intel Macs, with network, storage, graphics, input and
Bluetooth available without downloading firmware after installation. This is
not a claim of compatibility with every computer. ARM devices (including Apple
Silicon/M-series Macs), 32-bit CPUs, machines with unusual hardware, and devices
that require newer or out-of-tree kernels are outside the general guarantee.

## Confirmed in the existing 5 November ISO package manifest

Existing: `linux-image-amd64`, `network-manager`, `wpasupplicant`, `bluez`,
`rfkill`, `xserver-xorg-input-libinput`, Xorg ATI/AMD/Nouveau/fbdev/vesa
drivers, Mesa DRI, firmware for Intel Wi-Fi, Realtek, Atheros, MediaTek,
Broadcom `brcmfmac/brcmsmac`, Marvell Libertas, TI connectivity and some USB
Wi-Fi adapters. These are **included package checks**, not proof that a
specific physical device works.

## Generic firmware additions in this proposal

- Graphics: `firmware-amd-graphics`, `firmware-intel-graphics`,
  `firmware-intel-misc`, `firmware-nvidia-graphics`, and
  `firmware-misc-nonfree`. The NVIDIA package provides firmware, **not** a
  proprietary NVIDIA graphics driver. GPU support still depends on the
  in-kernel driver, supported GPU and boot/display path.
- Wired network: `firmware-bnx2`, `firmware-bnx2x`, `firmware-cavium`,
  `firmware-qlogic`, `firmware-netxen`, `firmware-netronome` and
  `firmware-myricom`.
- Older Wi-Fi: `firmware-zd1211`. The `firmware-ipw2x00` package
  requires interactive acceptance of its license during installation, and is
  deliberately **not** silently bundled in a universal unattended ISO.
- CPU stability/security: `intel-microcode`, `amd64-microcode`.
- Local diagnosis (not drivers): `pciutils`, `usbutils`, `ethtool`, `iw`.
  Nothing in this change uploads diagnostics or connects remotely.

The ISO build now gates on the **actual ISO package manifest** with
`tests/check_iso_hardware.py --iso <path>`. It fails when requested packages
were not installed, but cannot verify driver performance or hardware boot.

## Still NOT automatically supported

1. **MacBook Air 13-inch Early 2015 / BCM4360:** the built-in `brcmfmac`
   firmware package is insufficient. Debian provides
   `broadcom-sta-dkms` (`wl`) in `non-free`, but the package broadly
   blacklists `b43`, `brcmsmac`, `ssb`, `bcma`, and even `b44` Ethernet.
   Do **not** install it unconditionally in the universal image.
   The correct next step is a device-selective, offline, prebuilt-module
   integration for BCM4360, with matched kernel headers, DKMS build test,
   regressions for competing Broadcom wireless and Ethernet, and a physical
   MacBook test. Wi-Fi success is not yet established.
2. **Older b43 Broadcom Wi-Fi:** some chips need firmware that Debian cannot
   directly redistribute and which its installer downloads separately.
3. **T2 Intel Macs (e.g. MacBook Air 2018–2020):** keyboard, trackpad, Wi-Fi
   and other devices may require a T2-compatible patched kernel and
   machine-specific Apple firmware. A normal Debian ISO cannot promise
   full support merely by adding common packages.
4. **Secure Boot:** the development ISO has not been accepted as a
   Secure-Boot-signed image. Out-of-tree DKMS modules also require
   trusted module signatures/MOK enrollment when Secure Boot is enabled.
5. **Very recent chipsets, proprietary NVIDIA GPUs and unusual USB adapters:**
   stock Debian 13 kernel 6.12 and the available firmware may not suffice.
   Handle these via an independently tested kernel/firmware release process,
   not unsigned arbitrary downloads or blanket driver blacklists.
6. **Audio/webcam/fingerprint/other peripherals:** not part of the current
   Node's essential runtime workflow and not certified by these changes.

## Physical acceptance matrix before claiming compatibility

For each device, record its exact model/CPU, actual WLAN and Ethernet PCI IDs,
boot mode, firmware settings, ISO SHA-256, kernel version, installation mode,
and the outcomes of:

1. Live USB boot and installed first boot/restart; input, screen and disk.
2. Wi-Fi scan, connection, reconnect, WPA2/WPA3, Bluetooth mouse/keyboard.
3. Wired Ethernet, USB storage, NVMe/SATA detection, RAM-only Private Workspace.
4. Bitcoin Core 32.1 startup, pruned/full configuration, initial sync, backup,
   graceful restart and unattended software update.
5. Driver conflict regression: Intel Wi-Fi, Realtek, Atheros, AMD/NVIDIA
   display, b44 Broadcom Ethernet and Broadcom STA only where tested.

Start with ThinkPad T530, ThinkPad T550, the reported Early 2015 MacBook Air,
an AMD laptop and a desktop with discrete NVIDIA graphics. Failures and
unsupported firmware must be reported explicitly; success on one model is
not a blanket certification.

## Packaging / distribution

Maintain license notices and relevant upstream source/provenance for all
bundled firmware and any non-free drivers. Do not mark the image as accepted
until its actual checksum, hardware tests and legal/provenance review are
recorded alongside a release.
