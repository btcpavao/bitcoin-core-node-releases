import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from rpc import CoreError
from wallet_presence import watch_only_wallets_present

class WalletPresence(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/'imports').mkdir()
        self.loaded={};self.disk=[];self.offline=False;self.failed=set();self.calls=[]
    def tearDown(self):self.tmp.cleanup()
    def rpc(self,method,*args,**kwargs):
        self.calls.append(method)
        if self.offline:raise CoreError('offline')
        if method=='listwallets':return list(self.loaded)
        if method=='getwalletinfo':
            if kwargs['wallet'] in self.failed:raise CoreError('unavailable')
            return self.loaded[kwargs['wallet']]
        if method=='listwalletdir':return {'wallets':[{'name':n} for n in self.disk]}
        raise AssertionError('Presence must be read-only: '+method)
    def probe(self):return watch_only_wallets_present(self.rpc,self.root)
    def receipt(self,name,status):
        (self.root/'imports'/(name+'.json')).write_text(json.dumps({'status':status}))

    def test_empty_private_and_watch_only_wallets(self):
        self.assertIs(self.probe(),False)
        self.loaded={'signing':{'private_keys_enabled':True,'descriptors':True},
                     'legacy':{'private_keys_enabled':False,'descriptors':False}}
        self.assertIs(self.probe(),False)
        for name in ['first','second','']:
            self.loaded[name]={'private_keys_enabled':False,'descriptors':True}
            self.assertIs(self.probe(),True)
        self.assertNotIn('loadwallet',self.calls)

    def test_imported_unloaded_wallet_and_deleted_wallet(self):
        self.receipt('imported','complete');self.disk=['imported']
        self.assertIs(self.probe(),True)
        self.disk=[]
        self.assertIs(self.probe(),False)

    def test_stopped_core_with_existing_imports(self):
        self.offline=True
        self.assertIsNone(self.probe())
        self.receipt('not_created','creating')
        self.assertIsNone(self.probe())
        for status in ['importing','incomplete','complete']:
            self.receipt('imported',status)
            self.assertIs(self.probe(),True)

    def test_stale_receipt_does_not_reclassify_signing_wallet(self):
        self.receipt('wallet','complete');self.disk=['wallet']
        self.loaded={'wallet':{'private_keys_enabled':True,'descriptors':True}}
        self.assertIs(self.probe(),False)

    def test_rpc_uncertainty_is_not_empty(self):
        self.loaded={'wallet':{}};self.failed={'wallet'}
        self.assertIsNone(self.probe())

    def test_bad_and_symlink_receipts_are_ignored(self):
        (self.root/'imports/bad.json').write_text('{')
        (self.root/'imports/wrong.json').write_text('[]')
        (self.root/'outside').write_text('{"status":"complete"}')
        (self.root/'imports/link.json').symlink_to(self.root/'outside')
        self.offline=True
        self.assertIsNone(self.probe())

if __name__=='__main__':unittest.main()
