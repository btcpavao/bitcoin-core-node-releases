# KeePassXC and Date & Time

Local update of physically tested Node commit 85a55c476adde928d42d0b439e99aadb4386acb8.
No GitHub publication.

KeePassXC reuses Vault's native generator observer from
51059c52372a7b149a800183963f5300a2f4ebb1. It opens the native passphrase
generator with six EFF words. Automatic clipboard clearing is initially off;
user choices survive relaunch in the current session. Database/key-file history
and application update checks are off. Configuration, cache, state and working
directory use verified noswap RAM. A new boot restores the defaults. Users
explicitly save any database they want to keep to USB or persistent storage.

Home always shows the OS date and 24-hour time, even with Core stopped. The clock
and Node Settings open one Date & Time dialog. Timezone and automatic/manual time
apply to the OS and persist. systemd-timesyncd ships enabled. Time traffic follows
the existing OS policy: ordinary OS networking in Tor P2P mode and the enforced
VPN in WireGuard mode. Firewall rules are unchanged.

Reads are unprivileged; writes use the existing authenticated, bounded Node
admin helper. All fields, installed timezone files, date range and DST round
trips are validated before any change. Skipped or repeated local DST times are
refused. Manual changes use an absolute epoch and update the hardware clock
through timedated. UI workers keep DBus/authentication waits off the main thread.
Validation must never change the development host's clock.

Acceptance covers native generator defaults, RAM profile/relaunch choices,
clipboard behavior, clock visibility/click targets, theme/layout, native guest
timezone/manual changes, NTP enable/disable and reboot persistence. Exact-image
results belong in the local build's ACCEPTANCE.json. Physical T550 testing
remains a user test.

Native acceptance also exposed a pre-existing activity-worker lifetime race. Home activity, wallet inventory and Date & Time completion now use GUI-thread QObject slots that clear references before deletion. Repeated worker completion is covered by the real Qt regression harness, and final installed Home must keep its Core status visible.

Warm-boot acceptance also exposed a taskbar map/configure race: a transient X11 panel position could leave a 400-pixel reserved area while the actual panel occupied only 40 pixels. Each existing refresh now rechecks native coordinates and updates only changed strut properties. A native fixture also injects a stale reservation and verifies recovery without closing applications.
