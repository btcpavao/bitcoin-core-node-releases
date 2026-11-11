import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from wallets import read_file, amount, WalletError
from file_crypto import publish_new



class Files(unittest.TestCase):
    def test_no_overwrite_and_untrusted_file_types(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); destination = root/'export.psbt'
            source = root/'source'; source.write_bytes(b'original')
            publish_new(source, destination)
            source.write_bytes(b'replacement')
            with self.assertRaises(FileExistsError): publish_new(source, destination)
            self.assertEqual(read_file(destination), b'original')
            link = root/'link'; link.symlink_to(destination)
            with self.assertRaises(OSError): read_file(link)
            fifo = root/'fifo'; os.mkfifo(fifo)
            with self.assertRaises(WalletError): read_file(fifo)

    def test_amount_boundaries_and_gpg(self):
        self.assertEqual(amount('0.00000001'), '0.00000001')
        for value in ('NaN', 'Infinity', '-1', '0.000000001', '21000001'):
            with self.assertRaises(WalletError): amount(value)


if __name__ == '__main__': unittest.main()
