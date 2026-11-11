from pathlib import Path
import json,os,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import state

class ImportedFirstStart(unittest.TestCase):
    def test_fresh_install_retains_native_intro_and_import_skips_only_data_picker(self):
        setup=state.default_setup()
        for imported in (False,True):
            with patch.object(state,'has_imported_chain',return_value=imported):args=state.core_arguments(setup,gui=True)
            self.assertEqual(any(a.startswith('-datadir=') for a in args),imported)
            self.assertFalse(any(a.startswith(('-prune=','-daemon=')) for a in args))
            self.assertIn('-settings='+str(state.DATA/'settings.json'),args)

    @unittest.skipUnless(os.geteuid()==0,'receipt ownership checked in image chroot')
    def test_receipt_is_root_owned_bounded_and_network_specific(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp);path=data/state.CHAIN_IMPORT_RECEIPT;setup=state.default_setup()
            self.assertFalse(state.has_imported_chain(setup,data))
            record=dict(version=1,network='main',core_version='32.1',height=100,bestblockhash='a'*64)
            path.write_text(json.dumps(record));path.chmod(0o644)
            self.assertTrue(state.has_imported_chain(setup,data))
            self.assertFalse(state.has_imported_chain(dict(setup,network='signet'),data))
            path.chmod(0o666)
            with self.assertRaises(state.SetupError):state.has_imported_chain(setup,data)
            path.unlink();path.symlink_to('/etc/passwd')
            with self.assertRaises(state.SetupError):state.has_imported_chain(setup,data)

if __name__=='__main__':unittest.main()
