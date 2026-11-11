"""Run with the image's actual Blueman package; never touches a real device."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
from blueman.plugins.applet.AutoConnect import AutoConnect
from blueman.plugins.AppletPlugin import AppletPlugin
from blueman.plugins.applet.NodeQuietAutoConnect import NodeQuietAutoConnect

assert NodeQuietAutoConnect in AppletPlugin.__subclasses__(), 'Blueman must discover the plugin'
assert NodeQuietAutoConnect.__gsettings__ == AutoConnect.__gsettings__
assert 'DBusService' in NodeQuietAutoConnect.__depends__
device=Mock()
device.get.return_value=False
device.get_object_path.return_value='/org/bluez/hci0/dev_00_11_22_33_44_55'
manager=Mock();manager.find_device.return_value=device
dbus=Mock()
fake=SimpleNamespace(parent=SimpleNamespace(Manager=manager,Plugins=SimpleNamespace(DBusService=dbus)),
                     get_option=lambda name:[('00:11:22:33:44:55','00001124-0000-1000-8000-00805f9b34fb')])
with patch('blueman.plugins.applet.AutoConnect.Notification',side_effect=AssertionError('Reconnect must be silent')):
    assert NodeQuietAutoConnect._run(fake)
    args=dbus.connect_service.call_args.args
    assert args[:2]==(device.get_object_path(),'00001124-0000-1000-8000-00805f9b34fb')
    args[2]();args[3](RuntimeError('fixture unavailable'))
    dbus.reset_mock();device.get.return_value=True
    assert NodeQuietAutoConnect._run(fake);dbus.connect_service.assert_not_called()
    manager.find_device.return_value=None
    assert NodeQuietAutoConnect._run(fake);dbus.connect_service.assert_not_called()
    manager.find_device.return_value=device;device.get.return_value=False
    fake.get_option=lambda name:[('/org/bluez/hci0/dev_00_11_22_33_44_55','service')]
    with patch.object(AutoConnect,'_AutoConnect__fix_settings',return_value='00:11:22:33:44:55') as migrate:
        assert NodeQuietAutoConnect._run(fake)
        migrate.assert_called_once()
    manager.find_device.assert_called_with('00:11:22:33:44:55')
print('PASS: saved service reconnect, silent callbacks, connected/missing skip and legacy preference migration')
