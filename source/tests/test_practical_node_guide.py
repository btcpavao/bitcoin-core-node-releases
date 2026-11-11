"""Stand-alone Node tutorial and copy-only export documentation contracts."""
import ast,sys,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'app'))
from guide_content import SECTIONS

class PracticalNodeGuide(unittest.TestCase):
 def test_practical_workflow_is_first_and_complete(self):
  self.assertEqual(next(iter(SECTIONS)),'Start here: Node & Vault')
  intro=SECTIONS['Start here: Node & Vault']
  self.assertEqual(intro.count('<h3>'),13)
  for phrase in ('Export watch-only wallet','Restore Wallet','Create new receiving address','Create Unsigned','Load PSBT from file','Sign Tx','Broadcast Tx','PSBT Transfer Folder','Private Workspace'):
   self.assertIn(phrase,intro)
 def test_financial_privacy_and_password_boundaries(self):
  text=SECTIONS['Device privacy & login']
  for phrase in ('balances','transaction history','unlocked','not disk encryption','current session','login password','excludes the login password'):
   self.assertIn(phrase,text)
 def test_prune_units_budget_and_rescan_limits(self):
  text=SECTIONS['Storage & pruning']
  for phrase in ('chainstate','free-space reserve','90 GiB','20 GiB','40 GiB','1,024 MiB','40,960 MiB','prune','rescan','already been removed','does not automatically fetch','Illustrative example'):
   self.assertIn(phrase,text)
 def test_export_scope_not_confused_with_restore_or_authentication(self):
  text=SECTIONS['Backups & recovery']
  for phrase in ('All four Backup and Restore categories','no second pass','written and flushed','Restore checks remain enabled','GPG authentication is not disabled','latent media fault'):
   self.assertIn(phrase,text)
  self.assertIn('no separate read-back verification stage',SECTIONS['Blockchain backup'])
  self.assertIn('not reopened in a second Core process',SECTIONS['Watch-only backups'])
  self.assertIn('retains its recovery checks',SECTIONS['Encrypt & Decrypt Files'])
 def test_original_topics_and_standalone_tone_remain(self):
  for name in ('Networking','Status & diagnostics','Node configuration','Core configuration','Watch-only backups','Blockchain backup','Updates','Troubleshooting','Persistent storage'):
   self.assertIn(name,SECTIONS)
  text=' '.join(SECTIONS.values()).lower()
  for phrase in ('earlier discussion','as we discussed','bag of coins','saved-and-verified confirmation'):
   self.assertNotIn(phrase,text)
 def test_static_guide_matches_reader(self):
  html=(R/'runtime/usr/share/bitcoin-core-node/GUIDE.html').read_text()
  for chapter in SECTIONS.values():self.assertIn(chapter,html)
  tree=ast.parse((R/'app/guide_content.py').read_text())
  self.assertFalse(any(isinstance(n,(ast.Call,ast.Import,ast.ImportFrom)) for n in ast.walk(tree)))

if __name__=='__main__':unittest.main()
