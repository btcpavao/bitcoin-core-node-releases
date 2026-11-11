"""Regression checks without changing host credentials or requesting power."""
import json
import os
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import Mock,patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import ui
from PySide6.QtWidgets import QApplication,QWidget

APP=None


class LoginAndPower(unittest.TestCase):
    def test_only_machine_power_uses_password_free_bounded_helper(self):
        for action in ('reboot','poweroff','start','stop','restart','configure','software-install'):
            with self.subTest(action=action),patch.object(ui.subprocess,'run',return_value=Mock(returncode=0,stdout='{"ok":true}')) as run:
                self.assertTrue(ui.admin(action)['ok'])
                helper=run.call_args.args[0][1]
                expected=('/usr/libexec/core-node-power' if action in ('reboot','poweroff') else
                          '/usr/libexec/core-node-service' if action in ('start','stop','restart') else
                          '/usr/libexec/core-node-admin')
                self.assertEqual(helper,expected)

    def test_service_helper_cannot_delegate_other_admin_operations(self):
        module=runpy.run_path(str(ROOT/'runtime/usr/libexec/core-node-service'),run_name='service_test')
        for args in ([],['configure'],['reboot'],['software-install'],['start','sshd'],['stop','--force']):
            with self.subTest(args=args),patch.object(sys,'argv',['service',*args]),patch('os.geteuid',return_value=0),patch('os.execv') as execute:
                with self.assertRaises(RuntimeError):module['main']()
                execute.assert_not_called()
        for action in ('start','stop','restart'):
            with patch.object(sys,'argv',['service',action]),patch('os.geteuid',return_value=0),patch('os.execv') as execute:
                module['main']()
                execute.assert_called_once_with('/usr/libexec/core-node-admin',['core-node-admin',action])
        with patch.object(sys,'argv',['service','start']),patch('os.geteuid',return_value=1000),patch('os.execv') as execute:
            with self.assertRaises(RuntimeError):module['main']()
            execute.assert_not_called()

    def test_power_helper_cannot_delegate_other_admin_operations(self):
        module=runpy.run_path(str(ROOT/'runtime/usr/libexec/core-node-power'),run_name='power_test')
        for args in ([],['configure'],['restart'],['reboot','configure'],['poweroff','--force']):
            with self.subTest(args=args),patch.object(sys,'argv',['power',*args]),patch('os.geteuid',return_value=0),patch('os.execv') as execute:
                with self.assertRaises(RuntimeError):module['main']()
                execute.assert_not_called()
        for action in ('reboot','poweroff'):
            with patch.object(sys,'argv',['power',action]),patch('os.geteuid',return_value=0),patch('os.execv') as execute:
                module['main']()
                execute.assert_called_once_with('/usr/libexec/core-node-admin',['core-node-admin',action])


if __name__=='__main__':unittest.main()
