"""Core can be syncing headers while blocks and validation progress stay zero."""
import sys, time, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from activity_ui import chain_activity

class ActivityStages(unittest.TestCase):
    def test_first_sync_shows_increasing_header_presync(self):
        chain=dict(initialblockdownload=True,blocks=0,headers=0,time=1231006505,verificationprogress=0)
        network=dict(networkactive=True,connections=3)
        before=chain_activity(chain,network,[dict(presynced_headers=450000)])
        after=chain_activity(chain,network,[dict(presynced_headers=650000)])
        self.assertIn('450,000 headers',before[1]);self.assertIn('650,000 headers',after[1])
        self.assertNotIn('0.00%',after[1]);self.assertTrue(after[2])
        validated=chain_activity(dict(chain,headers=28000),network,[dict(presynced_headers=-1)])
        self.assertIn('28,000 headers',validated[1])

    def test_paused_network_is_distinct_from_missing_peers(self):
        chain=dict(initialblockdownload=True,blocks=0,headers=0,time=0,verificationprogress=0)
        paused=chain_activity(chain,dict(networkactive=False,connections=0),[])
        waiting=chain_activity(chain,dict(networkactive=True,connections=0),[])
        self.assertIn('paused',paused[1]);self.assertIn('Waiting for Bitcoin peers',waiting[1])
        self.assertFalse(paused[2]);self.assertFalse(waiting[2])

    def test_block_validation_and_catching_up_remain_visible(self):
        chain=dict(initialblockdownload=False,blocks=500,headers=600,time=time.time(),verificationprogress=.5)
        status=chain_activity(chain,dict(networkactive=True,connections=2),[])
        self.assertEqual(status[0],'syncing');self.assertIn('500 blocks',status[1])
        self.assertTrue(status[2])
        synced=chain_activity(dict(chain,blocks=600),dict(networkactive=True,connections=2),[])
        self.assertEqual(synced[0],'synchronized');self.assertFalse(synced[2])

if __name__=='__main__': unittest.main()
