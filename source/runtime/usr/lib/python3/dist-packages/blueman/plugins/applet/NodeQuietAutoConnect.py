# SPDX-License-Identifier: GPL-3.0-or-later
"""Use Blueman's saved reconnect policy without a success notification dialog."""
from blueman.plugins.applet.AutoConnect import AutoConnect
from blueman.plugins.AppletPlugin import AppletPlugin
from gi.repository import GLib


class NodeQuietAutoConnect(AppletPlugin):
    # Blueman discovers direct AppletPlugin subclasses.
    __depends__ = AutoConnect.__depends__
    __author__ = AutoConnect.__author__
    __icon__ = AutoConnect.__icon__
    __gsettings__ = AutoConnect.__gsettings__
    __options__ = AutoConnect.__options__
    __description__ = 'Reconnect saved Bluetooth services quietly.'

    def __init__(self, parent):
        super().__init__(parent)
        GLib.timeout_add(60000, self._run)

    on_manager_state_changed = AutoConnect.on_manager_state_changed
    on_adapter_property_changed = AutoConnect.on_adapter_property_changed

    def _run(self):
        for address, uuid in self.get_option('services'):
            # Keep upstream's migration of old object-path preferences.
            if address.startswith('/org/bluez'):
                address = AutoConnect._AutoConnect__fix_settings(address, uuid)
            device = self.parent.Manager.find_device(address)
            if device is None or device.get('Connected'):
                continue

            def connected():
                pass

            def failed(_reason):
                pass

            self.parent.Plugins.DBusService.connect_service(
                device.get_object_path(), uuid, connected, failed)
        return True
