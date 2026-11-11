"""Guard against missing identity on the interactive QEMU installation disk."""
import re
import unittest
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "tools/test-node-vm.sh"


class ManualVMLauncherTests(unittest.TestCase):
    def test_installer_can_identify_manual_virtio_disk(self):
        script = LAUNCHER.read_text()
        self.assertIn(
            '-drive "file=$NODE_TEST_VM/node.qcow2,format=qcow2,if=none,id=node-disk"',
            script,
        )
        self.assertIn(
            '-device "virtio-blk-pci,drive=node-disk,serial=NODE-MANUAL-49DF047"',
            script,
        )
        self.assertNotIn("if=virtio", script)
        # Both arguments belong to a single continued QEMU command. A stray
        # shell comment between backslash lines would silently break this.
        self.assertRegex(
            script,
            re.compile(
                r'-drive "file=\$NODE_TEST_VM/node\.qcow2,format=qcow2,if=none,id=node-disk" \\\n'
                r'    -device "virtio-blk-pci,drive=node-disk,serial=NODE-MANUAL-49DF047" \\\n'
                r'    -cdrom "\$NODE_TEST_ISO" -boot order=cd'
            ),
        )

    def test_existing_disk_is_preserved(self):
        script = LAUNCHER.read_text()
        self.assertIn('if [[ ! -e "$NODE_TEST_VM/node.qcow2" ]]', script)
        self.assertIn('sha256sum --check SHA256SUMS', script)
        self.assertNotIn('qemu-img convert', script)
        self.assertNotIn('rm -f "$NODE_TEST_VM/node.qcow2"', script)


if __name__ == "__main__":
    unittest.main()
