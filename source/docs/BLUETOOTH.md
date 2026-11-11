# Node Bluetooth input

Node ships Debian 13 BlueZ, Blueman and the distribution firmware packages for Intel, Realtek, Qualcomm/Atheros, Broadcom, MediaTek, Marvell and TI adapters. The image and installed APT sources use main and non-free-firmware. Firmware packages are explicitly listed, including the existing free firmware, rather than installing every unrelated GPU/media firmware package. Hardware support remains bounded by Debian's kernel/firmware and the physical radio/BIOS switch; it is not a guarantee for every adapter.

Node Settings → Bluetooth devices and Ctrl+Alt+B open the existing Blueman manager. The session runs its authentication agent before either the installer or Home. Native fallback dialogs show pairing confirmation and keyboard passkeys without requiring a system tray. Active local node/node-live sessions may change the Bluetooth rfkill state; other privileges are unchanged.

BlueZ enables present/hotplugged controllers, supports classic and LE input, keeps bonded-device-only HID security, and stores installed pairings in /var/lib/bluetooth. UHID is loaded at boot. Live-installer pairing is not copied from RAM into the installed system: pair again after installation. Use built-in or USB input for first-time pairing where necessary.

The BlueZ network plugin is disabled. Blueman network and transfer plugins default to disabled; the existing Node network/firewall management remains authoritative. No Vault files or policy are changed.

Physical checks: pair a mouse and keyboard, confirm a keyboard passkey, reboot and wake/reconnect each device, then verify optional login-password entry. Repeat on the target adapters; a VM without passed-through Bluetooth hardware cannot verify radio compatibility.
