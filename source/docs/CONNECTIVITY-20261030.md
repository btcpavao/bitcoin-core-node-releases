# Connectivity and startup corrections

The previous exact image was reproduced in an owned installed QEMU clone with a NAT NIC. Selecting Core's upstream default directory successfully reached public mainnet peers and downloaded headers. The observed pre-sync screenshot reached 454,000 headers while getblockchaininfo still reported zero blocks and zero validated headers. This does not establish the cause of the reported physical T550/iPhone failure.

Changes:

- Show Core's presynced_headers count, validated headers, peer count and paused-network state. Avoid displaying 0.00% throughout header pre-sync. Node status exposes pre-sync and network activity too.
- On fresh installs, make the upstream GUI default .bitcoin path link to the managed data directory. Both initial choices now reach the chain used by Files and chain backup/import. No existing data directory is migrated or overwritten.
- Route Node Settings Network connections through the existing Wi-Fi chooser. General network management is modeless and one-instance; the network control restores a minimized chooser.
- Close the chooser when handing control to the native advanced connection editor, including the Core startup chooser. No hidden Qt modal is left behind.
- Deliver worker results and cleanup through GUI-thread QObject slots, clear references before deletion, and cancel child processes when the chooser closes. Successful activation is checked without an immediate driver rescan.
- Complete the preceding Home worker before running its continuation. Starting Core after a network check needs no arbitrary timer delay.
- Disable Blueman ConnectionNotifier and use NodeQuietAutoConnect for saved-service reconnection. It inherits the upstream saved preferences, timer, adapter events and legacy preference migration, while omitting success notifications. BlueZ HID reconnection and the pairing/authentication agent remain enabled. Authentication is not suppressed.

Validation includes unit tests, real threaded Qt lifecycle/cancellation/reopen tests, exact payload checks, native installation and installed startup. Physical T550/iPhone transport and the user's actual Bluetooth mouse still need a physical retest. No Tor/VPN policy fallback or automatic privacy-profile change is introduced.
