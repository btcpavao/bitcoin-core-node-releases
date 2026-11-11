# Local Wi-Fi onboarding — 2026-10-28

Network Status now opens a dark Qt network picker. Scanning is asynchronous;
Wi-Fi off, missing adapter, empty scan, connection failure and Ethernet states
have visible explanations. Refresh rescans. Selecting a different network clears
the password. Advanced settings opens the existing NetworkManager editor.

Core launch checks local connection state asynchronously and offers the picker
when disconnected or when NetworkManager cannot be queried. Cancel does not start
Core; Use Core offline explicitly starts it without connectivity. Connected
means a NetworkManager device is activated, not a verified Internet connection.
No external connectivity probe or change to Tor, VPN or firewall policy is added.

The helper uses libnm with a password over a private stdin pipe, never argv or
diagnostic output. Profiles are limited to the local desktop user and use the
existing NetworkManager modify-own policy. No polkit rules were added. WPA-PSK,
SAE and open/OWE profiles use automatic IPv4/IPv6. Saved compatible profiles are
reused when no password is entered. Enterprise and legacy WEP setup remains in
Advanced settings. NetworkManager owns persistence and auto-reconnection.

Validation: unit tests and mocked Qt interaction tests cover scanning, escaped
SSIDs, no adapter, radio off, Ethernet, password handling, compact layout and
Core continuation/cancellation. libnm validates the generated profile schemas.
Physical T550 radio authentication and reboot reconnection require device testing.


## Runtime correction after T550 feedback

The first ISO omitted wpasupplicant because network-manager only recommends it
and image construction disables recommended packages. Firmware alone was not
enough. wpasupplicant and wireless-regdb are now explicit requirements. The
image hook fails if the packages, executable, D-Bus activation file, service or
regulatory database is missing.

Closing the picker now always ends its modal state, stops its refresh timer and
requests cancellation. Its workers belong to the application until they finish;
late callbacks never update a closed dialog. Subprocesses poll cancellation,
terminate with a bound and are reaped. Done / Use Core offline stays enabled
during scans. Closing a connection attempt also asks the libnm helper to stop
activation. No changes to host networking, global polkit or Bitcoin firewall.

Regression checks use an actual sleeping subprocess: Escape/reject, window close
and offline continuation return immediately, Home remains usable, the child and
worker finish, and reopening works. The real ThinkCentre Wi-Fi scan was also
tested read-only, without changing its active connection. T550 validation remains
pending because only ThinkCentre is remotely connected.

## Unicode hotspot correction

The C locale made GLib/nmcli replace non-ASCII SSID characters with question
marks (for example the curly apostrophe in an iPhone hotspot name). The helper
correctly rejected the altered name before authentication. Network subprocesses
now use C.UTF-8: stable English status values with intact UTF-8 SSIDs. The SSID
identity check remains in place. A real GLib-output regression test covers the
apostrophe and Croatian letters; the ISO radio test reproduces the old failure
and checks WPA2 authentication, DHCP and reconnection with the corrected name.
