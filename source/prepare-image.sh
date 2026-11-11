#!/bin/sh
set -eu
test -x /usr/lib/user-setup/user-setup-apply
test -x /usr/bin/lxpolkit
test -x /usr/bin/unsquashfs
test -x /usr/sbin/grub-install
test -x /usr/sbin/grub-mkconfig
test -x /usr/sbin/update-initramfs
test -s /etc/calamares/branding/core-node/show.qml
systemd-sysusers /etc/sysusers.d/bitcoin-core-node.conf
systemd-tmpfiles --create /etc/tmpfiles.d/bitcoin-core-node.conf
systemctl enable core-node-files.service core-node-private.service run-core\\x2dnode\\x2dprivate.mount bitcoin-core-node-transfer.path nftables.service systemd-resolved.service bitcoin-core-node-resolver.service NetworkManager.service bluetooth.service lightdm.service bitcoin-core-node-policy.service
systemctl enable core-node-settings-restore.service core-node-settings-time.service core-node-media.service
systemctl disable bitcoin-core-node.service
systemctl enable systemd-timesyncd.service
systemctl mask swap.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target systemd-hibernate.service systemd-hybrid-sleep.service systemd-suspend-then-hibernate.service
systemctl mask networking.service systemd-networkd.service systemd-networkd.socket
systemctl disable ssh.service ssh.socket 2>/dev/null || true
# The live session opens Calamares. Installation creates the default clearnet
# configuration; per-boot firewall and persistent-storage checks remain required.
test ! -e /etc/bitcoin-core-node/setup.json
test ! -e /etc/bitcoin-core-node/installed
test ! -e /etc/systemd/system/home-vault.mount
test ! -e /etc/systemd/system/run-core\\x2dvault.mount
test -x /usr/bin/gpgv
test -s /usr/share/bitcoin-core-node/release-keys.asc
chmod 755 /usr/libexec/core-node-* /usr/local/bin/bitcoin-core-node
chmod 644 /usr/lib/bitcoin-core-node/*.py

# A fresh automatic-login install must include its bounded management policy.
test -s /etc/polkit-1/rules.d/49-core-node.rules
# Runtime overlays must retain the Debian polkit rules directory group.
chown root:polkitd /etc/polkit-1/rules.d
chmod 0775 /etc/polkit-1/rules.d
# Git checkout permissions depend on the builder umask; normalize trusted policy files.
chown root:root /etc/lightdm/lightdm.conf.d/50-core-node-session.conf
chmod 0644 /etc/lightdm/lightdm.conf.d/50-core-node-session.conf
for policy in /etc/polkit-1/rules.d/*core-node*.rules /usr/share/polkit-1/actions/org.bitcoin-core-node.*.policy; do
    chown root:root "$policy"
    chmod 0644 "$policy"
done
# The greeter uses native LightDM/PAM with a fixed Node presentation.
test "$(dpkg-query -W -f='${Version}' lightdm-gtk-greeter)" = '2.0.9-1+corenode1'
apt-mark hold lightdm-gtk-greeter
for greeter_file in /etc/lightdm/lightdm-gtk-greeter.conf /usr/share/bitcoin-core-node/greeter.css /usr/share/bitcoin-core-node/bitcoin-ui.png /etc/calamares/modules/partition.conf; do
    chown root:root "$greeter_file"
    chmod 0644 "$greeter_file"
done
test -s /usr/share/polkit-1/actions/org.bitcoin-core-node.login.policy
test -x /usr/libexec/core-node-login
test -x /usr/libexec/core-node-service
test -s /usr/share/polkit-1/actions/org.bitcoin-core-node.service.policy
test -x /usr/libexec/core-node-defaults
test -s /usr/share/bitcoin-core-node/bitcoin-ui.png
test -s /usr/share/bitcoin-core-node/debian-ui.png

# Shared Vault power artwork must be present in the installed Node UI.
test -s /usr/share/bitcoin-core-node/icons/system-reboot.svg
test -s /usr/share/bitcoin-core-node/icons/system-shutdown.svg
test -s /usr/lib/x86_64-linux-gnu/qt6/plugins/iconengines/libqsvgicon.so

test -x /opt/bitcoin-core/32.1/bin/bitcoin-qt
test -x /usr/bin/xhost
test -x /usr/local/bin/core-node-numlock
# Use the exact Vault-derived Calamares and desktop components.
test "$(dpkg-query -W -f='${Version}' calamares)" = '3.3.14-1+corenode2'
apt-mark hold calamares
test -s /etc/calamares/branding/core-node/stylesheet.qss
test -s /etc/calamares/modules/finished.conf
test -s /usr/share/xsessions/core-node.desktop
test -x /usr/local/bin/core-node-session
test -x /usr/local/bin/core-node-installer-session
test -x /usr/local/bin/core-node-taskbar
test -s /usr/share/bitcoin-core-node/icons/debian-white.png

update-alternatives --install /usr/bin/x-session-manager x-session-manager /usr/local/bin/core-node-session 60


# Use Vault's graphical progress screen in both the live ISO and installed system.
test -x /usr/bin/nm-connection-editor
test -s /usr/share/plymouth/themes/core-node/core-node.plymouth
test -s /usr/share/plymouth/themes/core-node/core-node.script
plymouth-set-default-theme -R core-node
for node_initrd in /boot/initrd.img-*; do
    lsinitramfs "$node_initrd" | grep -q 'usr/share/plymouth/themes/core-node/core-node.script'
done

# Native Bluetooth pairing and HID support must ship in both installation modes.
test -x /usr/bin/blueman-manager
test -x /usr/bin/blueman-applet
test -x /usr/bin/bluetoothctl
test -x /usr/libexec/bluetooth/bluetoothd
test -s /etc/bluetooth/main.conf
test -s /etc/modules-load.d/core-node-bluetooth.conf
test -s /etc/systemd/system/bluetooth.service.d/core-node.conf
glib-compile-schemas --strict /usr/share/glib-2.0/schemas
systemctl is-enabled bluetooth.service

# Wi-Fi is mandatory even with apt recommendations disabled.
test "$(dpkg-query -W -f='${db:Status-Status}' wpasupplicant)" = installed
test "$(dpkg-query -W -f='${db:Status-Status}' wireless-regdb)" = installed
test -x /usr/sbin/wpa_supplicant
test -s /usr/share/dbus-1/system-services/fi.w1.wpa_supplicant1.service
test -s /usr/lib/systemd/system/wpa_supplicant.service
test -s /lib/firmware/regulatory.db


# Fail the image build if the private file workflow is incomplete.
test -x /usr/libexec/core-node-private-prepare
test -x /usr/local/bin/core-node-files-crypto
test -x /usr/bin/setfacl
test -s /usr/lib/bitcoin-core-node/private_workspace.py
test -s /usr/lib/bitcoin-core-node/file_crypto.py
test -s /usr/lib/bitcoin-core-node/gpg_backend.py
test -s /usr/lib/bitcoin-core-node/layered_backend.py
test ! -e /usr/lib/bitcoin-core-node/recovery.py
test -s /etc/systemd/sleep.conf.d/core-node-private.conf
test -s /etc/initramfs-tools/conf.d/core-node-noresume
test -x /usr/bin/bindfs
test -x /usr/bin/fusermount3
test -x /usr/local/bin/core-node-file-places
test -x /usr/libexec/core-node-files-prepare
test -x /usr/libexec/core-node-files-ready
test -s /usr/lib/bitcoin-core-node/power_ui.py
test -s /usr/lib/bitcoin-core-node/file_browser.py

# Vault's native passphrase generator and the shared system clock controls.
test -x /usr/local/bin/keepassxc
test -x /usr/local/bin/core-node-keepassxc
test -x /usr/local/bin/core-node-open-passphrase
test -s /usr/lib/bitcoin-core-node/keepass_launcher.py
test -s /usr/lib/bitcoin-core-node/system_time.py
test -s /usr/lib/bitcoin-core-node/time_ui.py
test -s /usr/share/bitcoin-core-node/icons/clock.svg
test -x /usr/bin/timedatectl
test -x /usr/lib/systemd/systemd-timesyncd
test -f /usr/share/zoneinfo/Europe/Zagreb
systemctl is-enabled systemd-timesyncd.service
test -x /opt/keepassxc/current/AppRun
test -x /opt/keepassxc/current/usr/bin/keepassxc
test -s /opt/keepassxc/current/node-release.json
test -s /usr/share/bitcoin-core-node/keepassxc-release-key.asc
test -x /usr/libexec/core-node-software-updates
test -s /usr/lib/systemd/system/core-node-software-install.service
test -s /etc/apt/sources.list.d/core-node.sources
test -x /usr/bin/xdg-open
test -x /usr/bin/file
test -x /usr/bin/dbus-run-session
test -x /usr/libexec/xdg-desktop-portal
test -x /usr/libexec/xdg-desktop-portal-gtk
test -x /usr/libexec/core-node-session-bus
# live-build's generated source list duplicates the managed Debian repositories
# and produces warnings in Software Update. Keep the reviewed deb822 source.
rm -f /etc/apt/sources.list.d/zz-sources.list

# The upstream bundle deliberately uses the system USB library.
test "$(dpkg-query -W -f='${db:Status-Status}' libusb-1.0-0)" = installed
python3 - <<'KEEPASS_RUNTIME'
import sys
from pathlib import Path
sys.path.insert(0, '/usr/lib/bitcoin-core-node')
from keepass_updates import validate_runtime
validate_runtime(Path('/opt/keepassxc/current'))
KEEPASS_RUNTIME

# Disk encryption must boot with a visible prompt and no embedded root key.
test -x /usr/sbin/cryptsetup
test -s /usr/share/initramfs-tools/hooks/cryptroot
test -s /usr/libexec/core-node-power
test -s /usr/share/polkit-1/actions/org.bitcoin-core-node.power.policy
grep -q SetDisplayPasswordFunction /usr/share/plymouth/themes/core-node/core-node.script
